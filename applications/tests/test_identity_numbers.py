"""Aadhaar / PAN: format checks, masking, encryption at rest, keyed hash."""
from cryptography.fernet import Fernet
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from applications import crypto
from applications.models import Applicant
from applications.tests.factories import fake_aadhaar, fake_pan, make_applicant
from applications.validators import (mask_aadhaar, mask_pan, normalise_aadhaar, normalise_pan, validate_aadhaar,
                                     validate_pan, verhoeff_check_digit, verhoeff_is_valid)


class VerhoeffTests(SimpleTestCase):
    def test_known_values(self):
        # Textbook example: 236 -> check digit 3.
        self.assertEqual(verhoeff_check_digit("236"), "3")
        self.assertTrue(verhoeff_is_valid("2363"))
        self.assertFalse(verhoeff_is_valid("2364"))

    def test_catches_single_typo_and_swapped_neighbours(self):
        number = fake_aadhaar(7)
        self.assertTrue(verhoeff_is_valid(number))
        typo = number[:5] + str((int(number[5]) + 1) % 10) + number[6:]
        self.assertFalse(verhoeff_is_valid(typo))
        i = next(i for i in range(11) if number[i] != number[i + 1])
        swapped = number[:i] + number[i + 1] + number[i] + number[i + 2:]
        self.assertFalse(verhoeff_is_valid(swapped))


class AadhaarPanFormatTests(SimpleTestCase):
    def test_valid_aadhaar(self):
        number = fake_aadhaar(1)
        validate_aadhaar(normalise_aadhaar(f"{number[:4]} {number[4:8]}-{number[8:]}"))

    def test_invalid_aadhaar(self):
        good = fake_aadhaar(1)
        bad_check = good[:-1] + str((int(good[-1]) + 1) % 10)
        for bad in ["12345678901", "1234567890123", "abcd56789012", "023456789012", "123456789012", bad_check]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_aadhaar(bad)

    def test_pan(self):
        validate_pan(normalise_pan(" abcpe1234f "))
        for bad in ["ABCPE1234", "ABCP1234FF", "1BCPE1234F", "ABCPE12345"]:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                validate_pan(bad)

    def test_masking_shows_last_four_only(self):
        self.assertEqual(mask_aadhaar("0124"), "XXXX XXXX 0124")
        self.assertEqual(mask_pan("234F"), "XXXXXX234F")


class CryptoTests(SimpleTestCase):
    def test_round_trip_and_random_iv(self):
        a, b = crypto.encrypt("234567890124"), crypto.encrypt("234567890124")
        self.assertNotEqual(a, b)                      # same number, different ciphertext
        self.assertNotIn("234567890124", a)
        self.assertEqual(crypto.decrypt(a), "234567890124")

    def test_key_rotation(self):
        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        with override_settings(FIELD_ENCRYPTION_KEYS=[old]):
            token = crypto.encrypt("ABCPE1234F")
        with override_settings(FIELD_ENCRYPTION_KEYS=[new, old]):   # new key first, old still readable
            self.assertEqual(crypto.decrypt(token), "ABCPE1234F")
        with override_settings(FIELD_ENCRYPTION_KEYS=[new]), self.assertRaises(crypto.InvalidToken):
            crypto.decrypt(token)                                    # without the old key: unreadable

    def test_blind_index_is_stable_and_keyed(self):
        self.assertEqual(crypto.blind_index("pan", "ABCPE1234F"), crypto.blind_index("pan", "ABCPE1234F"))
        self.assertNotEqual(crypto.blind_index("pan", "ABCPE1234F"), crypto.blind_index("aadhaar", "ABCPE1234F"))
        with override_settings(IDENTITY_HASH_KEY="another-secret"):
            other = crypto.blind_index("pan", "ABCPE1234F")
        self.assertNotEqual(other, crypto.blind_index("pan", "ABCPE1234F"))


class StorageTests(TestCase):
    def test_numbers_never_stored_in_plain_text(self):
        applicant = make_applicant(1)
        aadhaar, pan = fake_aadhaar(1), fake_pan(1)
        with connection.cursor() as cursor:   # look at the raw database row, not the model
            cursor.execute("SELECT * FROM applications_applicant WHERE id = %s", [applicant.pk])
            raw = " ".join(str(v) for v in cursor.fetchone())
        self.assertNotIn(aadhaar, raw)
        self.assertNotIn(pan, raw)
        self.assertEqual(applicant.masked_aadhaar, f"XXXX XXXX {aadhaar[-4:]}")
        self.assertEqual(applicant.masked_pan, f"XXXXXX{pan[-4:]}")
        self.assertEqual(applicant.decrypt_identity_numbers(), (aadhaar, pan))

    def test_str_shows_application_number_only(self):
        applicant = make_applicant(1)
        self.assertEqual(str(applicant), applicant.application_no)
        self.assertRegex(applicant.urn, r"^[1-9]\d{6}$")
        self.assertRegex(applicant.application_no, r"^QA\d{4}\d{6}$")

    def test_same_aadhaar_or_pan_cannot_register_twice(self):
        from django.db import IntegrityError, transaction

        from accounts.tests.factories import make_user
        from applications import services
        from applications.tests.factories import DETAILS
        make_applicant(1)
        for aadhaar, pan in [(fake_aadhaar(1), fake_pan(2)), (fake_aadhaar(2), fake_pan(1))]:
            with self.subTest(aadhaar=aadhaar, pan=pan), self.assertRaises(IntegrityError), transaction.atomic():
                services.submit_application(make_user(email=f"{pan}@example.com"), DETAILS, aadhaar, pan, [])
        self.assertEqual(Applicant.objects.count(), 1)
