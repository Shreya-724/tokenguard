"""WebSocket routes. In your asgi.py:

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from tokenguard.django.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
"""

from django.urls import path

from tokenguard.django.consumers import StatsConsumer

websocket_urlpatterns = [
    path("ws/tokenguard/stats/", StatsConsumer.as_asgi()),
]
