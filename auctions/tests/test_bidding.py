"""Bidding rules (auctions/bidding.py), one rule per test. Base rate 45,000 -> step Rs. 90."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from applications import services
from applications.tests.factories import make_applicant, make_officer
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
        applicant, _, _ = make_bidder(self.auction, 2)                      # Bidder 2 here
        other = make_auction(make_quarter("C-305"))
        _, _, there = make_bidder(other, 2, applicant=applicant)
        self.assertEqual(there.anonymous_code, "Bidder 1")                   # Bidder 1 there

    def test_joining_twice_returns_same_code(self):
        applicant, _, p = make_bidder(self.auction, 1)
        self.assertEqual(join_auction(self.auction, applicant), p)

    def test_cannot_join_closed_or_cancelled(self):
        applicant, _, _ = make_bidder(make_auction(make_quarter("Z-1")), 1)
        ended = make_auction(make_quarter("Z-2"), starts_in=timedelta(hours=-2), lasts=timedelta(hours=1))
        with self.assertRaises(BidRejected):
            join_auction(ended, applicant)

    def test_only_eligible_applicants_get_a_code(self):
        officer = make_officer()
        not_active = make_applicant(8, [self.auction.quarter])
        with self.assertRaises(BidRejected) as ctx:
            join_auction(self.auction, not_active)
        self.assertEqual(ctx.exception.code, "not_eligible")
        # ACTIVE, but EMD verified only for ANOTHER quarter: still no right to this one.
        other = make_quarter("Q-9")
        applicant = make_applicant(9, [self.auction.quarter, other])
        from applications.tests.factories import activate
        activate(applicant, officer, verify_quarters=[other])
        with self.assertRaises(BidRejected):
            join_auction(self.auction, applicant)


class PlaceBidTests(TestCase):
    def setUp(self):
        self.auction = make_auction()   # live, base 45,000, step 90
        self.a, _, self.pa = make_bidder(self.auction, 1)
        self.b, _, self.pb = make_bidder(self.auction, 2)

    def assertRejected(self, code, *args):
        with self.assertRaises(BidRejected) as ctx:
            bid(*args)
        self.assertEqual(ctx.exception.code, code)

    def test_first_bid_must_reach_base_rate(self):
        self.assertRejected("too_low", self.auction, self.a, "44999")
        self.assertEqual(bid(self.auction, self.a, "45000").bid.amount, Decimal("45000"))

    def test_next_bid_must_beat_highest_by_one_step(self):
        bid(self.auction, self.a, "45000")
        self.assertRejected("too_low", self.auction, self.b, "45089")
        self.assertRejected("too_low", self.auction, self.b, "45000")   # equal bid: earliest wins
        bid(self.auction, self.b, "45090")
        self.auction.refresh_from_db()
        self.assertEqual(self.auction.current_highest_bid, Decimal("45090"))
        self.assertEqual(self.auction.total_bids, 2)

    def test_any_amount_above_one_step_is_fine(self):
        # ASSUMPTION (open question 5): need not be a multiple of the step.
        bid(self.auction, self.a, "45000")
        self.assertEqual(bid(self.auction, self.b, "45,123").bid.amount, Decimal("45123"))

    def test_quick_bid_amounts_are_accepted(self):
        bid(self.auction, self.a, "45000")
        self.auction.refresh_from_db()
        amounts = dict(self.auction.quick_bid_amounts())
        self.assertEqual(amounts, {1: Decimal("45090"), 2: Decimal("45180"), 5: Decimal("45450")})
        self.assertEqual(bid(self.auction, self.b, str(amounts[5])).bid.amount, Decimal("45450"))

    def test_whole_rupees_only(self):
        self.assertRejected("invalid_amount", self.auction, self.a, "45000.50")
        self.assertEqual(bid(self.auction, self.a, "45000.00").bid.amount, Decimal("45000"))

    def test_accepted_bid_records_audit_details(self):
        bid(self.auction, self.a, "45000")
        second = bid(self.auction, self.b, "45,500").bid
        self.assertEqual((second.amount, second.previous_highest, second.participation),
                         (Decimal("45500"), Decimal("45000"), self.pb))
        self.assertIsNone(second.deadline_extended_to)

    def test_cannot_outbid_yourself(self):
        bid(self.auction, self.a, "45000")
        self.assertRejected("already_highest", self.auction, self.a, "50000")

    def test_must_have_a_code_in_this_auction(self):
        other = make_auction(make_quarter("C-305"))
        outsider, _, _ = make_bidder(other, 3)
        self.assertRejected("not_joined", self.auction, outsider, "45000")

    def test_suspended_mid_auction_cannot_bid(self):
        bid(self.auction, self.a, "45000")
        services.suspend(self.b, make_officer(), "Under review")
        # self.b is the stale in-memory copy (like an open WebSocket holds): still refused.
        self.assertRejected("not_eligible", self.auction, self.b, "46000")

    def test_emd_unverified_mid_auction_cannot_bid(self):
        application = self.b.quarter_applications.get(quarter=self.auction.quarter)
        services.unverify_emd(application, make_officer(), "Bounced payment")
        self.assertRejected("not_eligible", self.auction, self.b, "45000")

    def test_upcoming_closing_and_cancelled_auctions_refuse_bids(self):
        upcoming = make_auction(make_quarter("U-1"), starts_in=timedelta(hours=1))
        make_bidder(upcoming, 1, applicant=self.a)
        self.assertRejected("not_started", upcoming, self.a, "45000")

        Auction.objects.filter(pk=self.auction.pk).update(end_time=timezone.now() - timedelta(seconds=1))
        self.assertRejected("closed", self.auction, self.a, "45000")

        live = make_auction(make_quarter("L-1"))
        make_bidder(live, 1, applicant=self.a)
        live.cancel()
        self.assertRejected("closed", live, self.a, "45000")

    def test_invalid_amounts(self):
        for raw in ["abc", "", "-100", "0", "45000.123", "1e12", "NaN"]:
            with self.subTest(raw=raw):
                self.assertRejected("invalid_amount", self.auction, self.a, raw)
        self.assertEqual(Bid.objects.count(), 0)

    def test_invalid_client_bid_id(self):
        with self.assertRaises(BidRejected) as ctx:
            place_bid(self.auction.pk, self.a, "45000", "not-a-uuid")
        self.assertEqual(ctx.exception.code, "invalid_request")

    def test_duplicate_submission_is_not_a_second_bid(self):
        client_id = uuid.uuid4()
        first = bid(self.auction, self.a, "45000", client_id)
        again = bid(self.auction, self.a, "45000", client_id)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.bid.pk, first.bid.pk)
        self.assertEqual(Bid.objects.count(), 1)

    def test_applicant_may_bid_in_several_auctions_at_once(self):
        # The old "one quarter at a time" rule is gone (CR #3): the cap applies to WINNING.
        other = make_auction(make_quarter("C-305"))
        make_bidder(other, 1, applicant=self.a)
        bid(self.auction, self.a, "45000")
        self.assertEqual(bid(other, self.a, "45000").bid.amount, Decimal("45000"))


@override_settings(AUCTION_MAX_EXTENSIONS=2)
class AntiSnipingTests(TestCase):
    def setUp(self):
        self.base = make_auction(make_quarter("X-0"))
        self.a = make_bidder(self.base, 1)[0]
        self.b = make_bidder(self.base, 2)[0]

    def live_auction(self, ends_in, seconds):
        auction = make_auction(make_quarter(f"Q-{uuid.uuid4().hex[:6]}"), starts_in=timedelta(minutes=-4),
                               lasts=timedelta(minutes=4) + ends_in, anti_snipe_seconds=seconds)
        make_bidder(auction, 1, applicant=self.a)
        make_bidder(auction, 2, applicant=self.b)
        return auction

    def test_off_by_default(self):
        auction = self.live_auction(ends_in=timedelta(seconds=5), seconds=0)
        self.assertFalse(bid(auction, self.a, "45000").extended)

    def test_bid_in_last_n_seconds_extends_to_now_plus_n(self):
        auction = self.live_auction(ends_in=timedelta(seconds=10), seconds=30)
        before = timezone.now()
        outcome = bid(auction, self.a, "45000")
        auction.refresh_from_db()
        self.assertTrue(outcome.extended)
        self.assertGreaterEqual(auction.end_time, before + timedelta(seconds=30))
        self.assertEqual(outcome.bid.deadline_extended_to, auction.end_time)
        self.assertLess(auction.original_end_time, auction.end_time)  # scheduled end kept for audit
        self.assertEqual(auction.extensions_count, 1)

    def test_bid_earlier_does_not_extend(self):
        auction = self.live_auction(ends_in=timedelta(minutes=2), seconds=30)
        self.assertFalse(bid(auction, self.a, "45000").extended)

    def test_extensions_are_capped(self):
        auction = self.live_auction(ends_in=timedelta(seconds=10), seconds=30)
        amounts = iter(range(45000, 50000, 100))
        bidders = [self.a, self.b]
        for i in range(2):
            # Make the deadline close again, then bid.
            Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() + timedelta(seconds=10))
            self.assertTrue(bid(auction, bidders[i % 2], str(next(amounts))).extended)
        Auction.objects.filter(pk=auction.pk).update(end_time=timezone.now() + timedelta(seconds=10))
        self.assertFalse(bid(auction, self.a, str(next(amounts))).extended)   # cap of 2 reached
        auction.refresh_from_db()
        self.assertEqual(auction.extensions_count, 2)


class BroadcastTimingTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.applicant = make_bidder(self.auction, 1)[0]

    def test_broadcast_only_after_commit(self):
        with mock.patch("auctions.realtime.broadcast_bid") as broadcast:
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                outcome = bid(self.auction, self.applicant, "45000")
                broadcast.assert_not_called()       # not yet: still inside the transaction
            self.assertEqual(len(callbacks), 1)
        broadcast.assert_called_once_with(outcome.bid.pk)

    def test_rejected_bid_is_not_broadcast(self):
        with mock.patch("auctions.realtime.broadcast_bid") as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(BidRejected):
                    bid(self.auction, self.applicant, "1")
        broadcast.assert_not_called()
