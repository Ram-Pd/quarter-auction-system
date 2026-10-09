import re

from django import forms

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
