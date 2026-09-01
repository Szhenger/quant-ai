/**
 * A WebSocket that stays up.
 *
 * The browser's WebSocket reports clean closes, but not half-open connections
 * (proxy died, laptop slept, network switched): the socket object still looks
 * open while delivering nothing. Alerts are the product here — a silently dead
 * socket is worse than an obviously closed one.
 *
 * This wrapper adds the three things the raw socket lacks:
 *  - reconnection with capped exponential backoff + full jitter (see backoff.ts)
 *  - an application-level heartbeat: ping every HEARTBEAT_MS, and if the pong
 *    doesn't arrive within PONG_TIMEOUT_MS, the connection is declared dead
 *    and torn down (which triggers the reconnect path)
 *  - a URL builder called at *each* connect, so every reconnect picks up the
 *    current access token and workspace instead of the ones from page load
 */
import { reconnectDelayMs } from "./backoff";

export type SocketStatus = "connecting" | "open" | "down";

export interface AlertSocketOptions {
  /** Called on every (re)connect. Return null to skip (not authenticated yet). */
  buildUrl: () => string | null;
  /**
   * Subprotocols to offer at each (re)connect. The access token rides here
   * (`quantai.token.<jwt>`) instead of in the URL, so it never lands in
   * proxy/load-balancer access logs or browser history.
   */
  buildProtocols?: () => string[] | undefined;
  onAlert: (alert: unknown) => void;
  /** Strategy lifecycle pushes (e.g. a circuit breaker tripping to FAILED). */
  onStrategyStatus?: (strategy: unknown) => void;
  /** Workspace state-change events (`{type: "event", event: "...", ...ids}`). */
  onEvent?: (event: { event: string; [key: string]: unknown }) => void;
  onStatus: (status: SocketStatus) => void;
  heartbeatMs?: number;
  pongTimeoutMs?: number;
  random?: () => number;
}

const HEARTBEAT_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;

export class ReconnectingAlertSocket {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private stopped = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongDeadline: ReturnType<typeof setTimeout> | null = null;

  constructor(private opts: AlertSocketOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.ws) {
      // Detach handlers first so the close doesn't schedule a reconnect.
      this.ws.onopen = this.ws.onclose = this.ws.onerror = this.ws.onmessage = null;
      this.ws.close();
      this.ws = null;
    }
  }

  private connect(): void {
    if (this.stopped) return;
    const url = this.opts.buildUrl();
    if (!url) {
      this.scheduleReconnect();
      return;
    }

    this.opts.onStatus("connecting");
    const ws = new WebSocket(url, this.opts.buildProtocols?.());
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.opts.onStatus("open");
      this.startHeartbeat();
    };

    ws.onmessage = (event) => {
      let data: { type?: string; alert?: unknown; strategy?: unknown; event?: unknown };
      try {
        data = JSON.parse(event.data as string) as typeof data;
      } catch {
        return; // malformed frame — ignore
      }
      if (data.type === "pong" && this.pongDeadline) {
        clearTimeout(this.pongDeadline);
        this.pongDeadline = null;
      } else if (data.type === "alert" && data.alert) {
        this.opts.onAlert(data.alert);
      } else if (data.type === "strategy_status" && data.strategy) {
        this.opts.onStrategyStatus?.(data.strategy);
      } else if (data.type === "event" && typeof data.event === "string") {
        this.opts.onEvent?.(data as { event: string; [key: string]: unknown });
      }
      // Unknown frame types are ignored — the server may grow new ones.
    };

    ws.onerror = () => {
      // onclose always follows; the reconnect logic lives there.
      ws.close();
    };

    ws.onclose = () => {
      this.stopHeartbeat();
      this.ws = null;
      if (!this.stopped) {
        this.opts.onStatus("down");
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer) return;
    const delay = reconnectDelayMs(this.attempt++, this.opts.random ?? Math.random);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      const ws = this.ws;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: "ping", t: Date.now() }));
      if (!this.pongDeadline) {
        this.pongDeadline = setTimeout(() => {
          this.pongDeadline = null;
          // No pong: the connection is half-open. Kill it; onclose reconnects.
          ws.close();
        }, this.opts.pongTimeoutMs ?? PONG_TIMEOUT_MS);
      }
    }, this.opts.heartbeatMs ?? HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.pongDeadline) {
      clearTimeout(this.pongDeadline);
      this.pongDeadline = null;
    }
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.stopHeartbeat();
  }
}
