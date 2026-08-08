# Chapter 5 — Momentum: RSI & MACD

> **The question.** A stock has run up for two weeks. Everyone's excited. Is the rally **running out of steam** — about to roll over — or is it **just getting started**? "Momentum" is the word traders use for that feeling, and this chapter turns the feeling into two numbers you can actually compute.

---

## 5.1 Momentum is mean reversion's mirror

Back in [Chapter 3](03-zscore-and-mean-reversion.md) we built the z-score around a hunch: prices that stray far from their average tend to **snap back**. That's *mean reversion* — the belief that a stretched rubber band pulls in. It's a real effect, sometimes.

But the opposite is also real, sometimes. **Momentum** is the tendency of recent *direction to persist* — up begets up, down begets down. A crowd that has been buying keeps buying; a trend feeds on itself. Where mean reversion bets *against* the recent move, momentum bets *with* it.

They cannot both dominate the same market at the same time — and that tension is not a bug, it's the seed of [Chapter 7](07-signal-vs-noise.md)'s central doubt. For now, hold this:

> **Short: two lenses, one market.** The z-score is a **mean-reversion lens** — big value ⇒ "too far, expect a snap back." RSI and MACD are **momentum lenses** — they ask "is the recent push strong and still building?" A given market is usually described *well* by one lens and *badly* by the other. Knowing which you're holding is half of not fooling yourself.

There are two classic ways to measure momentum. We'll build both.

## 5.2 RSI: scoring the tug-of-war between buyers and sellers

The **Relative Strength Index** (RSI, invented by J. Welles Wilder) starts from the simplest possible view of momentum: over the last while, how much of the daily movement was **up** versus **down**? If almost every recent move is an up-move, buyers are winning the tug-of-war and momentum is strong; if the ups and downs roughly balance, momentum is neutral.

**Step 1 — split each day into a gain or a loss.** Take the daily change `Δ_t = p_t − p_{t−1}`. Turn it into two non-negative numbers:

```
gain_t  =  Δ_t   if Δ_t > 0,  else 0
loss_t  = −Δ_t   if Δ_t < 0,  else 0     (a positive magnitude)
```

Each day contributes to exactly one bucket. A `+1.50` day is a gain of `1.50` and a loss of `0`; a `−0.80` day is a gain of `0` and a loss of `0.80`. A perfectly flat day (`Δ_t = 0`) lands in neither — it contributes `0` to both. The point of the split is to keep the *up-energy* and the *down-energy* on separate books so we can weigh them against each other; smearing them into a single signed number would let a big up-day and a big down-day silently cancel, and momentum is precisely about which side is winning, not about the net.

**Step 2 — keep smoothed averages of each bucket.** We don't want the RSI to lurch on a single day, so we smooth. Wilder used his own flavor of exponential smoothing, called **Wilder smoothing** — an EMA (Chapter 4) with `α = 1/period`:

```
new_avg  =  ( old_avg · (period − 1)  +  current ) / period
```

Convince yourself this *is* an EMA with `α = 1/period`: rearrange it to `new_avg = (1/period)·current + (1 − 1/period)·old_avg`, which is exactly `EMA_t = α·(current) + (1−α)·(old_avg)` from §4.4. So Wilder smoothing is nothing new — it's the EMA recurrence you already derived, with a specific, slow `α`. We keep two of them running: `avg_gain` and `avg_loss`.

**Step 3 — form the ratio, then rescale to 0–100.** Define **relative strength** as the ratio of the two smoothed averages, and the RSI as a rescaling of it:

```
RS   =  avg_gain / avg_loss
RSI  =  100  −  100 / (1 + RS)
```

**Why this particular formula?** Because the raw ratio `RS` lives on an awkward scale — it runs from `0` (all losses) up through `1` (balanced) to `+∞` (all gains), and infinities are hard to eyeball. The map `RS ↦ 100 − 100/(1+RS)` squashes that whole half-line neatly onto `[0, 100]`. Check the ends:

```
RS = 0   (only losses)   → RSI = 100 − 100/1   =  0
RS = 1   (balanced)      → RSI = 100 − 100/2   = 50
RS → ∞   (only gains)    → RSI = 100 − 100/∞   = 100
```

So `RSI = 50` is the neutral tug-of-war, and the index rises toward 100 as gains dominate, falls toward 0 as losses dominate. The code even short-circuits the `avg_loss = 0` case — pure gains, `RS` would divide by zero — straight to `RSI = 100`, which is exactly the limit above.

> **Short: overbought / oversold.** By convention `RSI > 70` is called **overbought** (buyers have been dominating so lopsidedly the move may be stretched) and `RSI < 30` **oversold**. These are *conventions*, not laws of nature — 70 isn't handed down from physics. They're thresholds a human picked because they tend to be interesting, and in [Chapter 7](07-signal-vs-noise.md) we'll ask hard questions about trusting any fixed line.

> **Short: why `period = 14`?** Wilder's original default, and the code's default, is a 14-day period. There is nothing magic in it — it's roughly three trading weeks, long enough that a single loud day can't dominate the two averages, short enough to still respond within a couple of weeks. As an EMA with `α = 1/14 ≈ 0.071`, it has a long memory: by the average-age formula of [Chapter 4](04-trend-and-moving-averages.md), a slow, deliberate momentum reading. Shorten the period and the RSI gets twitchier; lengthen it and it smooths toward a flat 50.

## 5.3 MACD: the gap between fast and slow, revisited

The second momentum lens reuses the EMA from Chapter 4 directly — you've already built its parts.

**Moving Average Convergence Divergence** (MACD) starts with one idea: compare a **fast** EMA of the price to a **slow** EMA of the price. Their difference is the MACD line:

```
MACD_line(t)  =  EMA_fast(price)  −  EMA_slow(price)        (defaults: fast = 12, slow = 26)
```

This is *literally* the EMA cousin of Chapter 4's `SMA_CROSS`. When short-term price behavior pulls **away from** and **above** the long-term average, the fast EMA outruns the slow one and `MACD_line > 0` — recent momentum is beating the longer trend. When short-term behavior sags below, `MACD_line < 0`. The name says it: the two averages *converging* and *diverging* is the whole signal.

But a raw difference is jittery, and — just like a crossover — we care most about when it **turns**. So MACD smooths itself once more. Take an EMA *of the MACD line* (default span 9), call it the **signal line**, and subtract:

```
Signal_line(t)  =  EMA_signal( MACD_line )                 (default: signal = 9)
Histogram(t)    =  MACD_line(t)  −  Signal_line(t)
```

The **histogram** is the payoff. The signal line is the MACD line's *own recent average*, so the histogram asks: *is fast momentum right now above or below its own recent norm?*

- `Histogram > 0` — the MACD line is above its recent average — momentum is **accelerating** upward.
- `Histogram < 0` — momentum is **fading** relative to its own recent self.
- **Histogram crosses zero** — the moment momentum shifts gear. That zero-crossing is the event traders watch, and (like the golden cross in Chapter 4) detecting it needs today's value *and* yesterday's — the same `cross_above` / `cross_below` machinery.

> **Short: three EMAs, three warm-ups.** MACD stacks Chapter 4's EMA three deep — a fast one, a slow one, and a third *on top of their difference*. Each needs time to settle from its seed, so the honest earliest day you can trust the histogram is only after the slow EMA (26 days) *and* the signal EMA (9 more) have had room to breathe — which is exactly why the code refuses to compute anything until `n ≥ slow + signal` and masks the front of the series to `None`. The whole indicator is the golden thread compounded: a slow story, a fast story, and the gap between them, each filtered.

## 5.4 Two lenses, and the doubt to come

Step back. You now hold three instruments:

- **z-score** (Ch. 3) — a *mean-reversion* lens. Large magnitude says "stretched, expect reversal."
- **RSI** (this chapter) — a *momentum* lens. It reads the balance of recent up-days vs down-days.
- **MACD histogram** (this chapter) — a *momentum* lens. It reads whether fast momentum is pulling ahead of slow.

Point all three at the same chart and they will sometimes **disagree**. RSI at 75 screams "strong uptrend, momentum!" while a z-score of `+2.5` mutters "too far above the mean, expect a snap back." Both are correctly computed. Both cannot be right about what happens next. Which lens *fits this market* is the real question — and the honest answer, that no indicator knows whether it's the right one, is precisely the doubt we sharpen in [Chapter 7](07-signal-vs-noise.md).

There's a deeper reason the disagreement isn't just noise. Momentum and mean reversion genuinely coexist in real markets — they simply tend to live on **different time horizons**. A move can be trending strongly over weeks (momentum) while sitting far above its 20-day mean and due for a short pullback (mean reversion) *at the same time*. So an indicator isn't "wrong" for firing against another; each is answering a question at its own horizon. The mistake — the one that costs money — is forgetting *which question you asked* and treating every green light as the same light. Naming your lens before you read it is the discipline this whole course is quietly building toward.

## 5.5 In the code

Open [`backend/marketdata/indicators.py`](../backend/marketdata/indicators.py). Here is the RSI, matching §5.2 step for step — the gains/losses split, the `rsi_val` rescaling with its `avg_loss == 0 → 100` short-circuit, the seed average over the first `period` changes, and the Wilder recurrence:

```python
def _rsi_series(closes: List[float], period: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    def rsi_val(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return float(100 - 100 / (1 + rs))

    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = rsi_val(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = rsi_val(avg_gain, avg_loss)
    return out
```

Read the two lines inside the loop next to §5.2's Wilder formula: `avg_gain = (avg_gain*(period-1) + gains[i-1]) / period` *is* `new_avg = (old_avg·(period−1) + current)/period`. And `rsi_val` is `RSI = 100 − 100/(1+RS)` with the divide-by-zero guarded into the `RSI = 100` limit we derived.

Now the MACD histogram — §5.3, and notice it's built *entirely* out of the `_ema` you already know from Chapter 4:

```python
def _macd_hist_series(closes: List[float], fast: int, slow: int, signal: int) -> List[Optional[float]]:
    n = len(closes)
    if n < slow + signal:
        return [None] * n
    macd = _ema(closes, fast) - _ema(closes, slow)
    hist = macd - _ema(macd.tolist(), signal)
    # Mask the warm-up region where the slow EMA is unreliable.
    out: List[Optional[float]] = [None] * n
    for i in range(slow, n):
        out[i] = float(hist[i])
    return out
```

Line by line: `macd = _ema(closes, fast) - _ema(closes, slow)` is `MACD_line = EMA_fast − EMA_slow`; `hist = macd - _ema(macd.tolist(), signal)` is `Histogram = MACD_line − Signal_line`, the signal line being an EMA *of* the MACD line. The early days are masked to `None` because the slow EMA hasn't settled yet — the warm-up, honestly reported, exactly as everywhere else in this codebase.

## 5.6 Worked example

Let's compute an RSI by hand with a short `period = 3` so the arithmetic stays on one screen. Take six closes:

```
day:      0     1     2      3     4     5
close:  10.0  11.0  10.5  11.5  12.0  11.8
```

**Daily changes, split into gains and losses:**

```
Δ:   +1.0   −0.5   +1.0   +0.5   −0.2
gain: 1.0    0.0    1.0    0.5    0.0
loss: 0.0    0.5    0.0    0.0    0.2
```

**Seed** the two averages over the first `period = 3` changes (this lands the first RSI on day 3):

```
avg_gain = mean(1.0, 0.0, 1.0) = 2.0/3 = 0.6667
avg_loss = mean(0.0, 0.5, 0.0) = 0.5/3 = 0.1667

RS  = 0.6667 / 0.1667 = 4.000
RSI(day 3) = 100 − 100/(1+4.000) = 100 − 20.00 = 80.00
```

**Wilder update to day 4** (the 4th change is `gain = 0.5`, `loss = 0.0`):

```
avg_gain = (0.6667·2 + 0.5) / 3 = 1.8333/3 = 0.6111
avg_loss = (0.1667·2 + 0.0) / 3 = 0.3333/3 = 0.1111

RS  = 0.6111 / 0.1111 = 5.500
RSI(day 4) = 100 − 100/(1+5.500) = 100 − 15.38 = 84.62
```

**Wilder update to day 5** (the 5th change is `gain = 0.0`, `loss = 0.2`):

```
avg_gain = (0.6111·2 + 0.0) / 3 = 1.2222/3 = 0.4074
avg_loss = (0.1111·2 + 0.2) / 3 = 0.4222/3 = 0.1407

RS  = 0.4074 / 0.1407 = 2.895
RSI(day 5) = 100 − 100/(1+2.895) = 100 − 25.68 = 74.32
```

The RSI sat up in the high 70s–80s the whole way — this little series is dominated by up-moves, so momentum reads "strong," even "overbought" (`> 70`). Watch, too, how one down-day (day 5's `−0.2`) nudged it from `84.6` down to `74.3` but didn't crater it: the Wilder smoothing means no single day owns the number.

## 5.7 Problem set

1. **RSI hits the ceiling.** Take any all-up series, e.g. `closes = [10, 11, 12, 13, 14]` with `period = 3`. Show that every `loss` is `0`, hence `avg_loss = 0` at every step, hence `RSI = 100` throughout. Trace exactly which line of `_rsi_series` produces `100.0` in that case, and connect it to the `RS → ∞` limit in §5.2.

2. **The rescaling is a bijection.** Show that `RSI = 100 − 100/(1+RS)` is strictly increasing in `RS` for `RS ≥ 0`, and that it maps `[0, ∞)` onto `[0, 100)`. (Then argue the `avg_loss = 0` short-circuit is what supplies the endpoint `100` that the formula only approaches.) Why is a monotone rescaling the *right* kind of transform — what would we lose if it weren't one-to-one?

3. **MACD sign from the two EMAs.** Prove that `Histogram(t) > 0` exactly when `MACD_line(t) > Signal_line(t)`, and that `MACD_line(t) > 0` exactly when `EMA_fast(t) > EMA_slow(t)`. Then state, in one plain sentence each, what a **positive MACD line** and a **positive histogram** each tell you about fast vs. slow momentum. (They are *not* the same statement — be precise.)

4. **Wilder is just an EMA.** Show algebraically that `new_avg = (old_avg·(period−1) + current)/period` equals `α·current + (1−α)·old_avg` with `α = 1/period`. Then, using the average-age result from [Chapter 4](04-trend-and-moving-averages.md) §4.5, find the average age of a `period = 14` Wilder average. Is it slower or faster than a 14-day SMA?

5. **Two lenses, one chart.** Construct (by hand or with the synthetic provider) a short price path where the z-score is strongly positive (say `> +2`) at the same time the RSI is `> 70`. Explain which lens is betting on what, and why a system that trusted *both* at once would be incoherent. Keep your answer — it's the exact tension [Chapter 7](07-signal-vs-noise.md) resolves.

---

Previous: [Chapter 4 — Trend & moving averages](04-trend-and-moving-averages.md) · Next: momentum tells you *which way* a move is pushing, but not *how big* the moves are or how that scales with time. For that we need to measure the size of the noise itself — [Chapter 6 — Volatility & the square root of time](06-volatility.md).
