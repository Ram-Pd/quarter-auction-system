"""
Top-level URL map. Each app keeps its own urls.py:
    /                -> home page
    /register/ ...   -> accounts/urls.py  (registration, activation, login, password reset)
    /auctions/ ...   -> auctions/urls.py  (lobby; bidding pages in Milestone 4)
    /admin/          -> Django admin
"""
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('', include('accounts.urls')),
    path('auctions/', include('auctions.urls')),
    path('admin/', admin.site.urls),
]
