"""
Pages about quarters and auctions.

    home          /                    public: introduction, rules, FAQ (NO quarter data)
    listing       /auctions/           logged in: every quarter with EMD and slot,
                                       your registration status and eligibility
    auction_room  /auctions/<id>/      logged in: one auction (watch live); eligible
                                       bidders also get the bid panel; result shown here

Quarter information is shown only to logged-in users (decision 2026-10-14).

PRIVACY: these pages show quarter and price data, anonymous bidder codes and
the user's OWN status only. Never another person's identity.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from applications import eligibility
from applications.models import Applicant
from applications.services import application_window_open

from . import realtime
from .bidding import BidRejected, join_auction
from .models import Auction, Participation


def _with_phase(auctions, now):
    for auction in auctions:
        auction.current_phase = auction.phase(now)  # compute once per request
    return auctions


def _recently_closed(now):
    return (Auction.objects
            .filter(status__in=Auction.CLOSED_STATUSES,
                    closed_at__gte=now - timedelta(days=settings.AUCTION_RECENTLY_CLOSED_DAYS))
            .select_related("quarter", "winning_bid__participation")
            .order_by("-closed_at"))


def home(request):
    """Public home page: introduction, rules and FAQ. Quarters are listed only after login."""
    return render(request, "home.html")


@login_required
def listing(request):
    """
    After login: every quarter up for auction, with EMD and bidding slot, plus
    this user's registration status and which quarters they may bid on.
    """
    now = timezone.now()
    applicant = Applicant.for_user(request.user)
    applied_ids = set(applicant.quarter_applications.values_list("quarter_id", flat=True)) if applicant else set()
    eligible_ids = applicant.eligible_quarter_ids() if applicant else set()
    capped = applicant is not None and eligibility.has_reached_allotment_limit(applicant)

    auctions = _with_phase(Auction.objects.filter(status=Auction.Status.SCHEDULED)
                           .select_related("quarter").order_by("start_time"), now)
    for auction in auctions:
        auction.applied = auction.quarter_id in applied_ids
        auction.eligible = auction.quarter_id in eligible_ids and not capped
        auction.can_apply = application_window_open(auction, now)

    return render(request, "auctions/listing.html", {
        "applicant": applicant,
        "auctions": auctions,
        "eligible_count": sum(1 for a in auctions if a.eligible),
        "recently_closed": _recently_closed(now),
        "server_now": now,
        "max_quarters": settings.MAX_QUARTERS_PER_APPLICANT,
        "allotted": eligibility.allotted_count(applicant) if applicant else 0,
    })


@login_required
def auction_room(request, auction_id):
    """
    One auction's page. Any logged-in user may view it (live highest bid, history by code,
    and the result once closed). Only an ELIGIBLE applicant gets a "Bidder N"
    code (created here on the first visit) and the bid panel.
    """
    auction = get_object_or_404(Auction.objects.select_related("quarter", "winning_bid__participation"),
                                pk=auction_id)
    phase = auction.phase()
    applicant = Applicant.for_user(request.user)
    allowed = eligibility.check_user(request.user, auction.quarter)

    participation = None
    if applicant:
        participation = Participation.objects.filter(auction=auction, applicant=applicant).first()
        if participation is None and allowed.allowed and phase in (Auction.Phase.UPCOMING, Auction.Phase.LIVE):
            try:
                participation = join_auction(auction, applicant)
            except BidRejected:
                participation = None
    can_bid = participation is not None and allowed.allowed

    return render(request, "auctions/auction_room.html", {
        "auction": auction,
        "phase": phase,
        "participation": participation,
        "can_bid": can_bid,
        "not_eligible_reason": "" if can_bid else allowed.reason,
        # The same snapshot the WebSocket sends, so the page is correct even before it connects.
        "initial_state": realtime.snapshot(auction, participation if can_bid else None),
        "your_code": participation.anonymous_code if participation else None,
    })
