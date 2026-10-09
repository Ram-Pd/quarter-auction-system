import re
from datetime import date
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase

from accounts.models import Applicant, generate_urn
from accounts.tests.factories import new_applicant


class UrnGenerationTests(TestCase):
    def test_generate_urn_is_seven_digits_without_leading_zero(self):
        for _ in range(1000):
            urn = generate_urn()
            self.assertRegex(urn, r"^[1-9]\d{6}$")

    def test_urn_and_application_no_generated_on_save(self):
        a = new_applicant()
        a.save()
        a.refresh_from_db()
        self.assertRegex(a.urn, r"^[1-9]\d{6}$")
        self.assertEqual(a.application_no, f"QA{date.today():%Y}{a.pk:06d}")

    def test_many_applicants_get_unique_values(self):
        for n in range(50):
            new_applicant(n).save()
        self.assertEqual(Applicant.objects.values("urn").distinct().count(), 50)
        self.assertEqual(Applicant.objects.values("application_no").distinct().count(), 50)

    def test_urn_collision_is_retried(self):
        new_applicant(1, urn="1111111").save()
        # First random URN collides with the existing one, second is free.
        with mock.patch("accounts.models.generate_urn", side_effect=["1111111", "2222222"]):
            a = new_applicant(2)
            a.save()
        self.assertEqual(a.urn, "2222222")
        self.assertEqual(Applicant.objects.count(), 2)

    def test_gives_up_after_too_many_collisions(self):
        new_applicant(1, urn="1111111").save()
        with mock.patch("accounts.models.generate_urn", return_value="1111111"):
            with self.assertRaisesMessage(IntegrityError, "Could not find a free URN"):
                new_applicant(2).save()
        self.assertEqual(Applicant.objects.count(), 1)

    def test_duplicate_email_is_not_mistaken_for_urn_collision(self):
        new_applicant(1).save()
        with mock.patch("accounts.models.generate_urn", wraps=generate_urn) as gen:
            with self.assertRaises(IntegrityError):
                new_applicant(2, email="applicant1@example.com").save()
        self.assertEqual(gen.call_count, 1)  # no pointless retries
        self.assertEqual(Applicant.objects.count(), 1)

    def test_manually_supplied_urn_is_kept(self):
        a = new_applicant(urn="7654321")
        a.save()
        self.assertEqual(a.urn, "7654321")
        self.assertTrue(re.match(r"^QA\d{10}$", a.application_no))

    def test_resaving_does_not_change_generated_values(self):
        a = new_applicant()
        a.save()
        urn, app_no = a.urn, a.application_no
        a.name = "Changed"
        a.save()
        a.refresh_from_db()
        self.assertEqual((a.urn, a.application_no), (urn, app_no))
