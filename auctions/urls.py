from django.urls import path

from . import views

app_name = "auctions"

urlpatterns = [
    path("", views.listing, name="listing"),
    path("<int:auction_id>/", views.auction_room, name="auction_room"),
]
# The public home page ("/") is auctions.views.home, wired in config/urls.py.
# WebSocket URLs are in auctions/routing.py
