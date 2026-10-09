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
from django.db.models import Max
from django.utils import timezone

from accounts.models import Applicant

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
    Give the applicant an anonymous "Bidder N" code for this auction.
    Calling it again returns the existing participation (no second code).
    """
    existing = Participation.objects.filter(auction=auction, applicant=applicant).first()
    if existing:
        return existing
    if auction.phase() not in (Auction.Phase.UPCOMING, Auction.Phase.LIVE):
        raise BidRejected("closed", "This auction is no longer open for joining.")
    if not (applicant.is_verified and applicant.is_activated):
        raise BidRejected("not_eligible", "Only verified, activated applicants can join auctions.")

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

def other_active_auction(applicant, exclude_auction_id=None):
    """
    The still-open auction (other than `exclude_auction_id`) in which this
    applicant has already bid, or None. Used by rule 7 and by the pages to warn early.
    """
    return (Auction.objects.filter(status=Auction.Status.OPEN,
                                   bids__participation__applicant=applicant)
            .exclude(pk=exclude_auction_id).select_related("quarter").distinct().first())


def parse_amount(raw):
    """Turn user input into a Decimal with at most 2 decimal places, or reject it."""
    text = str(raw).strip().replace(",", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise BidRejected("invalid_amount", "Enter the bid as a number, e.g. 4600.")
    if not amount.is_finite() or amount <= 0:
        raise BidRejected("invalid_amount", "The bid must be a positive amount.")
    if -amount.as_tuple().exponent > 2:
        raise BidRejected("invalid_amount", "Use at most 2 decimal places (paise).")
    if amount >= Decimal("1e10"):
        raise BidRejected("invalid_amount", "That amount is too large.")
    return amount


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
      2. The applicant must have joined the auction.
      3. Same client_bid_id again -> treated as a duplicate, not a new bid.
      4. First bid >= base rate; later bids >= highest + minimum increment.
      5. ASSUMPTION: you cannot outbid yourself while you hold the highest bid.
      6. A bid in the final window extends the deadline (anti-sniping).
      7. One quarter at a time (confirmed by user): while you have bids in an
         auction that is still open, you cannot bid in any other auction.
         Switch off with settings.AUCTION_ONE_QUARTER_AT_A_TIME = False.
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
            raise BidRejected("not_joined", "Join the auction before bidding.")

        # Rule 3
        earlier = Bid.objects.filter(participation=participation, client_bid_id=client_bid_id).first()
        if earlier:
            return BidOutcome(bid=earlier, duplicate=True)

        # Rule 7. Lock the applicant row too, so two first bids sent at the same
        # moment to two DIFFERENT auctions can't both get through.
        # Lock order is always auction -> applicant, which avoids deadlocks.
        if settings.AUCTION_ONE_QUARTER_AT_A_TIME:
            Applicant.objects.select_for_update().get(pk=applicant.pk)
            other = other_active_auction(applicant, exclude_auction_id=auction.pk)
            if other:
                raise BidRejected(
                    "one_quarter_at_a_time",
                    f"You are already bidding for quarter {other.quarter.quarter_no}. You can bid on "
                    "another quarter only after that auction has ended.")

        # Rule 4
        minimum = auction.minimum_next_bid
        if amount < minimum:
            raise BidRejected("too_low", f"Your bid must be at least Rs. {minimum:,.2f}.")

        # Rule 5
        leader = auction.bids.select_related("participation").first()  # newest = highest
        if leader and leader.participation_id == participation.pk:
            raise BidRejected("already_highest", "You already hold the highest bid.")

        # Rule 6
        extended_to = None
        window = timedelta(seconds=settings.AUCTION_ANTI_SNIPE_WINDOW_SECONDS)
        if auction.end_time - now <= window and auction.anti_snipe_extension > timedelta(0):
            new_end = now + auction.anti_snipe_extension
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
        update_fields = ["current_highest_bid", "updated_at"]
        if extended_to:
            auction.end_time = extended_to
            update_fields.append("end_time")
        auction.save(update_fields=update_fields)

        # Tell the browsers only AFTER the transaction has committed, so nobody
        # ever sees a bid that was rolled back.
        transaction.on_commit(lambda: realtime.broadcast_bid(bid.pk))

    return BidOutcome(bid=bid, extended=extended_to is not None)
