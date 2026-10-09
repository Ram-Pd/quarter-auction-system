"""
Automatic closure of finished auctions.

close_auction() is IDEMPOTENT: it can be called any number of times, from any
number of processes at once, and the auction is still closed exactly once:

    1. lock the auction row (select_for_update): other closers wait here
    2. re-check: is it still OPEN and past its deadline? If not, do nothing
    3. pick the winner, write the result, update the quarter
    4. commit, then (and only then) broadcast + send the winner email

Who calls it:
    - run_auction_worker / close_auctions management commands (the scheduler)
    - the WebSocket consumer, when a watching browser reaches the deadline
"""
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import emails, realtime
from .models import Auction, Quarter

logger = logging.getLogger(__name__)


@dataclass
class ClosureResult:
    auction_id: int
    closed_now: bool          # False if it was already closed, not due, or cancelled
    status: str


def close_auction(auction_id, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        auction = Auction.objects.select_for_update(of=("self",)).select_related("quarter").get(pk=auction_id)

        if auction.status != Auction.Status.OPEN or now < auction.end_time:
            return ClosureResult(auction.pk, closed_now=False, status=auction.status)

        # Highest amount wins. Amounts are unique per auction, and "created_at"
        # breaks any theoretical tie in favour of the earliest bid (open question 6).
        winning_bid = auction.bids.order_by("-amount", "created_at").first()

        if winning_bid:
            auction.status = Auction.Status.CLOSED
            auction.winning_bid = winning_bid
            new_quarter_status = Quarter.Status.ALLOTTED
        else:
            auction.status = Auction.Status.CLOSED_NO_BIDS   # open question 7 placeholder
            new_quarter_status = Quarter.Status.VACANT       # quarter can be auctioned again
        auction.closed_at = now
        auction.save(update_fields=["status", "winning_bid", "closed_at", "updated_at"])
        Quarter.objects.filter(pk=auction.quarter_id).update(status=new_quarter_status)

        transaction.on_commit(lambda: _after_close(auction.pk))

    logger.info("Closed auction %s: %s", auction.pk, auction.status)
    return ClosureResult(auction.pk, closed_now=True, status=auction.status)


def _after_close(auction_id):
    """Runs after the closing transaction commits. Failures here never undo the closure."""
    auction = Auction.objects.select_related("quarter").get(pk=auction_id)
    realtime.broadcast_state(auction)
    send_pending_notifications(auction_id)


def send_pending_notifications(auction_id):
    """Winner email (and loser emails if enabled). Safe to call repeatedly."""
    try:
        emails.notify_winner(auction_id)
        emails.notify_losers(auction_id)
    except Exception:
        # The auction stays closed; the worker retries unsent emails on its next round.
        logger.exception("Sending result emails failed for auction %s", auction_id)


def close_due_auctions(now=None):
    """Close every OPEN auction whose deadline has passed. Returns the ones closed now."""
    now = now or timezone.now()
    due = Auction.objects.filter(status=Auction.Status.OPEN, end_time__lte=now).values_list("pk", flat=True)
    results = [close_auction(pk, now=now) for pk in due]
    return [r for r in results if r.closed_now]


def retry_unsent_notifications():
    """Closed auctions whose result emails failed earlier (e.g. SMTP was down)."""
    unsent = Q(winner_notified_at__isnull=True)
    if settings.AUCTION_NOTIFY_LOSERS:
        unsent |= Q(losers_notified_at__isnull=True)
    pending = Auction.objects.filter(unsent, status=Auction.Status.CLOSED)
    for pk in pending.values_list("pk", flat=True):
        send_pending_notifications(pk)
