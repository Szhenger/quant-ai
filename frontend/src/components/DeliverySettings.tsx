import type { ReactNode } from "react";
import type { Strategy, StrategyDelivery } from "../api/types";

/**
 * The delivery + scheduling knobs every strategy carries — poll interval,
 * cooldown, the two notification toggles and the webhook URL — as one piece of
 * form state, one validator, and two fragments of fields. The plain form, the
 * inline editor and the graph builder all render these; keeping them here means
 * a new channel or a changed bound lands in every builder at once.
 *
 * Numeric inputs are kept as strings so an emptied field stays empty on screen
 * instead of snapping to 0; `toDeliveryPayload` is where they become numbers.
 */
export interface DeliverySettings {
  pollInterval: string;
  cooldown: string;
  notifyInApp: boolean;
  notifyEmail: boolean;
  webhookUrl: string;
}

// Bars are daily, so a cooldown shorter than 1440 min can re-alert on the same bar.
export const DEFAULT_DELIVERY: DeliverySettings = {
  pollInterval: "15",
  cooldown: "1440",
  notifyInApp: true,
  notifyEmail: false,
  webhookUrl: "",
};

export function deliveryFromStrategy(s: Strategy): DeliverySettings {
  return {
    pollInterval: String(s.poll_interval_minutes),
    cooldown: String(s.cooldown_minutes),
    notifyInApp: s.notify_in_app,
    notifyEmail: s.notify_email,
    webhookUrl: s.webhook_url,
  };
}

/**
 * Validate and convert to the wire shape. Number("") is 0 — an emptied input
 * must not submit a hot-poll / zero-cooldown strategy (the server rejects it;
 * fail here with a clear message instead of a field-keyed 400).
 */
export function toDeliveryPayload(
  s: DeliverySettings,
): { ok: false; error: string } | { ok: true; payload: StrategyDelivery } {
  const poll = Number(s.pollInterval);
  const cool = Number(s.cooldown);
  if (!Number.isInteger(poll) || poll < 1 || !Number.isInteger(cool) || cool < 1) {
    return { ok: false, error: "Poll interval and cooldown must be whole minutes, at least 1." };
  }
  return {
    ok: true,
    payload: {
      poll_interval_minutes: poll,
      cooldown_minutes: cool,
      notify_in_app: s.notifyInApp,
      notify_email: s.notifyEmail,
      webhook_url: s.webhookUrl.trim(),
    },
  };
}

interface FieldsProps {
  value: DeliverySettings;
  onChange: (next: DeliverySettings) => void;
}

/** Poll / cooldown / webhook: three `.field` labels, meant to sit inside a `.form-grid`. */
export function DeliveryFields({ value, onChange }: FieldsProps) {
  const set = (patch: Partial<DeliverySettings>) => onChange({ ...value, ...patch });
  return (
    <>
      <label className="field">
        <span>Poll interval (min)</span>
        <input
          type="number"
          min={1}
          value={value.pollInterval}
          onChange={(e) => set({ pollInterval: e.target.value })}
        />
      </label>

      <label className="field">
        <span>Cooldown (min)</span>
        <input
          type="number"
          min={1}
          value={value.cooldown}
          onChange={(e) => set({ cooldown: e.target.value })}
        />
        <span className="muted small">
          Bars are daily — a cooldown shorter than 1440 min can re-alert on the same bar.
        </span>
      </label>

      <label className="field">
        <span>Webhook URL</span>
        <input
          value={value.webhookUrl}
          onChange={(e) => set({ webhookUrl: e.target.value })}
          placeholder="https://…"
        />
      </label>
    </>
  );
}

/** The notification toggles as a `.checks` row; `children` appends builder-specific checks. */
export function DeliveryChecks({ value, onChange, children }: FieldsProps & { children?: ReactNode }) {
  const set = (patch: Partial<DeliverySettings>) => onChange({ ...value, ...patch });
  return (
    <div className="checks">
      <label className="check">
        <input
          type="checkbox"
          checked={value.notifyInApp}
          onChange={(e) => set({ notifyInApp: e.target.checked })}
        />
        <span>Notify in-app</span>
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={value.notifyEmail}
          onChange={(e) => set({ notifyEmail: e.target.checked })}
        />
        <span>Notify email</span>
      </label>
      {children}
    </div>
  );
}
