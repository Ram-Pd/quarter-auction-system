"""
Top-level URL map. Each app keeps its own urls.py:
    /                    -> public home page (quarters, rules, FAQ): auctions/views.py
    /signup/, /login/... -> accounts/urls.py      (sign-up with email OTP, login, password reset)
    /apply/ ...          -> applications/urls.py  (register for bidding)
    /auctions/ ...       -> auctions/urls.py      (quarter listing, auction pages)
    /admin/              -> Django admin (staff; includes the verification screen)
"""
from django.contrib import admin
from django.urls import include, path

from auctions.views import home

urlpatterns = [
    path('', home, name='home'),
    path('', include('accounts.urls')),
    path('apply/', include('applications.urls')),
    path('auctions/', include('auctions.urls')),
    path('admin/', admin.site.urls),
]
