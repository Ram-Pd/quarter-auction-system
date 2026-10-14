"""Sign-up with email OTP (accounts/otp.py, accounts/views.py)."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import otp
from accounts.models import EmailOTP, User
from accounts.tests.factories import STRONG_PASSWORD, make_user

DETAILS = {"full_name": "  Ravi   Kumar ", "phone": "+91 98765-43210", "email": "Ravi@Example.com"}


def code_from(message):
    return re.search(r"\b(\d{6})\b", message.body).group(1)


class SignupFlowTests(TestCase):
    def setUp(self):
        cache.clear()

    def start(self, **overrides):
        return self.client.post(reverse("accounts:signup"), {**DETAILS, **overrides})

    def test_full_signup_flow(self):
        response = self.start()
        self.assertRedirects(response, reverse("accounts:signup_verify"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ravi@example.com"])
        code = code_from(mail.outbox[0])
        self.assertNotIn(code, mail.outbox[0].subject)   # not visible in notification previews
        self.assertEqual(User.objects.count(), 0)        # nothing saved before the end

        response = self.client.post(reverse("accounts:signup_verify"), {"code": code})
        self.assertRedirects(response, reverse("accounts:signup_password"))

        response = self.client.post(reverse("accounts:signup_password"),
                                    {"password1": STRONG_PASSWORD, "password2": STRONG_PASSWORD})
        self.assertRedirects(response, reverse("auctions:listing"))
        user = get_user(self.client)
        self.assertTrue(user.is_authenticated)
        self.assertEqual((user.email, user.full_name, user.phone), ("ravi@example.com", "Ravi Kumar", "9876543210"))
        self.assertIsNotNone(user.email_verified_at)
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_code_is_stored_hashed_only(self):
        self.start()
        code = code_from(mail.outbox[0])
        stored = EmailOTP.objects.get()
        self.assertNotIn(code, stored.code_hash)
        self.assertEqual(len(stored.code_hash), 64)
        self.assertEqual(len(code), 6)

    def test_existing_email_rejected(self):
        make_user(email="ravi@example.com")
        response = self.start()
        self.assertContains(response, "already exists")
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_phone_rejected(self):
        self.assertContains(self.start(phone="12345"), "valid 10-digit")

    def test_password_step_needs_a_confirmed_code(self):
        self.start()
        response = self.client.get(reverse("accounts:signup_password"))
        self.assertRedirects(response, reverse("accounts:signup_verify"))

    def test_steps_without_a_started_signup_go_back_to_start(self):
        for name in ["accounts:signup_verify", "accounts:signup_password"]:
            self.assertRedirects(self.client.get(reverse(name)), reverse("accounts:signup"))

    @override_settings(SIGNUP_VERIFIED_WINDOW_MINUTES=30)
    def test_confirmed_code_must_be_used_within_window(self):
        self.start()
        self.client.post(reverse("accounts:signup_verify"), {"code": code_from(mail.outbox[0])})
        later = timezone.now() + timedelta(minutes=31)
        with mock.patch("django.utils.timezone.now", return_value=later):
            response = self.client.get(reverse("accounts:signup_password"))
        self.assertRedirects(response, reverse("accounts:signup_verify"))

    def test_weak_password_rejected(self):
        self.start()
        self.client.post(reverse("accounts:signup_verify"), {"code": code_from(mail.outbox[0])})
        for weak in ["password", "12345678", "ravi@example.com"]:
            response = self.client.post(reverse("accounts:signup_password"), {"password1": weak, "password2": weak})
            self.assertEqual(response.status_code, 200, weak)
        self.assertEqual(User.objects.count(), 0)

    def test_resend_has_cooldown_and_new_code_replaces_old(self):
        self.start()
        first = code_from(mail.outbox[0])
        response = self.client.post(reverse("accounts:signup_resend"), follow=True)
        self.assertContains(response, "Please wait")
        self.assertEqual(len(mail.outbox), 1)

        EmailOTP.objects.update(created_at=timezone.now() - timedelta(minutes=2))  # cooldown over
        self.client.post(reverse("accounts:signup_resend"))
        self.assertEqual(len(mail.outbox), 2)
        second = code_from(mail.outbox[1])
        if first != second:  # (1 in a million they are equal)
            response = self.client.post(reverse("accounts:signup_verify"), {"code": first})
            self.assertContains(response, "Incorrect code")  # only the newest code works
        response = self.client.post(reverse("accounts:signup_verify"), {"code": second})
        self.assertRedirects(response, reverse("accounts:signup_password"))


class OtpServiceTests(TestCase):
    """The OTP rules directly, without the pages."""

    EMAIL = "otp@example.com"

    def setUp(self):
        cache.clear()
        self.request = mock.Mock(META={"REMOTE_ADDR": "10.0.0.1"})

    def send(self):
        otp.send_signup_otp(self.EMAIL, self.request)
        return code_from(mail.outbox[-1])

    def wrong(self, code):
        return "000000" if code != "000000" else "111111"

    def test_correct_code_works_once(self):
        code = self.send()
        otp.verify_signup_otp(self.EMAIL, code)
        with self.assertRaisesMessage(otp.OtpError, "expired"):
            otp.verify_signup_otp(self.EMAIL, code)  # single use

    @override_settings(OTP_MAX_ATTEMPTS=5)
    def test_five_wrong_attempts_kill_the_code(self):
        code = self.send()
        for left in [4, 3, 2, 1]:
            with self.assertRaisesMessage(otp.OtpError, f"{left} attempt"):
                otp.verify_signup_otp(self.EMAIL, self.wrong(code))
        with self.assertRaisesMessage(otp.OtpError, "Too many wrong attempts"):
            otp.verify_signup_otp(self.EMAIL, self.wrong(code))
        with self.assertRaisesMessage(otp.OtpError, "Too many wrong attempts"):
            otp.verify_signup_otp(self.EMAIL, code)  # even the right code is refused now
        self.assertEqual(EmailOTP.objects.get().failed_attempts, 5)

    @override_settings(OTP_VALID_MINUTES=10)
    def test_code_expires(self):
        code = self.send()
        later = timezone.now() + timedelta(minutes=10, seconds=1)
        with mock.patch("accounts.otp.timezone.now", return_value=later):
            with self.assertRaisesMessage(otp.OtpError, "expired"):
                otp.verify_signup_otp(self.EMAIL, code)

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=0, OTP_SENDS_PER_EMAIL_PER_HOUR=3)
    def test_sends_per_email_are_limited(self):
        for _ in range(3):
            self.send()
        with self.assertRaisesMessage(otp.OtpError, "Too many codes"):
            self.send()

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=0, OTP_SENDS_PER_EMAIL_PER_HOUR=100,
                       OTP_SENDS_PER_IP_PER_HOUR=2)
    def test_sends_per_ip_are_limited(self):
        otp.send_signup_otp("one@example.com", self.request)
        otp.send_signup_otp("two@example.com", self.request)
        with self.assertRaisesMessage(otp.OtpError, "Too many codes"):
            otp.send_signup_otp("three@example.com", self.request)

    def test_code_for_one_email_does_not_work_for_another(self):
        code = self.send()
        with self.assertRaises(otp.OtpError):
            otp.verify_signup_otp("someone.else@example.com", code)
