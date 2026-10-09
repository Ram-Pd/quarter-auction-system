import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .constants import STATE_CHOICES

URN_MAX_ATTEMPTS = 10


def generate_urn():
    """Random 7-digit URN, 1000000-9999999 (no leading zero). Not guessable."""
    return str(1_000_000 + secrets.randbelow(9_000_000))


mobile_validator = RegexValidator(r"^[6-9]\d{9}$", "Enter a valid 10-digit Indian mobile number.")
pin_validator = RegexValidator(r"^[1-9]\d{5}$", "Enter a valid 6-digit PIN code.")
# ASSUMPTION (open question 1): URN is a system-generated 7-digit number.
# Stored as text so a leading zero (e.g. "0123456") is never lost.
urn_validator = RegexValidator(r"^\d{7}$", "URN must be exactly 7 digits.")


class Applicant(models.Model):
    """
    A person who registers for quarter auctions.

    The Django User (login account) is created only at activation, with
    username = URN, so the password lives only in the User table.
    """

    # --- Details entered at registration ---
    name = models.CharField(max_length=150)
    father_name = models.CharField("father's name", max_length=150)
    mobile = models.CharField(max_length=10, validators=[mobile_validator])
    # ASSUMPTION: one applicant record per email address.
    email = models.EmailField(unique=True)
    address = models.TextField()
    state = models.CharField(max_length=50, choices=STATE_CHOICES)
    pin_code = models.CharField("PIN code", max_length=6, validators=[pin_validator])

    # --- System-generated in save() ---
    # Built from the row id after insert, e.g. "QA2026000001". NULL only for the
    # instant between the insert and the update inside save()'s transaction.
    application_no = models.CharField(
        "application number", max_length=20, unique=True, null=True, editable=False
    )
    application_date = models.DateField(default=timezone.localdate)
    # Leave blank to auto-generate. Editable so SAIL-supplied URNs could be entered.
    urn = models.CharField(
        "URN", max_length=7, unique=True, blank=True, validators=[urn_validator],
        help_text="Leave blank to generate automatically.",
    )
    urn_date = models.DateField("URN date", default=timezone.localdate)
    documents_emailed_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="When the Application Form and Intimation Slip were last emailed.",
    )

    # --- Status flags ---
    # ASSUMPTION (open question 3): an admin ticks this after checking EMD offline.
    is_verified = models.BooleanField(
        "verified", default=False, help_text="Ticked by admin after offline EMD verification."
    )
    is_activated = models.BooleanField(
        "activated", default=False, help_text="Set automatically when the applicant activates."
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # never silently lose an applicant's audit trail
        null=True,
        blank=True,
        related_name="applicant",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # An activated applicant must have a login account.
            models.CheckConstraint(
                condition=Q(is_activated=False) | Q(user__isnull=False),
                name="applicant_activated_has_user",
            ),
            # "A@x.com" and "a@x.com" are the same mailbox.
            models.UniqueConstraint(
                Lower("email"),
                name="applicant_email_unique_ci",
                violation_error_message="An applicant with this email already exists.",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        # One transaction: no other connection ever sees a row without an
        # application number.
        with transaction.atomic():
            if self.urn:
                super().save(*args, **kwargs)
            else:
                self._insert_with_new_urn(*args, **kwargs)
            if not self.application_no:
                self.application_no = f"QA{self.application_date:%Y}{self.pk:06d}"
                super().save(update_fields=["application_no"])
            # Password reset emails go to User.email, so keep it equal to ours.
            if self.user_id:
                User = get_user_model()
                User.objects.filter(pk=self.user_id).exclude(email=self.email).update(email=self.email)

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
                    raise  # failed for another reason (e.g. duplicate email)
        self.urn = ""
        raise IntegrityError(f"Could not find a free URN after {URN_MAX_ATTEMPTS} attempts.")

    def __str__(self):
        # Application number only; avoids printing personal data in logs or dropdowns.
        return self.application_no or "(new applicant)"
