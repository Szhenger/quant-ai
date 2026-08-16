import { FormEvent, useState } from "react";
import { extractError } from "../api/errors";
import { useRotateWebhookSecret, useUpdateStrategy } from "../api/hooks";
import type { Strategy } from "../api/types";

interface StrategyEditorProps {
  strategy: Strategy;
  onClose: () => void;
}

/**
 * Inline editor for an existing strategy. Everything the backend allows to
 * change is editable here; the condition itself stays fixed for composite
 * strategies (rebuild via the graph builder for a new condition), while
 * simple strategies can adjust their threshold.
 */
export default function StrategyEditor({ strategy, onClose }: StrategyEditorProps) {
  const update = useUpdateStrategy();
  const rotate = useRotateWebhookSecret();

  const isComposite = strategy.condition != null;

  const [name, setName] = useState(strategy.name);
  const [threshold, setThreshold] = useState(String(strategy.threshold));
  const [pollInterval, setPollInterval] = useState(String(strategy.poll_interval_minutes));
  const [cooldown, setCooldown] = useState(String(strategy.cooldown_minutes));
  const [webhookUrl, setWebhookUrl] = useState(strategy.webhook_url);
  const [notifyInApp, setNotifyInApp] = useState(strategy.notify_in_app);
  const [notifyEmail, setNotifyEmail] = useState(strategy.notify_email);
  const [aiEnabled, setAiEnabled] = useState(strategy.ai_enabled);
  const [aiPrompt, setAiPrompt] = useState(strategy.ai_prompt);

  const [showSecret, setShowSecret] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const patch: Partial<Strategy> = {
      name: name.trim() || strategy.name,
      poll_interval_minutes: Number(pollInterval),
      cooldown_minutes: Number(cooldown),
      webhook_url: webhookUrl.trim(),
      notify_in_app: notifyInApp,
      notify_email: notifyEmail,
      ai_enabled: aiEnabled,
      ai_prompt: aiPrompt,
    };
    if (!isComposite) {
      patch.threshold = Number(threshold);
    }
    update.mutate(
      { id: strategy.id, patch },
      { onSuccess: onClose, onError: (err) => setError(extractError(err)) },
    );
  };

  const onRotate = () => {
    setError(null);
    rotate.mutate(strategy.id, {
      onSuccess: () => setShowSecret(true),
      onError: (err) => setError(extractError(err)),
    });
  };

  const copySecret = async () => {
    try {
      await navigator.clipboard.writeText(strategy.webhook_secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (permissions/insecure context): reveal instead.
      setShowSecret(true);
    }
  };

  return (
    <form className="strategy-form" onSubmit={onSave}>
      <div className="form-grid">
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>

        {isComposite ? (
          <label className="field">
            <span>Condition</span>
            <input value="Composite (rebuild via graph builder to change)" disabled />
          </label>
        ) : (
          <label className="field">
            <span>
              Threshold ({strategy.indicator} {strategy.operator})
            </span>
            <input
              type="number"
              step="any"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              required
            />
          </label>
        )}

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
          <span>AI confirmation</span>
        </label>
      </div>

      {aiEnabled && (
        <label className="field">
          <span>AI prompt</span>
          <textarea value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} rows={2} />
        </label>
      )}

      <div className="secret-row">
        <span className="muted small">Webhook signing secret</span>
        <code className="mono small">
          {showSecret ? strategy.webhook_secret : "••••••••••••••••••••••••••••••••"}
        </code>
        <button type="button" className="btn small" onClick={() => setShowSecret((s) => !s)}>
          {showSecret ? "Hide" : "Reveal"}
        </button>
        <button type="button" className="btn small" onClick={() => void copySecret()}>
          {copied ? "Copied ✓" : "Copy"}
        </button>
        <button
          type="button"
          className="btn small danger"
          onClick={onRotate}
          disabled={rotate.isPending}
          title="Generate a new secret. Deliveries sign with the new secret immediately — update your receiver in the same step."
        >
          {rotate.isPending ? "Rotating…" : "Rotate"}
        </button>
      </div>
      <p className="muted small">
        Deliveries carry <code>X-QuantAI-Signature: sha256=HMAC(secret,
        &quot;&lt;timestamp&gt;.&lt;body&gt;&quot;)</code> and{" "}
        <code>X-QuantAI-Timestamp</code> — verify both and reject stale timestamps.
      </p>

      {error && <div className="alert error">{error}</div>}

      <div className="row gap">
        <button className="btn primary" type="submit" disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </button>
        <button className="btn ghost" type="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}
