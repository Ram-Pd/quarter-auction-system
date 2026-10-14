"""Helpers that build test data. Import these in any test module."""
from accounts.models import User

STRONG_PASSWORD = "Bokaro-Steel-2026!"


def make_user(n=1, password=STRONG_PASSWORD, **overrides):
    """A login account (no bidding registration)."""
    email = overrides.pop("email", f"user{n}@example.com")
    data = {"full_name": f"Test User {n}", "phone": "9876543210"}
    data.update(overrides)
    return User.objects.create_user(email, password, **data)
