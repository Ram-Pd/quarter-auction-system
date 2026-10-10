from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from accounts.models import Applicant
from accounts.tests.factories import make_activated_applicant


def make_applicant(**overrides):
    data = {
        "name": "Test Applicant",
        "father_name": "Test Father",
        "mobile": "9876543210",
        "email": "test@example.com",
        "address": "Fake address, for tests only",
        "state": "Jharkhand",
        "pin_code": "827001",
        "application_no": "APP-0001",
        "urn": "1234567",
    }
    data.update(overrides)
    return Applicant(**data)


class ApplicantModelTests(TestCase):
    def test_valid_applicant_passes_validation(self):
        a = make_applicant()
        a.full_clean()  # raises ValidationError if anything is wrong
        a.save()
        self.assertFalse(a.is_verified)
        self.assertFalse(a.is_activated)
        self.assertIsNone(a.user)

    def test_urn_must_be_seven_digits(self):
        for bad in ["123456", "12345678", "12A4567"]:
            with self.subTest(urn=bad), self.assertRaises(ValidationError):
                make_applicant(urn=bad).full_clean()

    def test_invalid_mobile_and_pin_rejected(self):
        with self.assertRaises(ValidationError):
            make_applicant(mobile="12345").full_clean()
        with self.assertRaises(ValidationError):
            make_applicant(pin_code="012345").full_clean()

    def test_duplicate_urn_rejected(self):
        make_applicant().save()
        with self.assertRaises(IntegrityError):
            make_applicant(email="other@example.com", application_no="APP-0002").save()

    def test_email_unique_case_insensitive(self):
        make_applicant().save()
        with self.assertRaises(IntegrityError):
            make_applicant(email="TEST@Example.com", application_no="APP-0002", urn="7654321").save()

    def test_activated_requires_user(self):
        with self.assertRaises(IntegrityError):
            make_applicant(is_activated=True).save()

    def test_user_with_applicant_cannot_be_deleted(self):
        user = User.objects.create_user(username="1234567", password="Str0ng-pass!")
        make_applicant(user=user, is_verified=True, is_activated=True).save()
        with self.assertRaises(ProtectedError):
            user.delete()


class ApplicantForUserTests(TestCase):
    """Applicant.for_user(): the one lookup used by views, the decorator and the WebSocket."""

    def test_activated_applicant_is_found(self):
        applicant, user = make_activated_applicant()
        self.assertEqual(Applicant.for_user(user), applicant)

    def test_user_without_applicant_gives_none(self):
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        self.assertIsNone(Applicant.for_user(staff))

    def test_anonymous_or_missing_user_gives_none(self):
        self.assertIsNone(Applicant.for_user(AnonymousUser()))
        self.assertIsNone(Applicant.for_user(None))
