"""Helpers that build test data. Import these in any test module."""
from accounts.models import Applicant
from accounts.services import activate_applicant

STRONG_PASSWORD = "Bokaro-Steel-2026!"


def new_applicant(n=1, **overrides):
    """Unsaved applicant WITHOUT urn / application_no (so save() generates them)."""
    data = {
        "name": f"Test Applicant {n}",
        "father_name": "Test Father",
        "mobile": "9876543210",
        "email": f"applicant{n}@example.com",
        "address": "Fake address",
        "state": "Jharkhand",
        "pin_code": "827001",
    }
    data.update(overrides)
    return Applicant(**data)


def make_applicant(n=1, **overrides):
    applicant = new_applicant(n, **overrides)
    applicant.save()
    return applicant


def make_verified_applicant(n=1, **overrides):
    return make_applicant(n, is_verified=True, **overrides)


def make_activated_applicant(n=1, password=STRONG_PASSWORD, **overrides):
    """Verified + activated; returns (applicant, user)."""
    applicant = make_verified_applicant(n, **overrides)
    user = activate_applicant(applicant, password)
    applicant.refresh_from_db()
    return applicant, user
