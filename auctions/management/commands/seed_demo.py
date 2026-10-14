"""
Fill the database with FAKE demo data:

    python manage.py seed_demo

Creates (skipping anything that already exists):
  - the 8 sample quarters + auctions (bidding a week from today, so they are
    still open for applications), imported exactly like the Excel upload
  - 3 extra demo quarters whose auctions are LIVE now / start soon (for bidding)
  - staff:   officer@example.com (Verification Officer), auctionadmin@example.com (Auction Admin)
  - users:   demo1-3 ACTIVE bidders (EMD verified for the live quarters),
             demo4 with documents pending (to show the verification screen),
             demo5 with an account only (to show "Register for bidding")
All passwords are DEMO_PASSWORD below. Aadhaar / PAN numbers are FAKE (valid format only).

Emails produced while seeding (documents for the demo applicants) are always
saved as .eml files in sent_emails/, never sent through SMTP, even if a real
mail server is configured: the demo addresses are fake.

Development only: refuses to run when DEBUG is False.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from django.utils import timezone

from accounts.models import User
from applications import services
from applications.models import Applicant, DocumentChecklistItem
from applications.validators import verhoeff_check_digit
from auctions.importers import import_quarters
from auctions.models import Auction, Quarter
from sample_data.make_samples import bidding_day, build_valid

DEMO_PASSWORD = "Demo-Pass-2026"

# Quarters with auctions running now, for the bidding demo:
# (quarter_no, type, base rate, EMD, starts in, duration in minutes)
LIVE_QUARTERS = [
    ("L-301", "B", Decimal("45000"), Decimal("9000"), timedelta(minutes=-1), 20),
    ("L-302", "C", Decimal("38000"), Decimal("7500"), timedelta(minutes=-1), 20),   # same time as L-301
    ("L-303", "A", Decimal("62000"), Decimal("12000"), timedelta(minutes=10), 5),
]

# (n, status to reach, quarters to apply for)
DEMO_APPLICANTS = [
    (1, "ACTIVE", ["L-301", "L-302", "L-303", "B-214"]),
    (2, "ACTIVE", ["L-301", "L-302", "L-303", "C-305"]),
    (3, "ACTIVE", ["L-301", "L-303", "A-021"]),
    (4, "DOCUMENTS_PENDING", ["B-214", "B-118"]),
]


def fake_aadhaar(n):
    """A FAKE 12-digit number with a correct Verhoeff check digit (format-valid only)."""
    body = f"99990000{n:03d}"
    return body + verhoeff_check_digit(body)


def fake_pan(n):
    return f"DEMOP{n:04d}F"


class Command(BaseCommand):
    help = "Create FAKE demo quarters, auctions, staff and applicants (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True (never on production data).")

        with override_settings(EMAIL_BACKEND="config.email_backends.EmlFileBackend"):
            self.seed_sample_quarters()
            self.seed_live_quarters()
            officer = self.seed_staff()
            self.seed_applicants(officer)
        self.stdout.write(self.style.SUCCESS("Demo data ready. ALL OF IT IS FAKE."))

    def seed_sample_quarters(self):
        if Quarter.objects.filter(quarter_no="B-214").exists():
            self.stdout.write("Sample quarters: already present, skipped.")
            return
        from io import BytesIO
        buf = BytesIO()
        build_valid(bidding_day()).save(buf)
        buf.seek(0)
        result = import_quarters(buf)
        if not result.ok:
            raise CommandError("Sample import failed: " + "; ".join(map(str, result.errors)))
        self.stdout.write(f"Sample quarters: imported {result.created} (bidding on {bidding_day():%d-%m-%Y}).")

    def seed_live_quarters(self):
        now = timezone.now()
        for quarter_no, qtype, base, emd, starts_in, minutes in LIVE_QUARTERS:
            quarter, _ = Quarter.objects.get_or_create(quarter_no=quarter_no, defaults={
                "sector": "Sector 1 (DEMO)", "location_block": "Demo block", "quarter_type": qtype,
                "floor": "1st", "area_sqft": Decimal("700"), "base_rate": base, "emd_amount": emd})
            if quarter.auctions.filter(status=Auction.Status.SCHEDULED).exists():
                continue
            if quarter.status == Quarter.Status.ALLOTTED:
                continue
            Auction.objects.create(quarter=quarter, start_time=now + starts_in, duration_minutes=minutes)
            self.stdout.write(f"Live demo auction: {quarter_no} from "
                              f"{timezone.localtime(now + starts_in):%H:%M} for {minutes} min.")

    def seed_staff(self):
        self.stdout.write("\nStaff (FAKE):")
        officer = None
        for email, name, group in [("officer@example.com", "Demo Verification Officer", "Verification Officer"),
                                   ("auctionadmin@example.com", "Demo Auction Admin", "Auction Admin")]:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, DEMO_PASSWORD, full_name=name, is_staff=True)
                user.groups.add(Group.objects.get(name=group))
            if group == "Verification Officer":
                officer = user
            self.stdout.write(f"  {email:28} {group:22} password {DEMO_PASSWORD}")
        return officer

    def seed_applicants(self, officer):
        self.stdout.write("\nApplicants (FAKE):")
        for n, target, quarter_nos in DEMO_APPLICANTS + [(5, None, [])]:
            email = f"demo{n}@example.com"
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, DEMO_PASSWORD, full_name=f"Demo User {n}",
                                                phone=f"98765000{n:02d}", email_verified_at=timezone.now())
            applicant = Applicant.for_user(user)
            if target and applicant is None:
                quarters = list(Quarter.objects.filter(quarter_no__in=quarter_nos).order_by("quarter_no"))
                applicant = services.submit_application(
                    user, {"name": f"Demo User {n}", "father_name": "Demo Father",
                           "address": "Demo address (FAKE)", "state": "Jharkhand", "pin_code": "827001"},
                    fake_aadhaar(n), fake_pan(n), quarters)
                if target == "ACTIVE":
                    self.verify_everything(applicant, officer)
                else:
                    first_item = DocumentChecklistItem.objects.filter(is_active=True).first()
                    services.set_document_check(applicant, first_item, True, officer)
            status = applicant.get_status_display() if applicant else "account only (not registered)"
            self.stdout.write(f"  {email:22} password {DEMO_PASSWORD}  {status}"
                              + (f"  URN {applicant.urn}" if applicant else ""))

    def verify_everything(self, applicant, officer):
        """What the Verification Officer would do at the counter (all FAKE)."""
        for item in DocumentChecklistItem.objects.filter(is_active=True):
            services.set_document_check(applicant, item, True, officer)
        for application in applicant.quarter_applications.all():
            services.record_emd(application, f"DEMO-{applicant.urn}-{application.quarter_id}",
                                application.emd_amount, timezone.localdate(), officer)
            services.verify_emd(application, officer)
        services.activate(applicant, officer)
