from django.db import models
from django.db.models import Q
from django.db.models.functions import Upper


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
