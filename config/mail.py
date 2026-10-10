"""
One helper for every email the project sends.

The WORDING of each email lives in two template files, never in Python:
    <name>_subject.txt   one line
    <name>_body.txt      the plain-text body

    accounts/templates/accounts/emails/   registration email, password reset
    auctions/templates/auctions/emails/   winner and loser emails
    templates/emails/                     pieces shared by all emails (footer)

So to change what an email says, edit the .txt file; no Python change needed.
"""
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


def build_email(template, context, to):
    """
    Build (but do not send) an EmailMessage from "<template>_subject.txt" and
    "<template>_body.txt". AUCTION_TITLE is always available to the templates.
    Call .attach(...) for attachments, then .send().
    """
    context = {"AUCTION_TITLE": settings.AUCTION_TITLE, **context}
    # Subjects must be one line: an email header can't contain line breaks.
    subject = " ".join(render_to_string(f"{template}_subject.txt", context).split())
    body = render_to_string(f"{template}_body.txt", context)
    return EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=to)
