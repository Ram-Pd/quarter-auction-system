"""
Sign-up in three steps, kept in the session between pages:

    1. /signup/           name, phone, email          -> code emailed
    2. /signup/verify/    the 6-digit code             -> email proven
    3. /signup/password/  choose a password            -> account created, logged in

Nothing is written to the User table until step 3, so abandoned sign-ups
leave no half-made accounts behind.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import otp
from .forms import ChoosePasswordForm, OtpForm, SignupForm
from .models import User

logger = logging.getLogger(__name__)

SESSION_KEY = "signup"  # {"full_name", "phone", "email", "verified_at"}


def _pending(request):
    return request.session.get(SESSION_KEY)


def _verified_recently(pending):
    verified_at = parse_datetime(pending.get("verified_at") or "")
    window = timedelta(minutes=settings.SIGNUP_VERIFIED_WINDOW_MINUTES)
    return verified_at is not None and timezone.now() - verified_at < window


def signup(request):
    if request.user.is_authenticated:
        return redirect("auctions:listing")
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                otp.send_signup_otp(data["email"], request)
            except otp.OtpError as error:
                form.add_error(None, error.message)
            except Exception:
                logger.exception("Could not send the sign-up code")
                form.add_error(None, "We could not send the code email. Please try again later.")
            else:
                request.session[SESSION_KEY] = {**data, "verified_at": None}
                return redirect("accounts:signup_verify")
    else:
        form = SignupForm(initial=_pending(request))
    return render(request, "accounts/signup.html", {"form": form})


def signup_verify(request):
    pending = _pending(request)
    if not pending:
        return redirect("accounts:signup")
    if request.method == "POST":
        form = OtpForm(request.POST)
        if form.is_valid():
            try:
                otp.verify_signup_otp(pending["email"], form.cleaned_data["code"])
            except otp.OtpError as error:
                form.add_error("code", error.message)
            else:
                pending["verified_at"] = timezone.now().isoformat()
                request.session[SESSION_KEY] = pending
                return redirect("accounts:signup_password")
    else:
        form = OtpForm()
    return render(request, "accounts/signup_verify.html", {
        "form": form, "email": pending["email"], "minutes": settings.OTP_VALID_MINUTES,
        "resend_wait": otp.seconds_until_resend(pending["email"]),
    })


@require_POST
def signup_resend(request):
    pending = _pending(request)
    if not pending:
        return redirect("accounts:signup")
    try:
        otp.send_signup_otp(pending["email"], request)
    except otp.OtpError as error:
        messages.error(request, error.message)
    except Exception:
        logger.exception("Could not re-send the sign-up code")
        messages.error(request, "We could not send the code email. Please try again later.")
    else:
        messages.success(request, f"A new code has been sent to {pending['email']}.")
    return redirect("accounts:signup_verify")


@sensitive_post_parameters("password1", "password2")
def signup_password(request):
    pending = _pending(request)
    if not pending:
        return redirect("accounts:signup")
    if not _verified_recently(pending):
        messages.error(request, "Please confirm your email address first.")
        return redirect("accounts:signup_verify")

    if request.method == "POST":
        form = ChoosePasswordForm(request.POST, email=pending["email"], full_name=pending["full_name"])
        if form.is_valid():
            try:
                user = User.objects.create_user(
                    email=pending["email"], password=form.cleaned_data["password1"],
                    full_name=pending["full_name"], phone=pending["phone"],
                    email_verified_at=parse_datetime(pending["verified_at"]))
            except IntegrityError:  # someone signed up with this email a moment ago
                del request.session[SESSION_KEY]
                messages.error(request, "An account with this email already exists. Please log in.")
                return redirect("accounts:login")
            del request.session[SESSION_KEY]
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Welcome! Your account has been created.")
            return redirect("auctions:listing")
    else:
        form = ChoosePasswordForm(email=pending["email"], full_name=pending["full_name"])
    return render(request, "accounts/signup_password.html", {"form": form, "email": pending["email"]})
