"""Helpers that build test data. Import these in any test module."""
import math
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from applications.tests.factories import make_eligible_applicant, make_eligible_for
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
        "base_rate": Decimal("45000"),   # step at the default 0.20 % = Rs. 90
        "emd_amount": Decimal("9000"),
    }
    data.update(overrides)
    return Quarter.objects.create(**data)


def make_auction(quarter=None, starts_in=timedelta(minutes=-5), lasts=timedelta(hours=1), **overrides):
    """
    Saved auction. Default: started 5 minutes ago, lasts 1 hour (so it is LIVE).
    Use starts_in=timedelta(hours=1) for an upcoming auction. `lasts` may be any
    timedelta (seconds too): the deadline is set exactly to start + lasts.
    """
    quarter = quarter or make_quarter()
    start = timezone.now() + starts_in
    data = {"quarter": quarter, "start_time": start, "end_time": start + lasts,
            "duration_minutes": max(1, math.ceil(lasts.total_seconds() / 60))}
    data.update(overrides)
    return Auction.objects.create(**data)


def make_bidder(auction, n, applicant=None):
    """
    An applicant ELIGIBLE for this auction's quarter (ACTIVE + EMD verified) who
    has joined it. Pass `applicant` to reuse one across auctions.
    Returns (applicant, user, participation).
    """
    if applicant is None:
        applicant = make_eligible_applicant(n, [auction.quarter])
    elif not applicant.quarter_applications.filter(quarter=auction.quarter, emd_verified=True).exists():
        make_eligible_for(applicant, auction.quarter)
    return applicant, applicant.user, join_auction(auction, applicant)
