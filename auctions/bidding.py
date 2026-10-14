"""
Bidding rules: joining an auction and placing a bid.

Every bid is checked HERE, on the server, inside a database transaction that
locks the auction row (select_for_update). Two bids for the same auction are
therefore processed one after the other, never at the same time.

Nothing in this file knows about WebSockets. After a bid commits, it hands the
result to auctions/realtime.py, which tells the browsers.
"""
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from applications import eligibility
from applications.models import Applicant

from . import realtime
from .models import Auction, Bid, Participation


class BidRejected(Exception):
    """A bid that breaks a rule. `message` is safe to show to the bidder."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class BidOutcome:
    bid: Bid
    duplicate: bool = False   # True if this exact submission was already accepted
    extended: bool = False    # True if this bid pushed the deadline later


# ---------------------------------------------------------------- joining

def join_auction(auction, applicant):
    """
    Give an ELIGIBLE applicant an anonymous "Bidder N" code for this auction.
    Calling it again returns the existing participation (no second code).
    Called automatically when an eligible applicant opens the auction page.
    """
    existing = Participation.objects.filter(auction=auction, applicant=applicant).first()
    if existing:
        return existing
    if auction.phase() not in (Auction.Phase.UPCOMING, Auction.Phase.LIVE):
        raise BidRejected("closed", "This auction is no longer open.")
    allowed = eligibility.check(applicant, auction.quarter)
    if not allowed.allowed:
        raise BidRejected("not_eligible", allowed.reason)

    with transaction.atomic():
        # Lock the auction so two people joining at once can't get the same number.
        Auction.objects.select_for_update().get(pk=auction.pk)
        existing = Participation.objects.filter(auction=auction, applicant=applicant).first()
        if existing:  # joined in another tab while we waited for the lock
            return existing
        last = Participation.objects.filter(auction=auction).aggregate(n=Max("bidder_number"))["n"]
        return Participation.objects.create(auction=auction, applicant=applicant,
                                            bidder_number=(last or 0) + 1)


# ---------------------------------------------------------------- bidding

def parse_amount(raw):
    """Turn user input into a whole-rupee Decimal, or reject it. "45,090" and "45090.00" are fine."""
    text = str(raw).strip().replace(",", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise BidRejected("invalid_amount", "Enter the bid as a number of rupees, e.g. 45090.")
    if not amount.is_finite() or amount <= 0:
        raise BidRejected("invalid_amount", "The bid must be a positive amount.")
    if amount != amount.to_integral_value():
        raise BidRejected("invalid_amount", "Bids are in whole rupees (no paise).")
    if amount >= Decimal("1e10"):
        raise BidRejected("invalid_amount", "That amount is too large.")
    return amount.quantize(Decimal("1"))


def parse_client_bid_id(raw):
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        raise BidRejected("invalid_request", "Invalid request. Please reload the page.")


def place_bid(auction_id, applicant, raw_amount, raw_client_bid_id):
    """
    Validate and store one bid. Returns BidOutcome, or raises BidRejected.

    Rules (placeholders where marked, see PROGRESS.md):
      1. The auction must be LIVE (started, deadline not passed, not closed).
      2. The applicant must have a code in this auction (Participation).
      3. Same client_bid_id again -> treated as a duplicate, not a new bid.
      4. The applicant must STILL be eligible (applications/eligibility.py):
         an officer may have suspended them or un-verified the EMD mid-auction.
      5. Whole rupees. First bid >= base rate (ASSUMPTION); later bids >=
         highest + one step (step = increment_percent % of the base rate).
         Any amount above that is accepted (ASSUMPTION: need not be a multiple of the step).
      6. ASSUMPTION: you cannot outbid yourself while you hold the highest bid.
      7. Anti-sniping, only if the auction's anti_snipe_seconds > 0: a bid in the
         last N seconds moves the deadline to now + N seconds, at most
         AUCTION_MAX_EXTENSIONS times.
    """
    amount = parse_amount(raw_amount)
    client_bid_id = parse_client_bid_id(raw_client_bid_id)

    with transaction.atomic():
        # THE LOCK: every other bid for this auction waits here until we commit.
        # of=("self",) locks only the auction row, not the joined quarter row.
        auction = (Auction.objects.select_for_update(of=("self",))
                   .select_related("quarter").get(pk=auction_id))
        now = timezone.now()

        # Rule 1
        phase = auction.phase(now)
        if phase == Auction.Phase.UPCOMING:
            raise BidRejected("not_started", "Bidding has not started yet.")
        if phase != Auction.Phase.LIVE:
            raise BidRejected("closed", "This auction has closed. No more bids are accepted.")

        # Rule 2
        participation = Participation.objects.filter(auction=auction, applicant=applicant).first()
        if participation is None:
            raise BidRejected("not_joined", "You are not a bidder in this auction.")

        # Rule 3
        earlier = Bid.objects.filter(participation=participation, client_bid_id=client_bid_id).first()
        if earlier:
            return BidOutcome(bid=earlier, duplicate=True)

        # Rule 4. Re-read the applicant from the database: the caller (e.g. an open
        # WebSocket) may hold a copy loaded before an officer suspended them.
        applicant = Applicant.objects.get(pk=applicant.pk)
        allowed = eligibility.check(applicant, auction.quarter)
        if not allowed.allowed:
            raise BidRejected("not_eligible", allowed.reason)

        # Rule 5
        minimum = auction.minimum_next_bid
        if amount < minimum:
            raise BidRejected("too_low", f"Your bid must be at least Rs. {minimum:,.0f}.")

        # Rule 6
        leader = auction.bids.select_related("participation").first()  # newest = highest
        if leader and leader.participation_id == participation.pk:
            raise BidRejected("already_highest", "You already hold the highest bid.")

        # Rule 7
        extended_to = None
        snipe = timedelta(seconds=auction.anti_snipe_seconds)
        if (auction.anti_snipe_seconds and auction.end_time - now <= snipe
                and auction.extensions_count < settings.AUCTION_MAX_EXTENSIONS):
            new_end = now + snipe
            if new_end > auction.end_time:  # never shorten the auction
                extended_to = new_end

        try:
            with transaction.atomic():  # savepoint, so a constraint error leaves the lock usable
                bid = Bid.objects.create(
                    auction=auction, participation=participation, amount=amount,
                    created_at=now, client_bid_id=client_bid_id,
                    previous_highest=auction.current_highest_bid,
                    deadline_extended_to=extended_to,
                )
        except IntegrityError:
            # Only reachable if locking failed (e.g. on SQLite): the DB backstop fired.
            raise BidRejected("conflict", "Another bid was accepted at the same moment. Please try again.")

        auction.current_highest_bid = amount
        auction.total_bids = F("total_bids") + 1
        update_fields = ["current_highest_bid", "total_bids", "updated_at"]
        if extended_to:
            auction.end_time = extended_to
            auction.extensions_count = F("extensions_count") + 1
            update_fields += ["end_time", "extensions_count"]
        auction.save(update_fields=update_fields)

        # Tell the browsers only AFTER the transaction has committed, so nobody
        # ever sees a bid that was rolled back.
        transaction.on_commit(lambda: realtime.broadcast_bid(bid.pk))

    return BidOutcome(bid=bid, extended=extended_to is not None)
