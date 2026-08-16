"""AI contextualisation layer.

When a strategy's quantitative condition fires, ``ClaudeClient.assess`` asks
Claude whether — given recent market news and the user's own prompt — the
trigger looks like a real signal worth alerting on, or noise to suppress.

Degrades gracefully: with no ``ANTHROPIC_API_KEY`` configured (or the SDK
missing), it fires on the quantitative condition alone and says so in the
rationale, so the pipeline still works end-to-end without an LLM.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# JSON schema Claude must return (structured outputs).
_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "trigger_alert": {"type": "boolean"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["trigger_alert", "rationale", "confidence"],
    "additionalProperties": False,
}


@dataclass
class AlertVerdict:
    trigger: bool
    rationale: str
    confidence: float
    ai_used: bool


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key if api_key is not None else getattr(settings, "ANTHROPIC_API_KEY", "")
        self.model = model or getattr(settings, "ANTHROPIC_MODEL", "claude-opus-5")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def assess(
        self,
        *,
        ticker: str,
        condition_summary: str,
        metric_value: Optional[float],
        user_prompt: str,
        news: Optional[List[dict]] = None,
        data_is_synthetic: bool = False,
    ) -> AlertVerdict:
        """Decide whether a triggered quant condition warrants alerting the user.

        ``condition_summary`` is a human-readable description of the (possibly
        composite) condition that fired, e.g. ``(RSI < 30 AND PRICE crosses above SMA)``.

        ``data_is_synthetic`` is passed through to the model so it is never asked to
        reason about fabricated prices/headlines as if they were real market data.
        """
        if not self.enabled:
            return AlertVerdict(
                trigger=True,
                rationale=(
                    "AI layer disabled (no ANTHROPIC_API_KEY). Alert fired on the "
                    "quantitative condition only."
                ),
                confidence=0.5,
                ai_used=False,
            )

        try:
            import anthropic
        except ImportError:
            logger.warning("anthropic SDK not installed; firing on quant condition only.")
            return AlertVerdict(True, "AI SDK unavailable; fired on quant condition only.", 0.5, False)

        headlines = "\n".join(
            f"- {n.get('title', '')} [{n.get('source', '?')}]" for n in (news or [])
        ) or "(no recent news)"
        directive = (user_prompt or "").strip() or (
            "Assess whether this move reflects a real, actionable signal rather than noise."
        )
        system = (
            "You are a quantitative research assistant. A user's market-monitoring "
            "strategy just fired on a numeric condition. Judge whether the trigger is a "
            "real, actionable signal given the market context, or likely noise. Be "
            "conservative: only set trigger_alert to true when the evidence supports it. "
            "Respond strictly via the provided schema."
        )
        if data_is_synthetic:
            system += (
                " IMPORTANT: the prices and headlines below are SYNTHETIC placeholder "
                "data (a deterministic random walk generated offline), not real market "
                "data. Do not treat them as genuine market information; say so in your "
                "rationale and keep confidence low."
            )
        value_str = f"{metric_value:.4f}" if metric_value is not None else "n/a"
        data_note = "\n(NOTE: data below is SYNTHETIC, not real market data.)\n" if data_is_synthetic else ""
        user = (
            f"Asset: {ticker}{data_note}\n"
            f"Condition met: {condition_summary} (representative value {value_str})\n\n"
            f"User's directive:\n{directive}\n\n"
            f"Recent headlines:\n{headlines}\n\n"
            "Should we alert the user?"
        )

        try:
            # Bounded timeout + one retry: the SDK's defaults (10 min, 2 retries)
            # could outlive the per-strategy eval lock and pin a worker slot.
            client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=float(getattr(settings, "ANTHROPIC_TIMEOUT_SECONDS", 30.0)),
                max_retries=1,
            )
            # max_tokens must cover adaptive thinking PLUS the JSON verdict on
            # Claude 5-family models (thinking is on by default and counts
            # toward the cap): 1024 risks a truncated verdict, which would
            # silently demote every alert to the no-AI fallback path.
            response = client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": _VERDICT_SCHEMA}},
            )
            if getattr(response, "stop_reason", None) == "refusal":
                return AlertVerdict(True, "AI declined to assess; fired on quant condition.", 0.5, False)
            text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
            data = json.loads(text)
            # Structured outputs can't express numeric bounds, so the schema
            # cannot force confidence into [0, 1] — clamp before persisting.
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
            return AlertVerdict(
                trigger=bool(data["trigger_alert"]),
                rationale=str(data.get("rationale", "")),
                confidence=confidence,
                ai_used=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claude assessment failed (%s); firing on quant condition only.", exc)
            return AlertVerdict(True, f"AI assessment error; fired on quant condition. ({exc})", 0.5, False)
