from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from .forms import QuarterImportForm
from .importers import EXPECTED_HEADERS, import_quarters
from .models import Auction, Quarter


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


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "quarter", "start_time", "end_time", "phase_display",
                    "min_increment", "current_highest_bid")
    list_filter = ("status",)
    search_fields = ("quarter__quarter_no",)
    date_hierarchy = "start_time"
    actions = ["cancel_auctions"]

    # Fields that may no longer change once bidding has started (fairness).
    LOCKED_AFTER_START = ("start_time", "min_increment", "anti_snipe_extension")

    @admin.display(description="Phase")
    def phase_display(self, obj):
        return obj.phase().label

    def get_readonly_fields(self, request, obj=None):
        always = ["status", "current_highest_bid", "created_at", "updated_at"]
        if obj is None:  # adding
            return always
        if obj.status != Auction.Status.OPEN:  # closed / cancelled: history, read-only
            return [f.name for f in obj._meta.fields if f.name != "id"]
        locked = ["quarter"]  # changing the quarter would break quarter status tracking
        if obj.phase() != Auction.Phase.UPCOMING:
            locked += self.LOCKED_AFTER_START
        return always + locked

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # When creating an auction, offer only Vacant quarters.
        if db_field.name == "quarter":
            kwargs["queryset"] = Quarter.objects.filter(status=Quarter.Status.VACANT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False  # keep every auction for the audit trail; use "Cancel" instead

    @admin.action(description="Cancel selected open auctions (quarter becomes Vacant again)")
    def cancel_auctions(self, request, queryset):
        cancelled = 0
        for auction in queryset.filter(status=Auction.Status.OPEN):
            auction.cancel()
            cancelled += 1
        skipped = queryset.count() - cancelled
        self.message_user(request, f"Cancelled {cancelled} auction(s).", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Skipped {skipped} auction(s) that were not open.",
                              messages.WARNING)
