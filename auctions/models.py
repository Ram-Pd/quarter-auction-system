from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Upper
from django.utils import timezone


class Quarter(models.Model):
    """A residential quarter that can be put up for auction."""

    class QuarterType(models.TextChoices):
        # Stored value "B"; shown as "Type B" (matches the Excel "Type" column).
        A = "A", "Type A"
        B = "B", "Type B"
        C = "C", "Type C"
        D = "D", "Type D"

    class Status(models.TextChoices):
        VACANT = "VACANT", "Vacant"
        IN_AUCTION = "IN_AUCTION", "In Auction"
        ALLOTTED = "ALLOTTED", "Allotted"

    quarter_no = models.CharField(
        "quarter no",
        max_length=20,
        unique=True,
        help_text='Alphanumeric, e.g. "B-214". Stored in upper case.',
    )
    sector = models.CharField(max_length=100)
    location_block = models.CharField("location / block", max_length=150)
    quarter_type = models.CharField("type", max_length=1, choices=QuarterType.choices)
    floor = models.CharField(max_length=20, help_text="Text, e.g. Ground, 1st, 2nd.")
    area_sqft = models.DecimalField("area (sq ft)", max_digits=8, decimal_places=2)
    base_rate = models.DecimalField(
        "base rate (Rs.)",
        max_digits=12,
        decimal_places=2,
        # ASSUMPTION (open question 12): unit not yet confirmed by SAIL.
        help_text="Placeholder: unit (total / monthly rent / per sq ft) not yet confirmed.",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.VACANT,
        db_index=True,  # the lobby and admin filter by status often
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["quarter_no"]
        constraints = [
            models.CheckConstraint(
                condition=Q(area_sqft__gt=0),
                name="quarter_area_positive",
                violation_error_message="Area must be greater than 0.",
            ),
            models.CheckConstraint(
                condition=Q(base_rate__gt=0),
                name="quarter_base_rate_positive",
                violation_error_message="Base rate must be greater than 0.",
            ),
            # "b-214" and "B-214" must count as the same quarter.
            models.UniqueConstraint(
                Upper("quarter_no"),
                name="quarter_no_unique_ci",
                violation_error_message="A quarter with this number already exists.",
            ),
        ]

    def save(self, *args, **kwargs):
        # Normalise so every code path (admin, import, shell) stores the same form.
        self.quarter_no = self.quarter_no.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.quarter_no


class Auction(models.Model):
    """
    One auction of one quarter. Several auctions can run at the same time.

    `status` stores only what the clock cannot tell us (open / closed / cancelled).
    Whether an OPEN auction is upcoming, live or awaiting closure is worked out
    from start_time / end_time; see `phase()`.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"                                # scheduled or running
        CLOSED = "CLOSED", "Closed - won"                    # set by the closure job (Milestone 5)
        CLOSED_NO_BIDS = "CLOSED_NO_BIDS", "Closed - no bids"  # open question 7 placeholder
        CANCELLED = "CANCELLED", "Cancelled"

    class Phase(models.TextChoices):
        """Computed, never stored. Used by the lobby and (later) the bidding page."""
        UPCOMING = "UPCOMING", "Upcoming"
        LIVE = "LIVE", "Live"
        CLOSING = "CLOSING", "Closing"  # deadline passed, closure job not run yet
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    quarter = models.ForeignKey(
        Quarter,
        on_delete=models.PROTECT,  # a quarter with auction history can't be deleted
        related_name="auctions",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(
        help_text="Current deadline. Anti-sniping may push it later.",
    )
    original_end_time = models.DateTimeField(
        null=True, editable=False,
        help_text="The scheduled deadline, before any anti-snipe extensions (audit).",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN,
                              db_index=True)
    # ASSUMPTION (open question 4): per-auction value, default is a placeholder.
    min_increment = models.DecimalField(
        "minimum increment (Rs.)", max_digits=12, decimal_places=2, default=Decimal("100.00"),
        help_text="Each new bid must beat the current highest bid by at least this much.",
    )
    # ASSUMPTION (open question 5): per-auction value, default is a placeholder.
    anti_snipe_extension = models.DurationField(
        default=timedelta(minutes=2),
        help_text="How much a bid in the final minute extends the deadline (HH:MM:SS).",
    )
    current_highest_bid = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False,
        help_text="Kept up to date by the bidding code (auctions/bidding.py).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        indexes = [
            # The closure job (Milestone 5) looks for OPEN auctions past end_time.
            models.Index(fields=["status", "end_time"], name="auction_status_end_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=models.F("start_time")),
                name="auction_end_after_start",
                violation_error_message="End time must be after start time.",
            ),
            models.CheckConstraint(
                condition=Q(min_increment__gt=0),
                name="auction_min_increment_positive",
                violation_error_message="Minimum increment must be greater than 0.",
            ),
            models.CheckConstraint(
                condition=Q(anti_snipe_extension__gte=timedelta(0)),
                name="auction_extension_not_negative",
                violation_error_message="Anti-snipe extension cannot be negative.",
            ),
            models.UniqueConstraint(
                fields=["quarter"],
                condition=Q(status="OPEN"),
                name="one_open_auction_per_quarter",
                violation_error_message="This quarter already has an open auction.",
            ),
        ]

    def __str__(self):
        quarter_no = self.quarter.quarter_no if self.quarter_id else "?"
        return f"{quarter_no} (auction #{self.pk})"

    # ---------- validation (admin forms call this) ----------

    def clean(self):
        errors = {}
        if self.quarter_id and self.quarter.status == Quarter.Status.ALLOTTED:
            errors["quarter"] = "This quarter is already allotted."
        if self._state.adding and self.end_time and self.end_time <= timezone.now():
            errors["end_time"] = "End time must be in the future."
        if errors:
            raise ValidationError(errors)

    # ---------- state changes ----------

    def save(self, *args, **kwargs):
        if self.original_end_time is None:
            self.original_end_time = self.end_time
        with transaction.atomic():
            creating = self._state.adding
            super().save(*args, **kwargs)
            if creating and self.status == self.Status.OPEN:
                Quarter.objects.filter(pk=self.quarter_id).update(status=Quarter.Status.IN_AUCTION)

    def cancel(self):
        """Cancel an open auction and free the quarter again. Bids are kept for audit."""
        from . import realtime  # imported here: realtime.py imports this module

        with transaction.atomic():
            # Same lock as bidding, so a bid can't slip in while we cancel.
            locked = Auction.objects.select_for_update().get(pk=self.pk)
            if locked.status != self.Status.OPEN:
                raise ValidationError("Only open auctions can be cancelled.")
            self.status = self.Status.CANCELLED
            self.save(update_fields=["status", "updated_at"])
            Quarter.objects.filter(pk=self.quarter_id).update(status=Quarter.Status.VACANT)
            transaction.on_commit(lambda: realtime.broadcast_state(self))

    # ---------- computed values (nothing stored) ----------

    def phase(self, now=None):
        now = now or timezone.now()
        if self.status == self.Status.CANCELLED:
            return self.Phase.CANCELLED
        if self.status != self.Status.OPEN:
            return self.Phase.CLOSED
        if now < self.start_time:
            return self.Phase.UPCOMING
        if now < self.end_time:
            return self.Phase.LIVE
        return self.Phase.CLOSING

    @property
    def minimum_next_bid(self):
        """
        Lowest acceptable next bid.
        ASSUMPTION: the first bid must be at least the quarter's base rate.
        """
        if self.current_highest_bid is None:
            return self.quarter.base_rate
        return self.current_highest_bid + self.min_increment


class Participation(models.Model):
    """
    An applicant taking part in one auction, under an anonymous per-auction code.

    PRIVACY: this table is the ONLY link between a real applicant and their
    "Bidder N" code. Public pages, bid history and WebSocket messages show
    only the code. Kept so eligibility can be checked, bids audited, disputes
    resolved and the real winner notified.
    """

    applicant = models.ForeignKey("accounts.Applicant", on_delete=models.PROTECT,
                                  related_name="participations")
    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="participations")
    # Shown as "Bidder 7". Numbered 1, 2, 3... in join order within each auction,
    # so the same applicant gets unrelated numbers in different auctions.
    bidder_number = models.PositiveIntegerField()
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["auction", "bidder_number"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "auction"],
                                    name="one_participation_per_applicant_per_auction"),
            models.UniqueConstraint(fields=["auction", "bidder_number"],
                                    name="unique_bidder_number_per_auction"),
        ]

    @property
    def anonymous_code(self):
        return f"Bidder {self.bidder_number}"

    def __str__(self):
        return f"{self.anonymous_code} in auction #{self.auction_id}"


class Bid(models.Model):
    """
    An ACCEPTED bid. Rejected attempts are never stored here.
    Rows are never edited or deleted: this is the audit trail.
    """

    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="bids")
    participation = models.ForeignKey(Participation, on_delete=models.PROTECT, related_name="bids")
    amount = models.DecimalField("amount (Rs.)", max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    # Random id made by the browser for each click. The same id sent twice
    # (double-click, resend after reconnect) is recognised as a duplicate.
    client_bid_id = models.UUIDField()
    # Audit details, recorded at the moment the bid was accepted:
    previous_highest = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deadline_extended_to = models.DateTimeField(
        null=True, blank=True, help_text="Set when this bid triggered an anti-snipe extension.")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["auction", "-amount"], name="bid_auction_amount_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="bid_amount_positive"),
            models.UniqueConstraint(fields=["participation", "client_bid_id"],
                                    name="no_duplicate_bid_submission"),
            # Every accepted bid beats the previous one, so amounts never repeat
            # within an auction. Backstop in case locking ever fails.
            models.UniqueConstraint(fields=["auction", "amount"], name="unique_bid_amount_per_auction"),
        ]

    def __str__(self):
        return f"Rs. {self.amount} by {self.participation.anonymous_code}"
