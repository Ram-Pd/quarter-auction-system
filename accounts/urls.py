from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from config.context_processors import reset_link_hours

from . import views
from .forms import EmailLoginForm

app_name = "accounts"

urlpatterns = [
    # Sign-up: details -> email code -> password (accounts/views.py)
    path("signup/", views.signup, name="signup"),
    path("signup/verify/", views.signup_verify, name="signup_verify"),
    path("signup/resend/", views.signup_resend, name="signup_resend"),
    path("signup/password/", views.signup_password, name="signup_password"),

    # Login with email + password; logout (POST only)
    path("login/", auth_views.LoginView.as_view(
        template_name="accounts/login.html",
        authentication_form=EmailLoginForm,
        redirect_authenticated_user=True,
    ), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # Password reset: Django's built-in, token-based flow
    path("password-reset/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/emails/password_reset_email.txt",
        subject_template_name="accounts/emails/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
        extra_email_context={"RESET_LINK_HOURS": reset_link_hours()},
    ), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html",
    ), name="password_reset_done"),
    path("password-reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="accounts/password_reset_confirm.html",
        success_url=reverse_lazy("accounts:password_reset_complete"),
    ), name="password_reset_confirm"),
    path("password-reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html",
    ), name="password_reset_complete"),
]
