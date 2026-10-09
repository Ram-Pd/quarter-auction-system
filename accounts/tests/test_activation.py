from django.contrib.auth import get_user
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Applicant
from accounts.services import ActivationError, activate_applicant
from accounts.tests.factories import (
    STRONG_PASSWORD, make_activated_applicant, make_applicant, make_verified_applicant,
)


class ActivationServiceTests(TestCase):
    def test_creates_user_with_urn_as_username(self):
        applicant = make_verified_applicant()
        user = activate_applicant(applicant, STRONG_PASSWORD)
        applicant.refresh_from_db()
        self.assertEqual(user.username, applicant.urn)
        self.assertEqual(user.email, applicant.email)
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertNotEqual(user.password, STRONG_PASSWORD)  # stored hashed
        self.assertTrue(applicant.is_activated)
        self.assertEqual(applicant.user, user)

    def test_refuses_unverified_and_already_activated(self):
        with self.assertRaises(ActivationError):
            activate_applicant(make_applicant(1), STRONG_PASSWORD)
        applicant, _ = make_activated_applicant(2)
        with self.assertRaises(ActivationError):
            activate_applicant(applicant, STRONG_PASSWORD)
        self.assertEqual(User.objects.count(), 1)

    def test_email_change_is_copied_to_user(self):
        applicant, user = make_activated_applicant()
        applicant.email = "new.address@example.com"
        applicant.save()
        user.refresh_from_db()
        self.assertEqual(user.email, "new.address@example.com")


class ActivationPageTests(TestCase):
    url = reverse("accounts:activate")

    def setUp(self):
        cache.clear()  # rate-limit counters live in the cache
        self.applicant = make_verified_applicant()

    def post(self, **overrides):
        data = {"email": self.applicant.email, "urn": self.applicant.urn,
                "password1": STRONG_PASSWORD, "password2": STRONG_PASSWORD}
        data.update(overrides)
        return self.client.post(self.url, data, follow=True)

    def test_successful_activation_logs_in_and_opens_lobby(self):
        response = self.post(email=self.applicant.email.upper())  # email is case-insensitive
        self.assertRedirects(response, reverse("auctions:lobby"))
        self.assertContains(response, "Your account is activated")
        self.assertTrue(get_user(self.client).is_authenticated)
        self.applicant.refresh_from_db()
        self.assertTrue(self.applicant.is_activated)

    def test_wrong_urn_or_email_gives_same_message(self):
        for overrides in ({"urn": "0000000"}, {"email": "someone.else@example.com"}):
            with self.subTest(**overrides):
                response = self.post(**overrides)
                self.assertContains(response, "do not match our records")
        self.assertEqual(User.objects.count(), 0)

    def test_unverified_applicant_told_to_wait(self):
        unverified = make_applicant(2)
        response = self.post(email=unverified.email, urn=unverified.urn)
        self.assertContains(response, "has not been verified yet")
        self.assertEqual(User.objects.count(), 0)

    def test_already_activated(self):
        self.post()
        self.client.logout()
        response = self.post()
        self.assertContains(response, "already activated")
        self.assertEqual(User.objects.count(), 1)

    def test_password_rules(self):
        cases = [
            ({"password2": "Different-Pass-99"}, "do not match"),
            ({"password1": "short", "password2": "short"}, "too short"),
            ({"password1": "12345678901", "password2": "12345678901"}, "entirely numeric"),
            ({"password1": "password123", "password2": "password123"}, "too common"),
        ]
        for overrides, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.post(**overrides), message)
        self.assertEqual(User.objects.count(), 0)

    def test_password_too_similar_to_urn_rejected(self):
        similar = f"{self.applicant.urn}a"
        self.assertContains(self.post(password1=similar, password2=similar), "too similar")

    @override_settings(AUTH_RATE_LIMIT_ATTEMPTS=3)
    def test_guessing_urns_is_rate_limited(self):
        for guess in ["1000001", "1000002", "1000003"]:
            self.assertContains(self.post(urn=guess), "do not match")
        # Even the CORRECT URN is now refused for this email until the window passes.
        response = self.post()
        self.assertContains(response, "Too many failed attempts")
        self.assertEqual(User.objects.count(), 0)

    def test_logged_in_user_is_sent_to_lobby(self):
        _, user = make_activated_applicant(2)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), reverse("auctions:lobby"))


class ApplicantAdminActivationTests(TestCase):
    def test_admin_cannot_tick_activated(self):
        """is_activated is read-only in admin; only the activation flow sets it."""
        admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        self.client.force_login(admin)
        applicant = make_verified_applicant()
        url = reverse("admin:accounts_applicant_change", args=[applicant.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'name="is_activated"')
        self.assertFalse(Applicant.objects.get().is_activated)
