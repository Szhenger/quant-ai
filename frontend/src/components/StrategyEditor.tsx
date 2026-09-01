import { FormEvent, useState } from "react";
import api from "../api/client";
import { extractError } from "../api/errors";
import { useRotateWebhookSecret, useUpdateStrategy } from "../api/hooks";
import type { Strategy } from "../api/types";
import {
  DeliveryChecks,
  DeliveryFields,
  deliveryFromStrategy,
  toDeliveryPayload,
} from "./DeliverySettings";

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
  const [delivery, setDelivery] = useState(() => deliveryFromStrategy(strategy));
  const [aiEnabled, setAiEnabled] = useState(strategy.ai_enabled);
  const [aiPrompt, setAiPrompt] = useState(strategy.ai_prompt);

  const [showSecret, setShowSecret] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The strategies LIST omits the signing secret (it has no business in every
  // page load); it is fetched from the detail endpoint on demand, and rotate
  // returns the fresh value in its response body.
  const [secret, setSecret] = useState<string | null>(strategy.webhook_secret ?? null);

  const fetchSecret = async (): Promise<string> => {
    if (secret) return secret;
    const { data } = await api.get<Strategy>(`/strategies/${strategy.id}/`);
    const fresh = data.webhook_secret ?? "";
    setSecret(fresh);
    return fresh;
  };

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const wire = toDeliveryPayload(delivery);
    if (!wire.ok) {
      setError(wire.error);
      return;
    }
    const patch: Partial<Strategy> = {
      name: name.trim() || strategy.name,
      ai_enabled: aiEnabled,
      ai_prompt: aiPrompt,
      ...wire.payload,
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
      // Show the NEW secret from the rotate response itself — the cached list
      // row still holds the dead pre-rotation value until the refetch lands.
      onSuccess: (fresh) => {
        setSecret(fresh.webhook_secret ?? null);
        setShowSecret(true);
      },
      onError: (err) => setError(extractError(err)),
    });
  };

  const onToggleReveal = () => {
    if (showSecret) {
      setShowSecret(false);
      return;
    }
    fetchSecret()
      .then(() => setShowSecret(true))
      .catch((err) => setError(extractError(err)));
  };

  const copySecret = async () => {
    try {
      await navigator.clipboard.writeText(await fetchSecret());
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (permissions/insecure context): reveal instead.
      onToggleReveal();
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

        <DeliveryFields value={delivery} onChange={setDelivery} />
      </div>

      <DeliveryChecks value={delivery} onChange={setDelivery}>
        <label className="check">
          <input
            type="checkbox"
            checked={aiEnabled}
            onChange={(e) => setAiEnabled(e.target.checked)}
          />
          <span>AI confirmation</span>
        </label>
      </DeliveryChecks>

      {aiEnabled && (
        <label className="field">
          <span>AI prompt</span>
          <textarea value={aiPrompt} onChange={(e) => setAiPrompt(e.target.value)} rows={2} />
        </label>
      )}

      <div className="secret-row">
        <span className="muted small">Webhook signing secret</span>
        <code className="mono small">
          {showSecret && secret ? secret : "••••••••••••••••••••••••••••••••"}
        </code>
        <button type="button" className="btn small" onClick={onToggleReveal}>
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
