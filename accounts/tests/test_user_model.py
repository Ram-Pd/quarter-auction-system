"""The custom User model: email is the login name."""
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import User
from accounts.tests.factories import STRONG_PASSWORD, make_user


class UserModelTests(TestCase):
    def test_project_uses_the_custom_user(self):
        self.assertIs(get_user_model(), User)
        self.assertEqual(User.USERNAME_FIELD, "email")
        self.assertFalse(hasattr(User(), "username") and User().username)

    def test_email_is_normalised(self):
        user = make_user(email="  Mixed.Case@Example.COM ")
        self.assertEqual(user.email, "mixed.case@example.com")

    def test_email_unique_case_insensitive(self):
        make_user(email="a@example.com")
        with self.assertRaises(IntegrityError):
            # .update() skips save(), so only the DB constraint can catch this.
            other = make_user(2, email="b@example.com")
            User.objects.filter(pk=other.pk).update(email="A@example.com")

    def test_password_is_hashed(self):
        user = make_user()
        self.assertNotIn(STRONG_PASSWORD, user.password)
        self.assertTrue(user.check_password(STRONG_PASSWORD))

    def test_authenticate_with_email(self):
        user = make_user()
        self.assertEqual(authenticate(username="user1@example.com", password=STRONG_PASSWORD), user)
        self.assertIsNone(authenticate(username="user1@example.com", password="wrong"))

    def test_superuser(self):
        admin = User.objects.create_superuser("boss@example.com", STRONG_PASSWORD, full_name="Boss")
        self.assertTrue(admin.is_staff and admin.is_superuser)
        self.assertEqual(admin.get_full_name(), "Boss")
        self.assertEqual(str(admin), "boss@example.com")
