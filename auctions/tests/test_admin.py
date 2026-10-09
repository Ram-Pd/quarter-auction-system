from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Applicant
from auctions.models import Quarter

QUARTER_FORM = {
    "quarter_no": "b-214",
    "sector": "Sector 4",
    "location_block": "Near market",
    "quarter_type": "B",
    "floor": "2nd",
    "area_sqft": "750",
    "base_rate": "4500",
    "status": "VACANT",
}

APPLICANT_FORM = {
    "name": "Test Applicant",
    "father_name": "Test Father",
    "mobile": "9876543210",
    "email": "test@example.com",
    "address": "Fake address",
    "state": "Jharkhand",
    "pin_code": "827001",
    "application_no": "APP-0001",
    "application_date": "2026-10-09",
    "urn": "1234567",
    "urn_date": "2026-10-09",
}


class AdminScreensTests(TestCase):
    """The checks a person would do by hand in /admin/, automated."""

    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.force_login(self.admin)
        self.quarter_add = reverse("admin:auctions_quarter_add")
        self.applicant_add = reverse("admin:accounts_applicant_add")

    def test_admin_pages_load(self):
        for name in ["admin:auctions_quarter_changelist", "admin:auctions_quarter_add",
                     "admin:accounts_applicant_changelist", "admin:accounts_applicant_add"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_add_quarter_saves_upper_case(self):
        response = self.client.post(self.quarter_add, QUARTER_FORM)
        self.assertEqual(response.status_code, 302)  # redirect = saved
        self.assertTrue(Quarter.objects.filter(quarter_no="B-214").exists())

    def test_duplicate_quarter_shows_error(self):
        self.client.post(self.quarter_add, QUARTER_FORM)
        response = self.client.post(self.quarter_add, {**QUARTER_FORM, "quarter_no": "B-214"})
        self.assertEqual(response.status_code, 200)  # form redisplayed
        self.assertContains(response, "already exists")
        self.assertEqual(Quarter.objects.count(), 1)

    def test_negative_area_shows_error(self):
        response = self.client.post(self.quarter_add, {**QUARTER_FORM, "area_sqft": "-5"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Area must be greater than 0.")
        self.assertEqual(Quarter.objects.count(), 0)

    def test_applicant_bad_urn_shows_error(self):
        response = self.client.post(self.applicant_add, {**APPLICANT_FORM, "urn": "123"})
        self.assertContains(response, "URN must be exactly 7 digits.")
        self.assertEqual(Applicant.objects.count(), 0)

    def test_applicant_cannot_be_activated_from_admin(self):
        # Even if someone forges is_activated in the POST, the field is read-only.
        response = self.client.post(self.applicant_add, {**APPLICANT_FORM, "is_activated": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Applicant.objects.get().is_activated)
