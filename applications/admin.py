"""
Admin screens for applications.

    Applicants              list + read-only details + the VERIFICATION SCREEN
                            (/admin/applications/applicant/<id>/verify/)
    Document checklist      the list of documents to check (editable)
    Audit log               read-only history of every verification action

Who sees what (applications/roles.py):
    - "Verification Officer": applicants, verification screen, reveal (audited)
    - "Auction Admin": NOT the applicants (no personal data); may edit the checklist
"""
import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from . import eligibility, emails, services
from .models import Applicant, AuditLog, DocumentChecklistItem, QuarterApplication

logger = logging.getLogger(__name__)


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    """
    PERSONAL DATA: only staff with the "applications | applicant" view permission
    (the Verification Officer group) see this. Aadhaar/PAN are shown masked.
    """

    list_display = ("application_no", "urn", "name", "status", "quarters_summary", "documents_emailed_at",
                    "verify_link")
    list_filter = ("status",)
    search_fields = ("application_no", "urn", "name", "user__email")
    list_select_related = ("user",)
    actions = ["resend_documents"]
    change_form_template = "admin/applications/applicant/change_form.html"  # adds the "Verify" button
    fields = ("application_no", "application_date", "urn", "urn_date", "user", "name", "father_name",
              "address", "state", "pin_code", "masked_aadhaar", "masked_pan", "status", "status_reason",
              "status_changed_at", "status_changed_by", "documents_emailed_at", "created_at")
    readonly_fields = fields

    @admin.display(description="Quarters (EMD verified / applied)")
    def quarters_summary(self, obj):
        apps = obj.quarter_applications.all()
        return f"{sum(1 for a in apps if a.emd_verified)} / {len(apps)}"

    @admin.display(description="")
    def verify_link(self, obj):
        return format_html('<a class="button" href="{}">Verify</a>',
                           reverse("admin:applications_applicant_verify", args=[obj.pk]))

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("quarter_applications")

    def has_add_permission(self, request):
        return False  # applicants register themselves

    def has_delete_permission(self, request, obj=None):
        return False  # audit trail

    def get_urls(self):
        custom = [path("<int:applicant_id>/verify/", self.admin_site.admin_view(self.verify_view),
                       name="applications_applicant_verify")]
        return custom + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = {**(extra_context or {}),
                         "verify_url": reverse("admin:applications_applicant_verify", args=[object_id])}
        return super().change_view(request, object_id, form_url, extra_context)

    # ------------------------------------------------------------ verification screen

    def verify_view(self, request, applicant_id):
        if not request.user.has_perm("applications.verify_applicant"):
            raise PermissionDenied
        applicant = get_object_or_404(Applicant.objects.select_related("user"), pk=applicant_id)
        revealed = None

        if request.method == "POST":
            action = request.POST.get("action", "")
            try:
                if action == "reveal":
                    revealed = services.reveal_identity_numbers(applicant, request.user, request.POST.get("reason"))
                else:
                    self._handle_action(request, applicant, action)
                    return redirect(request.path)
            except services.VerificationError as error:
                messages.error(request, error.message)
                if action != "reveal":
                    return redirect(request.path)

        applications = list(applicant.quarter_applications.select_related("quarter", "emd_verified_by")
                            .order_by("quarter__quarter_no"))
        checks = {c.item_id: c for c in applicant.document_checks.select_related("checked_by")}
        items = [(item, checks.get(item.pk)) for item in DocumentChecklistItem.objects.filter(is_active=True)]
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Verify application {applicant.application_no}",
            "applicant": applicant,
            "applications": applications,
            "items": items,
            "missing": services.missing_required_documents(applicant),
            "allotted": eligibility.allotted_count(applicant),
            "audit_entries": applicant.audit_entries.select_related("actor")[:50],
            "can_reveal": request.user.has_perm("applications.reveal_identity_numbers"),
            "revealed": revealed,
            "today": date.today(),
        }
        return TemplateResponse(request, "admin/applications/applicant/verify.html", context)

    def _handle_action(self, request, applicant, action):
        user, post = request.user, request.POST
        if action == "documents":
            ticked = {int(v) for v in post.getlist("items") if v.isdigit()}
            for item in DocumentChecklistItem.objects.filter(is_active=True):
                services.set_document_check(applicant, item, item.pk in ticked, user)
            messages.success(request, "Document checklist saved.")
        elif action in ("save_emd", "verify_emd", "unverify_emd"):
            application = get_object_or_404(QuarterApplication, pk=post.get("application_id"), applicant=applicant)
            if action == "save_emd":
                services.record_emd(application, post.get("receipt_no", ""), _decimal(post.get("amount_paid")),
                                    _date(post.get("payment_date")), user)
                messages.success(request, f"Receipt details saved for {application.quarter}.")
            elif action == "verify_emd":
                services.verify_emd(application, user)
                messages.success(request, f"EMD verified for {application.quarter}.")
            else:
                services.unverify_emd(application, user, post.get("reason"))
                messages.warning(request, f"EMD un-verified for {application.quarter}.")
        elif action == "activate":
            services.activate(applicant, user)
            messages.success(request, "Applicant activated.")
        elif action == "reject":
            services.reject(applicant, user, post.get("reason"))
            messages.warning(request, "Application rejected.")
        elif action == "suspend":
            services.suspend(applicant, user, post.get("reason"))
            messages.warning(request, "Applicant suspended.")
        else:
            raise services.VerificationError("Unknown action.")

    # ------------------------------------------------------------ actions

    @admin.action(description="Resend documents (Application Form + Intimation Slip)")
    def resend_documents(self, request, queryset):
        sent, failed = 0, []
        for applicant in queryset.select_related("user"):
            try:
                emails.send_application_documents(applicant)
                sent += 1
            except Exception:
                logger.exception("Resend failed for %s", applicant.application_no)
                failed.append(applicant.application_no)
        if sent:
            self.message_user(request, f"Documents sent to {sent} applicant(s).", messages.SUCCESS)
        if failed:
            self.message_user(request, f"Sending failed for: {', '.join(failed)}", messages.ERROR)


def _decimal(text):
    try:
        value = Decimal((text or "").replace(",", "").strip())
    except InvalidOperation:
        raise services.VerificationError("Amount paid must be a number.")
    if value <= 0:
        raise services.VerificationError("Amount paid must be greater than 0.")
    return value


def _date(text):
    try:
        value = date.fromisoformat((text or "").strip())
    except ValueError:
        raise services.VerificationError("Enter the payment date.")
    if value > date.today():
        raise services.VerificationError("The payment date cannot be in the future.")
    return value


@admin.register(DocumentChecklistItem)
class DocumentChecklistItemAdmin(admin.ModelAdmin):
    list_display = ("name", "required", "is_active", "order")
    list_editable = ("required", "is_active", "order")

    def has_delete_permission(self, request, obj=None):
        return False  # untick "is active" instead; past ticks refer to the item


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only. Shows the application number, never personal data."""

    list_display = ("created_at", "actor", "action", "applicant", "summary")
    list_filter = ("action",)
    search_fields = ("applicant__application_no", "summary")
    list_select_related = ("actor", "applicant")
    readonly_fields = ("created_at", "actor", "action", "applicant", "summary", "details")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# DocumentCheck and QuarterApplication are deliberately NOT registered: they are
# changed only through the verification screen, so every change goes through
# services.py and lands in the audit log.
