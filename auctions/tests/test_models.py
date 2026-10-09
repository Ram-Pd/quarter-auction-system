from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from auctions.models import Quarter


def make_quarter(**overrides):
    data = {
        "quarter_no": "B-214",
        "sector": "Sector 4",
        "location_block": "Near market",
        "quarter_type": Quarter.QuarterType.B,
        "floor": "2nd",
        "area_sqft": Decimal("750"),
        "base_rate": Decimal("4500"),
    }
    data.update(overrides)
    return Quarter.objects.create(**data)


class QuarterModelTests(TestCase):
    def test_defaults_to_vacant(self):
        self.assertEqual(make_quarter().status, Quarter.Status.VACANT)

    def test_quarter_no_is_normalised(self):
        q = make_quarter(quarter_no="  b-214 ")
        self.assertEqual(q.quarter_no, "B-214")

    def test_duplicate_quarter_no_rejected(self):
        make_quarter()
        with self.assertRaises(IntegrityError):
            make_quarter()

    def test_duplicate_quarter_no_rejected_case_insensitive_at_db_level(self):
        make_quarter()
        # .update() bypasses save(), so only the DB constraint can catch this.
        other = make_quarter(quarter_no="B-118")
        with self.assertRaises(IntegrityError):
            Quarter.objects.filter(pk=other.pk).update(quarter_no="b-214")

    def test_area_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            make_quarter(area_sqft=Decimal("0"))

    def test_base_rate_must_be_positive(self):
        with self.assertRaises(IntegrityError):
            make_quarter(base_rate=Decimal("-100"))

    def test_str(self):
        self.assertEqual(str(make_quarter()), "B-214")
