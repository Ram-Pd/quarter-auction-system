"""
Emails sent to applicants after "Register for bidding". The wording is in
applications/templates/applications/emails/ (documents_*.txt, supplementary_*.txt).

Called through transaction.on_commit() in applications/services.py, i.e. only
after the application is safely saved, and exactly once per submission. A
mail failure never loses the application: it is logged, and an officer can
resend from the admin ("Resend documents").

PRIVACY: Aadhaar and PAN never appear in an email body. The attached PDFs
show them masked.
"""
import logging

from django.utils import timezone

from config.mail import build_email

from .models import Applicant, AuditLog, QuarterApplication
from .pdfs import application_form_pdf, intimation_slip_pdf

logger = logging.getLogger(__name__)


def _applications(applicant, ids=None):
    qs = applicant.quarter_applications.select_related("quarter").order_by("quarter__quarter_no")
    return list(qs.filter(pk__in=ids) if ids is not None else qs)


def send_application_documents(applicant):
    """Email the Application Form and Intimation Slip (all selected quarters). Raises on failure."""
    from .services import audit

    applications = _applications(applicant)
    message = build_email("applications/emails/documents",
                          {"applicant": applicant, "applications": applications,
                           "total_emd": sum(a.emd_amount for a in applications)},
                          to=[applicant.email])
    message.attach(f"Application_Form_{applicant.application_no}.pdf",
                   application_form_pdf(applicant, applications), "application/pdf")
    message.attach(f"Intimation_Slip_{applicant.application_no}.pdf",
                   intimation_slip_pdf(applicant, applications), "application/pdf")
    message.send()

    now = timezone.now()
    applicant.documents_emailed_at = now
    applicant.save(update_fields=["documents_emailed_at"])
    QuarterApplication.objects.filter(pk__in=[a.pk for a in applications]).update(slip_emailed_at=now)
    audit(None, AuditLog.Action.DOCUMENTS_EMAILED, "Application Form and Intimation Slip emailed",
          applicant=applicant)


def send_supplementary_slip(applicant, application_ids):
    """Email an Intimation Slip for quarters ADDED later (only those). Raises on failure."""
    from .services import audit

    applications = _applications(applicant, application_ids)
    message = build_email("applications/emails/supplementary",
                          {"applicant": applicant, "applications": applications,
                           "total_emd": sum(a.emd_amount for a in applications)},
                          to=[applicant.email])
    message.attach(f"Intimation_Slip_{applicant.application_no}_supplementary.pdf",
                   intimation_slip_pdf(applicant, applications, supplementary=True), "application/pdf")
    message.send()

    QuarterApplication.objects.filter(pk__in=application_ids).update(slip_emailed_at=timezone.now())
    audit(None, AuditLog.Action.DOCUMENTS_EMAILED, f"Supplementary slip emailed ({len(applications)} quarter(s))",
          applicant=applicant)


def send_application_documents_safely(applicant_id):
    applicant = Applicant.objects.select_related("user").get(pk=applicant_id)
    try:
        send_application_documents(applicant)
    except Exception:
        logger.exception("Documents email failed for %s", applicant.application_no)


def send_supplementary_slip_safely(applicant_id, application_ids):
    applicant = Applicant.objects.select_related("user").get(pk=applicant_id)
    try:
        send_supplementary_slip(applicant, application_ids)
    except Exception:
        logger.exception("Supplementary slip email failed for %s", applicant.application_no)
