from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Applicant
from accounts.tests.factories import new_applicant

VALID = {
    "name": "  Ravi   Kumar ",
    "father_name": "Mohan Kumar",
    "mobile": "+91 98765-43210",
    "email": "Ravi.Kumar@Example.com",
    "address": "Qtr 12, Street 3, Sector 4",
    "state": "Jharkhand",
    "pin_code": "827 001",
    "declaration": "on",
}


class RegistrationPageTests(TestCase):
    url = reverse("accounts:register")

    def test_home_page_links_to_registration(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, self.url)
        self.assertContains(response, "not an official SAIL website")

    def test_form_page_loads(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Applicant Registration")
        self.assertContains(response, "Jharkhand")  # state dropdown

    def test_valid_registration(self):
        response = self.client.post(self.url, VALID, follow=True)
        self.assertRedirects(response, reverse("accounts:register_done"))

        a = Applicant.objects.get()
        self.assertEqual(a.name, "Ravi Kumar")         # whitespace collapsed
        self.assertEqual(a.mobile, "9876543210")       # +91 and dash removed
        self.assertEqual(a.email, "ravi.kumar@example.com")
        self.assertEqual(a.pin_code, "827001")
        self.assertRegex(a.urn, r"^\d{7}$")
        self.assertFalse(a.is_verified)
        self.assertFalse(a.is_activated)
        self.assertIsNone(a.user)
        self.assertEqual(User.objects.count(), 0)      # no login account until activation
        self.assertIsNotNone(a.documents_emailed_at)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(len(mail.outbox[0].attachments), 2)

        self.assertContains(response, a.application_no)
        self.assertContains(response, "have been emailed")
        self.assertNotContains(response, a.urn)  # URN is only sent by email

    def test_refreshing_success_page_does_not_register_again(self):
        self.client.post(self.url, VALID)
        self.client.get(reverse("accounts:register_done"))
        self.client.get(reverse("accounts:register_done"))
        self.assertEqual(Applicant.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_success_page_without_registration_redirects(self):
        response = self.client.get(reverse("accounts:register_done"))
        self.assertRedirects(response, self.url)

    def test_field_errors(self):
        cases = {
            "mobile": ("12345", "valid 10-digit Indian mobile"),
            "pin_code": ("012345", "valid 6-digit PIN"),
            "email": ("not-an-email", "valid email"),
            "state": ("Atlantis", "Select a valid choice"),
            "name": ("", "This field is required"),
            "declaration": ("", "You must accept the declaration"),
        }
        for field, (value, message) in cases.items():
            with self.subTest(field=field):
                response = self.client.post(self.url, {**VALID, field: value})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
        self.assertEqual(Applicant.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_duplicate_email_rejected_case_insensitive(self):
        new_applicant(email="ravi.kumar@example.com").save()
        response = self.client.post(self.url, VALID)
        self.assertContains(response, "already registered")
        self.assertEqual(Applicant.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_registration_kept_when_email_fails(self):
        with mock.patch("accounts.views.send_registration_documents",
                        side_effect=ConnectionRefusedError("SMTP down")), \
                self.assertLogs("accounts.views", level="ERROR") as logs:
            response = self.client.post(self.url, VALID, follow=True)
        self.assertIn("Registration email failed", logs.output[0])  # admins can find it
        a = Applicant.objects.get()
        self.assertIsNone(a.documents_emailed_at)
        self.assertContains(response, a.application_no)
        self.assertContains(response, "could not send the email")


class ResendActionTests(TestCase):
    def test_admin_can_resend_documents(self):
        admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.force_login(admin)
        a = new_applicant()
        a.save()
        response = self.client.post(
            reverse("admin:accounts_applicant_changelist"),
            {"action": "resend_documents", "_selected_action": [a.pk]},
            follow=True,
        )
        self.assertContains(response, "Documents sent to 1 applicant(s).")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [a.email])
