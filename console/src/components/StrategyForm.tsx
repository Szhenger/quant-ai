import { FormEvent, useEffect, useState } from "react";
import api from "../api/client";
import { extractError } from "../api/errors";
import { useIndicatorCatalog } from "../api/hooks";

interface StrategyFormProps {
  onCreated: () => void;
}

export default function StrategyForm({ onCreated }: StrategyFormProps) {
  // Shared React Query catalog (staleTime: Infinity): one fetch per session,
  // deduped with any other mounted consumer (e.g. the graph builder), and
  // properly aborted if this form unmounts mid-flight.
  const catalogQuery = useIndicatorCatalog();
  const catalog = catalogQuery.data ?? null;

  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("AAPL");
  const [indicator, setIndicator] = useState("");
  // Editable indicator parameters (e.g. window/period), seeded from the
  // catalog defaults whenever the indicator changes.
  const [params, setParams] = useState<Record<string, string>>({});
  const [operator, setOperator] = useState("");
  const [threshold, setThreshold] = useState("30");
  const [aiEnabled, setAiEnabled] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [notifyInApp, setNotifyInApp] = useState(true);
  const [notifyEmail, setNotifyEmail] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [pollInterval, setPollInterval] = useState("15");
  const [cooldown, setCooldown] = useState("60");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed the initial indicator/operator once the catalog arrives.
  useEffect(() => {
    if (!catalog) return;
    setIndicator((prev) => prev || catalog.indicators[0]?.key || "");
    setOperator((prev) => prev || catalog.operators[0]?.key || "");
  }, [catalog]);

  const selectedIndicator = catalog?.indicators.find((i) => i.key === indicator);

  const pickIndicator = (key: string) => {
    setIndicator(key);
    const defaults = catalog?.indicators.find((i) => i.key === key)?.defaults ?? {};
    setParams(
      Object.fromEntries(Object.entries(defaults).map(([k, v]) => [k, String(v)])),
    );
  };

  // Seed params once the catalog (and the initial indicator) arrive.
  useEffect(() => {
    if (!selectedIndicator) return;
    setParams((prev) =>
      Object.keys(prev).length > 0
        ? prev
        : Object.fromEntries(
            Object.entries(selectedIndicator.defaults).map(([k, v]) => [k, String(v)]),
          ),
    );
  }, [selectedIndicator]);

  const submittedParams = (): Record<string, number> =>
    Object.fromEntries(
      Object.entries(params)
        .filter(([, v]) => v.trim() !== "")
        .map(([k, v]) => [k, Number(v)]),
    );

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await api.post("/strategies/", {
        name: name.trim() || `${ticker} ${indicator}`,
        ticker: ticker.trim().toUpperCase(),
        indicator,
        params: submittedParams(),
        operator,
        threshold: Number(threshold),
        ai_enabled: aiEnabled,
        ai_prompt: aiPrompt,
        notify_in_app: notifyInApp,
        notify_email: notifyEmail,
        webhook_url: webhookUrl.trim(),
        poll_interval_minutes: Number(pollInterval),
        cooldown_minutes: Number(cooldown),
      });
      // Reset the volatile fields; keep sensible defaults.
      setName("");
      setAiPrompt("");
      onCreated();
    } catch (err) {
      setError(extractError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (catalogQuery.isError) {
    return (
      <div className="alert error">
        Could not load indicators: {extractError(catalogQuery.error)}
      </div>
    );
  }
  if (!catalog) {
    return <p className="muted">Loading indicators…</p>;
  }

  return (
    <form className="strategy-form" onSubmit={onSubmit}>
      <div className="form-grid">
        <label className="field">
          <span>Name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Oversold RSI alert"
          />
        </label>

        <label className="field">
          <span>Ticker</span>
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            required
          />
        </label>

        <label className="field">
          <span>Indicator</span>
          <select value={indicator} onChange={(e) => pickIndicator(e.target.value)}>
            {catalog.indicators.map((i) => (
              <option key={i.key} value={i.key}>
                {i.label}
              </option>
            ))}
          </select>
        </label>

        {Object.keys(selectedIndicator?.defaults ?? {}).map((key) => (
          <label className="field" key={`${indicator}-${key}`}>
            <span>
              {key} <span className="muted small">(param)</span>
            </span>
            <input
              type="number"
              min={1}
              value={params[key] ?? ""}
              onChange={(e) => setParams((p) => ({ ...p, [key]: e.target.value }))}
            />
          </label>
        ))}

        <label className="field">
          <span>Operator</span>
          <select value={operator} onChange={(e) => setOperator(e.target.value)}>
            {catalog.operators.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label} ({o.key})
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>Threshold</span>
          <input
            type="number"
            step="any"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            required
          />
        </label>

        <label className="field">
          <span>Poll interval (min)</span>
          <input
            type="number"
            min={1}
            value={pollInterval}
            onChange={(e) => setPollInterval(e.target.value)}
          />
        </label>

        <label className="field">
          <span>Cooldown (min)</span>
          <input
            type="number"
            min={1}
            value={cooldown}
            onChange={(e) => setCooldown(e.target.value)}
          />
        </label>

        <label className="field">
          <span>Webhook URL</span>
          <input
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            placeholder="https://…"
          />
        </label>
      </div>

      {selectedIndicator?.help && <p className="muted small">{selectedIndicator.help}</p>}

      <div className="checks">
        <label className="check">
          <input
            type="checkbox"
            checked={notifyInApp}
            onChange={(e) => setNotifyInApp(e.target.checked)}
          />
          <span>Notify in-app</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={notifyEmail}
            onChange={(e) => setNotifyEmail(e.target.checked)}
          />
          <span>Notify email</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={aiEnabled}
            onChange={(e) => setAiEnabled(e.target.checked)}
          />
          <span>Enable AI confirmation</span>
        </label>
      </div>

      {aiEnabled && (
        <label className="field">
          <span>AI prompt</span>
          <textarea
            value={aiPrompt}
            onChange={(e) => setAiPrompt(e.target.value)}
            rows={3}
            placeholder="Only alert if this looks like a genuine trend reversal."
          />
        </label>
      )}

      {error && <div className="alert error">{error}</div>}

      <button className="btn primary" type="submit" disabled={submitting}>
        {submitting ? "Creating…" : "Create strategy"}
      </button>
    </form>
  );
}
