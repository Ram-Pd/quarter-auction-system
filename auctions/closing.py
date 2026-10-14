"""
Automatic closure of finished auctions.

close_auction() is IDEMPOTENT: it can be called any number of times, from any
number of processes at once, and the auction is still closed exactly once:

    1. lock the auction row (select_for_update): other closers wait here
    2. re-check: is it still SCHEDULED and past its deadline? If not, do nothing
    3. lock every bidder's Applicant row (always in id order: no deadlocks)
    4. pick the winner: highest bid whose bidder is still eligible AND holds
       fewer than MAX_QUARTERS_PER_APPLICANT quarters; otherwise the next highest
    5. write the result, update the quarter
    6. commit, then (and only then) broadcast + send the winner email

Why step 3: two auctions closing at the same moment might both pick the same
applicant, who holds 1 quarter, giving them 3. The applicant lock makes the
second closure wait until the first commits; it then counts 2 and skips them.

Outcomes:
    CLOSED_WON              a valid winner         -> quarter ALLOTTED
    CLOSED_NO_BIDS          nobody bid             -> quarter VACANT
    CLOSED_NO_VALID_WINNER  bids, but every bidder was capped out or no longer
                            eligible               -> quarter VACANT

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

from applications import eligibility
from applications.models import Applicant

from . import emails, realtime
from .models import Auction, Quarter

logger = logging.getLogger(__name__)


@dataclass
class ClosureResult:
    auction_id: int
    closed_now: bool          # False if it was already closed, not due, or cancelled
    status: str


def pick_winning_bid(auction):
    """
    The highest bid from a bidder who may still win, or None.
    Call inside the closing transaction, after the bidders' rows are locked.

    Ties: amounts are unique per auction (DB constraint), and "created_at"
    breaks any theoretical tie in favour of the earliest bid (open question 6).
    """
    skipped = set()
    for bid in auction.bids.select_related("participation__applicant").order_by("-amount", "created_at"):
        applicant = bid.participation.applicant
        if applicant.pk in skipped:
            continue
        # The SAME rules as bidding (applications/eligibility.py), including the
        # 2-quarter cap. ASSUMPTION (CR #3 open question 7): if the top bidder
        # can't win, the next-highest eligible bidder wins at THEIR highest bid.
        if eligibility.check(applicant, auction.quarter).allowed:
            return bid
        skipped.add(applicant.pk)
    return None


def close_auction(auction_id, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        auction = Auction.objects.select_for_update(of=("self",)).select_related("quarter").get(pk=auction_id)

        if auction.status != Auction.Status.SCHEDULED or now < auction.end_time:
            return ClosureResult(auction.pk, closed_now=False, status=auction.status)

        # Lock all bidders of this auction, in id order (the same order in every
        # process, so two closers can never wait for each other in a circle).
        bidder_ids = auction.bids.values_list("participation__applicant_id", flat=True)
        list(Applicant.objects.select_for_update().filter(pk__in=bidder_ids).order_by("pk")
             .values_list("pk", flat=True))

        winning_bid = pick_winning_bid(auction)
        if winning_bid:
            auction.status = Auction.Status.CLOSED_WON
            new_quarter_status = Quarter.Status.ALLOTTED
        elif auction.bids.exists():
            auction.status = Auction.Status.CLOSED_NO_VALID_WINNER
            new_quarter_status = Quarter.Status.VACANT
        else:
            auction.status = Auction.Status.CLOSED_NO_BIDS   # open question 7 placeholder
            new_quarter_status = Quarter.Status.VACANT       # quarter can be auctioned again
        auction.winning_bid = winning_bid
        auction.closed_at = now
        auction.total_bids = auction.bids.count()
        auction.save(update_fields=["status", "winning_bid", "closed_at", "total_bids", "updated_at"])
        Quarter.objects.filter(pk=auction.quarter_id).update(status=new_quarter_status)

        transaction.on_commit(lambda: _after_close(auction.pk))

    logger.info("Closed auction %s: %s", auction.pk, auction.status)
    return ClosureResult(auction.pk, closed_now=True, status=auction.status)


def _after_close(auction_id):
    """Runs after the closing transaction commits. Failures here never undo the closure."""
    auction = Auction.objects.select_related("quarter", "winning_bid__participation").get(pk=auction_id)
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
    """Close every SCHEDULED auction whose deadline has passed. Returns the ones closed now."""
    now = now or timezone.now()
    due = (Auction.objects.filter(status=Auction.Status.SCHEDULED, end_time__lte=now)
           .order_by("end_time").values_list("pk", flat=True))
    results = [close_auction(pk, now=now) for pk in due]
    return [r for r in results if r.closed_now]


def retry_unsent_notifications():
    """Won auctions whose result emails failed earlier (e.g. SMTP was down)."""
    unsent = Q(winner_email_sent_at__isnull=True)
    if settings.AUCTION_NOTIFY_LOSERS:
        unsent |= Q(losers_notified_at__isnull=True)
    pending = Auction.objects.filter(unsent, status=Auction.Status.CLOSED_WON)
    for pk in pending.values_list("pk", flat=True):
        send_pending_notifications(pk)
