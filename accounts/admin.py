import logging

from django.contrib import admin, messages

from .emails import send_registration_documents
from .models import Applicant

logger = logging.getLogger(__name__)


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    """
    This screen shows personal data. Only give the "accounts | applicant"
    permissions to staff who are allowed to see applicant identities.
    """

    list_display = ("application_no", "urn", "name", "mobile", "is_verified", "is_activated",
                    "documents_emailed_at")
    list_filter = ("is_verified", "is_activated", "state")
    search_fields = ("application_no", "urn", "name", "email", "mobile")
    # System-set fields: never edited by hand.
    readonly_fields = ("application_no", "documents_emailed_at", "is_activated", "user",
                       "created_at", "updated_at")
    actions = ["resend_documents"]
    fieldsets = (
        ("Applicant details", {
            "fields": ("name", "father_name", "mobile", "email", "address", "state", "pin_code"),
        }),
        ("Application & URN", {
            "fields": ("application_no", "application_date", "urn", "urn_date",
                       "documents_emailed_at"),
        }),
        ("Status", {
            "fields": ("is_verified", "is_activated", "user", "created_at", "updated_at"),
        }),
    )

    @admin.action(description="Resend registration documents (Application Form + Intimation Slip)")
    def resend_documents(self, request, queryset):
        sent, failed = 0, []
        for applicant in queryset:
            try:
                send_registration_documents(applicant)
                sent += 1
            except Exception:
                logger.exception("Resend failed for %s", applicant.application_no)
                failed.append(applicant.application_no)
        if sent:
            self.message_user(request, f"Documents sent to {sent} applicant(s).", messages.SUCCESS)
        if failed:
            self.message_user(request, f"Sending failed for: {', '.join(failed)}", messages.ERROR)
