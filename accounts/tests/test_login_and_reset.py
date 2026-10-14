import re

from django.contrib.auth import get_user
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.tests.factories import STRONG_PASSWORD, make_user


class LoginLogoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def login(self, username=None, password=STRONG_PASSWORD):
        return self.client.post(reverse("accounts:login"),
                                {"username": username or self.user.email, "password": password},
                                follow=True)

    def test_login_with_email_goes_to_listing(self):
        response = self.login()
        self.assertRedirects(response, reverse("auctions:listing"))
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_email_is_not_case_sensitive(self):
        self.login(username="  USER1@Example.com ")
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_login_page_asks_for_email_and_offers_signup(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertContains(response, '<label for="id_username">Email address:</label>', html=True)
        self.assertContains(response, reverse("accounts:signup"))

    def test_wrong_password(self):
        response = self.login(password="wrong-password")
        self.assertContains(response, "Incorrect email or password.")
        self.assertFalse(get_user(self.client).is_authenticated)

    @override_settings(AUTH_RATE_LIMIT_ATTEMPTS=3)
    def test_password_guessing_is_rate_limited(self):
        for _ in range(3):
            self.login(password="wrong-password")
        response = self.login()  # correct password, but blocked
        self.assertContains(response, "Too many failed attempts")
        self.assertFalse(get_user(self.client).is_authenticated)

    @override_settings(AUTH_RATE_LIMIT_ATTEMPTS=100, AUTH_RATE_LIMIT_IP_ATTEMPTS=4)
    def test_many_accounts_from_one_ip_is_rate_limited(self):
        for n in range(4):
            self.login(username=f"nobody{n}@example.com", password="x")
        self.assertContains(self.login(), "Too many failed attempts")

    def test_logout_requires_post_and_works(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        response = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertRedirects(response, reverse("home"))
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_navigation_changes_when_logged_in(self):
        self.assertContains(self.client.get(reverse("home")), reverse("accounts:login"))
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Log out")
        self.assertContains(response, self.user.full_name)


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user()

    def request_reset(self, email):
        return self.client.post(reverse("accounts:password_reset"), {"email": email}, follow=True)

    def test_full_reset_flow(self):
        response = self.request_reset(self.user.email.upper())
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("expires in 1 hour", mail.outbox[0].body)

        link = re.search(r"http://testserver(/password-reset/\S+/\S+/)", mail.outbox[0].body).group(1)
        # Django swaps the token for a session marker and redirects to a "set-password" URL.
        form_page = self.client.get(link, follow=True)
        self.assertContains(form_page, "Set a new password")
        new_password = "Another-Strong-Pass-77"
        done = self.client.post(form_page.redirect_chain[-1][0],
                                {"new_password1": new_password, "new_password2": new_password},
                                follow=True)
        self.assertRedirects(done, reverse("accounts:password_reset_complete"))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new_password))
        # The link is single-use.
        self.assertContains(self.client.get(link, follow=True), "Link not valid")

    def test_unknown_email_shows_same_page_but_sends_nothing(self):
        response = self.request_reset("nobody@example.com")
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_tampered_token_rejected(self):
        self.request_reset(self.user.email)
        link = re.search(r"http://testserver(/password-reset/\S+/)\S+/", mail.outbox[0].body).group(1)
        response = self.client.get(link + "bad-token/", follow=True)
        self.assertContains(response, "Link not valid")
