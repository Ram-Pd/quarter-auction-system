"""
Quarters, their auctions, participation codes and bids.

    Quarter        - a residential quarter (from the Excel import)
    Auction        - the bidding slot for ONE quarter (also from the Excel import)
    Participation  - an eligible applicant's anonymous "Bidder N" code in one auction
    Bid            - an accepted bid (audit trail; never edited or deleted)
"""
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Upper
from django.utils import timezone

ONE_RUPEE = Decimal("1")


def default_duration_minutes():
    return settings.DEFAULT_AUCTION_DURATION_MINUTES


def default_increment_percent():
    return settings.DEFAULT_INCREMENT_PERCENT


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

    quarter_no = models.CharField("quarter no", max_length=20, unique=True,
                                  help_text='Alphanumeric, e.g. "B-214". Stored in upper case.')
    sector = models.CharField(max_length=100)
    location_block = models.CharField("location / block", max_length=150)
    quarter_type = models.CharField("type", max_length=1, choices=QuarterType.choices)
    floor = models.CharField(max_length=20, help_text="Text, e.g. Ground, 1st, 2nd.")
    area_sqft = models.DecimalField("area (sq ft)", max_digits=8, decimal_places=2)
    base_rate = models.DecimalField(
        "base rate (Rs.)", max_digits=12, decimal_places=2,
        # ASSUMPTION (CLAUDE.md open question 12): unit not yet confirmed.
        help_text="Placeholder: unit (total / monthly rent / per sq ft) not yet confirmed.")
    emd_amount = models.DecimalField(
        "EMD amount (Rs.)", max_digits=12, decimal_places=2,
        help_text="Earnest money deposit for THIS quarter, paid offline through SBI Collect.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VACANT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["quarter_no"]
        constraints = [
            models.CheckConstraint(condition=Q(area_sqft__gt=0), name="quarter_area_positive",
                                   violation_error_message="Area must be greater than 0."),
            models.CheckConstraint(condition=Q(base_rate__gt=0), name="quarter_base_rate_positive",
                                   violation_error_message="Base rate must be greater than 0."),
            models.CheckConstraint(condition=Q(emd_amount__gt=0), name="quarter_emd_positive",
                                   violation_error_message="EMD amount must be greater than 0."),
            # "b-214" and "B-214" must count as the same quarter.
            models.UniqueConstraint(Upper("quarter_no"), name="quarter_no_unique_ci",
                                    violation_error_message="A quarter with this number already exists."),
        ]

    def save(self, *args, **kwargs):
        # Normalise so every code path (admin, import, shell) stores the same form.
        self.quarter_no = self.quarter_no.strip().upper()
        super().save(*args, **kwargs)

    @property
    def locality(self):
        """'Locality details' on the public pages = sector + location / block."""
        return f"{self.sector}, {self.location_block}"

    def __str__(self):
        return self.quarter_no


class Auction(models.Model):
    """
    The bidding slot of ONE quarter. Several auctions can run at the same time.

    `status` stores only what the clock cannot tell us (scheduled / closed with
    which outcome / cancelled). Whether a SCHEDULED auction is upcoming, live or
    waiting for closure is worked out from start_time / end_time: see phase().
    """

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"                         # upcoming or running
        CLOSED_WON = "CLOSED_WON", "Closed - won"
        CLOSED_NO_BIDS = "CLOSED_NO_BIDS", "Closed - no bids"
        CLOSED_NO_VALID_WINNER = "CLOSED_NO_VALID_WINNER", "Closed - no valid winner"
        CANCELLED = "CANCELLED", "Cancelled"

    CLOSED_STATUSES = (Status.CLOSED_WON, Status.CLOSED_NO_BIDS, Status.CLOSED_NO_VALID_WINNER)

    class Phase(models.TextChoices):
        """Computed, never stored."""
        UPCOMING = "UPCOMING", "Upcoming"
        LIVE = "LIVE", "Live"
        CLOSING = "CLOSING", "Closing"  # deadline passed, closure not run yet
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    quarter = models.ForeignKey(Quarter, on_delete=models.PROTECT, related_name="auctions")
    start_time = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(
        "duration (minutes)", default=default_duration_minutes,
        help_text="Length of the bidding window. Editable until the auction starts.")
    end_time = models.DateTimeField(
        editable=False,
        help_text="Current deadline = start + duration, pushed later by anti-sniping if it is on.")
    original_end_time = models.DateTimeField(
        null=True, editable=False, help_text="The scheduled deadline, before any anti-snipe extensions.")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    # ASSUMPTION (CLAUDE.md open question 4): step = increment_percent % of the base rate.
    increment_percent = models.DecimalField(
        "increment (% of base rate)", max_digits=5, decimal_places=2, default=default_increment_percent,
        help_text="Bid step as a percentage of the base rate, e.g. 0.20 means 0.2%.")
    # CR #3 open question 6: off (0) by default.
    anti_snipe_seconds = models.PositiveIntegerField(
        "anti-snipe seconds", default=0,
        help_text="0 = off. Otherwise a bid in the last N seconds moves the deadline to now + N seconds "
                  "(at most AUCTION_MAX_EXTENSIONS times).")
    extensions_count = models.PositiveIntegerField(default=0, editable=False)
    current_highest_bid = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, editable=False,
        help_text="Kept up to date by the bidding code (auctions/bidding.py).")

    # --- Final result, written once by auctions/closing.py ---
    winning_bid = models.OneToOneField(
        "Bid", on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="won_auction",
        help_text="The winning bid. Empty unless the auction closed with a valid winner.")
    closed_at = models.DateTimeField(null=True, blank=True, editable=False)
    total_bids = models.PositiveIntegerField(default=0, editable=False,
                                             help_text="Number of accepted bids (published with the result).")
    winner_email_sent_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="When the winner email was sent. Set once; prevents duplicate emails.")
    losers_notified_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        indexes = [
            # The closure job (auctions/closing.py) looks for SCHEDULED auctions past end_time.
            models.Index(fields=["status", "end_time"], name="auction_status_end_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_time__gt=models.F("start_time")),
                                   name="auction_end_after_start",
                                   violation_error_message="End time must be after start time."),
            models.CheckConstraint(condition=Q(duration_minutes__gt=0), name="auction_duration_positive",
                                   violation_error_message="Duration must be at least 1 minute."),
            models.CheckConstraint(condition=Q(increment_percent__gt=0), name="auction_increment_positive",
                                   violation_error_message="Increment percent must be greater than 0."),
            models.UniqueConstraint(fields=["quarter"], condition=Q(status="SCHEDULED"),
                                    name="one_scheduled_auction_per_quarter",
                                    violation_error_message="This quarter already has a scheduled auction."),
            # Last line of defence: a quarter can be WON only once, ever.
            models.UniqueConstraint(fields=["quarter"], condition=Q(status="CLOSED_WON"),
                                    name="quarter_won_only_once",
                                    violation_error_message="This quarter has already been won."),
            # "Closed - won" always has a winning bid; every other status has none.
            models.CheckConstraint(
                condition=(Q(status="CLOSED_WON", winning_bid__isnull=False)
                           | (~Q(status="CLOSED_WON") & Q(winning_bid__isnull=True))),
                name="winning_bid_matches_status",
                violation_error_message="Only a closed-won auction has a winning bid."),
        ]

    def __str__(self):
        quarter_no = self.quarter.quarter_no if self.quarter_id else "?"
        return f"{quarter_no} (auction #{self.pk})"

    # ---------- validation (admin forms call this) ----------

    def clean(self):
        errors = {}
        if self.quarter_id and self._state.adding and self.quarter.status == Quarter.Status.ALLOTTED:
            errors["quarter"] = "This quarter is already allotted."
        if self._state.adding and self.start_time and self.start_time <= timezone.now():
            errors["start_time"] = "Start time must be in the future."
        if errors:
            raise ValidationError(errors)

    # ---------- state changes ----------

    def schedule_end(self):
        """Set the deadline from start + duration. Only meaningful before bidding starts."""
        self.end_time = self.start_time + timedelta(minutes=self.duration_minutes)
        self.original_end_time = self.end_time

    def save(self, *args, **kwargs):
        if self.end_time is None:
            self.schedule_end()
        if self.original_end_time is None:
            self.original_end_time = self.end_time
        with transaction.atomic():
            creating = self._state.adding
            super().save(*args, **kwargs)
            if creating and self.status == self.Status.SCHEDULED:
                Quarter.objects.filter(pk=self.quarter_id).update(status=Quarter.Status.IN_AUCTION)

    def cancel(self):
        """Cancel a scheduled auction and free the quarter again. Bids are kept for audit."""
        from . import realtime  # imported here: realtime.py imports this module

        with transaction.atomic():
            # Same lock as bidding, so a bid can't slip in while we cancel.
            locked = Auction.objects.select_for_update().get(pk=self.pk)
            if locked.status != self.Status.SCHEDULED:
                raise ValidationError("Only scheduled auctions can be cancelled.")
            self.status = self.Status.CANCELLED
            self.save(update_fields=["status", "updated_at"])
            Quarter.objects.filter(pk=self.quarter_id).update(status=Quarter.Status.VACANT)
            transaction.on_commit(lambda: realtime.broadcast_state(self))

    # ---------- computed values (nothing stored) ----------

    def phase(self, now=None):
        now = now or timezone.now()
        if self.status == self.Status.CANCELLED:
            return self.Phase.CANCELLED
        if self.status != self.Status.SCHEDULED:
            return self.Phase.CLOSED
        if now < self.start_time:
            return self.Phase.UPCOMING
        if now < self.end_time:
            return self.Phase.LIVE
        return self.Phase.CLOSING

    @property
    def is_closed(self):
        return self.status in self.CLOSED_STATUSES

    @property
    def bid_step(self):
        """
        One bid step in whole rupees = increment_percent % of the base rate,
        rounded to the nearest rupee (ASSUMPTION), never less than Rs. 1.
        Example: 0.20 % of 45,000 = Rs. 90.
        """
        step = (self.quarter.base_rate * self.increment_percent / 100).quantize(ONE_RUPEE, ROUND_HALF_UP)
        return max(step, ONE_RUPEE)

    @property
    def minimum_next_bid(self):
        """
        Lowest acceptable next bid.
        ASSUMPTION (CR #3 open question 3): the first bid must be at least the base rate.
        """
        if self.current_highest_bid is None:
            return self.quarter.base_rate.quantize(ONE_RUPEE, ROUND_CEILING)
        return self.current_highest_bid + self.bid_step

    def quick_bid_amounts(self):
        """The "+1 / +2 / +5 steps" buttons: n steps over the current highest bid."""
        return [(n, self.minimum_next_bid + (n - 1) * self.bid_step) for n in settings.QUICK_BID_STEPS]

    @property
    def winner_participation(self):
        """The winning Participation (who won, internally), or None."""
        return self.winning_bid.participation if self.winning_bid_id else None


class Participation(models.Model):
    """
    An eligible applicant taking part in one auction, under an anonymous per-auction code.

    PRIVACY: this table is the ONLY link between a real applicant and their
    "Bidder N" code. Public pages, bid history and WebSocket messages show
    only the code. Kept so eligibility can be checked, bids audited, disputes
    resolved and the real winner notified.
    """

    applicant = models.ForeignKey("applications.Applicant", on_delete=models.PROTECT,
                                  related_name="participations")
    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="participations")
    # Shown as "Bidder 7". Numbered 1, 2, 3... in joining order within each auction,
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
