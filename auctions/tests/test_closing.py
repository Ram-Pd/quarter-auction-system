"""Automatic closure, winner selection, result emails (auctions/closing.py, auctions/emails.py)."""
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auctions.bidding import BidRejected, join_auction, place_bid
from auctions.closing import close_auction, close_due_auctions, retry_unsent_notifications
from auctions.models import Auction, Quarter
from auctions.tests.factories import make_auction, make_bidder, make_quarter


def expire(auction):
    """Move the deadline into the past (as if time had passed)."""
    Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))
    auction.refresh_from_db()


class ClosureRuleTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.a, _, _ = make_bidder(self.auction, 1)
        self.b, _, _ = make_bidder(self.auction, 2)

    def bid(self, applicant, amount):
        return place_bid(self.auction.pk, applicant, amount, uuid.uuid4()).bid

    def test_not_closed_before_deadline(self):
        result = close_auction(self.auction.pk)
        self.assertFalse(result.closed_now)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.OPEN)

    def test_highest_bid_wins_and_quarter_is_allotted(self):
        self.bid(self.a, "4500")
        winning = self.bid(self.b, "4800")
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            result = close_auction(self.auction.pk)
        self.assertTrue(result.closed_now)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.CLOSED)
        self.assertEqual(self.auction.winning_bid, winning)
        self.assertEqual(self.auction.winner_participation.applicant, self.b)
        self.assertIsNotNone(self.auction.closed_at)
        self.assertEqual(self.auction.quarter.status, Quarter.Status.ALLOTTED)

    def test_no_bids_outcome_keeps_quarter_vacant(self):
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            result = close_auction(self.auction.pk)
        self.assertEqual(result.status, Auction.Status.CLOSED_NO_BIDS)
        self.auction.refresh_from_db()
        self.assertIsNone(self.auction.winning_bid)
        self.assertEqual(self.auction.quarter.status, Quarter.Status.VACANT)
        self.assertEqual(len(mail.outbox), 0)  # nobody to notify

    def test_closing_twice_does_nothing_the_second_time(self):
        self.bid(self.a, "4500")
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            first = close_auction(self.auction.pk)
            second = close_auction(self.auction.pk)
        self.assertTrue(first.closed_now)
        self.assertFalse(second.closed_now)
        self.assertEqual(len(mail.outbox), 1)  # winner emailed once

    def test_cancelled_auction_is_never_closed(self):
        self.auction.cancel()
        expire(self.auction)
        self.assertFalse(close_auction(self.auction.pk).closed_now)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.CANCELLED)

    def test_bids_after_closure_are_rejected(self):
        expire(self.auction)
        close_auction(self.auction.pk)
        with self.assertRaises(BidRejected):
            self.bid(self.a, "4500")

    def test_close_due_auctions_only_touches_due_ones(self):
        later = make_auction(make_quarter("C-305"))      # still live
        expire(self.auction)
        closed = close_due_auctions()
        self.assertEqual([r.auction_id for r in closed], [self.auction.pk])
        later.refresh_from_db()
        self.assertEqual(later.status, Auction.Status.OPEN)

    def test_database_refuses_awarding_a_quarter_twice(self):
        self.bid(self.a, "4500")
        expire(self.auction)
        close_auction(self.auction.pk)
        # A second auction of the same quarter with its own valid bid...
        second = Auction.objects.create(quarter=self.auction.quarter,
                                        start_time=timezone.now() - timedelta(hours=1),
                                        end_time=timezone.now() + timedelta(hours=1))
        join_auction(second, self.b)
        other_bid = place_bid(second.pk, self.b, "4500", uuid.uuid4()).bid
        # ...cannot ALSO be marked won, even bypassing all the Python code:
        with self.assertRaises(IntegrityError):
            Auction.objects.filter(pk=second.pk).update(status=Auction.Status.CLOSED, winning_bid=other_bid)


class WinnerEmailTests(TestCase):
    def setUp(self):
        self.auction = make_auction(make_quarter("A-021", sector="Sector 12", floor="Ground"))
        self.winner, _, _ = make_bidder(self.auction, 1)
        self.loser, _, _ = make_bidder(self.auction, 2)
        place_bid(self.auction.pk, self.loser, "4500", uuid.uuid4())
        place_bid(self.auction.pk, self.winner, "5200", uuid.uuid4())
        expire(self.auction)

    def close(self):
        with self.captureOnCommitCallbacks(execute=True):
            close_auction(self.auction.pk)
        self.auction.refresh_from_db()

    def test_winner_email_contents(self):
        self.close()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, [self.winner.email])
        self.assertIn("A-021", msg.subject)
        for text in ["Congratulations", "A-021", "Sector 12", "Ground", "750 sq ft",
                     "Rs. 5,200.00", "Next steps", self.winner.application_no]:
            self.assertIn(text, msg.body)
        self.assertIsNotNone(self.auction.winner_notified_at)

    def test_losers_not_emailed_by_default(self):
        self.close()
        self.assertEqual([m.to for m in mail.outbox], [[self.winner.email]])

    @override_settings(AUCTION_NOTIFY_LOSERS=True)
    def test_losers_emailed_once_when_enabled(self):
        self.close()
        retry_unsent_notifications()
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, sorted([self.winner.email, self.loser.email]))
        loser_mail = next(m for m in mail.outbox if m.to == [self.loser.email])
        self.assertIn("not the highest", loser_mail.body)

    def test_failed_email_is_retried_later_and_sent_once(self):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=ConnectionError("SMTP down")), \
                self.assertLogs("auctions.closing", level="ERROR"):
            self.close()
        self.assertIsNone(self.auction.winner_notified_at)  # auction closed, email pending
        self.assertEqual(self.auction.status, Auction.Status.CLOSED)

        retry_unsent_notifications()   # SMTP is back
        retry_unsent_notifications()   # and again: must not send a second email
        self.assertEqual(len(mail.outbox), 1)
        self.auction.refresh_from_db()
        self.assertIsNotNone(self.auction.winner_notified_at)


class CommandTests(TransactionTestCase):
    """TransactionTestCase: the worker runs outside any transaction, like in real life."""

    def test_close_auctions_command(self):
        auction = make_auction()
        expire(auction)
        out = StringIO()
        call_command("close_auctions", stdout=out)
        self.assertIn(f"Closed auction #{auction.pk}: CLOSED_NO_BIDS", out.getvalue())

    def test_worker_one_round(self):
        auction = make_auction()
        expire(auction)
        out = StringIO()
        call_command("run_auction_worker", rounds=1, stdout=out)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.CLOSED_NO_BIDS)

    def test_worker_survives_errors(self):
        with mock.patch("auctions.management.commands.run_auction_worker.close_due_auctions",
                        side_effect=RuntimeError("database hiccup")), \
                self.assertLogs("auctions.management.commands.run_auction_worker", level="ERROR"):
            call_command("run_auction_worker", rounds=2, stdout=StringIO())  # no crash


class ResultDisplayTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.winner, self.winner_user, _ = make_bidder(self.auction, 1)
        self.other, self.other_user, _ = make_bidder(self.auction, 2)
        place_bid(self.auction.pk, self.winner, "4700", uuid.uuid4())
        expire(self.auction)
        close_auction(self.auction.pk)

    def test_winner_sees_congratulations(self):
        self.client.force_login(self.winner_user)
        response = self.client.get(reverse("auctions:auction_room", args=[self.auction.pk]))
        self.assertContains(response, "Congratulations, you won!")
        self.assertContains(response, "4,700.00")

    def test_others_see_code_not_identity(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("auctions:auction_room", args=[self.auction.pk]))
        self.assertContains(response, "Won by <strong>Bidder 1</strong>")
        body = response.content.decode()
        for private in [self.winner.name, self.winner.urn, self.winner.email]:
            self.assertNotIn(private, body)

    def test_lobby_lists_recently_closed(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("auctions:lobby"))
        self.assertContains(response, "Recently closed (1)")
        self.assertContains(response, "Won by Bidder 1")
        self.assertNotContains(response, self.winner.name)

    def test_admin_list_shows_result_by_code(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "x"))
        response = self.client.get(reverse("admin:auctions_auction_changelist"))
        self.assertContains(response, "Rs. 4,700.00 by Bidder 1")
