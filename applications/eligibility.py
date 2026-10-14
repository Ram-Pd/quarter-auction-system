"""
Who may bid on which quarter. The ONE place these rules are written; the
auction page, the WebSocket consumer and the bidding service all ask here.

A user may bid on a quarter's auction only if ALL of these hold:
    1. logged in, with a bidding registration (Applicant)
    2. they applied for THIS quarter
    3. their registration is ACTIVE (documents verified by the office)
    4. their EMD for THIS quarter is verified
    5. they have not already been allotted MAX_QUARTERS_PER_APPLICANT quarters

Paying the EMD for quarter A gives no right to bid on quarter B (rule 4).
"""
from dataclasses import dataclass

from django.conf import settings

from .models import Applicant


@dataclass
class Eligibility:
    allowed: bool
    reason: str = ""   # shown to the user when not allowed


def allotted_count(applicant):
    """How many quarters this applicant has won so far."""
    from auctions.models import Auction  # imported here: auctions imports this module
    return Auction.objects.filter(status=Auction.Status.CLOSED_WON,
                                  winning_bid__participation__applicant=applicant).count()


def has_reached_allotment_limit(applicant):
    return allotted_count(applicant) >= settings.MAX_QUARTERS_PER_APPLICANT


def check(applicant, quarter):
    """Eligibility of an applicant (may be None) for one quarter, with a reason if not."""
    if applicant is None:
        return Eligibility(False, "Register for bidding to take part in auctions.")
    application = applicant.quarter_applications.filter(quarter=quarter).first()
    if application is None:
        return Eligibility(False, "You did not apply for this quarter, so you cannot bid on it.")
    if applicant.status != Applicant.Status.ACTIVE:
        return Eligibility(False, f"Your registration is not active (status: {applicant.get_status_display()}). "
                                  "The auction office activates it after checking your documents.")
    if not application.emd_verified:
        return Eligibility(False, "Your EMD for this quarter has not been verified yet.")
    if has_reached_allotment_limit(applicant):
        return Eligibility(False, f"You have already been allotted the maximum of "
                                  f"{settings.MAX_QUARTERS_PER_APPLICANT} quarters.")
    return Eligibility(True)


def check_user(user, quarter):
    """Same as check(), starting from a login (anonymous users included)."""
    if user is None or not user.is_authenticated:
        return Eligibility(False, "Log in to bid.")
    return check(Applicant.for_user(user), quarter)
