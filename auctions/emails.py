"""
Result emails after an auction closes.

Each email is sent at most once per auction: the auction row is locked, the
"already sent?" timestamp is checked, the email is sent, and the timestamp is
saved in the same transaction. If sending fails, the transaction rolls back,
the timestamp stays empty, and the worker tries again later.

(Honest limit: if the email is handed to the mail server but the database
commit then fails, a retry could send it twice. That window is tiny; true
exactly-once delivery to an external mail server is not possible.)
"""
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import Auction

FOOTER = "\nThis is an automated message from a TRAINING PROJECT, not an official SAIL communication.\n"


def _quarter_lines(auction):
    q = auction.quarter
    return (
        f"  Quarter number : {q.quarter_no}\n"
        f"  Sector/location: {q.sector}, {q.location_block}\n"
        f"  Floor          : {q.floor}\n"
        f"  Area           : {q.area_sqft:,.0f} sq ft\n"
    )


def notify_winner(auction_id):
    """Email the winner. Returns True if an email was sent now."""
    with transaction.atomic():
        auction = (Auction.objects.select_for_update(of=("self",))
                   .select_related("quarter", "winning_bid__participation__applicant")
                   .get(pk=auction_id))
        if auction.status != Auction.Status.CLOSED or auction.winner_notified_at:
            return False

        bid = auction.winning_bid
        applicant = bid.participation.applicant
        body = (
            f"Dear {applicant.name},\n\n"
            f"Congratulations! Your bid was the highest in the {settings.AUCTION_TITLE}.\n\n"
            f"{_quarter_lines(auction)}"
            f"  Winning amount : Rs. {bid.amount:,.2f}\n"
            f"  Your bidder code in this auction: {bid.participation.anonymous_code}\n\n"
            "Next steps (placeholder, to be confirmed by the auction office):\n"
            "  1. Wait for the formal allotment letter from the auction office.\n"
            "  2. Complete the documentation and payment formalities within the time stated in that letter.\n"
            "  3. Quote your application number in all correspondence: "
            f"{applicant.application_no}\n"
            + FOOTER
        )
        EmailMessage(
            subject=f"You won the auction for quarter {auction.quarter.quarter_no}",
            body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[applicant.email],
        ).send()

        auction.winner_notified_at = timezone.now()
        auction.save(update_fields=["winner_notified_at", "updated_at"])
    return True


def notify_losers(auction_id):
    """
    Email every other bidder that the auction has closed. OFF by default
    (settings.AUCTION_NOTIFY_LOSERS). Returns the number of emails sent now.
    """
    if not settings.AUCTION_NOTIFY_LOSERS:
        return 0
    with transaction.atomic():
        auction = (Auction.objects.select_for_update(of=("self",)).select_related("quarter", "winning_bid")
                   .get(pk=auction_id))
        if auction.status != Auction.Status.CLOSED or auction.losers_notified_at:
            return 0

        winner_participation_id = auction.winning_bid.participation_id
        losers = {bid.participation.applicant for bid in
                  auction.bids.exclude(participation_id=winner_participation_id)
                  .select_related("participation__applicant")}
        for applicant in losers:
            EmailMessage(
                subject=f"Auction result for quarter {auction.quarter.quarter_no}",
                body=(f"Dear {applicant.name},\n\n"
                      f"The auction for quarter {auction.quarter.quarter_no} has closed. "
                      "Your bid was not the highest this time.\n\n"
                      "Thank you for taking part. Other quarters may be auctioned later.\n" + FOOTER),
                from_email=settings.DEFAULT_FROM_EMAIL, to=[applicant.email],
            ).send()

        auction.losers_notified_at = timezone.now()
        auction.save(update_fields=["losers_notified_at", "updated_at"])
    return len(losers)
