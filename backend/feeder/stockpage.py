"""Stock-page compilation: the two measures behind a watched ticker.

A "stock page" is what QuantAI compiles for each company on the watchlist. It
has two measures, each produced in a **detailed** and a **summarised** form:

  * quantitative — the standard indicators (SMA, EMA, z-score, RSI, MACD, %
    change, volatility) over a macro window, reusing ``analyze_market`` and the
    fleet-wide bar cache. This is the macroscale measure recomputed every m
    hours.
  * qualitative  — this week's news headlines plus a plain-language summary
    written by Claude (``advisor.ClaudeClient.summarize_news``), refreshed every
    n hours.

Pure functions returning JSON-safe dicts: the ORM models and Celery tasks in
other apps persist and schedule them. Nothing here touches the database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from django.conf import settings

from .indicators import analyze_market
from .providers import get_provider

# Indicators surfaced in the quantitative *summary* (the detailed form keeps the
# full catalog). These are the ones a non-expert reads first.
_SUMMARY_INDICATORS = ("RSI", "Z_SCORE", "VOLATILITY", "PCT_CHANGE")


def _macro_days() -> int:
    return int(getattr(settings, "STOCKPAGE_MACRO_DAYS", 180))


def _news_window_days() -> int:
    return int(getattr(settings, "STOCKPAGE_NEWS_WINDOW_DAYS", 7))


def _news_limit() -> int:
    return int(getattr(settings, "STOCKPAGE_NEWS_LIMIT", 8))


# --------------------------------------------------------------------------- #
# Quantitative measure (macroscale)
# --------------------------------------------------------------------------- #
def _reading(indicator: str, value: Optional[float]) -> str:
    """A one-word plain-language reading of an indicator value for a non-expert."""
    if value is None:
        return "not enough history yet"
    if indicator == "RSI":
        if value < 30:
            return "oversold"
        if value > 70:
            return "overbought"
        return "neutral"
    if indicator == "Z_SCORE":
        if value <= -2:
            return "unusually cheap vs. its recent average"
        if value >= 2:
            return "unusually expensive vs. its recent average"
        return "near its recent average"
    if indicator == "VOLATILITY":
        if value >= 40:
            return "highly volatile"
        if value <= 15:
            return "calm"
        return "moderate volatility"
    if indicator == "PCT_CHANGE":
        if value > 0:
            return "up over the window"
        if value < 0:
            return "down over the window"
        return "flat"
    return ""


def _week_view(dates: List[str], closes: List[float]) -> dict:
    """The last week of price action, sliced from the macro series for display."""
    week = _news_window_days()
    wk_dates = dates[-week:] if dates else []
    wk_closes = closes[-week:] if closes else []
    change_pct = None
    if len(wk_closes) >= 2 and wk_closes[0]:
        change_pct = round((wk_closes[-1] - wk_closes[0]) / wk_closes[0] * 100, 2)
    return {
        "dates": wk_dates,
        "closes": wk_closes,
        "start": wk_dates[0] if wk_dates else None,
        "end": wk_dates[-1] if wk_dates else None,
        "change_pct": change_pct,
    }


def build_quantitative(ticker: str, days: Optional[int] = None) -> dict:
    """Compute the quantitative measure: full detail + a summarised form."""
    days = int(days or _macro_days())
    analysis = analyze_market(ticker, days=days)  # reuses the shared bar cache
    indicators = analysis.get("indicators", {}) or {}
    week = _week_view(analysis.get("dates", []), analysis.get("closes", []))

    measures = []
    for key in _SUMMARY_INDICATORS:
        cell = indicators.get(key)
        if not cell:
            continue
        measures.append({
            "key": key,
            "label": cell.get("label", key),
            "unit": cell.get("unit", ""),
            "value": cell.get("value"),
            "reading": _reading(key, cell.get("value")),
        })

    latest = analysis.get("latest_price")
    change = week.get("change_pct")
    if change is None:
        headline = f"{analysis['ticker']}: latest price {latest}."
    else:
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
        headline = f"{analysis['ticker']} is {direction} {abs(change)}% this week (latest {latest})."

    summary = {
        "latest_price": latest,
        "week_change_pct": change,
        "headline": headline,
        "measures": measures,
    }
    # The detailed form is the full analysis plus the week slice.
    detailed = {**analysis, "week": week}
    return {
        "detailed": detailed,
        "summary": summary,
        "synthetic": bool(analysis.get("synthetic")),
    }


# --------------------------------------------------------------------------- #
# Qualitative measure (this week's news + Claude summary)
# --------------------------------------------------------------------------- #
def _parse_published(value) -> Optional[datetime]:
    """Best-effort parse of a news item's published_at into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):  # yfinance epoch seconds
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        raw = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _within_week(items: List[dict], now: Optional[datetime] = None) -> List[dict]:
    """Keep this week's headlines. Items with no parseable date are kept (a
    missing timestamp shouldn't silently drop a real, recent headline)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=_news_window_days())
    kept = []
    for item in items:
        published = _parse_published(item.get("published_at"))
        if published is None or published >= cutoff:
            kept.append(item)
    return kept


def build_qualitative(ticker: str, now: Optional[datetime] = None) -> dict:
    """Compile the qualitative measure: this week's news + a Claude summary,
    in detailed (full list + summary) and summarised (headline) forms."""
    from advisor import ClaudeClient  # local import: advisor is a peer leaf lib

    provider = get_provider()
    raw = provider.news(ticker, limit=_news_limit()) or []
    news = _within_week(raw, now=now)
    synthetic = any(n.get("source") == "synthetic" for n in news)

    verdict = ClaudeClient().summarize_news(
        ticker=ticker.upper().strip(), news=news, data_is_synthetic=synthetic,
    )
    detailed = {
        "window_days": _news_window_days(),
        "news": news,
        "summary": verdict.text,
        "summary_source": verdict.source,
        "synthetic": synthetic,
    }
    summary = {
        "headline": verdict.text,
        "article_count": len(news),
        "summary_source": verdict.source,
    }
    return {"detailed": detailed, "summary": summary, "synthetic": synthetic}
