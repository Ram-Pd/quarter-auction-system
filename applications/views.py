"""
Applicant-side pages for "Register for bidding".

    /apply/            the application form (once per account)
    /apply/mine/       my application: status, quarters, EMD verification
    /apply/add/        add more quarters (supplementary Intimation Slip)

Submissions use Post/Redirect/Get: after saving we redirect, so refreshing
the next page can never submit (or email) twice.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters

from . import eligibility, services
from .forms import AddQuartersForm, ApplicationForm
from .models import Applicant


@sensitive_post_parameters("aadhaar", "pan")  # never shown in error reports or logs
@login_required
def apply(request):
    if Applicant.for_user(request.user):
        return redirect("applications:mine")
    if request.method == "POST":
        form = ApplicationForm(request.POST)
        if form.is_valid():
            try:
                applicant = services.submit_application(
                    request.user, form.details(), form.cleaned_data["aadhaar"], form.cleaned_data["pan"],
                    list(form.cleaned_data["quarters"].order_by("quarter_no")))
            except IntegrityError:
                # Lost a race: submitted twice at once, or the Aadhaar/PAN was registered a moment ago.
                if Applicant.for_user(request.user):
                    return redirect("applications:mine")
                form.add_error(None, "This Aadhaar number or PAN is already registered.")
            else:
                applicant.refresh_from_db()
                if applicant.documents_emailed_at:
                    messages.success(request, f"Application {applicant.application_no} submitted. Your Application "
                                              f"Form and Intimation Slip have been emailed to {request.user.email}.")
                else:
                    messages.error(request, f"Application {applicant.application_no} submitted, but the email "
                                            "could not be sent. Please contact the auction office.")
                return redirect("applications:mine")
    else:
        form = ApplicationForm(initial={"name": request.user.full_name})
    return render(request, "applications/apply.html", {"form": form})


@login_required
def mine(request):
    applicant = Applicant.for_user(request.user)
    if applicant is None:
        return redirect("applications:apply")
    applications = list(applicant.quarter_applications.select_related("quarter").order_by("quarter__quarter_no"))
    return render(request, "applications/mine.html", {
        "applicant": applicant,
        "applications": applications,
        "total_emd": sum(a.emd_amount for a in applications),
        "allotted": eligibility.allotted_count(applicant),
        "can_add": bool(AddQuartersForm(applicant=applicant).open_auctions)
                   and applicant.status != Applicant.Status.REJECTED,
    })


@login_required
def add(request):
    applicant = Applicant.for_user(request.user)
    if applicant is None:
        return redirect("applications:apply")
    if applicant.status == Applicant.Status.REJECTED:
        messages.error(request, "Your application was rejected, so quarters can't be added.")
        return redirect("applications:mine")
    if request.method == "POST":
        form = AddQuartersForm(request.POST, applicant=applicant)
        if form.is_valid():
            added = services.add_quarters(applicant, list(form.cleaned_data["quarters"].order_by("quarter_no")),
                                          request.user)
            if added:
                messages.success(request, f"{len(added)} quarter(s) added. A supplementary Intimation Slip "
                                          f"has been emailed to {request.user.email}.")
            return redirect("applications:mine")
    else:
        form = AddQuartersForm(applicant=applicant)
    return render(request, "applications/add.html", {"form": form, "applicant": applicant})
