import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User

from . import ratelimit
from .models import Applicant


class RegistrationForm(forms.ModelForm):
    # Wider than the DB columns so "+91 98765 43210" / "827 001" reach the clean_*
    # methods; the model's 10-digit / 6-digit validators run afterwards.
    mobile = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "placeholder": "10-digit mobile"}),
    )
    pin_code = forms.CharField(label="PIN code", max_length=10,
                               widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    declaration = forms.BooleanField(
        required=True,
        label="I declare that the information given above is true and correct.",
        error_messages={"required": "You must accept the declaration to register."},
    )

    class Meta:
        model = Applicant
        fields = ["name", "father_name", "mobile", "email", "address", "state", "pin_code"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}
        error_messages = {
            # Shown instead of Django's default "Applicant with this Email already exists."
            "email": {"unique": "This email address is already registered. If you have lost "
                                "your documents, please contact the auction office."},
        }

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_father_name(self):
        return " ".join(self.cleaned_data["father_name"].split())

    def clean_mobile(self):
        # Accept "+91 98765-43210", "098765 43210", etc. -> "9876543210"
        digits = re.sub(r"[\s\-()]", "", self.cleaned_data["mobile"])
        if digits.startswith("+91"):
            digits = digits[3:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        return digits

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean_pin_code(self):
        return self.cleaned_data["pin_code"].replace(" ", "")


class ActivationForm(forms.Form):
    """
    Email + URN (both needed: the URN arrives only by email) + new password.
    On success `self.applicant` holds the matching applicant.
    """

    email = forms.EmailField()
    urn = forms.CharField(label="URN", max_length=7, min_length=7,
                          widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
                          help_text="The 7-digit number on your Intimation Slip.")
    password1 = forms.CharField(label="New password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirm password", strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.applicant = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip().lower()
        urn = (cleaned.get("urn") or "").strip()
        if not email or not urn:
            return cleaned  # field errors already shown

        keys = ratelimit.attempt_keys("activate", self.request, email)
        if ratelimit.is_blocked(keys):
            raise forms.ValidationError(ratelimit.blocked_message(), code="rate_limited")

        applicant = Applicant.objects.filter(email=email, urn=urn).first()
        if applicant is None:
            ratelimit.record_failure(keys)
            # Same message whichever one is wrong: don't help a guesser.
            raise forms.ValidationError("The email address and URN do not match our records.")
        ratelimit.reset_identifier(keys)

        # Email + URN are correct, so it is safe to say exactly what is wrong.
        if applicant.is_activated:
            raise forms.ValidationError("This account is already activated. Please log in, "
                                        "or use 'Forgot password' if you need a new password.")
        if not applicant.is_verified:
            raise forms.ValidationError("Your EMD payment has not been verified yet. Please try "
                                        "again after the auction office confirms your payment.")

        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    # Checked against a not-yet-saved user so "too similar to
                    # username/email" rules work.
                    password_validation.validate_password(
                        password1, User(username=applicant.urn, email=applicant.email))
                except forms.ValidationError as error:
                    self.add_error("password1", error)

        self.applicant = applicant
        return cleaned


class UrnLoginForm(AuthenticationForm):
    """Django's login form, with the username labelled "URN" and rate limiting."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "URN"
        self.fields["username"].widget.attrs.update({"inputmode": "numeric", "autofocus": True})
        self.error_messages["invalid_login"] = "Incorrect URN or password."

    def clean(self):
        username = self.cleaned_data.get("username") or ""
        keys = ratelimit.attempt_keys("login", self.request, username)
        if ratelimit.is_blocked(keys):
            raise forms.ValidationError(ratelimit.blocked_message(), code="rate_limited")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            ratelimit.record_failure(keys)
            raise
        ratelimit.reset_identifier(keys)
        return cleaned
