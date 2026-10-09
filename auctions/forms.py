from django import forms
from django.core.validators import FileExtensionValidator

MAX_UPLOAD_MB = 5


class QuarterImportForm(forms.Form):
    file = forms.FileField(
        label="Excel file (.xlsx)",
        validators=[FileExtensionValidator(["xlsx"])],
        help_text=f"Maximum {MAX_UPLOAD_MB} MB. Columns: Quarter No | Sector | Location / Block | "
                  "Type | Floor | Area (sq ft) | Base Rate (Rs.) | Status",
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"File is too large (maximum {MAX_UPLOAD_MB} MB).")
        return f
