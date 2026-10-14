from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.utils import timezone

from auctions.models import Auction, Quarter
from auctions.tests.factories import make_auction, make_quarter


class QuarterModelTests(TestCase):
    def test_defaults_to_vacant(self):
        self.assertEqual(make_quarter().status, Quarter.Status.VACANT)

    def test_quarter_no_is_normalised(self):
        self.assertEqual(make_quarter(quarter_no="  b-214 ").quarter_no, "B-214")

    def test_duplicate_quarter_no_rejected_case_insensitive_at_db_level(self):
        make_quarter()
        other = make_quarter(quarter_no="B-118")
        with self.assertRaises(IntegrityError):
            # .update() bypasses save(), so only the DB constraint can catch this.
            Quarter.objects.filter(pk=other.pk).update(quarter_no="b-214")

    def test_money_and_area_must_be_positive(self):
        for field in ["area_sqft", "base_rate", "emd_amount"]:
            with self.subTest(field=field), self.assertRaises(IntegrityError):
                from django.db import transaction
                with transaction.atomic():
                    make_quarter(quarter_no=f"Z-{field}", **{field: Decimal("0")})

    def test_locality(self):
        self.assertEqual(make_quarter().locality, "Sector 4, Near market")


class AuctionModelTests(TestCase):
    def test_end_time_is_start_plus_duration(self):
        start = timezone.now() + timedelta(days=1)
        auction = Auction.objects.create(quarter=make_quarter(), start_time=start, duration_minutes=7)
        self.assertEqual(auction.end_time, start + timedelta(minutes=7))
        self.assertEqual(auction.original_end_time, auction.end_time)

    @override_settings(DEFAULT_AUCTION_DURATION_MINUTES=5, DEFAULT_INCREMENT_PERCENT=Decimal("0.20"))
    def test_defaults_come_from_settings(self):
        auction = Auction.objects.create(quarter=make_quarter(), start_time=timezone.now() + timedelta(days=1))
        self.assertEqual(auction.duration_minutes, 5)
        self.assertEqual(auction.increment_percent, Decimal("0.20"))
        self.assertEqual(auction.anti_snipe_seconds, 0)   # anti-sniping off by default

    def test_creating_scheduled_auction_marks_quarter_in_auction(self):
        auction = make_auction()
        auction.quarter.refresh_from_db()
        self.assertEqual(auction.quarter.status, Quarter.Status.IN_AUCTION)

    def test_database_rules(self):
        from django.db import transaction
        for overrides in [{"lasts": timedelta(0)}, {"increment_percent": Decimal("0")}, {"duration_minutes": 0}]:
            with self.subTest(overrides=overrides), self.assertRaises(IntegrityError), transaction.atomic():
                make_auction(make_quarter(f"Z-{len(str(overrides))}"), **overrides)

    def test_only_one_scheduled_auction_per_quarter(self):
        auction = make_auction()
        with self.assertRaises(IntegrityError):
            make_auction(quarter=auction.quarter)

    def test_new_auction_allowed_after_cancel(self):
        first = make_auction()
        first.cancel()
        self.assertEqual(make_auction(quarter=first.quarter).status, Auction.Status.SCHEDULED)

    def test_cancel_frees_quarter_and_only_once(self):
        auction = make_auction()
        auction.cancel()
        auction.quarter.refresh_from_db()
        self.assertEqual(auction.quarter.status, Quarter.Status.VACANT)
        with self.assertRaises(ValidationError):
            auction.cancel()

    def test_clean_rejects_allotted_quarter_and_past_start(self):
        quarter = make_quarter(status=Quarter.Status.ALLOTTED)
        auction = Auction(quarter=quarter, start_time=timezone.now() - timedelta(hours=1), duration_minutes=5)
        with self.assertRaises(ValidationError) as ctx:
            auction.clean()
        self.assertEqual(set(ctx.exception.message_dict), {"quarter", "start_time"})

    def test_phase_follows_the_clock(self):
        auction = make_auction(starts_in=timedelta(hours=1), lasts=timedelta(minutes=5))
        start, end = auction.start_time, auction.end_time
        self.assertEqual(auction.phase(now=start - timedelta(seconds=1)), Auction.Phase.UPCOMING)
        self.assertEqual(auction.phase(now=start), Auction.Phase.LIVE)
        self.assertEqual(auction.phase(now=end - timedelta(seconds=1)), Auction.Phase.LIVE)
        self.assertEqual(auction.phase(now=end), Auction.Phase.CLOSING)
        for status in Auction.CLOSED_STATUSES:
            auction.status = status
            self.assertEqual(auction.phase(now=end), Auction.Phase.CLOSED)
        auction.status = Auction.Status.CANCELLED
        self.assertEqual(auction.phase(now=start), Auction.Phase.CANCELLED)

    def test_bid_step_is_percent_of_base_rate_in_whole_rupees(self):
        cases = [  # (base rate, percent, expected step)
            ("45000", "0.20", "90"),      # mentor's example scale: 0.2 % of 45,000
            ("4500", "0.20", "9"),        # CR #3 example
            ("36000", "0.20", "72"),
            ("12345", "0.20", "25"),      # 24.69 -> 25 (nearest rupee, ASSUMPTION)
            ("100", "0.20", "1"),         # 0.2 -> never below Rs. 1
            ("45000", "1.00", "450"),
        ]
        for base, percent, step in cases:
            with self.subTest(base=base, percent=percent):
                auction = Auction(quarter=Quarter(base_rate=Decimal(base)), increment_percent=Decimal(percent))
                self.assertEqual(auction.bid_step, Decimal(step))

    def test_minimum_next_bid_and_quick_bids(self):
        auction = make_auction()   # base rate 45,000 -> step 90
        self.assertEqual(auction.minimum_next_bid, Decimal("45000"))
        self.assertEqual(auction.quick_bid_amounts(), [(1, Decimal("45000")), (2, Decimal("45090")),
                                                       (5, Decimal("45360"))])
        auction.current_highest_bid = Decimal("46000")
        self.assertEqual(auction.minimum_next_bid, Decimal("46090"))
        self.assertEqual(auction.quick_bid_amounts(), [(1, Decimal("46090")), (2, Decimal("46180")),
                                                       (5, Decimal("46450"))])

    def test_first_bid_rounds_up_paise_in_base_rate(self):
        auction = Auction(quarter=Quarter(base_rate=Decimal("72500.50")), increment_percent=Decimal("0.20"))
        self.assertEqual(auction.minimum_next_bid, Decimal("72501"))

    def test_quarter_with_auction_cannot_be_deleted(self):
        auction = make_auction()
        with self.assertRaises(ProtectedError):
            auction.quarter.delete()
