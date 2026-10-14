"""Automatic closure, winner selection, 2-quarter cap, result emails (auctions/closing.py, emails.py)."""
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from applications import services
from applications.tests.factories import make_officer
from auctions.bidding import BidRejected, place_bid
from auctions.closing import close_auction, close_due_auctions, retry_unsent_notifications
from auctions.models import Auction, Quarter
from auctions.tests.factories import make_auction, make_bidder, make_quarter


def expire(auction):
    """Move the deadline into the past (as if time had passed)."""
    Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))
    auction.refresh_from_db()


def bid(auction, applicant, amount):
    return place_bid(auction.pk, applicant, amount, uuid.uuid4()).bid


def win(applicant, quarter_no, n=1):
    """Make `applicant` win a fresh auction (used to fill up their allotment)."""
    auction = make_auction(make_quarter(quarter_no))
    make_bidder(auction, n, applicant=applicant)
    bid(auction, applicant, "45000")
    expire(auction)
    close_auction(auction.pk)
    auction.refresh_from_db()
    assert auction.status == Auction.Status.CLOSED_WON
    return auction


class ClosureRuleTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.a, _, _ = make_bidder(self.auction, 1)
        self.b, _, _ = make_bidder(self.auction, 2)

    def test_not_closed_before_deadline(self):
        self.assertFalse(close_auction(self.auction.pk).closed_now)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.SCHEDULED)

    def test_highest_bid_wins_and_quarter_is_allotted(self):
        bid(self.auction, self.a, "45000")
        winning = bid(self.auction, self.b, "48000")
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            result = close_auction(self.auction.pk)
        self.assertTrue(result.closed_now)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.CLOSED_WON)
        self.assertEqual(self.auction.winning_bid, winning)
        self.assertEqual(self.auction.winner_participation.applicant, self.b)
        self.assertEqual(self.auction.total_bids, 2)
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
        bid(self.auction, self.a, "45000")
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

    def test_bids_after_closure_are_rejected(self):
        expire(self.auction)
        close_auction(self.auction.pk)
        with self.assertRaises(BidRejected):
            bid(self.auction, self.a, "45000")

    def test_close_due_auctions_only_touches_due_ones(self):
        later = make_auction(make_quarter("C-305"))      # still live
        expire(self.auction)
        self.assertEqual([r.auction_id for r in close_due_auctions()], [self.auction.pk])
        later.refresh_from_db()
        self.assertEqual(later.status, Auction.Status.SCHEDULED)

    def test_database_refuses_awarding_a_quarter_twice(self):
        bid(self.auction, self.a, "45000")
        expire(self.auction)
        close_auction(self.auction.pk)
        second = Auction.objects.create(quarter=self.auction.quarter, start_time=timezone.now() - timedelta(hours=1),
                                        end_time=timezone.now() + timedelta(hours=1), duration_minutes=120)
        make_bidder(second, 2, applicant=self.b)
        other_bid = bid(second, self.b, "45000")
        # ...cannot ALSO be marked won, even bypassing all the Python code:
        with self.assertRaises(IntegrityError):
            Auction.objects.filter(pk=second.pk).update(status=Auction.Status.CLOSED_WON, winning_bid=other_bid)


@override_settings(MAX_QUARTERS_PER_APPLICANT=2)
class AllotmentCapTests(TestCase):
    """CR #3: apply for many, be ALLOTTED at most 2."""

    def setUp(self):
        self.auction = make_auction(make_quarter("C-305"))
        self.top, _, _ = make_bidder(self.auction, 1)
        self.second, _, _ = make_bidder(self.auction, 2)
        self.third, _, _ = make_bidder(self.auction, 3)

    def test_capped_top_bidder_is_skipped_for_next_highest(self):
        bid(self.auction, self.third, "45000")
        second_bid = bid(self.auction, self.second, "46000")
        bid(self.auction, self.top, "47000")
        # The top bidder wins two OTHER quarters before this auction closes.
        win(self.top, "W-1")
        win(self.top, "W-2")
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            close_auction(self.auction.pk)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.status, Auction.Status.CLOSED_WON)
        self.assertEqual(self.auction.winning_bid, second_bid)          # next-highest, at THEIR bid
        self.assertEqual(mail.outbox[-1].to, [self.second.email])

    def test_skip_uses_each_bidders_highest_bid(self):
        bid(self.auction, self.second, "45000")
        bid(self.auction, self.top, "45090")
        second_best = bid(self.auction, self.second, "46000")
        bid(self.auction, self.top, "47000")
        win(self.top, "W-1")
        win(self.top, "W-2")
        expire(self.auction)
        close_auction(self.auction.pk)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.winning_bid, second_best)

    def test_no_valid_winner_when_every_bidder_is_capped_or_ineligible(self):
        bid(self.auction, self.top, "45000")
        bid(self.auction, self.second, "46000")
        win(self.top, "W-1")
        win(self.top, "W-2")
        services.suspend(self.second, make_officer(), "Investigation")
        expire(self.auction)
        with self.captureOnCommitCallbacks(execute=True):
            result = close_auction(self.auction.pk)
        self.assertEqual(result.status, Auction.Status.CLOSED_NO_VALID_WINNER)
        self.auction.refresh_from_db()
        self.assertIsNone(self.auction.winning_bid)
        self.assertEqual(self.auction.total_bids, 2)
        self.assertEqual(self.auction.quarter.status, Quarter.Status.VACANT)
        self.assertEqual(len(mail.outbox), 0)

    def test_capped_applicant_cannot_even_bid(self):
        win(self.top, "W-1")
        win(self.top, "W-2")
        with self.assertRaises(BidRejected) as ctx:
            bid(self.auction, self.top, "45000")
        self.assertIn("maximum of 2", ctx.exception.message)

    def test_one_win_still_leaves_room_for_a_second(self):
        win(self.top, "W-1")
        bid(self.auction, self.top, "45000")
        expire(self.auction)
        close_auction(self.auction.pk)
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.winner_participation.applicant, self.top)


class WinnerEmailTests(TestCase):
    def setUp(self):
        self.auction = make_auction(make_quarter("A-021", sector="Sector 12", location_block="Main road",
                                                 floor="Ground"))
        self.winner, _, _ = make_bidder(self.auction, 1)
        self.loser, _, _ = make_bidder(self.auction, 2)
        bid(self.auction, self.loser, "45000")
        bid(self.auction, self.winner, "52000")
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
        for text in ["Congratulations", "A-021", "Sector 12, Main road", "Ground", "750 sq ft",
                     "Rs. 52,000", "Next steps", self.winner.application_no]:
            self.assertIn(text, msg.body)
        for private in [self.winner.masked_aadhaar[-4:] + "X", self.winner.urn]:
            self.assertNotIn(private, msg.body)
        self.assertIsNotNone(self.auction.winner_email_sent_at)

    def test_losers_not_emailed_by_default(self):
        self.close()
        self.assertEqual([m.to for m in mail.outbox], [[self.winner.email]])

    @override_settings(AUCTION_NOTIFY_LOSERS=True)
    def test_losers_emailed_once_when_enabled(self):
        self.close()
        retry_unsent_notifications()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), sorted([self.winner.email, self.loser.email]))

    def test_failed_email_is_retried_later_and_sent_once(self):
        with mock.patch("django.core.mail.EmailMessage.send", side_effect=ConnectionError("SMTP down")), \
                self.assertLogs("auctions.closing", level="ERROR"):
            self.close()
        self.assertIsNone(self.auction.winner_email_sent_at)  # auction closed, email pending
        self.assertEqual(self.auction.status, Auction.Status.CLOSED_WON)
        retry_unsent_notifications()   # SMTP is back
        retry_unsent_notifications()   # and again: must not send a second email
        self.assertEqual(len(mail.outbox), 1)


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
        call_command("run_auction_worker", rounds=1, stdout=StringIO())
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.CLOSED_NO_BIDS)

    def test_worker_survives_errors(self):
        with mock.patch("auctions.management.commands.run_auction_worker.close_due_auctions",
                        side_effect=RuntimeError("database hiccup")), \
                self.assertLogs("auctions.management.commands.run_auction_worker", level="ERROR"):
            call_command("run_auction_worker", rounds=2, stdout=StringIO())  # no crash


class ResultDisplayTests(TestCase):
    """The result is published on the SAME auction page, by anonymous code only."""

    def setUp(self):
        self.auction = make_auction()
        self.winner, self.winner_user, _ = make_bidder(self.auction, 1)
        self.other, self.other_user, _ = make_bidder(self.auction, 2)
        bid(self.auction, self.other, "45000")
        bid(self.auction, self.winner, "47000")
        expire(self.auction)
        close_auction(self.auction.pk)
        self.url = reverse("auctions:auction_room", args=[self.auction.pk])

    def test_winner_sees_congratulations(self):
        self.client.force_login(self.winner_user)
        response = self.client.get(self.url)
        self.assertContains(response, "Congratulations, you won!")
        self.assertContains(response, "47,000")

    def test_other_users_see_code_amount_and_total_bids_only(self):
        from accounts.tests.factories import make_user
        self.client.force_login(make_user(50))   # any logged-in user, not a bidder here
        response = self.client.get(self.url)
        self.assertContains(response, "Won by <strong>Bidder 1</strong>")
        self.assertContains(response, "Total bids: 2")
        body = response.content.decode()
        for private in [self.winner.name, self.winner.urn, self.winner.email, self.winner.phone]:
            self.assertNotIn(private, body)

    def test_listing_lists_recently_closed(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("auctions:listing"))
        self.assertContains(response, "Recently closed")
        self.assertContains(response, "Won by Bidder 1")
        self.assertNotContains(response, self.winner.name)

    def test_admin_list_shows_result_by_code(self):
        self.client.force_login(User.objects.create_superuser("boss@example.com", "x", full_name="Boss"))
        response = self.client.get(reverse("admin:auctions_auction_changelist"))
        self.assertContains(response, "Rs. 47,000 by Bidder 1")
