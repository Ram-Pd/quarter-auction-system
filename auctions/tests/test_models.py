from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from auctions.models import Auction, Quarter
from auctions.tests.factories import make_auction, make_quarter


class QuarterModelTests(TestCase):
    def test_defaults_to_vacant(self):
        self.assertEqual(make_quarter().status, Quarter.Status.VACANT)

    def test_quarter_no_is_normalised(self):
        q = make_quarter(quarter_no="  b-214 ")
        self.assertEqual(q.quarter_no, "B-214")

    def test_duplicate_quarter_no_rejected(self):
        make_quarter()
        with self.assertRaises(IntegrityError):
            make_quarter()

    def test_duplicate_quarter_no_rejected_case_insensitive_at_db_level(self):
        make_quarter()
        # .update() bypasses save(), so only the DB constraint can catch this.
        other = make_quarter(quarter_no="B-118")
        with self.assertRaises(IntegrityError):
            Quarter.objects.filter(pk=other.pk).update(quarter_no="b-214")

    def test_area_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            make_quarter(area_sqft=Decimal("0"))

    def test_base_rate_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            make_quarter(base_rate=Decimal("-100"))

    def test_str(self):
        self.assertEqual(str(make_quarter()), "B-214")


class AuctionModelTests(TestCase):
    def test_creating_open_auction_marks_quarter_in_auction(self):
        auction = make_auction()
        auction.quarter.refresh_from_db()
        self.assertEqual(auction.quarter.status, Quarter.Status.IN_AUCTION)

    def test_end_must_be_after_start(self):
        with self.assertRaises(IntegrityError):
            make_auction(lasts=timedelta(0))

    def test_min_increment_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            make_auction(min_increment=Decimal("0"))

    def test_only_one_open_auction_per_quarter(self):
        auction = make_auction()
        with self.assertRaises(IntegrityError):
            make_auction(quarter=auction.quarter)

    def test_new_auction_allowed_after_cancel(self):
        first = make_auction()
        first.cancel()
        second = make_auction(quarter=first.quarter)
        self.assertEqual(second.status, Auction.Status.OPEN)

    def test_cancel_frees_quarter(self):
        auction = make_auction()
        auction.cancel()
        auction.quarter.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.CANCELLED)
        self.assertEqual(auction.quarter.status, Quarter.Status.VACANT)

    def test_cannot_cancel_twice(self):
        auction = make_auction()
        auction.cancel()
        with self.assertRaises(ValidationError):
            auction.cancel()

    def test_clean_rejects_allotted_quarter_and_past_end(self):
        quarter = make_quarter(status=Quarter.Status.ALLOTTED)
        now = timezone.now()
        auction = Auction(quarter=quarter, start_time=now - timedelta(hours=2),
                          end_time=now - timedelta(hours=1))
        with self.assertRaises(ValidationError) as ctx:
            auction.full_clean()
        self.assertIn("quarter", ctx.exception.message_dict)
        self.assertIn("end_time", ctx.exception.message_dict)

    def test_phase_follows_the_clock(self):
        auction = make_auction(starts_in=timedelta(hours=1), lasts=timedelta(hours=1))
        start, end = auction.start_time, auction.end_time
        self.assertEqual(auction.phase(now=start - timedelta(seconds=1)), Auction.Phase.UPCOMING)
        self.assertEqual(auction.phase(now=start), Auction.Phase.LIVE)
        self.assertEqual(auction.phase(now=end - timedelta(seconds=1)), Auction.Phase.LIVE)
        self.assertEqual(auction.phase(now=end), Auction.Phase.CLOSING)
        auction.status = Auction.Status.CLOSED_NO_BIDS
        self.assertEqual(auction.phase(now=end), Auction.Phase.CLOSED)
        auction.status = Auction.Status.CANCELLED
        self.assertEqual(auction.phase(now=start), Auction.Phase.CANCELLED)

    def test_minimum_next_bid(self):
        auction = make_auction(min_increment=Decimal("250"))
        self.assertEqual(auction.minimum_next_bid, Decimal("4500"))  # base rate
        auction.current_highest_bid = Decimal("5000")
        self.assertEqual(auction.minimum_next_bid, Decimal("5250"))

    def test_quarter_with_auction_cannot_be_deleted(self):
        auction = make_auction()
        with self.assertRaises(ProtectedError):
            auction.quarter.delete()
