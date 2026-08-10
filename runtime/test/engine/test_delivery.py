"""Per-channel delivery tasks: fan-out, outcome recording, retry semantics."""
from unittest.mock import patch

import pytest
from django.core import mail

from engine.delivery import TransientDeliveryError, _record, _send_webhook
from engine.models import Strategy, Alert
from engine.tasks import evaluate_strategy

pytestmark = pytest.mark.django_db


def _strategy(workspace, **kwargs):
    defaults = dict(
        workspace=workspace, name="d", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0,
        ai_enabled=False, notify_in_app=True,
    )
    defaults.update(kwargs)
    return Strategy.objects.create(**defaults)


def test_only_enabled_channels_are_delivered(workspace):
    s = _strategy(workspace, notify_in_app=True, notify_email=False)
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    assert set(alert.delivery) == {"in_app"}
    assert alert.delivery["in_app"]["ok"] is True
    assert alert.delivery["in_app"]["attempts"] == 1


def test_email_channel_delivers_to_workspace_owner(workspace):
    s = _strategy(workspace, notify_email=True)
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    assert alert.delivery["email"]["ok"] is True
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["trader@example.com"]


def test_failed_webhook_outcome_is_recorded(workspace):
    s = _strategy(workspace, webhook_url="https://example.com/hook",
                  notify_in_app=False)
    with patch("requests.post", side_effect=RuntimeError("connection refused")):
        evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    assert alert.delivery["webhook"]["ok"] is False
    assert "connection refused" in alert.delivery["webhook"]["detail"]


def test_webhook_for_deleted_strategy_is_permanent_failure(workspace):
    s = _strategy(workspace, webhook_url="https://example.com/hook")
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    alert.strategy = None
    alert.save(update_fields=["strategy"])
    result = _send_webhook(alert)
    assert result["ok"] is False
    assert result["permanent"] is True


def test_webhook_payload_is_hmac_signed(workspace):
    import hashlib
    import hmac as hmac_mod

    s = _strategy(workspace, webhook_url="https://example.com/hook",
                  notify_in_app=False)
    captured = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured.update(url=url, data=data, headers=headers)

        class _Resp:
            ok = True
            status_code = 200

        return _Resp()

    with patch("requests.post", side_effect=fake_post):
        evaluate_strategy(str(s.id))

    alert = Alert.objects.get()
    assert alert.delivery["webhook"]["ok"] is True
    expected = "sha256=" + hmac_mod.new(
        s.webhook_secret.encode(), captured["data"], hashlib.sha256
    ).hexdigest()
    assert captured["headers"]["X-QuantAI-Signature"] == expected
    assert captured["headers"]["Content-Type"] == "application/json"


def test_record_merges_channels_instead_of_replacing(workspace):
    s = _strategy(workspace)
    evaluate_strategy(str(s.id))
    alert = Alert.objects.get()
    _record(str(alert.id), "webhook", {"ok": False, "detail": "HTTP 500"})
    alert.refresh_from_db()
    # The earlier in_app outcome survives the webhook write.
    assert set(alert.delivery) == {"in_app", "webhook"}


def test_webhook_secrets_are_unique_per_strategy(workspace):
    # Each strategy must get its own HMAC key — a shared secret would let one
    # receiver forge deliveries for another strategy.
    a = _strategy(workspace, name="a")
    b = _strategy(workspace, name="b")
    assert a.webhook_secret and b.webhook_secret
    assert a.webhook_secret != b.webhook_secret


def test_transient_failure_error_names_the_channel():
    err = TransientDeliveryError("webhook: HTTP 502")
    assert "webhook" in str(err)
