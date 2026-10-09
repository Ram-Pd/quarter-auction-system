"""
WebSocket consumer: one instance per open browser tab on an auction page.

Messages FROM the browser (JSON):
    {"type": "bid", "amount": "4600", "client_bid_id": "<uuid>"}
    {"type": "sync"}                      -> asks for a fresh snapshot

Messages TO the browser (JSON), all built in auctions/realtime.py:
    {"type": "snapshot", ...}             -> on connect and on "sync"
    {"type": "bid_accepted", ...}         -> to everyone in the auction group
    {"type": "state", ...}                -> auction changed (e.g. closed)
    {"type": "bid_result", "ok": true/false, "client_bid_id": ..., "message": ...}
                                          -> only to the tab that sent the bid

This is a *synchronous* consumer: Channels runs it in a worker thread, so it
can use the Django ORM directly, just like a normal view.
"""
import logging
import time

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.conf import settings

from accounts.models import Applicant

from . import realtime
from .bidding import BidRejected, place_bid
from .models import Auction, Participation

logger = logging.getLogger(__name__)

# WebSocket close codes (4000-4999 are free for applications to use).
CLOSE_NOT_LOGGED_IN = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class AuctionConsumer(JsonWebsocketConsumer):

    # ------------------------------------------------------------ connect

    def connect(self):
        self.auction_id = self.scope["url_route"]["kwargs"]["auction_id"]
        self.group = realtime.group_name(self.auction_id)
        self.participation = None
        self.last_bid_at = 0.0

        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            self.close(code=CLOSE_NOT_LOGGED_IN)
            return

        auction = Auction.objects.select_related("quarter").filter(pk=self.auction_id).first()
        if auction is None:
            self.close(code=CLOSE_NOT_FOUND)
            return

        # AUTHORISATION, per auction: only applicants who joined THIS auction may
        # connect (and bid). Staff may connect to watch, but cannot bid.
        applicant = Applicant.objects.filter(user=user, is_activated=True).first()
        if applicant:
            self.participation = Participation.objects.filter(auction=auction, applicant=applicant).first()
        if self.participation is None and not user.is_staff:
            self.close(code=CLOSE_FORBIDDEN)
            return

        async_to_sync(self.channel_layer.group_add)(self.group, self.channel_name)
        self.accept()
        self.send_json(realtime.snapshot(auction, self.participation))

    def disconnect(self, code):
        if hasattr(self, "group"):
            async_to_sync(self.channel_layer.group_discard)(self.group, self.channel_name)

    # ------------------------------------------------------------ from browser

    def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if kind == "bid":
            self.handle_bid(content)
        elif kind == "sync":
            auction = Auction.objects.select_related("quarter").get(pk=self.auction_id)
            self.send_json(realtime.snapshot(auction, self.participation))
        else:
            self.send_json({"type": "error", "message": "Unknown message."})

    def handle_bid(self, content):
        client_bid_id = content.get("client_bid_id")

        def reply(ok, message):
            self.send_json({"type": "bid_result", "ok": ok, "client_bid_id": client_bid_id,
                            "message": message})

        if self.participation is None:
            reply(False, "Only participants can bid.")
            return

        # Anti-flooding: one bid per connection per AUCTION_BID_MIN_INTERVAL_SECONDS.
        now = time.monotonic()
        if now - self.last_bid_at < settings.AUCTION_BID_MIN_INTERVAL_SECONDS:
            reply(False, "You are bidding too fast. Please wait a moment.")
            return
        self.last_bid_at = now

        try:
            outcome = place_bid(self.auction_id, self.participation.applicant,
                                content.get("amount"), client_bid_id)
        except BidRejected as rejected:
            reply(False, rejected.message)
            return
        except Exception:
            logger.exception("Unexpected error placing bid in auction %s", self.auction_id)
            reply(False, "Something went wrong. Your bid was not placed. Please try again.")
            return

        if outcome.duplicate:
            reply(True, "This bid was already accepted.")
        else:
            reply(True, f"Your bid of Rs. {outcome.bid.amount:,.2f} was accepted.")
        # Everyone (including this tab) gets the bid itself via the group broadcast.

    # ------------------------------------------------------------ from group

    def auction_message(self, event):
        """Called for every message sent to this auction's group (see realtime.py)."""
        self.send_json(event["message"])
