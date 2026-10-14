from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm

from .models import EmailOTP, User


class UserCreationForm(AdminUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "full_name", "phone")


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Django's user admin, adjusted for email login (there is no username).
    Staff roles: put a staff user in the "Verification Officer" or
    "Auction Admin" group (see applications/roles.py).
    """

    form = UserEditForm
    add_form = UserCreationForm
    ordering = ("email",)
    list_display = ("email", "full_name", "is_staff", "is_active", "last_login", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "full_name")
    readonly_fields = ("email_verified_at", "last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "phone", "email_verified_at")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",),
                "fields": ("email", "full_name", "phone", "usable_password", "password1", "password2")}),
    )


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    """Read-only, for support. Shows only that a code was sent, never the code."""

    list_display = ("email", "purpose", "created_at", "expires_at", "failed_attempts", "used_at")
    list_filter = ("purpose",)
    search_fields = ("email",)
    exclude = ("code_hash",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
