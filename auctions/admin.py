from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .forms import QuarterImportForm
from .importers import EXPECTED_HEADERS, import_quarters
from .models import Quarter


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    change_list_template = "admin/auctions/quarter/change_list.html"  # adds the Import button
    list_display = (
        "quarter_no", "sector", "location_block", "quarter_type",
        "floor", "area_sqft", "base_rate", "status",
    )
    list_filter = ("status", "quarter_type", "sector")
    search_fields = ("quarter_no", "sector", "location_block")
    readonly_fields = ("created_at", "updated_at")

    def get_urls(self):
        custom = [
            path("import/", self.admin_site.admin_view(self.import_view),
                 name="auctions_quarter_import"),
        ]
        return custom + super().get_urls()  # custom first, or "import" is read as an object id

    def import_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        result = None
        if request.method == "POST":
            form = QuarterImportForm(request.POST, request.FILES)
            if form.is_valid():
                result = import_quarters(form.cleaned_data["file"])
                if result.ok:
                    self.message_user(
                        request, f"Imported {result.created} quarter(s) successfully.",
                        messages.SUCCESS)
                    return redirect(reverse("admin:auctions_quarter_changelist"))
        else:
            form = QuarterImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Import quarters from Excel",
            "form": form,
            "result": result,
            "expected_headers": EXPECTED_HEADERS,
        }
        return TemplateResponse(request, "admin/auctions/quarter/import.html", context)
