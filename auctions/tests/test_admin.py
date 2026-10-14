"""Admin screens for quarters and auctions, and who may see what."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from applications.tests.factories import make_staff
from auctions.models import Auction, Quarter
from auctions.tests.factories import make_auction, make_bidder, make_quarter

QUARTER_FORM = {"quarter_no": "b-214", "sector": "Sector 4", "location_block": "Near market", "quarter_type": "B",
                "floor": "2nd", "area_sqft": "750", "base_rate": "45000", "emd_amount": "9000", "status": "VACANT"}


class AdminScreensTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser("boss@example.com", "pass", full_name="Boss")
        self.client.force_login(self.superuser)
        self.quarter_add = reverse("admin:auctions_quarter_add")

    def test_admin_pages_load(self):
        auction = make_auction()
        for url in [reverse("admin:auctions_quarter_changelist"), self.quarter_add,
                    reverse("admin:auctions_auction_changelist"),
                    reverse("admin:auctions_auction_change", args=[auction.pk]),
                    reverse("admin:applications_applicant_changelist"),
                    reverse("admin:applications_auditlog_changelist"),
                    reverse("admin:applications_documentchecklistitem_changelist"),
                    reverse("admin:accounts_user_changelist"), reverse("admin:accounts_user_add")]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_add_quarter_saves_upper_case_and_checks_values(self):
        self.assertEqual(self.client.post(self.quarter_add, QUARTER_FORM).status_code, 302)
        self.assertTrue(Quarter.objects.filter(quarter_no="B-214").exists())
        response = self.client.post(self.quarter_add, {**QUARTER_FORM, "quarter_no": "B-214"})
        self.assertContains(response, "already exists")
        response = self.client.post(self.quarter_add, {**QUARTER_FORM, "quarter_no": "X-1", "emd_amount": "0"})
        self.assertContains(response, "EMD amount must be greater than 0.")

    def test_duration_editable_before_start_and_moves_the_deadline(self):
        auction = make_auction(starts_in=timedelta(days=1), lasts=timedelta(minutes=5))
        url = reverse("admin:auctions_auction_change", args=[auction.pk])
        start = timezone.localtime(auction.start_time)
        response = self.client.post(url, {
            "start_time_0": start.strftime("%Y-%m-%d"), "start_time_1": start.strftime("%H:%M:%S"),
            "duration_minutes": "8", "increment_percent": "0.50", "anti_snipe_seconds": "30",
            "bids-TOTAL_FORMS": "0", "bids-INITIAL_FORMS": "0"})   # the (empty) read-only bid list
        self.assertEqual(response.status_code, 302, response.content[:300])
        auction.refresh_from_db()
        self.assertEqual(auction.duration_minutes, 8)
        self.assertEqual(auction.end_time, auction.start_time + timedelta(minutes=8))
        self.assertEqual(auction.increment_percent, Decimal("0.50"))
        self.assertEqual(auction.anti_snipe_seconds, 30)

    def test_timing_locked_once_bidding_started(self):
        auction = make_auction()   # live
        response = self.client.get(reverse("admin:auctions_auction_change", args=[auction.pk]))
        self.assertNotContains(response, 'name="duration_minutes"')
        self.assertNotContains(response, 'name="increment_percent"')

    def test_auctions_cannot_be_deleted(self):
        auction = make_auction()
        response = self.client.get(reverse("admin:auctions_auction_delete", args=[auction.pk]))
        self.assertEqual(response.status_code, 403)


class RolePrivacyTests(TestCase):
    def setUp(self):
        self.auction = make_auction()
        self.applicant, _, _ = make_bidder(self.auction, 1)

    def test_auction_admin_sees_bids_by_code_only(self):
        from auctions.bidding import place_bid
        import uuid
        place_bid(self.auction.pk, self.applicant, "45000", uuid.uuid4())
        self.client.force_login(make_staff("aa@example.com", "Auction Admin"))
        response = self.client.get(reverse("admin:auctions_bid_changelist"))
        self.assertContains(response, "Bidder 1")
        for private in [self.applicant.name, self.applicant.urn, self.applicant.application_no]:
            self.assertNotContains(response, private)
        page = self.client.get(reverse("admin:auctions_auction_change", args=[self.auction.pk]))
        self.assertNotContains(page, self.applicant.name)

    def test_participation_mapping_is_superuser_only(self):
        url = reverse("admin:auctions_participation_changelist")
        for group in ["Auction Admin", "Verification Officer"]:
            self.client.force_login(make_staff(f"{group[:3].lower()}@example.com", group))
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(User.objects.create_superuser("boss@example.com", "x", full_name="Boss"))
        self.assertContains(self.client.get(url), self.applicant.application_no)

    def test_verification_officer_cannot_edit_auctions(self):
        self.client.force_login(make_staff("vo@example.com", "Verification Officer"))
        self.assertEqual(self.client.get(reverse("admin:auctions_auction_changelist")).status_code, 403)
