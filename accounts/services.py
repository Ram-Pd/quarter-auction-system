"""
Business actions on applicants. Views stay thin and call these functions,
so the same rules apply wherever an action is triggered from.
"""
from django.contrib.auth.models import User
from django.db import transaction

from .models import Applicant


class ActivationError(Exception):
    pass


def activate_applicant(applicant, password):
    """
    Create the login account (username = URN) and mark the applicant activated.

    The applicant row is locked for the duration, so two simultaneous
    activation requests cannot both succeed. (Locking takes effect on
    PostgreSQL; SQLite serialises writes anyway.)
    """
    with transaction.atomic():
        applicant = Applicant.objects.select_for_update().get(pk=applicant.pk)
        if applicant.is_activated:
            raise ActivationError("This account is already activated.")
        if not applicant.is_verified:
            raise ActivationError("EMD payment not verified yet.")
        user = User.objects.create_user(
            username=applicant.urn,
            email=applicant.email,  # used by password reset
            password=password,      # hashed by Django; never stored in Applicant
        )
        applicant.user = user
        applicant.is_activated = True
        applicant.save(update_fields=["user", "is_activated", "updated_at"])
    return user
