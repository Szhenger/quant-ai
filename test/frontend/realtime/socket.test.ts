/**
 * ReconnectingAlertSocket against a scripted fake WebSocket: connect
 * arguments, frame dispatch, heartbeat + missed-pong teardown, backoff
 * reconnects, and a clean stop.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReconnectingAlertSocket, type SocketStatus } from "../../../frontend/src/realtime/socket";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  constructor(public url: string, public protocols?: string[]) {
    FakeWebSocket.instances.push(this);
  }
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  receive(frame: unknown) {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

function lastSocket() {
  return FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
}

describe("realtime/socket", () => {
  let statuses: SocketStatus[];
  let alerts: unknown[];
  let events: unknown[];
  let socket: ReconnectingAlertSocket;

  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    statuses = [];
    alerts = [];
    events = [];
    socket = new ReconnectingAlertSocket({
      buildUrl: () => "ws://test/ws/alerts/ws1/",
      buildProtocols: () => ["quantai.v1", "quantai.token.abc"],
      onAlert: (a) => alerts.push(a),
      onEvent: (e) => events.push(e),
      onStatus: (s) => statuses.push(s),
      heartbeatMs: 1000,
      pongTimeoutMs: 200,
      random: () => 0, // deterministic backoff: exp/2
    });
  });

  afterEach(() => {
    socket.stop();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("dials the built URL with the token in the subprotocol list, never the URL", () => {
    socket.start();
    const ws = lastSocket();
    expect(ws.url).toBe("ws://test/ws/alerts/ws1/");
    expect(ws.url).not.toContain("abc");
    expect(ws.protocols).toEqual(["quantai.v1", "quantai.token.abc"]);
    expect(statuses).toEqual(["connecting"]);
    ws.open();
    expect(statuses).toEqual(["connecting", "open"]);
  });

  it("dispatches alert and event frames by type and ignores the rest", () => {
    socket.start();
    const ws = lastSocket();
    ws.open();
    ws.receive({ type: "alert", alert: { id: "a1" } });
    ws.receive({ type: "event", event: "strategy.evaluated", strategy_id: "s1" });
    ws.receive({ type: "connected", workspace_id: "ws1" });
    ws.onmessage?.({ data: "not json" });
    expect(alerts).toEqual([{ id: "a1" }]);
    expect(events).toEqual([{ type: "event", event: "strategy.evaluated", strategy_id: "s1" }]);
  });

  it("pings on the heartbeat, and a missed pong tears the socket down and reconnects", () => {
    socket.start();
    const first = lastSocket();
    first.open();
    vi.advanceTimersByTime(1000);
    expect(first.sent).toHaveLength(1);
    expect(JSON.parse(first.sent[0])).toMatchObject({ type: "ping" });
    // No pong within 200ms: declared half-open.
    vi.advanceTimersByTime(200);
    expect(statuses).toEqual(["connecting", "open", "down"]);
    // Backoff: attempt 0 with random()=0 -> 500ms, then a fresh socket.
    vi.advanceTimersByTime(499);
    expect(FakeWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(statuses.at(-1)).toBe("connecting");
  });

  it("a pong in time keeps the connection alive", () => {
    socket.start();
    const ws = lastSocket();
    ws.open();
    vi.advanceTimersByTime(1000);
    ws.receive({ type: "pong", t: 1 });
    vi.advanceTimersByTime(300);
    expect(statuses).toEqual(["connecting", "open"]);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("backs off exponentially across consecutive failures", () => {
    socket.start();
    lastSocket().close(); // attempt 0 -> 500ms
    vi.advanceTimersByTime(500);
    expect(FakeWebSocket.instances).toHaveLength(2);
    lastSocket().close(); // attempt 1 -> 1000ms
    vi.advanceTimersByTime(999);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);
  });

  it("stop() closes without reconnecting", () => {
    socket.start();
    const ws = lastSocket();
    ws.open();
    socket.stop();
    expect(ws.readyState).toBe(3);
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses).toEqual(["connecting", "open"]); // no "down" after a deliberate stop
  });
});
