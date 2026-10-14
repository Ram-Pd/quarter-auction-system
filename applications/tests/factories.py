"""
Helpers that build applicants for tests. Everything goes through
applications/services.py, exactly like the real screens.
"""
from decimal import Decimal

from django.contrib.auth.models import Group
from django.utils import timezone

from accounts.tests.factories import make_user
from applications import services
from applications.models import DocumentChecklistItem
from applications.validators import verhoeff_check_digit

DETAILS = {"name": "Test Applicant", "father_name": "Test Father", "address": "Fake address, for tests only",
           "state": "Jharkhand", "pin_code": "827001"}


def fake_aadhaar(n=1):
    """A FAKE, format-valid Aadhaar number (correct Verhoeff check digit)."""
    body = f"23456789{n:03d}"
    return body + verhoeff_check_digit(body)


def fake_pan(n=1):
    return f"ABCPE{n:04d}F"


def make_staff(email, group_name, password="Staff-Pass-2026!"):
    user = make_user(email=email, full_name=group_name, is_staff=True, password=password)
    user.groups.add(Group.objects.get(name=group_name))
    return user


def make_officer(n=1):
    """A Verification Officer (the same account is reused if it already exists)."""
    from accounts.models import User
    email = f"officer{n}@example.com"
    return User.objects.filter(email=email).first() or make_staff(email, "Verification Officer")


def make_applicant(n=1, quarters=(), user=None, **details):
    """A registered applicant (status REGISTERED) who applied for `quarters`."""
    user = user or make_user(n)
    return services.submit_application(user, {**DETAILS, **details}, fake_aadhaar(n), fake_pan(n), list(quarters))


def verify_emd(applicant, quarter, officer):
    application = applicant.quarter_applications.get(quarter=quarter)
    services.record_emd(application, f"RCPT-{applicant.pk}-{quarter.pk}", application.emd_amount,
                        timezone.localdate(), officer)
    return services.verify_emd(application, officer)


def activate(applicant, officer, verify_quarters=None):
    """Tick every document, verify the EMD for `verify_quarters` (default: all applied), activate."""
    for item in DocumentChecklistItem.objects.filter(is_active=True):
        services.set_document_check(applicant, item, True, officer)
    quarters = verify_quarters if verify_quarters is not None else [a.quarter for a in
                                                                     applicant.quarter_applications.all()]
    for quarter in quarters:
        verify_emd(applicant, quarter, officer)
    services.activate(applicant, officer)
    applicant.refresh_from_db()
    return applicant


def make_eligible_applicant(n, quarters, officer=None):
    """ACTIVE applicant with the EMD verified for every quarter in `quarters`."""
    officer = officer or make_officer(1000 + n)
    return activate(make_applicant(n, quarters), officer)


def make_eligible_for(applicant, quarter, officer=None):
    """Add `quarter` to an existing applicant's application and verify its EMD."""
    from applications.models import QuarterApplication
    officer = officer or make_officer(2000 + applicant.pk)
    QuarterApplication.objects.get_or_create(applicant=applicant, quarter=quarter,
                                             defaults={"emd_amount": quarter.emd_amount or Decimal("1")})
    return verify_emd(applicant, quarter, officer)
