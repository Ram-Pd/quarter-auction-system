import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from . import ratelimit
from .models import User, normalise_email, phone_validator


def clean_indian_mobile(value):
    """Accept "+91 98765-43210", "098765 43210", etc. -> "9876543210"."""
    digits = re.sub(r"[\s\-()]", "", value or "")
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    phone_validator(digits)
    return digits


class SignupForm(forms.Form):
    """Step 1 of sign-up: name, phone, email. The phone is collected, not verified."""

    full_name = forms.CharField(label="Name", max_length=150)
    # Wider than 10 so "+91 98765 43210" reaches clean_phone().
    phone = forms.CharField(label="Phone number", max_length=20,
                            widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "10-digit mobile"}),
                            help_text="Collected for contact only. It is not verified.")
    email = forms.EmailField(help_text="We will email a 6-digit code to confirm this address.")

    def clean_full_name(self):
        return " ".join(self.cleaned_data["full_name"].split())

    def clean_phone(self):
        return clean_indian_mobile(self.cleaned_data["phone"])

    def clean_email(self):
        email = normalise_email(self.cleaned_data["email"])
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("An account with this email already exists. Please log in, "
                                        "or use 'Forgot password'.")
        return email


class OtpForm(forms.Form):
    """Step 2 of sign-up: the code from the email."""

    code = forms.CharField(label="6-digit code", min_length=6, max_length=6,
                           widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code",
                                                         "autofocus": True}))

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("The code has digits only.")
        return code


class ChoosePasswordForm(forms.Form):
    """Step 3 of sign-up: choose a password (Django's password rules apply)."""

    password1 = forms.CharField(label="Password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirm password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, email="", full_name="", **kwargs):
        self.email = email
        self.full_name = full_name
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    # Checked against a not-yet-saved user so "too similar to your email/name" works.
                    password_validation.validate_password(password1, User(email=self.email,
                                                                          full_name=self.full_name))
                except forms.ValidationError as error:
                    self.add_error("password1", error)
        return cleaned


class EmailLoginForm(AuthenticationForm):
    """Django's login form (field "username" is the email here), with rate limiting."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].widget.attrs.update({"autofocus": True, "autocomplete": "email"})
        self.error_messages["invalid_login"] = "Incorrect email or password."

    def clean_username(self):
        return normalise_email(self.cleaned_data["username"])

    def clean(self):
        email = self.cleaned_data.get("username") or ""
        keys = ratelimit.attempt_keys("login", self.request, email)
        if ratelimit.is_blocked(keys):
            raise forms.ValidationError(ratelimit.blocked_message(), code="rate_limited")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            ratelimit.record_failure(keys)
            raise
        ratelimit.reset_identifier(keys)
        return cleaned
