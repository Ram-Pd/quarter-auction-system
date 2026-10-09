from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Applicant


def is_activated_applicant(user):
    return user.is_authenticated and Applicant.objects.filter(user=user, is_activated=True).exists()


def applicant_required(view_func):
    """
    Allow activated applicants (and staff, for monitoring/demo).
    Not logged in -> redirect to login. Logged in but not allowed -> 403.
    """
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.is_staff or is_activated_applicant(request.user):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapper
