"""
ASGI entry point: serves normal HTTP pages AND WebSockets.

    http://...        -> Django as usual
    ws://.../ws/...   -> Channels consumers (auctions/routing.py)

AuthMiddlewareStack reads the normal Django session cookie, so
scope["user"] in a consumer is the logged-in user, like request.user in a view.
AllowedHostsOriginValidator rejects WebSocket connections opened by pages on
other websites (the WebSocket equivalent of CSRF protection).
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Must run before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from auctions.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
