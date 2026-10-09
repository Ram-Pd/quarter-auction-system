"""
Everything that is SENT TO BROWSERS about an auction is built in this file.

PRIVACY RULE: messages contain only anonymous codes ("Bidder 7"), amounts and
times. Never a name, email, URN, mobile or any other applicant field. Keeping
all message building here makes that rule easy to check (and it is tested).
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone

from .models import Auction, Bid


def group_name(auction_id):
    """Channels group for one auction: everyone watching auction 7 is in "auction_7"."""
    return f"auction_{auction_id}"


def _money(value):
    return None if value is None else f"{value:.2f}"


def _time(value):
    # ISO 8601 in project local time (IST), e.g. "2026-10-09T20:15:03.120000+05:30".
    return None if value is None else timezone.localtime(value).isoformat()


def public_bid(bid):
    return {
        "bidder": bid.participation.anonymous_code,
        "amount": _money(bid.amount),
        "time": _time(bid.created_at),
    }


def auction_result(auction):
    """The final result as the public may see it: code and amount, never a name."""
    if auction.status == Auction.Status.CLOSED:
        return {"outcome": "won", "bidder": auction.winning_bid.participation.anonymous_code,
                "amount": _money(auction.winning_bid.amount)}
    if auction.status == Auction.Status.CLOSED_NO_BIDS:
        return {"outcome": "no_bids"}
    if auction.status == Auction.Status.CANCELLED:
        return {"outcome": "cancelled"}
    return None


def auction_state(auction):
    """The live numbers every watcher needs (sent with every update)."""
    return {
        "auction_id": auction.pk,
        "phase": auction.phase().value,
        "phase_label": auction.phase().label,
        "result": auction_result(auction),
        "highest_bid": _money(auction.current_highest_bid),
        "minimum_next_bid": _money(auction.minimum_next_bid),
        "min_increment": _money(auction.min_increment),
        "start_time": _time(auction.start_time),
        "end_time": _time(auction.end_time),
        "server_now": _time(timezone.now()),  # lets the browser correct its clock
    }


def snapshot(auction, participation=None):
    """
    Full picture, sent when a browser connects or reconnects (resync after a
    network drop or a sleeping laptop).
    """
    recent = (Bid.objects.filter(auction=auction).select_related("participation")
              .order_by("-created_at")[:settings.AUCTION_RECENT_BIDS_SHOWN])
    return {
        "type": "snapshot",
        **auction_state(auction),
        "you": participation.anonymous_code if participation else None,
        "bids": [public_bid(b) for b in recent],
    }


def _send_to_group(auction_id, message):
    layer = get_channel_layer()
    if layer is None:
        return
    # "type" names the consumer method that delivers it: "auction.message" ->
    # AuctionConsumer.auction_message() in auctions/consumers.py
    async_to_sync(layer.group_send)(group_name(auction_id), {"type": "auction.message", "message": message})


def broadcast_bid(bid_id):
    """Tell everyone watching the auction about a newly accepted bid."""
    bid = Bid.objects.select_related("participation", "auction__quarter").get(pk=bid_id)
    _send_to_group(bid.auction_id, {
        "type": "bid_accepted",
        "bid": public_bid(bid),
        "extended": bid.deadline_extended_to is not None,
        **auction_state(bid.auction),
    })


def broadcast_state(auction):
    """Tell everyone the auction changed without a bid (closed, cancelled, time edited)."""
    _send_to_group(auction.pk, {"type": "state", **auction_state(auction)})
