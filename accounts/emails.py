from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from .pdfs import application_form_pdf, intimation_slip_pdf


def send_registration_documents(applicant):
    """
    Email the Application Form and Intimation Slip to the applicant.
    Raises on failure (e.g. SMTP down); callers decide how to report it.
    """
    body = (
        f"Dear {applicant.name},\n\n"
        f"Thank you for registering for the {settings.AUCTION_TITLE}.\n\n"
        f"Application number: {applicant.application_no}\n\n"
        "Two documents are attached:\n"
        "  1. Auction Application Form\n"
        "  2. Auction Intimation Slip - contains your URN and the EMD payment instructions\n\n"
        "Next steps:\n"
        "  - Pay the EMD through SBI Collect using the URN on the Intimation Slip.\n"
        "  - After the auction office verifies your payment, activate your account on the\n"
        "    auction website with your email address and URN.\n"
        "  - Log in and choose the quarter(s) you want to bid on.\n\n"
        "Keep your URN confidential.\n\n"
        "This is an automated message from a TRAINING PROJECT, not an official SAIL communication.\n"
    )
    message = EmailMessage(
        subject=f"Auction registration {applicant.application_no}",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[applicant.email],
    )
    message.attach(f"Application_Form_{applicant.application_no}.pdf",
                   application_form_pdf(applicant), "application/pdf")
    message.attach(f"Intimation_Slip_{applicant.application_no}.pdf",
                   intimation_slip_pdf(applicant), "application/pdf")
    message.send()

    applicant.documents_emailed_at = timezone.now()
    applicant.save(update_fields=["documents_emailed_at"])
