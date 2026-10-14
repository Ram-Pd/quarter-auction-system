"""
Login accounts.

    User      - one per person. Logs in with EMAIL + password (no username).
    EmailOTP  - a one-time code emailed during sign-up to prove the person
                owns the email address. Only a keyed hash of the code is stored.

The bidding registration (father's name, Aadhaar, URN, ...) is NOT here: it is
the Applicant in the "applications" app, created later by "Register for bidding".
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

# Indian mobile number: 10 digits starting 6-9. Collected but NOT verified
# (CR #3 open question 9).
phone_validator = RegexValidator(r"^[6-9]\d{9}$", "Enter a valid 10-digit Indian mobile number.")


def normalise_email(email):
    """One spelling for every email address we store: trimmed and lower case."""
    return (email or "").strip().lower()


class UserManager(BaseUserManager):
    """
    Django's default manager expects a username. Ours creates users from an
    email instead (used by sign-up, tests and "manage.py createsuperuser").
    """

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalise_email(email), **extra_fields)
        user.set_password(password)  # hashed; the plain password is never stored
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    A login account. AbstractUser gives us password hashing, is_active,
    is_staff, groups and permissions; we only swap the username for the email.
    """

    username = None      # removed: the email is the login name
    first_name = None    # replaced by full_name (Indian names don't split neatly)
    last_name = None

    email = models.EmailField("email address", unique=True)
    full_name = models.CharField("name", max_length=150)
    phone = models.CharField("phone number", max_length=10, blank=True, validators=[phone_validator],
                             help_text="Collected at sign-up. Not verified.")
    email_verified_at = models.DateTimeField(
        null=True, blank=True, editable=False,
        help_text="When the sign-up OTP was confirmed. Empty for accounts made by an admin.")

    USERNAME_FIELD = "email"        # what people type on the login page
    EMAIL_FIELD = "email"           # where password-reset emails go
    REQUIRED_FIELDS = ["full_name"]  # asked by "createsuperuser" (besides email + password)

    objects = UserManager()

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        constraints = [
            # "A@x.com" and "a@x.com" are the same mailbox.
            models.UniqueConstraint(Lower("email"), name="user_email_unique_ci",
                                    violation_error_message="An account with this email already exists."),
        ]

    def save(self, *args, **kwargs):
        self.email = normalise_email(self.email)
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.email

    def __str__(self):
        return self.email


class EmailOTP(models.Model):
    """
    A 6-digit code emailed to prove ownership of an email address.

    Rules (enforced in accounts/otp.py, values in settings):
      - stored as a keyed hash, never as the plain code
      - expires after OTP_VALID_MINUTES
      - at most OTP_MAX_ATTEMPTS wrong guesses, then it is dead
      - single use (used_at is set on success)
    """

    class Purpose(models.TextChoices):
        SIGNUP = "SIGNUP", "Sign-up"

    email = models.EmailField()
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.SIGNUP)
    code_hash = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "email OTP"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "purpose", "-created_at"], name="otp_lookup_idx")]

    def __str__(self):
        return f"OTP for {self.email} ({self.created_at:%d %b %H:%M})"
