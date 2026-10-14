from django import forms

from auctions.models import Quarter

from . import crypto
from .constants import STATE_CHOICES
from .models import Applicant, pin_validator
from .services import auctions_open_for_application
from .validators import normalise_aadhaar, normalise_pan, validate_aadhaar, validate_pan


class QuarterChoiceMixin:
    """
    The "quarters" field: any number of quarters whose application window is open.
    The template draws it as a searchable list with EMD amounts and a running total
    (applications/templates/applications/includes/quarter_picker.html).
    """

    def setup_quarters(self, exclude_ids=()):
        self.open_auctions = [a for a in auctions_open_for_application() if a.quarter_id not in exclude_ids]
        self.fields["quarters"].queryset = Quarter.objects.filter(pk__in=[a.quarter_id for a in self.open_auctions])

    def selected_ids(self):
        """Quarter ids ticked in the submitted form (to re-tick them after an error)."""
        if not self.is_bound:
            return set()
        return {int(v) for v in self.data.getlist("quarters") if str(v).isdigit()}


class ApplicationForm(QuarterChoiceMixin, forms.Form):
    """'Register for bidding'. Name is pre-filled from the account."""

    name = forms.CharField(max_length=150)
    father_name = forms.CharField(label="Father's name", max_length=150)
    # ADDITION to the mentor's field list: needed by the Application Form (to be confirmed).
    address = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    state = forms.ChoiceField(choices=[("", "Select state")] + STATE_CHOICES)
    pin_code = forms.CharField(label="PIN code", max_length=10,
                               widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    aadhaar = forms.CharField(label="Aadhaar number", max_length=20,
                              widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
                              help_text="12 digits. Stored encrypted; shown only as XXXX XXXX 1234.")
    pan = forms.CharField(label="PAN", max_length=12,
                          widget=forms.TextInput(attrs={"autocomplete": "off", "style": "text-transform:uppercase"}),
                          help_text="e.g. ABCPE1234F. Stored encrypted; shown only masked.")
    quarters = forms.ModelMultipleChoiceField(
        queryset=Quarter.objects.none(), widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Select at least one quarter."})
    declaration = forms.BooleanField(
        required=True, label="I declare that the information given above is true and correct.",
        error_messages={"required": "You must accept the declaration."})

    # Rendered by hand in the template (picker + declaration at the end).
    PERSONAL_FIELDS = ["name", "father_name", "address", "state", "pin_code", "aadhaar", "pan"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_quarters()

    def personal_fields(self):
        return [self[name] for name in self.PERSONAL_FIELDS]

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_father_name(self):
        return " ".join(self.cleaned_data["father_name"].split())

    def clean_pin_code(self):
        pin = self.cleaned_data["pin_code"].replace(" ", "")
        pin_validator(pin)
        return pin

    def clean_aadhaar(self):
        number = normalise_aadhaar(self.cleaned_data["aadhaar"])
        validate_aadhaar(number)
        if Applicant.objects.filter(aadhaar_index=crypto.blind_index("aadhaar", number)).exists():
            raise forms.ValidationError("This Aadhaar number is already registered.")
        return number

    def clean_pan(self):
        number = normalise_pan(self.cleaned_data["pan"])
        validate_pan(number)
        if Applicant.objects.filter(pan_index=crypto.blind_index("pan", number)).exists():
            raise forms.ValidationError("This PAN is already registered.")
        return number

    def details(self):
        """The plain personal fields, ready for services.submit_application()."""
        return {k: self.cleaned_data[k] for k in ["name", "father_name", "address", "state", "pin_code"]}


class AddQuartersForm(QuarterChoiceMixin, forms.Form):
    """Add more quarters to an existing application (supplementary slip)."""

    quarters = forms.ModelMultipleChoiceField(
        queryset=Quarter.objects.none(), widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Select at least one quarter to add."})

    def __init__(self, *args, applicant, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_quarters(exclude_ids=set(applicant.quarter_applications.values_list("quarter_id", flat=True)))
