"""Alert delivery across the three channels the user opted into."""
import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from rest_framework.renderers import JSONRenderer

from .serializers import AlertSerializer

logger = logging.getLogger(__name__)


def _payload(alert) -> dict:
    """JSON-safe dict (UUIDs/datetimes rendered to strings)."""
    return json.loads(JSONRenderer().render(AlertSerializer(alert).data))


def deliver_alert(alert, strategy) -> dict:
    results = {}
    if strategy.notify_in_app:
        results["in_app"] = _push_ws(alert)
    if strategy.notify_email:
        results["email"] = _send_email(alert, strategy)
    if strategy.webhook_url:
        results["webhook"] = _post_webhook(alert, strategy)
    alert.delivery = results
    alert.save(update_fields=["delivery"])
    return results


def _push_ws(alert) -> dict:
    try:
        layer = get_channel_layer()
        if layer is None:
            return {"ok": False, "detail": "no channel layer configured"}
        async_to_sync(layer.group_send)(
            f"ws_{alert.workspace_id}",
            {"type": "alert.message", "data": _payload(alert)},
        )
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS delivery failed: %s", exc)
        return {"ok": False, "detail": str(exc)}


def _send_email(alert, strategy) -> dict:
    try:
        to = strategy.workspace.owner.email
        if not to:
            return {"ok": False, "detail": "workspace owner has no email address"}
        send_mail(
            subject=f"[QuantAI] {alert.ticker} — {alert.indicator} alert",
            message=alert.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
        return {"ok": True, "detail": to}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Email delivery failed: %s", exc)
        return {"ok": False, "detail": str(exc)}


def _post_webhook(alert, strategy) -> dict:
    try:
        import requests

        resp = requests.post(strategy.webhook_url, json=_payload(alert), timeout=5)
        return {"ok": resp.ok, "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook delivery failed: %s", exc)
        return {"ok": False, "detail": str(exc)}
