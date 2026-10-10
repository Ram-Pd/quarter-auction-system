"""
Emails sent to applicants. The wording is in
accounts/templates/accounts/emails/registration_subject.txt and registration_body.txt.
"""
from django.utils import timezone

from config.mail import build_email

from .pdfs import application_form_pdf, intimation_slip_pdf


def send_registration_documents(applicant):
    """
    Email the Application Form and Intimation Slip to the applicant.
    Raises on failure (e.g. SMTP down); callers decide how to report it.
    """
    message = build_email("accounts/emails/registration", {"applicant": applicant}, to=[applicant.email])
    message.attach(f"Application_Form_{applicant.application_no}.pdf",
                   application_form_pdf(applicant), "application/pdf")
    message.attach(f"Intimation_Slip_{applicant.application_no}.pdf",
                   intimation_slip_pdf(applicant), "application/pdf")
    message.send()

    applicant.documents_emailed_at = timezone.now()
    applicant.save(update_fields=["documents_emailed_at"])
