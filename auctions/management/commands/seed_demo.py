"""
Fill the database with FAKE demo data:

    python manage.py seed_demo

Creates (skipping anything that already exists):
  - the 8 sample quarters from sample_data/quarters_sample.xlsx
  - 2 live auctions and 2 upcoming auctions
  - 3 activated demo applicants (can log in and bid)
  - 1 verified-but-not-activated applicant (to demonstrate activation)

Development only: refuses to run when DEBUG is False.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Applicant
from accounts.services import activate_applicant
from auctions.importers import import_quarters
from auctions.models import Auction, Quarter

DEMO_PASSWORD = "Demo-Pass-2026"
SAMPLE_FILE = settings.BASE_DIR / "sample_data" / "quarters_sample.xlsx"

# (quarter_no, starts in, lasts, min increment)
DEMO_AUCTIONS = [
    ("B-214", timedelta(minutes=-10), timedelta(hours=2), Decimal("100")),
    ("C-305", timedelta(minutes=-5), timedelta(minutes=30), Decimal("50")),
    ("A-021", timedelta(hours=1), timedelta(hours=1), Decimal("200")),
    ("D-407", timedelta(days=1), timedelta(hours=2), Decimal("50")),
]

DEMO_APPLICANTS = [
    # (n, activate?)
    (1, True), (2, True), (3, True), (4, False),
]


class Command(BaseCommand):
    help = "Create FAKE demo quarters, auctions and applicants (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DEBUG=True (never on production data).")

        self.seed_quarters()
        self.seed_auctions()
        self.seed_applicants()
        self.stdout.write(self.style.SUCCESS("Demo data ready. ALL OF IT IS FAKE."))

    def seed_quarters(self):
        if Quarter.objects.exists():
            self.stdout.write("Quarters: already present, skipped.")
            return
        result = import_quarters(SAMPLE_FILE)
        if not result.ok:
            raise CommandError("Sample import failed: " + "; ".join(map(str, result.errors)))
        self.stdout.write(f"Quarters: imported {result.created}.")

    def seed_auctions(self):
        now = timezone.now()
        for quarter_no, starts_in, lasts, increment in DEMO_AUCTIONS:
            quarter = Quarter.objects.filter(quarter_no=quarter_no).first()
            if quarter is None or quarter.auctions.filter(status=Auction.Status.OPEN).exists():
                continue
            start = now + starts_in
            Auction.objects.create(quarter=quarter, start_time=start, end_time=start + lasts,
                                   min_increment=increment)
            self.stdout.write(f"Auction: {quarter_no} from {timezone.localtime(start):%d %b %H:%M}.")

    def seed_applicants(self):
        self.stdout.write("\nDemo applicants (FAKE):")
        for n, activate in DEMO_APPLICANTS:
            email = f"demo{n}@example.com"
            applicant = Applicant.objects.filter(email=email).first()
            if applicant is None:
                applicant = Applicant.objects.create(
                    name=f"Demo Applicant {n}", father_name="Demo Father", mobile=f"98765000{n:02d}",
                    email=email, address="Demo address (FAKE)", state="Jharkhand",
                    pin_code="827001", is_verified=True,
                )
            if activate and not applicant.is_activated:
                activate_applicant(applicant, DEMO_PASSWORD)
            if activate:
                self.stdout.write(f"  log in:   URN {applicant.urn}  password {DEMO_PASSWORD}  ({email})")
            else:
                self.stdout.write(f"  activate: email {email}  URN {applicant.urn}")
