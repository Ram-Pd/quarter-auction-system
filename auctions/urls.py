from django.urls import path

from . import views

app_name = "auctions"

urlpatterns = [
    path("", views.lobby, name="lobby"),
    path("<int:auction_id>/", views.auction_room, name="auction_room"),
    path("<int:auction_id>/join/", views.join, name="join"),
]
# WebSocket URLs are in auctions/routing.py
