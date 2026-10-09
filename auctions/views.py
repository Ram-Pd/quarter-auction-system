from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import applicant_required
from accounts.models import Applicant

from . import realtime
from .bidding import BidRejected, join_auction
from .models import Auction, Participation


def _applicant_for(user):
    """The activated applicant behind a login, or None (e.g. staff)."""
    return Applicant.objects.filter(user=user, is_activated=True).first()


@applicant_required
def lobby(request):
    """
    List open auctions, split into "Live now" and "Upcoming".
    Shows quarter details and prices only: never anything about bidders.
    """
    now = timezone.now()
    open_auctions = (Auction.objects.filter(status=Auction.Status.OPEN)
                     .select_related("quarter")
                     .order_by("end_time"))

    applicant = _applicant_for(request.user)
    joined_ids = set(Participation.objects.filter(applicant=applicant).values_list("auction_id", flat=True)
                     ) if applicant else set()

    sections = {Auction.Phase.LIVE: [], Auction.Phase.CLOSING: [], Auction.Phase.UPCOMING: []}
    for auction in open_auctions:
        auction.current_phase = auction.phase(now)  # compute once per request
        auction.joined = auction.pk in joined_ids
        sections[auction.current_phase].append(auction)

    recently_closed = (Auction.objects
                       .filter(status__in=[Auction.Status.CLOSED, Auction.Status.CLOSED_NO_BIDS],
                               closed_at__gte=now - timedelta(days=settings.AUCTION_RECENTLY_CLOSED_DAYS))
                       .select_related("quarter", "winning_bid__participation")
                       .order_by("-closed_at"))

    return render(request, "auctions/lobby.html", {
        "live": sections[Auction.Phase.LIVE] + sections[Auction.Phase.CLOSING],
        "upcoming": sorted(sections[Auction.Phase.UPCOMING], key=lambda a: a.start_time),
        "recently_closed": recently_closed,
        "server_now": now,
    })


@applicant_required
def auction_room(request, auction_id):
    """The bidding page for one auction. Live updates come over the WebSocket."""
    auction = get_object_or_404(Auction.objects.select_related("quarter"), pk=auction_id)
    applicant = _applicant_for(request.user)
    participation = (Participation.objects.filter(auction=auction, applicant=applicant).first()
                     if applicant else None)
    phase = auction.phase()
    return render(request, "auctions/auction_room.html", {
        "auction": auction,
        "phase": phase,
        "participation": participation,
        "can_join": bool(applicant) and participation is None
                    and phase in (Auction.Phase.UPCOMING, Auction.Phase.LIVE),
        "is_watcher": participation is None and request.user.is_staff,
        # The same snapshot the WebSocket sends, so the page is correct even before it connects.
        "initial_state": realtime.snapshot(auction, participation),
    })


@require_POST
@applicant_required
def join(request, auction_id):
    auction = get_object_or_404(Auction, pk=auction_id)
    applicant = _applicant_for(request.user)
    if applicant is None:
        raise PermissionDenied  # staff accounts watch, they don't bid
    try:
        participation = join_auction(auction, applicant)
    except BidRejected as rejected:
        messages.error(request, rejected.message)
    else:
        messages.success(request, f"You have joined this auction as {participation.anonymous_code}. "
                                  "Other bidders only ever see this code, never your name.")
    return redirect("auctions:auction_room", auction_id=auction.pk)
