"""
Business actions on applications. Views and the admin stay thin and call
these functions, so the same rules (and the same audit log entries) apply
wherever an action is triggered from.

    Applying          submit_application(), add_quarters()
    Verification      set_document_check(), record_emd(), verify_emd(), unverify_emd()
    Status            activate(), reject(), suspend()
    Sensitive data    reveal_identity_numbers()   (permission-checked, audited)

Status flow:   REGISTERED -> DOCUMENTS_PENDING -> ACTIVE
                    (any, except REJECTED) -> REJECTED      (reason required)
                    ACTIVE -> SUSPENDED -> ACTIVE again      (reason required to suspend)
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .models import Applicant, AuditLog, DocumentCheck, DocumentChecklistItem, QuarterApplication

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """A rule that blocks an officer's action. `message` is shown on the screen."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def audit(actor, action, summary, applicant=None, **details):
    """Write one audit log entry. NEVER pass a full Aadhaar or PAN in `details`."""
    return AuditLog.objects.create(actor=actor, action=action, summary=summary[:255],
                                   applicant=applicant, details=details)


# ---------------------------------------------------------------- applying

def application_window_open(auction, now=None):
    """Can this auction's quarter still be selected? (until N hours before it starts)"""
    from auctions.models import Auction
    now = now or timezone.now()
    cutoff = timedelta(hours=settings.APPLICATION_CLOSES_HOURS_BEFORE_AUCTION)
    return auction.status == Auction.Status.SCHEDULED and auction.start_time - now > cutoff


def auctions_open_for_application(now=None):
    """Scheduled auctions whose quarter can still be selected, earliest first."""
    from auctions.models import Auction
    now = now or timezone.now()
    cutoff = now + timedelta(hours=settings.APPLICATION_CLOSES_HOURS_BEFORE_AUCTION)
    return (Auction.objects.filter(status=Auction.Status.SCHEDULED, start_time__gt=cutoff)
            .select_related("quarter").order_by("start_time", "quarter__quarter_no"))


def submit_application(user, details, aadhaar, pan, quarters):
    """
    Create the Applicant (URN and application number are generated on save) and
    one QuarterApplication per selected quarter. The two PDFs are emailed AFTER
    the database commit, exactly once (transaction.on_commit).

    `details`: name, father_name, address, state, pin_code (already cleaned).
    `aadhaar`, `pan`: already normalised and validated. Raises IntegrityError if
    the user already applied or the Aadhaar/PAN is already registered.
    """
    from . import emails

    with transaction.atomic():
        applicant = Applicant(user=user, **details)
        applicant.set_aadhaar(aadhaar)
        applicant.set_pan(pan)
        applicant.save()
        _create_quarter_applications(applicant, quarters)
        audit(user, AuditLog.Action.APPLICATION_SUBMITTED,
              f"Application {applicant.application_no} submitted for {len(quarters)} quarter(s)",
              applicant=applicant, quarters=[q.quarter_no for q in quarters])
        transaction.on_commit(lambda: emails.send_application_documents_safely(applicant.pk))
    return applicant


def add_quarters(applicant, quarters, actor):
    """
    ASSUMPTION (CR #3 open question 4): more quarters may be added while their
    application window is open. Emails a supplementary Intimation Slip for the
    ADDED quarters only.
    """
    from . import emails

    with transaction.atomic():
        Applicant.objects.select_for_update().get(pk=applicant.pk)  # one addition at a time
        already = set(applicant.quarter_applications.values_list("quarter_id", flat=True))
        new = [q for q in quarters if q.pk not in already]
        if not new:
            return []
        created = _create_quarter_applications(applicant, new)
        audit(actor, AuditLog.Action.QUARTERS_ADDED, f"{len(new)} quarter(s) added", applicant=applicant,
              quarters=[q.quarter_no for q in new])
        ids = [a.pk for a in created]
        transaction.on_commit(lambda: emails.send_supplementary_slip_safely(applicant.pk, ids))
    return created


def _create_quarter_applications(applicant, quarters):
    # The EMD is copied from the quarter now, so a later change can't alter what was asked.
    return [QuarterApplication.objects.create(applicant=applicant, quarter=q, emd_amount=q.emd_amount)
            for q in quarters]


# ---------------------------------------------------------------- verification

def _lock(applicant):
    return Applicant.objects.select_for_update().get(pk=applicant.pk)


def _start_verification(applicant, actor):
    """The first verification action moves REGISTERED -> DOCUMENTS_PENDING."""
    if applicant.status == Applicant.Status.REGISTERED:
        _change_status(applicant, Applicant.Status.DOCUMENTS_PENDING, actor, "")


def _change_status(applicant, new_status, actor, reason):
    old = applicant.get_status_display()
    applicant.status = new_status
    applicant.status_reason = reason
    applicant.status_changed_at = timezone.now()
    applicant.status_changed_by = actor
    applicant.save(update_fields=["status", "status_reason", "status_changed_at", "status_changed_by",
                                  "updated_at"])
    audit(actor, AuditLog.Action.STATUS_CHANGED, f"Status {old} -> {applicant.get_status_display()}",
          applicant=applicant, reason=reason)


def _require_not_rejected(applicant):
    if applicant.status == Applicant.Status.REJECTED:
        raise VerificationError("This application was rejected. No further changes are possible.")


def set_document_check(applicant, item, checked, actor):
    with transaction.atomic():
        applicant = _lock(applicant)
        _require_not_rejected(applicant)
        check, _ = DocumentCheck.objects.get_or_create(applicant=applicant, item=item)
        if check.checked == checked:
            return check
        check.checked = checked
        check.checked_by = actor
        check.checked_at = timezone.now()
        check.save()
        _start_verification(applicant, actor)
        audit(actor, AuditLog.Action.DOCUMENT_CHECKED if checked else AuditLog.Action.DOCUMENT_UNCHECKED,
              f"{item.name}: {'ticked' if checked else 'unticked'}", applicant=applicant, item=item.name)
    return check


def record_emd(application, receipt_no, amount_paid, payment_date, actor):
    """Save the receipt details the officer typed (not yet "verified")."""
    with transaction.atomic():
        applicant = _lock(application.applicant)
        _require_not_rejected(applicant)
        application = QuarterApplication.objects.select_for_update().get(pk=application.pk)
        if application.emd_verified:
            raise VerificationError("Un-verify this EMD first (with a reason) before changing its receipt.")
        application.emd_receipt_no = receipt_no.strip()
        application.emd_amount_paid = amount_paid
        application.emd_payment_date = payment_date
        application.save(update_fields=["emd_receipt_no", "emd_amount_paid", "emd_payment_date"])
        _start_verification(applicant, actor)
    return application


def verify_emd(application, actor):
    with transaction.atomic():
        applicant = _lock(application.applicant)
        _require_not_rejected(applicant)
        application = QuarterApplication.objects.select_for_update().select_related("quarter").get(
            pk=application.pk)
        if application.emd_verified:
            return application
        missing = [label for label, value in [("receipt / reference no.", application.emd_receipt_no),
                                              ("amount paid", application.emd_amount_paid),
                                              ("payment date", application.emd_payment_date)] if not value]
        if missing:
            raise VerificationError(f"Enter the {', '.join(missing)} before verifying.")
        if application.emd_amount_paid < application.emd_amount:
            raise VerificationError(f"Amount paid (Rs. {application.emd_amount_paid:,.2f}) is less than the "
                                    f"EMD for {application.quarter} (Rs. {application.emd_amount:,.2f}).")
        application.emd_verified = True
        application.emd_verified_by = actor
        application.emd_verified_at = timezone.now()
        application.save(update_fields=["emd_verified", "emd_verified_by", "emd_verified_at"])
        _start_verification(applicant, actor)
        audit(actor, AuditLog.Action.EMD_VERIFIED, f"EMD verified for {application.quarter}", applicant=applicant,
              quarter=str(application.quarter), receipt_no=application.emd_receipt_no,
              amount_paid=str(application.emd_amount_paid))
    return application


def unverify_emd(application, actor, reason):
    reason = (reason or "").strip()
    if not reason:
        raise VerificationError("Give a reason for un-verifying the EMD.")
    with transaction.atomic():
        applicant = _lock(application.applicant)
        application = QuarterApplication.objects.select_for_update().select_related("quarter").get(
            pk=application.pk)
        if not application.emd_verified:
            return application
        application.emd_verified = False
        application.emd_verified_by = None
        application.emd_verified_at = None
        application.save(update_fields=["emd_verified", "emd_verified_by", "emd_verified_at"])
        audit(actor, AuditLog.Action.EMD_UNVERIFIED, f"EMD un-verified for {application.quarter}",
              applicant=applicant, quarter=str(application.quarter), reason=reason)
    return application


def missing_required_documents(applicant):
    """Required, active checklist items not yet ticked for this applicant."""
    ticked = set(applicant.document_checks.filter(checked=True).values_list("item_id", flat=True))
    return [item for item in DocumentChecklistItem.objects.filter(required=True, is_active=True)
            if item.pk not in ticked]


def activate(applicant, actor):
    """Allowed only when every required document is ticked."""
    with transaction.atomic():
        applicant = _lock(applicant)
        _require_not_rejected(applicant)
        if applicant.status == Applicant.Status.ACTIVE:
            return applicant
        missing = missing_required_documents(applicant)
        if missing:
            raise VerificationError("Cannot activate: these required documents are not ticked: "
                                    + ", ".join(item.name for item in missing) + ".")
        _change_status(applicant, Applicant.Status.ACTIVE, actor, "")
    return applicant


def reject(applicant, actor, reason):
    reason = (reason or "").strip()
    if not reason:
        raise VerificationError("Give a reason for rejecting the application.")
    with transaction.atomic():
        applicant = _lock(applicant)
        _require_not_rejected(applicant)
        _change_status(applicant, Applicant.Status.REJECTED, actor, reason)
    return applicant


def suspend(applicant, actor, reason):
    reason = (reason or "").strip()
    if not reason:
        raise VerificationError("Give a reason for suspending the applicant.")
    with transaction.atomic():
        applicant = _lock(applicant)
        if applicant.status != Applicant.Status.ACTIVE:
            raise VerificationError("Only an active applicant can be suspended.")
        _change_status(applicant, Applicant.Status.SUSPENDED, actor, reason)
    return applicant


def reveal_identity_numbers(applicant, actor, reason):
    """
    The single place a full Aadhaar / PAN is decrypted for a person to see.
    Needs the "reveal_identity_numbers" permission and a reason; always audited.
    """
    if not actor.has_perm("applications.reveal_identity_numbers"):
        raise PermissionDenied
    reason = (reason or "").strip()
    if not reason:
        raise VerificationError("Give a reason for revealing the full numbers.")
    audit(actor, AuditLog.Action.IDENTITY_REVEALED, "Full Aadhaar / PAN viewed", applicant=applicant,
          reason=reason)
    return applicant.decrypt_identity_numbers()
