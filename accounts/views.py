import logging

from django.contrib import messages
from django.contrib.auth import login
from django.db import transaction
from django.shortcuts import redirect, render

from .emails import send_registration_documents
from .forms import ActivationForm, RegistrationForm
from .models import Applicant
from .services import ActivationError, activate_applicant

logger = logging.getLogger(__name__)


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                applicant = form.save()  # URN + application number generated here

            # Sent AFTER the applicant is safely saved: a mail failure must not
            # lose the registration. The admin can resend from the admin screen.
            try:
                send_registration_documents(applicant)
                email_ok = True
            except Exception:
                logger.exception("Registration email failed for %s", applicant.application_no)
                email_ok = False

            # Post/Redirect/Get: refreshing the success page can't re-submit the form.
            request.session["registered_application_no"] = applicant.application_no
            request.session["registration_email_ok"] = email_ok
            return redirect("accounts:register_done")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def register_done(request):
    application_no = request.session.get("registered_application_no")
    if not application_no:
        return redirect("accounts:register")
    applicant = Applicant.objects.filter(application_no=application_no).first()
    return render(request, "accounts/register_done.html", {
        "application_no": application_no,
        "email": applicant.email if applicant else "",
        "email_ok": request.session.get("registration_email_ok", False),
    })


def activate(request):
    if request.user.is_authenticated:
        return redirect("auctions:lobby")
    if request.method == "POST":
        form = ActivationForm(request.POST, request=request)
        if form.is_valid():
            try:
                user = activate_applicant(form.applicant, form.cleaned_data["password1"])
            except ActivationError as error:  # e.g. activated in another tab a moment ago
                form.add_error(None, str(error))
            else:
                login(request, user)
                messages.success(request, f"Your account is activated. Your username is your URN ({user.username}).")
                return redirect("auctions:lobby")
    else:
        form = ActivationForm(request=request)
    return render(request, "accounts/activate.html", {"form": form})
