from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from . import realtime
from .closing import close_auction, send_pending_notifications
from .forms import QuarterImportForm
from .importers import EXPECTED_HEADERS, import_quarters
from .models import Auction, Bid, Participation, Quarter


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    change_list_template = "admin/auctions/quarter/change_list.html"  # adds the Import button
    list_display = (
        "quarter_no", "sector", "location_block", "quarter_type",
        "floor", "area_sqft", "base_rate", "emd_amount", "status",
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
                        request, f"Imported {result.created} quarter(s), each with its scheduled auction.",
                        messages.SUCCESS)
                    return redirect(reverse("admin:auctions_auction_changelist"))
        else:
            form = QuarterImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Import quarters from Excel",
            "form": form,
            "result": result,
            "expected_headers": EXPECTED_HEADERS,
            "default_duration": settings.DEFAULT_AUCTION_DURATION_MINUTES,
        }
        return TemplateResponse(request, "admin/auctions/quarter/import.html", context)


class BidInline(admin.TabularInline):
    """Accepted bids, read-only, shown on the auction page. Codes only, no identities."""
    model = Bid
    fields = ("created_at", "bidder", "amount", "previous_highest", "deadline_extended_to")
    readonly_fields = fields
    extra = 0
    can_delete = False
    ordering = ("-created_at",)

    @admin.display(description="Bidder")
    def bidder(self, obj):
        return obj.participation.anonymous_code

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "start_time", "duration_minutes", "end_time", "phase_display",
                    "increment_percent", "anti_snipe_seconds", "current_highest_bid", "result_display")
    list_filter = ("status",)
    search_fields = ("quarter__quarter_no",)
    date_hierarchy = "start_time"
    actions = ["cancel_auctions", "close_if_due", "send_result_emails"]

    # Fields that may no longer change once bidding has started (fairness).
    LOCKED_AFTER_START = ("start_time", "duration_minutes", "increment_percent", "anti_snipe_seconds")
    fields = ("quarter", "start_time", "duration_minutes", "end_time", "original_end_time",
              "increment_percent", "anti_snipe_seconds", "status", "current_highest_bid",
              "extensions_count", "total_bids", "closed_at", "winner_email_sent_at")

    @admin.display(description="Phase")
    def phase_display(self, obj):
        return obj.phase().label

    @admin.display(description="Result")
    def result_display(self, obj):
        # Anonymous code only; the identity is in Participation (superusers).
        if obj.status == Auction.Status.CLOSED_WON:
            return f"Rs. {obj.winning_bid.amount:,.0f} by {obj.winning_bid.participation.anonymous_code}"
        if obj.is_closed or obj.status == Auction.Status.CANCELLED:
            return obj.get_status_display()
        return "-"

    def get_readonly_fields(self, request, obj=None):
        always = ["status", "end_time", "current_highest_bid", "original_end_time", "extensions_count",
                  "total_bids", "closed_at", "winner_email_sent_at"]
        if obj is None:  # adding
            return always
        if obj.status != Auction.Status.SCHEDULED:  # closed / cancelled: history, read-only
            return list(self.fields)
        locked = ["quarter"]  # changing the quarter would break quarter status tracking
        if obj.phase() != Auction.Phase.UPCOMING:
            locked += self.LOCKED_AFTER_START
        return always + locked

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # When creating an auction, offer only Vacant quarters.
        if db_field.name == "quarter":
            kwargs["queryset"] = Quarter.objects.filter(status=Quarter.Status.VACANT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_inlines(self, request, obj):
        return [BidInline] if obj else []  # a new auction has no bids to show

    def save_model(self, request, obj, form, change):
        if {"start_time", "duration_minutes"} & set(form.changed_data):
            obj.schedule_end()  # re-scheduled before the start: deadline = start + duration
        super().save_model(request, obj, form, change)
        if change:
            # Open auction pages update their deadline/status immediately.
            transaction.on_commit(lambda: realtime.broadcast_state(obj))

    def has_delete_permission(self, request, obj=None):
        return False  # keep every auction for the audit trail; use "Cancel" instead

    @admin.action(description="Cancel selected scheduled auctions (quarter becomes Vacant again)")
    def cancel_auctions(self, request, queryset):
        cancelled = 0
        for auction in queryset.filter(status=Auction.Status.SCHEDULED):
            auction.cancel()
            cancelled += 1
        skipped = queryset.count() - cancelled
        self.message_user(request, f"Cancelled {cancelled} auction(s).", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Skipped {skipped} auction(s) that were not scheduled.",
                              messages.WARNING)

    @admin.action(description="Close selected auctions now (only if their deadline has passed)")
    def close_if_due(self, request, queryset):
        closed = [r for r in (close_auction(a.pk) for a in queryset) if r.closed_now]
        self.message_user(request, f"Closed {len(closed)} auction(s). Auctions not yet due or "
                                   "already closed were left unchanged.", messages.SUCCESS)

    @admin.action(description="Send result emails (only those not sent yet)")
    def send_result_emails(self, request, queryset):
        for auction in queryset.filter(status=Auction.Status.CLOSED_WON):
            send_pending_notifications(auction.pk)
        unsent = queryset.filter(status=Auction.Status.CLOSED_WON, winner_email_sent_at__isnull=True).count()
        if unsent:
            self.message_user(request, f"{unsent} winner email(s) could not be sent. Check the email "
                                       "settings and the server log.", messages.ERROR)
        else:
            self.message_user(request, "All winner emails for the selected auctions have been sent.",
                              messages.SUCCESS)


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    """
    Audit view of every accepted bid. Read-only: bids are never edited or deleted.
    Shows the anonymous code only; identities are in Participation (superusers only).
    """
    list_display = ("created_at", "auction", "bidder", "amount", "previous_highest", "deadline_extended_to")
    list_filter = ("auction",)
    search_fields = ("auction__quarter__quarter_no",)
    list_select_related = ("auction__quarter", "participation")
    exclude = ("participation",)  # the edit form would otherwise list applicants
    readonly_fields = ("auction", "bidder", "amount", "created_at", "client_bid_id",
                       "previous_highest", "deadline_extended_to")

    @admin.display(description="Bidder")
    def bidder(self, obj):
        return obj.participation.anonymous_code

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    """
    The applicant <-> anonymous code mapping. CONFIDENTIAL: superusers only,
    for audits, disputes and contacting the winner.
    """
    list_display = ("auction", "anonymous_code", "applicant", "joined_at")
    list_filter = ("auction",)
    search_fields = ("applicant__application_no", "applicant__urn")
    readonly_fields = ("auction", "applicant", "bidder_number", "joined_at")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
