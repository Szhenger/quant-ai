"""Workspace event bus: server-side state changes pushed to the browser.

The console used to learn about background work by polling — the strategies
list every 30s, a compiling stock page every 2.5s, a timer after a queued
evaluation. This is the subscription side of that story: whoever changes a
workspace's state publishes one small event to the workspace's WebSocket
group, and the client invalidates the matching cache entry. Payloads carry
identifiers, not data — the client refetches through the same authenticated
REST path it always used, so an event can never leak more than "something
about X changed".

Alerts keep their dedicated ``alert.message`` frame (they carry the full row
because they *are* the product); everything else rides here.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

# Event vocabulary. The client switches on these strings (realtime/useAlertsSocket.ts).
STOCKPAGE_UPDATED = "stockpage.updated"      # {watch_id, ticker, measure}
STRATEGY_EVALUATED = "strategy.evaluated"    # {strategy_id, status, value?}


def workspace_group(workspace_id) -> str:
    """The channel-layer group every socket for this workspace joins."""
    return f"ws_{workspace_id}"


def publish(workspace_id, event: str, **data) -> bool:
    """Best-effort: a missing or failing channel layer must never break the
    task that did the real work. Returns whether the send was attempted."""
    layer = get_channel_layer()
    if layer is None:
        return False
    try:
        async_to_sync(layer.group_send)(
            workspace_group(workspace_id),
            {"type": "workspace.event", "data": {"event": event, **data}},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Event %s for workspace %s not published: %s", event, workspace_id, exc)
        return False
