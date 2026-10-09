import logging

from django.db import transaction
from django.shortcuts import redirect, render

from .emails import send_registration_documents
from .forms import RegistrationForm
from .models import Applicant

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
