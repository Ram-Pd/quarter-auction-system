from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    path("", views.apply, name="apply"),
    path("mine/", views.mine, name="mine"),
    path("add/", views.add, name="add"),
]
