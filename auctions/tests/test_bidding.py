"""Bidding rules (auctions/bidding.py), one rule per test."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.tests.factories import make_activated_applicant, make_applicant
from auctions.bidding import BidRejected, join_auction, place_bid
from auctions.models import Auction, Bid
from auctions.tests.factories import make_auction, make_bidder, make_quarter


def bid(auction, applicant, amount, client_bid_id=None):
    return place_bid(auction.pk, applicant, amount, client_bid_id or uuid.uuid4())


class JoinTests(TestCase):
    def setUp(self):
        self.auction = make_auction()

    def test_codes_are_numbered_per_auction(self):
        _, _, p1 = make_bidder(self.auction, 1)
        _, _, p2 = make_bidder(self.auction, 2)
        self.assertEqual((p1.anonymous_code, p2.anonymous_code), ("Bidder 1", "Bidder 2"))

    def test_same_applicant_gets_independent_codes_in_other_auctions(self):
        make_bidder(self.auction, 1)
        applicant, _, _ = make_bidder(self.auction, 2)               # Bidder 2 here
        other = make_auction(make_quarter("C-305"))
        self.assertEqual(join_auction(other, applicant).anonymous_code, "Bidder 1")  # Bidder 1 there

    def test_joining_twice_returns_same_code(self):
        applicant, _, p = make_bidder(self.auction, 1)
        self.assertEqual(join_auction(self.auction, applicant), p)

    def test_cannot_join_closed_or_cancelled(self):
        applicant, _, _ = make_bidder(make_auction(make_quarter("Z-1")), 1)
        ended = make_auction(make_quarter("Z-2"), starts_in=timedelta(hours=-2), lasts=timedelta(hours=1))
        with self.assertRaises(BidRejected):
            join_auction(ended, applicant)
        cancelled = make_auction(make_quarter("Z-3"))
        cancelled.cancel()
        with self.assertRaises(BidRejected):
            join_auction(cancelled, applicant)

    def test_unverified_applicant_cannot_join(self):
        with self.assertRaises(BidRejected) as ctx:
            join_auction(self.auction, make_applicant(9))
        self.assertEqual(ctx.exception.code, "not_eligible")


class PlaceBidTests(TestCase):
    def setUp(self):
        # Base rate 4500, increment 100, live for another hour.
        self.auction = make_auction(min_increment=Decimal("100"))
        self.a, _, self.pa = make_bidder(self.auction, 1)
        self.b, _, self.pb = make_bidder(self.auction, 2)

    def assertRejected(self, code, *args):
        with self.assertRaises(BidRejected) as ctx:
            bid(*args)
        self.assertEqual(ctx.exception.code, code)

    def test_first_bid_must_reach_base_rate(self):
        self.assertRejected("too_low", self.auction, self.a, "4499.99")
        outcome = bid(self.auction, self.a, "4500")
        self.assertEqual(outcome.bid.amount, Decimal("4500"))

    def test_next_bid_must_beat_highest_by_increment(self):
        bid(self.auction, self.a, "4500")
        self.assertRejected("too_low", self.auction, self.b, "4599")
        self.assertRejected("too_low", self.auction, self.b, "4500")   # equal bid: earliest wins
        bid(self.auction, self.b, "4600")
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal("4600"))

    def test_accepted_bid_records_audit_details(self):
        bid(self.auction, self.a, "4500")
        second = bid(self.auction, self.b, "4,750").bid   # thousands separator accepted
        self.assertEqual(second.amount, Decimal("4750"))
        self.assertEqual(second.previous_highest, Decimal("4500"))
        self.assertEqual(second.participation, self.pb)
        self.assertIsNone(second.deadline_extended_to)

    def test_cannot_outbid_yourself(self):
        bid(self.auction, self.a, "4500")
        self.assertRejected("already_highest", self.auction, self.a, "5000")

    def test_must_have_joined(self):
        outsider, _ = make_activated_applicant(3)
        self.assertRejected("not_joined", self.auction, outsider, "4500")

    def test_upcoming_closing_and_cancelled_auctions_refuse_bids(self):
        upcoming = make_auction(make_quarter("U-1"), starts_in=timedelta(hours=1))
        join_auction(upcoming, self.a)
        self.assertRejected("not_started", upcoming, self.a, "4500")

        Auction.objects.filter(pk=self.auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        self.assertRejected("closed", self.auction, self.a, "4500")

        live = make_auction(make_quarter("L-1"))
        join_auction(live, self.a)
        live.cancel()
        self.assertRejected("closed", live, self.a, "4500")

    def test_invalid_amounts(self):
        for raw in ["abc", "", "-100", "0", "4500.123", "1e12", "NaN"]:
            with self.subTest(raw=raw):
                self.assertRejected("invalid_amount", self.auction, self.a, raw)
        self.assertEqual(Bid.objects.count(), 0)

    def test_invalid_client_bid_id(self):
        with self.assertRaises(BidRejected) as ctx:
            place_bid(self.auction.pk, self.a, "4500", "not-a-uuid")
        self.assertEqual(ctx.exception.code, "invalid_request")

    def test_duplicate_submission_is_not_a_second_bid(self):
        client_id = uuid.uuid4()
        first = bid(self.auction, self.a, "4500", client_id)
        again = bid(self.auction, self.a, "4500", client_id)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.bid.pk, first.bid.pk)
        self.assertEqual(Bid.objects.count(), 1)


class AntiSnipingTests(TestCase):
    def setUp(self):
        self.applicant = make_bidder(make_auction(make_quarter("X-0")), 1)[0]

    def live_auction(self, ends_in, extension=timedelta(minutes=2)):
        auction = make_auction(make_quarter(f"Q-{uuid.uuid4().hex[:6]}"), starts_in=timedelta(hours=-1),
                               lasts=timedelta(hours=1) + ends_in, anti_snipe_extension=extension)
        join_auction(auction, self.applicant)
        return auction

    def test_bid_in_final_minute_extends_deadline(self):
        auction = self.live_auction(ends_in=timedelta(seconds=30))
        before = timezone.now()
        outcome = bid(auction, self.applicant, "4500")
        auction.refresh_from_db()
        self.assertTrue(outcome.extended)
        self.assertGreaterEqual(auction.end_time, before + timedelta(minutes=2))
        self.assertEqual(outcome.bid.deadline_extended_to, auction.end_time)
        self.assertLess(auction.original_end_time, auction.end_time)  # scheduled end kept for audit

    def test_bid_earlier_does_not_extend(self):
        auction = self.live_auction(ends_in=timedelta(minutes=5))
        end_before = auction.end_time
        self.assertFalse(bid(auction, self.applicant, "4500").extended)
        auction.refresh_from_db()
        self.assertEqual(auction.end_time, end_before)

    def test_extension_never_shortens_deadline(self):
        # 50 s left but extension only 10 s: now+10 s is EARLIER than the deadline.
        auction = self.live_auction(ends_in=timedelta(seconds=50), extension=timedelta(seconds=10))
        end_before = auction.end_time
        self.assertFalse(bid(auction, self.applicant, "4500").extended)
        auction.refresh_from_db()
        self.assertEqual(auction.end_time, end_before)

    def test_zero_extension_disables_anti_sniping(self):
        auction = self.live_auction(ends_in=timedelta(seconds=30), extension=timedelta(0))
        self.assertFalse(bid(auction, self.applicant, "4500").extended)


class BroadcastTimingTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.applicant = make_bidder(self.auction, 1)[0]

    def test_broadcast_only_after_commit(self):
        with mock.patch("auctions.realtime.broadcast_bid") as broadcast:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                outcome = bid(self.auction, self.applicant, "4500")
                broadcast.assert_not_called()       # not yet: still inside the transaction
            self.assertEqual(len(callbacks), 1)
        broadcast.assert_called_once_with(outcome.bid.pk)

    def test_rejected_bid_is_not_broadcast(self):
        with mock.patch("auctions.realtime.broadcast_bid") as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(BidRejected):
                    bid(self.auction, self.applicant, "1")
        broadcast.assert_not_called()


class OneQuarterAtATimeTests(TestCase):
    """Rule 7: while you have bids in an open auction, you can't bid in another."""

    def setUp(self):
        self.first = make_auction(make_quarter("B-214"))
        self.second = make_auction(make_quarter("C-305"))
        self.applicant, _, _ = make_bidder(self.first, 1)
        join_auction(self.second, self.applicant)
        self.rival, _, _ = make_bidder(self.first, 2)

    def test_cannot_bid_on_second_quarter_while_first_is_open(self):
        bid(self.first, self.applicant, "4500")
        with self.assertRaises(BidRejected) as ctx:
            bid(self.second, self.applicant, "4500")
        self.assertEqual(ctx.exception.code, "one_quarter_at_a_time")
        self.assertIn("B-214", ctx.exception.message)

    def test_still_allowed_to_keep_bidding_on_the_same_quarter(self):
        bid(self.first, self.applicant, "4500")
        bid(self.first, self.rival, "4600")
        self.assertEqual(bid(self.first, self.applicant, "4700").bid.amount, Decimal("4700"))

    def test_joining_and_watching_other_auctions_is_fine(self):
        bid(self.first, self.applicant, "4500")
        third = make_auction(make_quarter("D-407"))
        self.assertEqual(join_auction(third, self.applicant).anonymous_code, "Bidder 1")

    def test_free_again_after_first_auction_closes(self):
        from auctions.closing import close_auction
        bid(self.first, self.applicant, "4500")
        Auction.objects.filter(pk=self.first.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        close_auction(self.first.pk)
        self.assertEqual(bid(self.second, self.applicant, "4500").bid.amount, Decimal("4500"))

    def test_free_again_after_first_auction_is_cancelled(self):
        bid(self.first, self.applicant, "4500")
        self.first.cancel()
        self.assertEqual(bid(self.second, self.applicant, "4500").bid.amount, Decimal("4500"))

    def test_joined_but_never_bid_does_not_count(self):
        # Joined `first` but no bid there yet: bidding on `second` is allowed.
        self.assertEqual(bid(self.second, self.applicant, "4500").bid.amount, Decimal("4500"))

    @override_settings(AUCTION_ONE_QUARTER_AT_A_TIME=False)
    def test_rule_can_be_switched_off(self):
        bid(self.first, self.applicant, "4500")
        self.assertEqual(bid(self.second, self.applicant, "4500").bid.amount, Decimal("4500"))

    def test_pages_warn_in_advance(self):
        from django.urls import reverse
        bid(self.first, self.applicant, "4500")
        self.client.force_login(self.applicant.user)
        lobby = self.client.get(reverse("auctions:lobby"))
        self.assertContains(lobby, "You are bidding for quarter")
        self.assertContains(lobby, "Bidding here")
        room = self.client.get(reverse("auctions:auction_room", args=[self.second.pk]))
        self.assertContains(room, "You are already bidding for quarter")
