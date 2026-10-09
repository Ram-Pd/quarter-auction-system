import uuid
from datetime import timedelta

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from accounts.tests.factories import make_activated_applicant
from auctions.bidding import place_bid
from auctions.models import Bid, Participation
from auctions.tests.factories import make_auction, make_bidder, make_quarter


class AuctionRoomPageTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.url = reverse("auctions:auction_room", args=[self.auction.pk])
        self.join_url = reverse("auctions:join", args=[self.auction.pk])
        self.applicant, self.user = make_activated_applicant(1)

    def test_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('accounts:login')}?next={self.url}")

    def test_not_joined_sees_join_button(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(response, "Join auction")
        self.assertNotContains(response, 'id="bid-form"')
        self.assertNotContains(response, "auction_room.js")  # no live socket until joined

    def test_join_then_see_bid_form(self):
        self.client.force_login(self.user)
        response = self.client.post(self.join_url, follow=True)
        self.assertContains(response, "You have joined this auction as Bidder 1")
        self.assertContains(response, 'id="bid-form"')
        self.assertContains(response, "auction_room.js")
        self.assertEqual(Participation.objects.count(), 1)

    def test_join_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.join_url).status_code, 405)

    def test_cannot_join_cancelled_auction(self):
        self.auction.cancel()
        self.client.force_login(self.user)
        response = self.client.post(self.join_url, follow=True)
        self.assertContains(response, "no longer open")
        self.assertEqual(Participation.objects.count(), 0)

    def test_staff_watch_but_cannot_join(self):
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(self.url), "Staff accounts cannot bid")
        self.assertEqual(self.client.post(self.join_url).status_code, 403)

    def test_history_shows_codes_not_identities(self):
        other, _, _ = make_bidder(self.auction, 2)
        place_bid(self.auction.pk, other, "4500", uuid.uuid4())
        self.client.force_login(self.user)
        body = self.client.get(self.url).content.decode()
        self.assertIn("Bidder 1", body)  # Bidder 1 = `other` (joined first)
        for private in [other.name, other.email, other.urn, other.mobile]:
            self.assertNotIn(private, body)

    def test_lobby_links_to_room_and_marks_joined(self):
        self.client.force_login(self.user)
        self.client.post(self.join_url)
        response = self.client.get(reverse("auctions:lobby"))
        self.assertContains(response, self.url)
        self.assertContains(response, "Joined")


class AdminPrivacyTests(TestCase):
    """Ordinary staff must never see who is behind a bidder code."""

    def setUp(self):
        self.auction = make_auction(make_quarter("B-214"), starts_in=timedelta(minutes=-1))
        self.bidder, _, _ = make_bidder(self.auction, 1)
        place_bid(self.auction.pk, self.bidder, "4500", uuid.uuid4())

        self.staff = User.objects.create_user("clerk", password="x", is_staff=True)
        self.staff.user_permissions.add(*Permission.objects.filter(
            codename__in=["view_bid", "view_auction", "view_participation"]))
        self.superuser = User.objects.create_superuser("admin", "a@example.com", "x")

    def test_bid_admin_shows_code_only(self):
        self.client.force_login(self.staff)
        body = self.client.get(reverse("admin:auctions_bid_changelist")).content.decode()
        self.assertIn("Bidder 1", body)
        for private in [self.bidder.name, self.bidder.urn, self.bidder.application_no]:
            self.assertNotIn(private, body)

    def test_auction_admin_bid_list_shows_code_only(self):
        self.client.force_login(self.staff)
        body = self.client.get(reverse("admin:auctions_auction_change", args=[self.auction.pk])).content.decode()
        self.assertIn("Bidder 1", body)
        self.assertNotIn(self.bidder.name, body)
        self.assertNotIn(self.bidder.application_no, body)

    def test_participation_mapping_hidden_from_staff(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("admin:auctions_participation_changelist")).status_code, 403)
        self.assertNotContains(self.client.get(reverse("admin:index")), "Participations")

    def test_participation_mapping_visible_to_superuser(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:auctions_participation_changelist"))
        self.assertContains(response, "Bidder 1")
        self.assertContains(response, self.bidder.application_no)

    def test_bids_cannot_be_edited_or_deleted(self):
        self.client.force_login(self.superuser)
        bid = Bid.objects.get()
        self.assertEqual(self.client.get(reverse("admin:auctions_bid_delete", args=[bid.pk])).status_code, 403)
        page = self.client.get(reverse("admin:auctions_bid_change", args=[bid.pk]))
        self.assertNotContains(page, 'name="amount"')  # shown read-only, no input
