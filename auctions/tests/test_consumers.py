"""
WebSocket consumer tests, using Channels' WebsocketCommunicator: a fake
browser tab that connects, sends JSON and reads what the server pushes.
"""
import json
import uuid
from datetime import timedelta

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser, User
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from accounts.tests.factories import make_activated_applicant
from auctions.models import Auction, Bid
from auctions.routing import websocket_urlpatterns
from auctions.tests.factories import make_auction, make_bidder, make_quarter

application = URLRouter(websocket_urlpatterns)


def tab(user, auction):
    """A fake browser tab on the auction page, logged in as `user`."""
    communicator = WebsocketCommunicator(application, f"/ws/auctions/{auction.pk}/")
    communicator.scope["user"] = user  # what AuthMiddlewareStack would set from the session
    return communicator


def bid_message(amount):
    return {"type": "bid", "amount": amount, "client_bid_id": str(uuid.uuid4())}


@override_settings(AUCTION_BID_MIN_INTERVAL_SECONDS=0)
class ConsumerTests(TransactionTestCase):

    def setUp(self):
        self.auction = make_auction()  # live, base rate 4500, increment 100
        self.a, self.user_a, _ = make_bidder(self.auction, 1)  # Bidder 1
        self.b, self.user_b, _ = make_bidder(self.auction, 2)  # Bidder 2

    # ---------------------------------------------------------- authorisation

    async def test_anonymous_user_rejected(self):
        connected, code = await tab(AnonymousUser(), self.auction).connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_applicant_who_has_not_joined_rejected(self):
        _, outsider = await sync_to_async(make_activated_applicant)(3)
        connected, code = await tab(outsider, self.auction).connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4403)

    async def test_unknown_auction_rejected(self):
        communicator = WebsocketCommunicator(application, "/ws/auctions/999999/")
        communicator.scope["user"] = self.user_a
        connected, code = await communicator.connect()
        self.assertEqual((connected, code), (False, 4404))

    async def test_participant_gets_snapshot_with_own_code(self):
        communicator = tab(self.user_a, self.auction)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        snapshot = await communicator.receive_json_from()
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(snapshot["you"], "Bidder 1")
        self.assertEqual(snapshot["phase"], "LIVE")
        self.assertEqual(snapshot["minimum_next_bid"], "4500.00")
        self.assertEqual(snapshot["bids"], [])
        await communicator.disconnect()

    async def test_staff_can_watch_but_not_bid(self):
        staff = await sync_to_async(User.objects.create_user)("staff", password="x", is_staff=True)
        communicator = tab(staff, self.auction)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        self.assertIsNone((await communicator.receive_json_from())["you"])
        await communicator.send_json_to(bid_message("4500"))
        result = await communicator.receive_json_from()
        self.assertEqual((result["type"], result["ok"]), ("bid_result", False))
        self.assertEqual(await sync_to_async(Bid.objects.count)(), 0)
        await communicator.disconnect()

    # ---------------------------------------------------------- bidding

    async def test_accepted_bid_reaches_everyone_without_identity(self):
        tab_a, tab_b = tab(self.user_a, self.auction), tab(self.user_b, self.auction)
        await tab_a.connect()
        await tab_b.connect()
        await tab_a.receive_json_from()  # snapshots
        await tab_b.receive_json_from()

        message = bid_message("4500")
        await tab_a.send_json_to(message)
        # Bidder A's tab gets its personal result AND the broadcast (either order).
        a_msgs = [await tab_a.receive_json_from(), await tab_a.receive_json_from()]
        by_type = {m["type"]: m for m in a_msgs}
        self.assertTrue(by_type["bid_result"]["ok"])
        self.assertEqual(by_type["bid_result"]["client_bid_id"], message["client_bid_id"])

        # Bidder B's tab gets only the broadcast.
        b_msg = await tab_b.receive_json_from()
        self.assertEqual(b_msg["type"], "bid_accepted")
        self.assertEqual(b_msg["bid"]["bidder"], "Bidder 1")
        self.assertEqual(b_msg["bid"]["amount"], "4500.00")
        self.assertEqual(b_msg["highest_bid"], "4500.00")
        self.assertEqual(b_msg["minimum_next_bid"], "4600.00")
        self.assertIn("end_time", b_msg)
        self.assertIn("server_now", b_msg)
        self.assertTrue(await tab_b.receive_nothing())

        # PRIVACY: nothing identifying in any message.
        everything = json.dumps(a_msgs + [b_msg])
        for private in [self.a.name, self.a.email, self.a.urn, self.a.mobile, self.a.application_no,
                        self.b.name, self.b.urn, self.user_a.username]:
            self.assertNotIn(private, everything)

        await tab_a.disconnect()
        await tab_b.disconnect()

    async def test_rejected_bid_goes_only_to_sender(self):
        tab_a, tab_b = tab(self.user_a, self.auction), tab(self.user_b, self.auction)
        await tab_a.connect()
        await tab_b.connect()
        await tab_a.receive_json_from()
        await tab_b.receive_json_from()

        await tab_a.send_json_to(bid_message("100"))
        result = await tab_a.receive_json_from()
        self.assertEqual(result["type"], "bid_result")
        self.assertFalse(result["ok"])
        self.assertIn("at least Rs. 4,500.00", result["message"])
        self.assertTrue(await tab_b.receive_nothing())
        await tab_a.disconnect()
        await tab_b.disconnect()

    async def test_sync_returns_fresh_snapshot_with_history(self):
        communicator = tab(self.user_a, self.auction)
        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to(bid_message("4500"))
        await communicator.receive_json_from()
        await communicator.receive_json_from()

        # A reconnecting / waking tab asks for a resync.
        await communicator.send_json_to({"type": "sync"})
        snapshot = await communicator.receive_json_from()
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(snapshot["highest_bid"], "4500.00")
        self.assertEqual([b["bidder"] for b in snapshot["bids"]], ["Bidder 1"])
        await communicator.disconnect()

    async def test_auctions_are_isolated(self):
        other = await sync_to_async(make_auction)(await sync_to_async(make_quarter)("C-305"))
        _, user_c, _ = await sync_to_async(make_bidder)(other, 3)
        tab_a, tab_c = tab(self.user_a, self.auction), tab(user_c, other)
        await tab_a.connect()
        await tab_c.connect()
        await tab_a.receive_json_from()
        await tab_c.receive_json_from()

        await tab_a.send_json_to(bid_message("4500"))
        await tab_a.receive_json_from()
        await tab_a.receive_json_from()
        self.assertTrue(await tab_c.receive_nothing())  # watcher of the OTHER auction hears nothing
        await tab_a.disconnect()
        await tab_c.disconnect()

    async def test_unknown_message_type(self):
        communicator = tab(self.user_a, self.auction)
        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to({"type": "hack"})
        self.assertEqual((await communicator.receive_json_from())["type"], "error")
        await communicator.disconnect()

    @override_settings(AUCTION_BID_MIN_INTERVAL_SECONDS=60)
    async def test_bidding_too_fast_is_refused(self):
        communicator = tab(self.user_a, self.auction)
        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to(bid_message("100"))   # first attempt (rejected: too low)
        await communicator.receive_json_from()
        await communicator.send_json_to(bid_message("4500"))  # second attempt within 60 s
        result = await communicator.receive_json_from()
        self.assertIn("too fast", result["message"])
        await communicator.disconnect()

    async def test_cancel_is_pushed_to_open_pages(self):
        communicator = tab(self.user_a, self.auction)
        await communicator.connect()
        await communicator.receive_json_from()
        await sync_to_async(self.auction.cancel)()
        message = await communicator.receive_json_from()
        self.assertEqual((message["type"], message["phase"]), ("state", "CANCELLED"))
        await communicator.disconnect()

    async def test_sync_after_deadline_closes_and_pushes_result(self):
        tab_a, tab_b = tab(self.user_a, self.auction), tab(self.user_b, self.auction)
        await tab_a.connect()
        await tab_b.connect()
        await tab_a.receive_json_from()
        await tab_b.receive_json_from()
        await tab_a.send_json_to(bid_message("4500"))
        await tab_a.receive_json_from()
        await tab_a.receive_json_from()
        await tab_b.receive_json_from()

        # Time passes: the deadline is now in the past.
        await sync_to_async(Auction.objects.filter(pk=self.auction.pk).update)(
            end_time=timezone.now() - timedelta(seconds=1))

        # Bidder B's countdown hit zero, so the page asks for a resync.
        await tab_b.send_json_to({"type": "sync"})
        b_msgs = [await tab_b.receive_json_from(), await tab_b.receive_json_from()]
        snapshot = next(m for m in b_msgs if m["type"] == "snapshot")
        self.assertEqual(snapshot["phase"], "CLOSED")
        self.assertEqual(snapshot["result"], {"outcome": "won", "bidder": "Bidder 1", "amount": "4500.00"})

        # Bidder A (the winner) is told too, without asking.
        pushed = await tab_a.receive_json_from()
        self.assertEqual((pushed["type"], pushed["phase"]), ("state", "CLOSED"))
        self.assertEqual(pushed["result"]["bidder"], "Bidder 1")
        self.assertNotIn(self.a.name, json.dumps(b_msgs + [pushed]))

        await tab_a.disconnect()
        await tab_b.disconnect()
