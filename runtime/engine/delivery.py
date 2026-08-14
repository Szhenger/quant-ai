"""Alert delivery across the channels the user opted into.

Each channel is delivered by its own Celery task, so a slow or failing webhook
neither blocks strategy evaluation nor the other channels. Transient failures
retry with exponential backoff; permanent ones (no email address, strategy
deleted) do not. Every attempt's outcome is recorded per-channel on
``Alert.delivery`` under a row lock, so concurrent channel tasks can't clobber
each other's results.
"""
import hashlib
import hmac
import json
import logging
import time

from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from rest_framework.renderers import JSONRenderer

from identity.validators import UnresolvableWebhookHostError, ensure_public_webhook_url
from .serializers import AlertSerializer

logger = logging.getLogger(__name__)


class TransientDeliveryError(Exception):
    """Raised AFTER a failed attempt was recorded, so Celery retries the channel."""


def _payload(alert) -> dict:
    """JSON-safe dict (UUIDs/datetimes rendered to strings)."""
    return json.loads(JSONRenderer().render(AlertSerializer(alert).data))


def deliver_alert(alert, strategy) -> None:
    """Fan the alert out to each enabled channel as its own retryable task.

    Called after the alert's transaction commits; returns immediately.
    """
    channels = []
    if strategy.notify_in_app:
        channels.append("in_app")
    if strategy.notify_email:
        channels.append("email")
    if strategy.webhook_url:
        channels.append("webhook")
    for channel in channels:
        deliver_alert_channel.delay(str(alert.id), channel)


@shared_task(
    bind=True,
    autoretry_for=(TransientDeliveryError,),
    max_retries=3,
    retry_backoff=30,  # 30s, 60s, 120s (jittered) between attempts
    retry_backoff_max=600,
    retry_jitter=True,
)
def deliver_alert_channel(self, alert_id: str, channel: str):
    from .models import Alert

    try:
        alert = Alert.objects.select_related("strategy", "workspace__owner").get(id=alert_id)
    except Alert.DoesNotExist:
        return {"ok": False, "detail": "alert no longer exists"}
    sender = _SENDERS.get(channel)
    if sender is None:
        return {"ok": False, "detail": f"unknown channel {channel!r}"}
    result = {**sender(alert), "attempts": self.request.retries + 1}
    _record(alert_id, channel, result)
    if not result["ok"] and not result.get("permanent"):
        raise TransientDeliveryError(f"{channel}: {result.get('detail', 'failed')}")
    return result


def _record(alert_id: str, channel: str, result: dict) -> None:
    """Merge one channel's outcome into ``Alert.delivery`` under a row lock."""
    from .models import Alert

    with transaction.atomic():
        try:
            alert = Alert.objects.select_for_update().get(id=alert_id)
        except Alert.DoesNotExist:
            return
        delivery = dict(alert.delivery or {})
        delivery[channel] = result
        alert.delivery = delivery
        alert.save(update_fields=["delivery"])


def _send_in_app(alert) -> dict:
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


def _send_email(alert) -> dict:
    try:
        # The workspace owner, not the strategy: still deliverable if the
        # strategy was deleted between firing and delivery.
        to = alert.workspace.owner.email
        if not to:
            return {"ok": False, "permanent": True,
                    "detail": "workspace owner has no email address"}
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


def _send_webhook(alert) -> dict:
    strategy = alert.strategy
    if strategy is None or not strategy.webhook_url:
        return {"ok": False, "permanent": True,
                "detail": "strategy deleted or webhook removed"}
    # Re-validate at delivery time: the URL was checked at save, but DNS may
    # have changed since (rebinding toward a private address). Redirects are
    # NOT followed below for the same reason — a public URL answering
    # 302 -> http://169.254.169.254/ must not be dereferenced from inside
    # our network.
    try:
        ensure_public_webhook_url(strategy.webhook_url)
    except UnresolvableWebhookHostError as exc:
        # A resolver blip is transient — retry with backoff, don't drop.
        return {"ok": False, "detail": str(exc)}
    except ValueError as exc:
        return {"ok": False, "permanent": True,
                "detail": f"unsafe webhook URL: {exc}"}
    try:
        import requests

        # Sign "<timestamp>.<body bytes>" so the receiver can verify with the
        # strategy's webhook_secret (exposed read-only in the API) AND reject
        # replayed deliveries by checking the timestamp's freshness.
        body = json.dumps(_payload(alert), separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json",
                   "X-QuantAI-Timestamp": timestamp}
        if strategy.webhook_secret:
            signature = hmac.new(strategy.webhook_secret.encode(),
                                 f"{timestamp}.".encode() + body,
                                 hashlib.sha256).hexdigest()
            headers["X-QuantAI-Signature"] = f"sha256={signature}"
        resp = requests.post(strategy.webhook_url, data=body, headers=headers,
                             timeout=5, allow_redirects=False)
        if resp.ok:
            return {"ok": True, "detail": f"HTTP {resp.status_code}"}
        # 3xx: redirects are deliberately not followed. 4xx (bar 408/429): the
        # receiver rejected the delivery — retrying the same request is futile.
        permanent = 300 <= resp.status_code < 500 and resp.status_code not in (408, 429)
        return {"ok": False, "permanent": permanent, "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook delivery failed: %s", exc)
        return {"ok": False, "detail": str(exc)}


_SENDERS = {"in_app": _send_in_app, "email": _send_email, "webhook": _send_webhook}
