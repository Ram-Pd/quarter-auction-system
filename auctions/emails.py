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
from django.db import transaction
from django.utils import timezone

from config.mail import build_email

from .models import Auction

# The wording of each email is in auctions/templates/auctions/emails/:
#   winner_subject.txt, winner_body.txt, loser_subject.txt, loser_body.txt


def notify_winner(auction_id):
    """Email the winner. Returns True if an email was sent now."""
    with transaction.atomic():
        auction = (Auction.objects.select_for_update(of=("self",))
                   .select_related("quarter", "winning_bid__participation__applicant")
                   .get(pk=auction_id))
        if auction.status != Auction.Status.CLOSED_WON or auction.winner_email_sent_at:
            return False

        bid = auction.winning_bid
        applicant = bid.participation.applicant
        build_email("auctions/emails/winner",
                    {"applicant": applicant, "quarter": auction.quarter, "bid": bid},
                    to=[applicant.email]).send()

        auction.winner_email_sent_at = timezone.now()
        auction.save(update_fields=["winner_email_sent_at", "updated_at"])
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
        if auction.status != Auction.Status.CLOSED_WON or auction.losers_notified_at:
            return 0

        winner_participation_id = auction.winning_bid.participation_id
        losers = {bid.participation.applicant for bid in
                  auction.bids.exclude(participation_id=winner_participation_id)
                  .select_related("participation__applicant")}
        for applicant in losers:
            build_email("auctions/emails/loser", {"applicant": applicant, "quarter": auction.quarter},
                        to=[applicant.email]).send()

        auction.losers_notified_at = timezone.now()
        auction.save(update_fields=["losers_notified_at", "updated_at"])
    return len(losers)
