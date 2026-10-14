"""
Registration for bidding and offline verification.

    Applicant              - one per user who clicked "Register for bidding":
                             personal details, encrypted Aadhaar/PAN, URN, status.
    QuarterApplication     - one row per quarter the applicant selected, with that
                             quarter's EMD and the offline EMD receipt check.
    DocumentChecklistItem  - the list of documents to check (editable in the admin).
    DocumentCheck          - one tick per applicant per checklist item.
    AuditLog               - who did what, and when (verification, activation, reveals).

Bidding eligibility for a quarter = applicant ACTIVE + that quarter's EMD verified
(see Applicant.is_eligible_for).
"""
import secrets

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.utils import timezone

from . import crypto
from .constants import STATE_CHOICES
from .validators import mask_aadhaar, mask_pan

URN_MAX_ATTEMPTS = 10

pin_validator = RegexValidator(r"^[1-9]\d{5}$", "Enter a valid 6-digit PIN code.")
# ASSUMPTION (CLAUDE.md open question 1): URN is a system-generated 7-digit number.
# Stored as text so a leading zero (e.g. "0123456") is never lost.
urn_validator = RegexValidator(r"^\d{7}$", "URN must be exactly 7 digits.")


def generate_urn():
    """Random 7-digit URN, 1000000-9999999 (no leading zero). Not guessable."""
    return str(1_000_000 + secrets.randbelow(9_000_000))


class Applicant(models.Model):
    """
    A user's registration for bidding. Created by the "Register for bidding" form.

    PRIVACY: Aadhaar and PAN are stored only ENCRYPTED (see applications/crypto.py),
    plus a keyed hash for uniqueness and the last 4 characters for masked display.
    Name, phone and email are never shown on public pages or to other bidders.
    """

    class Status(models.TextChoices):
        REGISTERED = "REGISTERED", "Registered"                     # applied; documents not yet seen
        DOCUMENTS_PENDING = "DOCUMENTS_PENDING", "Documents pending"  # verification started
        ACTIVE = "ACTIVE", "Active"                                 # may bid (per verified quarter)
        REJECTED = "REJECTED", "Rejected"
        SUSPENDED = "SUSPENDED", "Suspended"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                related_name="applicant")

    # --- Entered on the "Register for bidding" form ---
    name = models.CharField(max_length=150)
    father_name = models.CharField("father's name", max_length=150)
    # ADDITION to the mentor's field list (needed by the Application Form); to be confirmed.
    address = models.TextField()
    state = models.CharField(max_length=50, choices=STATE_CHOICES)
    pin_code = models.CharField("PIN code", max_length=6, validators=[pin_validator])

    # --- Aadhaar / PAN: never stored in plain text (CR #3 open question 1) ---
    aadhaar_encrypted = models.TextField(editable=False)
    aadhaar_index = models.CharField(max_length=64, unique=True, editable=False,
                                     error_messages={"unique": "This Aadhaar number is already registered."})
    aadhaar_last4 = models.CharField(max_length=4, editable=False)
    pan_encrypted = models.TextField(editable=False)
    pan_index = models.CharField(max_length=64, unique=True, editable=False,
                                 error_messages={"unique": "This PAN is already registered."})
    pan_last4 = models.CharField(max_length=4, editable=False)

    # --- System-generated in save() ---
    application_no = models.CharField("application number", max_length=20, unique=True,
                                      null=True, editable=False)
    application_date = models.DateField(default=timezone.localdate)
    urn = models.CharField("URN", max_length=7, unique=True, blank=True, validators=[urn_validator],
                           help_text="Leave blank to generate automatically.")
    urn_date = models.DateField("URN date", default=timezone.localdate)
    documents_emailed_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="When the Application Form and Intimation Slip were emailed.")

    # --- Verification status (changed only through applications/services.py) ---
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REGISTERED,
                              db_index=True)
    status_reason = models.TextField(blank=True, help_text="Reason for a rejection or suspension.")
    status_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    status_changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                          null=True, blank=True, editable=False, related_name="+")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("verify_applicant", "Can verify documents and EMD, and activate applicants"),
            ("reveal_identity_numbers", "Can reveal full Aadhaar / PAN (every reveal is audited)"),
        ]

    # ---------- lookups ----------

    @classmethod
    def for_user(cls, user):
        """The applicant behind a login, or None. The ONE place this lookup is written."""
        if user is None or not user.is_authenticated:
            return None
        return cls.objects.filter(user=user).first()

    # ---------- personal data helpers ----------

    @property
    def email(self):
        return self.user.email

    @property
    def phone(self):
        return self.user.phone

    def set_aadhaar(self, number):
        """`number` must already be normalised and validated (see validators.py)."""
        self.aadhaar_encrypted = crypto.encrypt(number)
        self.aadhaar_index = crypto.blind_index("aadhaar", number)
        self.aadhaar_last4 = number[-4:]

    def set_pan(self, number):
        self.pan_encrypted = crypto.encrypt(number)
        self.pan_index = crypto.blind_index("pan", number)
        self.pan_last4 = number[-4:]

    @property
    def masked_aadhaar(self):
        return mask_aadhaar(self.aadhaar_last4)

    @property
    def masked_pan(self):
        return mask_pan(self.pan_last4)

    def decrypt_identity_numbers(self):
        """
        Full Aadhaar and PAN. Call ONLY from services.reveal_identity_numbers(),
        which checks permission and writes the audit log.
        """
        return crypto.decrypt(self.aadhaar_encrypted), crypto.decrypt(self.pan_encrypted)

    # ---------- eligibility ----------

    def is_eligible_for(self, quarter):
        """Bidding right for ONE quarter: ACTIVE and that quarter's EMD verified."""
        return (self.status == self.Status.ACTIVE
                and self.quarter_applications.filter(quarter=quarter, emd_verified=True).exists())

    def eligible_quarter_ids(self):
        if self.status != self.Status.ACTIVE:
            return set()
        return set(self.quarter_applications.filter(emd_verified=True).values_list("quarter_id", flat=True))

    # ---------- saving ----------

    def save(self, *args, **kwargs):
        # One transaction: no other connection ever sees a row without an application number.
        with transaction.atomic():
            if self.urn:
                super().save(*args, **kwargs)
            else:
                self._insert_with_new_urn(*args, **kwargs)
            if not self.application_no:
                self.application_no = f"QA{self.application_date:%Y}{self.pk:06d}"
                super().save(update_fields=["application_no"])

    def _insert_with_new_urn(self, *args, **kwargs):
        """Try random URNs until one is free (the unique constraint is the referee)."""
        for _ in range(URN_MAX_ATTEMPTS):
            self.urn = generate_urn()
            try:
                with transaction.atomic():  # savepoint: undo only this attempt
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                if not Applicant.objects.filter(urn=self.urn).exists():
                    self.urn = ""
                    raise  # failed for another reason (e.g. duplicate Aadhaar)
        self.urn = ""
        raise IntegrityError(f"Could not find a free URN after {URN_MAX_ATTEMPTS} attempts.")

    def __str__(self):
        # Application number only: never print personal data in logs or dropdowns.
        return self.application_no or "(new applicant)"


class QuarterApplication(models.Model):
    """
    One quarter selected by one applicant, and the offline check of the EMD
    paid for it. Paying the EMD for quarter A gives no right to bid on quarter B.
    """

    applicant = models.ForeignKey(Applicant, on_delete=models.PROTECT, related_name="quarter_applications")
    quarter = models.ForeignKey("auctions.Quarter", on_delete=models.PROTECT, related_name="applications")
    # Copied from the quarter when applying, so a later change to the quarter's EMD
    # can't change what this applicant was asked to pay (audit).
    emd_amount = models.DecimalField("EMD amount (Rs.)", max_digits=12, decimal_places=2)
    applied_at = models.DateTimeField(default=timezone.now)
    slip_emailed_at = models.DateTimeField(null=True, blank=True, editable=False)

    # --- Offline EMD receipt check (Verification Officer) ---
    emd_receipt_no = models.CharField("receipt / reference no.", max_length=50, blank=True)
    emd_amount_paid = models.DecimalField("amount paid (Rs.)", max_digits=12, decimal_places=2,
                                          null=True, blank=True)
    emd_payment_date = models.DateField("payment date", null=True, blank=True)
    emd_verified = models.BooleanField("EMD verified", default=False)
    emd_verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                        null=True, blank=True, editable=False, related_name="+")
    emd_verified_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["applicant", "quarter__quarter_no"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "quarter"], name="one_application_per_quarter"),
            models.CheckConstraint(condition=Q(emd_amount__gt=0), name="application_emd_positive"),
            # A verified EMD always has a receipt, a date, an officer, and covers the EMD.
            # ASSUMPTION: paying MORE than the EMD is accepted; less is not.
            models.CheckConstraint(
                condition=Q(emd_verified=False) | (
                    ~Q(emd_receipt_no="") & Q(emd_payment_date__isnull=False)
                    & Q(emd_amount_paid__gte=F("emd_amount")) & Q(emd_verified_by__isnull=False)),
                name="verified_emd_is_complete",
                violation_error_message="A verified EMD needs a receipt number, payment date and "
                                        "an amount at least equal to the EMD."),
        ]
        indexes = [models.Index(fields=["quarter", "emd_verified"], name="application_quarter_emd_idx")]

    @property
    def amount_matches(self):
        """None = nothing entered yet; True / False = does the paid amount cover the EMD?"""
        if self.emd_amount_paid is None:
            return None
        return self.emd_amount_paid >= self.emd_amount

    def __str__(self):
        quarter_no = self.quarter.quarter_no if self.quarter_id else "?"
        return f"{self.applicant} - {quarter_no}"


class DocumentChecklistItem(models.Model):
    """
    One document the applicant must show in person. The list is a PLACEHOLDER
    (CR #3 open question 8): add, rename or deactivate items in the admin.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    required = models.BooleanField(default=True, help_text="Activation is blocked until ticked.")
    is_active = models.BooleanField(default=True, help_text="Untick to stop using this item.")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class DocumentCheck(models.Model):
    """One applicant's tick against one checklist item, with who ticked it and when."""

    applicant = models.ForeignKey(Applicant, on_delete=models.PROTECT, related_name="document_checks")
    item = models.ForeignKey(DocumentChecklistItem, on_delete=models.PROTECT, related_name="checks")
    checked = models.BooleanField(default=False)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   null=True, blank=True, related_name="+")
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["item__order", "item__name"]
        constraints = [models.UniqueConstraint(fields=["applicant", "item"], name="one_check_per_item")]

    def __str__(self):
        return f"{self.applicant} - {self.item}: {'yes' if self.checked else 'no'}"


class AuditLog(models.Model):
    """
    Append-only record of important actions. Never edited or deleted.
    PRIVACY: never write a full Aadhaar or PAN into `details`.
    """

    class Action(models.TextChoices):
        APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED", "Application submitted"
        QUARTERS_ADDED = "QUARTERS_ADDED", "Quarters added to application"
        DOCUMENTS_EMAILED = "DOCUMENTS_EMAILED", "Documents emailed"
        DOCUMENT_CHECKED = "DOCUMENT_CHECKED", "Document ticked"
        DOCUMENT_UNCHECKED = "DOCUMENT_UNCHECKED", "Document unticked"
        EMD_VERIFIED = "EMD_VERIFIED", "EMD verified"
        EMD_UNVERIFIED = "EMD_UNVERIFIED", "EMD un-verified"
        STATUS_CHANGED = "STATUS_CHANGED", "Status changed"
        IDENTITY_REVEALED = "IDENTITY_REVEALED", "Aadhaar / PAN revealed"

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                              related_name="+", help_text="Empty = done by the system.")
    action = models.CharField(max_length=30, choices=Action.choices)
    applicant = models.ForeignKey(Applicant, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="audit_entries")
    summary = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d %b %Y %H:%M} {self.get_action_display()}"
