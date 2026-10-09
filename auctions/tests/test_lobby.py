from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.tests.factories import make_activated_applicant, make_applicant
from auctions.models import Auction
from auctions.tests.factories import make_auction, make_quarter


class LobbyAccessTests(TestCase):
    url = reverse("auctions:lobby")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")

    def test_logged_in_user_without_applicant_forbidden(self):
        self.client.force_login(User.objects.create_user("someone", password="x"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_activated_applicant_allowed(self):
        _, user = make_activated_applicant()
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_staff_allowed(self):
        self.client.force_login(User.objects.create_user("staff", password="x", is_staff=True))
        self.assertEqual(self.client.get(self.url).status_code, 200)


class LobbyContentTests(TestCase):
    url = reverse("auctions:lobby")

    def setUp(self):
        _, user = make_activated_applicant()
        self.client.force_login(user)

    def test_live_and_upcoming_sections(self):
        make_auction(make_quarter("B-214"))  # live
        make_auction(make_quarter("C-305"), starts_in=timedelta(hours=2))  # upcoming
        response = self.client.get(self.url)
        self.assertEqual([a.quarter.quarter_no for a in response.context["live"]], ["B-214"])
        self.assertEqual([a.quarter.quarter_no for a in response.context["upcoming"]], ["C-305"])
        self.assertContains(response, "Live now (1)")
        self.assertContains(response, "Upcoming (1)")
        self.assertContains(response, 'data-countdown="')

    def test_shows_quarter_details_and_prices(self):
        auction = make_auction(make_quarter("A-021", sector="Sector 12", floor="Ground",
                                            area_sqft=Decimal("980"), base_rate=Decimal("6200")),
                               min_increment=Decimal("500"))
        auction.current_highest_bid = Decimal("7000")
        auction.save()
        response = self.client.get(self.url)
        for text in ["A-021", "Sector 12", "Ground", "980", "6,200.00", "7,000.00", "7,500.00"]:
            self.assertContains(response, text)

    def test_cancelled_auctions_not_listed(self):
        make_auction().cancel()
        response = self.client.get(self.url)
        self.assertEqual(response.context["live"], [])
        self.assertEqual(response.context["upcoming"], [])

    def test_no_applicant_data_on_page(self):
        other = make_applicant(2, name="Secret Person", email="secret@example.com")
        make_auction()
        body = self.client.get(self.url).content.decode()
        for private in ["Secret Person", "secret@example.com", other.urn, other.mobile]:
            self.assertNotIn(private, body)


class AuctionAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "pass"))

    def test_add_form_offers_only_vacant_quarters(self):
        make_quarter("B-214")
        make_auction(make_quarter("C-305"))  # now In Auction
        response = self.client.get(reverse("admin:auctions_auction_add"))
        choices = [str(q) for q in response.context["adminform"].form.fields["quarter"].queryset]
        self.assertEqual(choices, ["B-214"])

    def test_create_auction_via_admin(self):
        quarter = make_quarter()
        response = self.client.post(reverse("admin:auctions_auction_add"), {
            "quarter": quarter.pk,
            "start_time_0": "2099-01-01", "start_time_1": "10:00:00",
            "end_time_0": "2099-01-01", "end_time_1": "11:00:00",
            "min_increment": "100", "anti_snipe_extension": "00:02:00",
        })
        self.assertEqual(response.status_code, 302)
        quarter.refresh_from_db()
        self.assertEqual(quarter.status, "IN_AUCTION")

    def test_end_before_start_rejected_in_admin(self):
        quarter = make_quarter()
        response = self.client.post(reverse("admin:auctions_auction_add"), {
            "quarter": quarter.pk,
            "start_time_0": "2099-01-01", "start_time_1": "11:00:00",
            "end_time_0": "2099-01-01", "end_time_1": "10:00:00",
            "min_increment": "100", "anti_snipe_extension": "00:02:00",
        })
        self.assertContains(response, "End time must be after start time.")
        self.assertEqual(Auction.objects.count(), 0)

    def test_started_auction_locks_fields(self):
        auction = make_auction()  # live
        response = self.client.get(reverse("admin:auctions_auction_change", args=[auction.pk]))
        form_fields = response.context["adminform"].form.fields
        for locked in ["quarter", "start_time", "min_increment", "anti_snipe_extension"]:
            self.assertNotIn(locked, form_fields)
        self.assertIn("end_time", form_fields)

    def test_cancel_action(self):
        auction = make_auction()
        response = self.client.post(reverse("admin:auctions_auction_changelist"),
                                    {"action": "cancel_auctions", "_selected_action": [auction.pk]},
                                    follow=True)
        self.assertContains(response, "Cancelled 1 auction(s).")
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.CANCELLED)

    def test_auctions_cannot_be_deleted(self):
        auction = make_auction()
        url = reverse("admin:auctions_auction_delete", args=[auction.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
