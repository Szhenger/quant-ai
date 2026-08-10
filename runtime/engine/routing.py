from django.urls import re_path

from .consumers import AlertConsumer

websocket_urlpatterns = [
    re_path(r"^ws/alerts/(?P<workspace_id>[0-9a-fA-F-]+)/$", AlertConsumer.as_asgi()),
]
