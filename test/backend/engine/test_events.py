"""The workspace event bus: background work publishes a small "X changed"
frame to the workspace's socket group so the console refetches instead of
polling. Payloads carry identifiers only."""
from unittest.mock import patch

import pytest

from engine import events
from engine.models import Strategy
from engine.tasks import compile_stock_qualitative, compile_stock_quantitative, evaluate_strategy
from identity.models import WatchedTicker

pytestmark = pytest.mark.django_db


def test_publish_sends_a_workspace_event_to_the_workspace_group(workspace):
    sent = []

    class Layer:
        async def group_send(self, group, message):
            sent.append((group, message))

    with patch("engine.events.get_channel_layer", return_value=Layer()):
        assert events.publish(workspace.id, "thing.changed", thing_id="42") is True
    assert sent == [(
        f"ws_{workspace.id}",
        {"type": "workspace.event", "data": {"event": "thing.changed", "thing_id": "42"}},
    )]


def test_publish_is_best_effort_without_a_channel_layer(workspace):
    with patch("engine.events.get_channel_layer", return_value=None):
        assert events.publish(workspace.id, "thing.changed") is False


def test_stock_page_compiles_publish_one_event_per_measure(workspace):
    wt = WatchedTicker.objects.create(workspace=workspace, ticker="AAPL")
    with patch("engine.tasks.publish") as publish:
        compile_stock_quantitative(str(wt.id))
        compile_stock_qualitative(str(wt.id))
    calls = [c.args + tuple(sorted(c.kwargs.items())) for c in publish.call_args_list]
    assert calls == [
        (workspace.id, events.STOCKPAGE_UPDATED,
         ("measure", "quantitative"), ("ticker", "AAPL"), ("watch_id", str(wt.id))),
        (workspace.id, events.STOCKPAGE_UPDATED,
         ("measure", "qualitative"), ("ticker", "AAPL"), ("watch_id", str(wt.id))),
    ]


def test_every_evaluation_outcome_publishes_strategy_evaluated(workspace):
    s = Strategy.objects.create(
        workspace=workspace, name="t", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=1e12, ai_enabled=False,
    )
    with patch("engine.tasks.publish") as publish:
        result = evaluate_strategy(str(s.id))
    assert result["status"] == "quant_not_met"
    publish.assert_called_once_with(
        workspace.id, events.STRATEGY_EVALUATED,
        strategy_id=str(s.id), status="quant_not_met", value=result["value"],
    )


def test_a_deleted_strategy_publishes_nothing(workspace):
    s = Strategy.objects.create(
        workspace=workspace, name="t", ticker="AAPL",
        indicator="PRICE", operator=">", threshold=0.0, ai_enabled=False,
    )
    sid = str(s.id)
    s.delete()
    with patch("engine.tasks.publish") as publish:
        assert evaluate_strategy(sid) == {"status": "not_found"}
    publish.assert_not_called()
