"""Helpers that build test data. Import these in any test module."""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from accounts.tests.factories import make_activated_applicant
from auctions.bidding import join_auction
from auctions.models import Auction, Quarter


def make_quarter(quarter_no="B-214", **overrides):
    data = {
        "quarter_no": quarter_no,
        "sector": "Sector 4",
        "location_block": "Near market",
        "quarter_type": Quarter.QuarterType.B,
        "floor": "2nd",
        "area_sqft": Decimal("750"),
        "base_rate": Decimal("4500"),
    }
    data.update(overrides)
    return Quarter.objects.create(**data)


def make_auction(quarter=None, starts_in=timedelta(minutes=-5), lasts=timedelta(hours=1), **overrides):
    """
    Saved auction. Default: started 5 minutes ago, lasts 1 hour (so it is LIVE).
    Use starts_in=timedelta(hours=1) for an upcoming auction.
    """
    quarter = quarter or make_quarter()
    start = timezone.now() + starts_in
    data = {"quarter": quarter, "start_time": start, "end_time": start + lasts}
    data.update(overrides)
    return Auction.objects.create(**data)


def make_bidder(auction, n):
    """An activated applicant who has joined `auction`. Returns (applicant, user, participation)."""
    applicant, user = make_activated_applicant(n)
    return applicant, user, join_auction(auction, applicant)
