"""
Email one-time codes (OTP) for sign-up.

    send_signup_otp(email, request)   -> emails a new 6-digit code
    verify_signup_otp(email, code)    -> checks it (raises OtpError if wrong)

Security rules (numbers in settings.py, "Sign-up email OTP"):
  - The code is random (secrets module) and stored only as a KEYED hash
    (HMAC with SECRET_KEY), so a database leak alone does not reveal codes.
  - It expires after OTP_VALID_MINUTES and works once (used_at).
  - After OTP_MAX_ATTEMPTS wrong guesses it stops working.
  - Asking for a new code: OTP_RESEND_COOLDOWN_SECONDS between codes, and at
    most OTP_SENDS_PER_EMAIL_PER_HOUR / OTP_SENDS_PER_IP_PER_HOUR codes.
  - A new code replaces the previous one (only the newest code works).
"""
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from config.mail import build_email

from . import ratelimit
from .models import EmailOTP, normalise_email


class OtpError(Exception):
    """A problem the user should see, e.g. "Incorrect code. 3 attempts left." """

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _hash(email, code):
    return salted_hmac("accounts.otp", f"{email}:{code}", algorithm="sha256").hexdigest()


def _new_code():
    return f"{secrets.randbelow(10 ** settings.OTP_LENGTH):0{settings.OTP_LENGTH}d}"


def seconds_until_resend(email, purpose=EmailOTP.Purpose.SIGNUP):
    """0 if a new code may be sent now, otherwise how many seconds to wait."""
    last = EmailOTP.objects.filter(email=normalise_email(email), purpose=purpose).first()
    if last is None:
        return 0
    ready_at = last.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    remaining = (ready_at - timezone.now()).total_seconds()
    return math.ceil(remaining) if remaining > 0 else 0


def send_signup_otp(email, request):
    """Create and email a new code. Raises OtpError if the user must wait."""
    email = normalise_email(email)
    wait = seconds_until_resend(email)
    if wait:
        raise OtpError(f"Please wait {wait} seconds before asking for a new code.")
    if not ratelimit.allow("otp_send", request, email, per_id=settings.OTP_SENDS_PER_EMAIL_PER_HOUR,
                           per_ip=settings.OTP_SENDS_PER_IP_PER_HOUR, window=60 * 60):
        raise OtpError("Too many codes have been requested. Please try again in an hour.")

    code = _new_code()
    now = timezone.now()
    with transaction.atomic():
        # Older codes stop working: only the newest one counts.
        EmailOTP.objects.filter(email=email, purpose=EmailOTP.Purpose.SIGNUP, used_at__isnull=True,
                                expires_at__gt=now).update(expires_at=now)
        EmailOTP.objects.create(email=email, purpose=EmailOTP.Purpose.SIGNUP, code_hash=_hash(email, code),
                                created_at=now,
                                expires_at=now + timedelta(minutes=settings.OTP_VALID_MINUTES))
    # The code itself exists only in this email (and this function's memory).
    build_email("accounts/emails/otp", {"code": code, "minutes": settings.OTP_VALID_MINUTES},
                to=[email]).send()


def verify_signup_otp(email, code):
    """Accept the newest unused code for this email, or raise OtpError."""
    email = normalise_email(email)
    code = (code or "").strip()
    now = timezone.now()
    error = None
    with transaction.atomic():
        # Locked so two guesses sent at the same moment are counted one after the other.
        otp = (EmailOTP.objects.select_for_update()
               .filter(email=email, purpose=EmailOTP.Purpose.SIGNUP).first())
        if otp is None or otp.used_at or otp.expires_at <= now:
            error = "This code has expired or was replaced. Ask for a new code."
        elif otp.failed_attempts >= settings.OTP_MAX_ATTEMPTS:
            error = "Too many wrong attempts. Ask for a new code."
        elif not constant_time_compare(otp.code_hash, _hash(email, code)):
            otp.failed_attempts += 1
            otp.save(update_fields=["failed_attempts"])
            left = settings.OTP_MAX_ATTEMPTS - otp.failed_attempts
            error = (f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left." if left
                     else "Too many wrong attempts. Ask for a new code.")
        else:
            otp.used_at = now
            otp.save(update_fields=["used_at"])
    # Raised AFTER the transaction, so the failed-attempt count is saved, not rolled back.
    if error:
        raise OtpError(error)
