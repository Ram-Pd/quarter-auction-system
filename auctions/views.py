from django.shortcuts import render
from django.utils import timezone

from accounts.decorators import applicant_required

from .models import Auction


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

    sections = {Auction.Phase.LIVE: [], Auction.Phase.CLOSING: [], Auction.Phase.UPCOMING: []}
    for auction in open_auctions:
        auction.current_phase = auction.phase(now)  # compute once per request
        sections[auction.current_phase].append(auction)

    return render(request, "auctions/lobby.html", {
        "live": sections[Auction.Phase.LIVE] + sections[Auction.Phase.CLOSING],
        "upcoming": sorted(sections[Auction.Phase.UPCOMING], key=lambda a: a.start_time),
        "server_now": now,
    })
