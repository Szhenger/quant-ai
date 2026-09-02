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

from .budget import reserve_call

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
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 user_id=None):
        self.api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        self.model = model or settings.ANTHROPIC_MODEL
        # The account every paid call is charged against (advisor.budget).
        # None = ungated; every production caller passes the workspace owner.
        self.user_id = user_id

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _within_budget(self) -> bool:
        """Reserve one call against the user's daily budget. Checked only on
        the paid path — a disabled client (no key, no SDK) spends nothing."""
        return reserve_call(self.user_id)

    # --- shared plumbing ----------------------------------------------------
    def _sdk(self):
        """The ``anthropic`` module, or None when the SDK is not installed."""
        try:
            import anthropic
        except ImportError:
            return None
        return anthropic

    def _client(self, anthropic):
        # Bounded timeout + one retry: the SDK's defaults (10 min, 2 retries)
        # could outlive the per-strategy eval lock and pin a worker slot.
        return anthropic.Anthropic(
            api_key=self.api_key,
            timeout=float(settings.ANTHROPIC_TIMEOUT_SECONDS),
            max_retries=1,
        )

    @staticmethod
    def _headlines(news: Optional[List[dict]]) -> str:
        return "\n".join(
            f"- {n.get('title', '')} [{n.get('source', '?')}]" for n in (news or [])
        )

    @staticmethod
    def _text_of(response) -> str:
        return "".join(
            b.text for b in response.content if getattr(b, "type", None) == "text"
        ).strip()

    # --- alert contextualisation ---------------------------------------------
    @staticmethod
    def _quant_only(reason: str) -> AlertVerdict:
        """The fail-open verdict: fire on the quantitative condition, say why."""
        return AlertVerdict(trigger=True, rationale=reason, confidence=0.5, ai_used=False)

    @staticmethod
    def _assess_prompt(*, ticker, condition_summary, metric_value, user_prompt,
                       news, data_is_synthetic):
        """(system, user) messages for the alert verdict."""
        headlines = ClaudeClient._headlines(news) or "(no recent news)"
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
        return system, user

    @staticmethod
    def _parse_verdict(response) -> AlertVerdict:
        if getattr(response, "stop_reason", None) == "refusal":
            return ClaudeClient._quant_only("AI declined to assess; fired on quant condition.")
        data = json.loads(ClaudeClient._text_of(response))
        # Structured outputs can't express numeric bounds, so the schema
        # cannot force confidence into [0, 1] — clamp before persisting.
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        return AlertVerdict(
            trigger=bool(data["trigger_alert"]),
            rationale=str(data.get("rationale", "")),
            confidence=confidence,
            ai_used=True,
        )

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

        Every failure mode fails OPEN: the quantitative alert still fires, and
        the rationale says why it was not contextualised.
        """
        if not self.enabled:
            return self._quant_only(
                "AI layer disabled (no ANTHROPIC_API_KEY). Alert fired on the "
                "quantitative condition only."
            )
        anthropic = self._sdk()
        if anthropic is None:
            logger.warning("anthropic SDK not installed; firing on quant condition only.")
            return self._quant_only("AI SDK unavailable; fired on quant condition only.")
        if not self._within_budget():
            logger.warning("AI daily budget exhausted for user %s; firing on quant condition only.",
                           self.user_id)
            return self._quant_only("AI daily budget exhausted; fired on quant condition only.")

        system, user = self._assess_prompt(
            ticker=ticker, condition_summary=condition_summary, metric_value=metric_value,
            user_prompt=user_prompt, news=news, data_is_synthetic=data_is_synthetic,
        )
        try:
            # max_tokens must cover adaptive thinking PLUS the JSON verdict on
            # Claude 5-family models (thinking is on by default and counts
            # toward the cap): 1024 risks a truncated verdict, which would
            # silently demote every alert to the no-AI fallback path.
            response = self._client(anthropic).messages.create(
                model=self.model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": _VERDICT_SCHEMA}},
            )
            return self._parse_verdict(response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claude assessment failed (%s); firing on quant condition only.", exc)
            return self._quant_only(f"AI assessment error; fired on quant condition. ({exc})")

    # --- stock-page news briefing --------------------------------------------
    @staticmethod
    def _news_prompt(*, ticker, items, data_is_synthetic):
        """(system, user) messages for the weekly briefing."""
        system = (
            "You are a financial news analyst briefing a non-expert (a busy "
            "medical student who follows the market). Summarise the week's "
            "headlines for one company into 2-4 plain-language sentences: the "
            "overall tone (positive / negative / mixed), the concrete drivers, "
            "and anything a casual investor should note. No jargon, no advice, "
            "no preamble — just the briefing."
        )
        if data_is_synthetic:
            system += (
                " IMPORTANT: these headlines are SYNTHETIC placeholder data, not "
                "real news. Say so plainly and keep it high-level."
            )
        user = f"Company ticker: {ticker}\n\nThis week's headlines:\n{ClaudeClient._headlines(items)}"
        return system, user

    def summarize_news(
        self,
        *,
        ticker: str,
        news: Optional[List[dict]] = None,
        data_is_synthetic: bool = False,
    ) -> "NewsSummary":
        """Summarise this week's headlines for a ticker into a short briefing.

        The qualitative half of a stock page. Degrades gracefully: with no API
        key (or the SDK missing / an API error) it returns a deterministic
        fallback that still lists how many headlines were found, so the page is
        useful without an LLM. Never raises.
        """
        items = list(news or [])
        if not items:
            return NewsSummary(
                text="No recent headlines were found for this company this week.",
                source="fallback",
            )
        fallback = NewsSummary(text=_fallback_news_text(items), source="fallback")
        if not self.enabled:
            return fallback
        anthropic = self._sdk()
        if anthropic is None:
            logger.warning("anthropic SDK not installed; using fallback news summary.")
            return fallback
        if not self._within_budget():
            logger.warning("AI daily budget exhausted for user %s; using fallback news summary.",
                           self.user_id)
            return fallback

        system, user = self._news_prompt(ticker=ticker, items=items,
                                         data_is_synthetic=data_is_synthetic)
        try:
            response = self._client(anthropic).messages.create(
                model=self.model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            if getattr(response, "stop_reason", None) == "refusal":
                return fallback
            text = self._text_of(response)
            return NewsSummary(text=text, source="claude") if text else fallback
        except Exception as exc:  # noqa: BLE001
            logger.warning("Claude news summary failed (%s); using fallback.", exc)
            return fallback


@dataclass
class NewsSummary:
    text: str
    source: str  # "claude" | "fallback"


def _fallback_news_text(items: List[dict]) -> str:
    n = len(items)
    lead = items[0].get("title", "").strip() if items else ""
    head = f"{n} recent headline{'s' if n != 1 else ''} found this week"
    if lead:
        return f"{head}; the latest: “{lead}”. (AI summary unavailable — full list below.)"
    return f"{head}. (AI summary unavailable — full list below.)"
