# Chapter 3 — The z-score & mean reversion

*Prev: [Chapter 2 — The statistics of returns](02-statistics-of-returns.md) · Next: [Chapter 4 — Trend & moving averages](04-trend-and-moving-averages.md)*

> **The question.** You pull up a chart, the price has dropped, and someone at the next desk says "that looks unusually cheap." It's a seductive sentence. But *unusually* compared to what? *Cheap* by whose ruler? Until we can replace that gut feeling with a number, we can't build a rule, back-test it, or trust it at 3 a.m. when it fires an alert. Let's make "unusually cheap" mean something exact — and then find the assumption hiding inside it.

---

## 3.1 Standardization: a universal ruler

Chapter 2 left us with two summaries of a sample: its center `μ̂` and its spread `σ̂`. The final move of that chapter combined them into a single unit-free score. Here it is again, front and center, because this whole chapter is one long meditation on it:

```
z = (x − μ̂) / σ̂
```

Read it in two motions. First, `x − μ̂` **centers** the value — it asks "how far from average is this?", positive above, negative below. Second, dividing by `σ̂` **rescales** that distance into units of standard deviations — it asks "and is that far *for this particular series*?" The result, the **z-score**, answers the whole question in one number: **how many standard deviations from the mean does this value sit?**

The magic is in what division by `σ̂` buys you: the z-score is **unit-free**. The `μ̂` and `σ̂` carry the same units as `x`, so their ratio has no units at all — a `z` of `−2` is `−2` whether the price was in dollars, yen, or post-split pennies. That means z-scores are **comparable across assets**. A `z = −2` on a sleepy utility and a `z = −2` on a manic biotech are the *same amount of unusual*, even though the biotech's raw price swings dwarf the utility's. The z-score has quietly divided out each asset's personality and left behind pure surprise. That comparability is why it's the first indicator we reach for.

> **Short: "unusual" is relative to your own history.** The z-score never compares an asset to other assets or to some absolute notion of "expensive." It compares the asset **to itself** — to its own recent mean and its own recent spread. A `z = −2` doesn't say "cheap versus fair value"; it says "cheap versus where *this thing* has been lately." That humility is a feature. Nobody knows fair value. Everybody can measure a series against its own past.

## 3.2 Reading the z-score through the bell curve

A number is only useful once you know which values are big. Chapter 2's 68–95–99.7 rule hands us the calibration for free. If the data are roughly normal, then the fraction of days landing *beyond* a given `z` is:

```
|z| > 1   →  about 32% of days     (outside μ̂ ± 1σ̂ — 100% − 68%)
|z| > 2   →  about  5% of days     (outside μ̂ ± 2σ̂ — 100% − 95%)
|z| > 3   →  about 0.3% of days    (outside μ̂ ± 3σ̂ — 100% − 99.7%)
```

Split those in half for a one-sided question. A `z` **below** `−2` happens on only about `5%/2 ≈ 2.5%` of days — call it one day in forty. So when someone says "unusually cheap," a `z = −2` is a defensible place to plant the flag: it is a genuinely uncommon day, not everyday jitter. A `z = −0.5` is noise; a `z = −2` is an event; a `z = −3` is a once-a-year lightning strike (and, per Chapter 2's warning about fat tails, in real markets a lot more common than 0.3% would suggest — keep that asterisk).

This table is the bridge from "how many sigmas" to "how often" to "should I care." It is what turns a raw z-score into a decision.

## 3.3 The rolling z-score on prices — exactly what the code computes

Now we have to be precise, because the code makes a specific choice and a vague mental model will mislead you. QuantAI's `Z_SCORE` indicator computes a **rolling z-score on prices**. Read that phrase carefully — *on prices*, not on returns — and here is what "rolling" means, day by day:

> On day `t`, take the last `n` closing prices — the window `p_{t−n+1}, ..., p_t`, with the most recent day included. Compute *that window's* mean and *that window's* sample standard deviation (with `ddof = 1`, per Chapter 2). Then

```
z_t = (p_t − mean of the window) / (sample std of the window)
```

The window **rolls**: tomorrow it drops the oldest close and admits a new one, so the mean and std are recomputed fresh every day. The z-score you get is therefore always relative to *recent* history, and "recent" is exactly `n` days long. This directly answers the human question: **"how extreme is today's price relative to its own recent history?"** A `z_t` of `−2` means today's close sits two standard deviations below the average of the last `n` closes — unusually low *for this series, right now*.

Notice we are standardizing the *level* (`p_t`) against a window of levels, not standardizing a return. That's a deliberate design choice: it directly measures "is today's price an outlier versus the recent range," which is exactly the "unusually cheap" question. It also quietly assumes the recent window has a stable center to be an outlier *from* — an assumption we are about to interrogate in §3.5.

**The flat-window guard.** One edge case must be handled or the formula explodes. If every close in the window is identical — a perfectly flat stretch — then the spread is zero, `σ̂ = 0`, and `z = (p_t − μ̂)/0` is a division by zero. What *should* the answer be? If the price hasn't moved at all, today is not surprising in the slightest, so the only sane z-score is **zero**. The code returns exactly `0.0` in that case. No spread means no surprise means no signal. Watch for this guard in §3.7 — it is a small thing that separates code that runs in production from code that crashes on the one boring day the market didn't move.

## 3.4 The mean-reversion hypothesis

So we can flag an unusual day. Why would anyone *trade* on it? Because of a hypothesis about how some series behave, and it deserves to be stated as a hypothesis, not a fact.

**Mean reversion** is the claim that a series tends to be *pulled back toward its own average* — that deviations are temporary and self-correcting. Picture a rubber band tethering the price to its recent mean: stretch it far in either direction and it tugs back. Some real quantities behave like this. The spread between two closely-related companies' stocks, an exchange rate under a central bank's watch, an over-sold stock that panicked sellers pushed too far — these often snap back.

*If* a series is mean-reverting, the z-score becomes a trading signal with a direction:

```
z very negative  ("unusually cheap")  →  expect a bounce back up   →  a reason to BUY
z very positive  ("unusually dear")   →  expect a pullback down     →  a reason to SELL
```

This is the entire thesis behind a rule like **"z-score `< −2`"**: *the price has stretched two standard deviations below its recent mean; if the rubber band holds, it should snap back, so an unusually cheap reading is a buy signal.* Clean, quantitative, and — when the hypothesis is true — genuinely profitable. It is one of the oldest strategies in the book.

But look hard at the word *if*. Everything rides on the rubber band actually existing.

## 3.5 The caveat that sinks fortunes: trends aren't rubber bands

Here is the failure mode, and it is not a footnote — it is the whole reason a serious quant treats the z-score with respect rather than affection. A **trending** series is *not* mean-reverting. There is no rubber band. There is a freight train.

Imagine a stock in genuine decline — bad fundamentals, a slow collapse — falling steadily day after day. Its rolling window is always centered near where it's been *recently*, and each new low is only modestly below that recent average. So the z-score sits down around `−2`... and the price keeps falling... and the window slides down to follow it... and the z-score sits at `−2` *again*, refreshed against a lower mean. Your "unusually cheap, expect a bounce" rule fires, you buy, and the freight train runs you over. Then it fires again the next day, one dollar lower. This has a grim trader's name: **catching a falling knife.** The z-score told you the truth — the price *is* two sigmas below its recent average — but the *inference* you drew from it, "therefore it will bounce," was false, because you assumed a rubber band where there was a trend.

The mathematical name for the buried assumption is **stationarity**: the z-score's logic only holds if the series' mean and spread are roughly *stable over time*, so that "far from the mean" implies "temporarily dislocated, will return." A trending series is **non-stationary** — its mean is *moving* — and against a moving mean, "far below" can mean "leading the way down," not "overshot and snapping back." When stationarity fails, the rule doesn't just underperform; it **bleeds**, buying every step of a decline.

> **Short: honesty about assumptions is the whole game.** Every indicator in this course is a lens that assumes something about the world, and it is invisible until it breaks. The z-score assumes stationarity. It says so nowhere in the formula — you have to *know* to look for it. The difference between a quant who makes money and one who blows up is rarely a fancier formula; it is knowing precisely which assumption each formula is quietly betting on, and watching for the day that bet goes bad. This is why Chapter 4 (trend) and Chapter 7 (signal vs. noise) exist: to teach you to detect a trend *before* you fire a mean-reversion rule into it, and to doubt any single signal on principle.

## 3.6 Operators: thresholds and crossovers

A z-score is a number; a *rule* needs a comparison. QuantAI offers two flavors, and the difference between them is why the code bothers to track a **previous** value.

A **threshold** operator asks about *today alone*: is `z_t < −2` right now? Simple, but it fires on *every* day the condition holds. If `z` sits below `−2` for a week (hello, falling knife), a `<` rule alerts you seven times — often not what you want.

A **crossover** operator asks about a *transition*: did `z` just *cross* the line today, having been on the other side yesterday? `cross_below` fires on the single day `z` passes from `≥ −2` down through `−2` — the *moment* of dislocation, not every day after. To detect a crossing you fundamentally need two data points: yesterday's value and today's. One number can tell you which side of a line you're on; it cannot tell you that you just *crossed* it.

That is exactly why `compute_indicator` returns **both** a `value` and a `previous`:

```
value     = z_t       (today's z-score, the latest valid reading)
previous  = z_{t−1}   (yesterday's — the one before it)
```

The threshold operators (`<`, `>`, `<=`, `>=`) use only `value`. The crossover operators (`cross_above`, `cross_below`) need `previous` too, to see the transition. We'll read both the producing code and the evaluating code in §3.7.

## 3.7 In the code

Open [`backend/feeder/indicators.py`](../backend/feeder/indicators.py). First, the z-score itself — the rolling window of §3.3, the two Chapter-2 statistics, and the flat-window guard, all in six lines:

```python
def _zscore_series(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        w = np.asarray(closes[i - window + 1:i + 1], dtype=float)
        std = w.std(ddof=1)
        out[i] = 0.0 if std == 0 else float((closes[i] - w.mean()) / std)
    return out
```

Read it against the prose line by line. The loop starts at `window - 1`, not `0`: the first `window − 1` days can't fill a full window, so they stay `None` — the **warm-up** from the preface. `closes[i - window + 1:i + 1]` is the rolling window ending at *and including* day `i` (that `+ 1` on the upper bound is what keeps today in the window — exactly the "most recent day is included" from §3.3). `w.mean()` and `w.std(ddof=1)` are `μ̂` and the Bessel-corrected `σ̂` from Chapter 2. The final line is `z = (p_t − μ̂)/σ̂` — with the guard `0.0 if std == 0` catching the flat-window division-by-zero and returning "no surprise," precisely as argued in §3.3.

The default window lives in the indicator spec, alongside a one-line description that is really just §3.1 compressed:

```python
"Z_SCORE": {"label": "Z-Score", "unit": "σ", "defaults": {"window": 20},
            "help": "Standard deviations the latest close sits from its rolling mean."},
```

The unit is literally `"σ"` — the code agrees with us that a z-score is measured in sigmas — and the default window is 20 trading days (about a month; remember from Chapter 2 that this number is a bet about how fast the world changes).

Now the rule engine. Here is `evaluate_condition`, and note especially the `<` branch (the threshold behind "unusually cheap") and the `cross_below` branch (the transition operator that consumes `previous`):

```python
def evaluate_condition(operator: str, value: Optional[float],
                       previous: Optional[float], threshold: float) -> bool:
    """Return True when ``value`` (with ``previous`` for cross ops) satisfies the
    condition ``value <operator> threshold``."""
    if value is None:
        return False
    if operator == "<":
        return value < threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">=":
        return value >= threshold
    if operator == "==":
        return value == threshold
    if operator == "cross_above":
        return previous is not None and previous <= threshold < value
    if operator == "cross_below":
        return previous is not None and previous >= threshold > value
    raise ValueError(f"Unknown operator: {operator!r}")
```

The `<` branch is the whole of a "z-score `< −2`" rule: one comparison of today's `value` against the `threshold`. The `cross_below` branch is subtler and worth reading as a chained inequality: `previous >= threshold > value` is `True` only when yesterday was *at or above* the line **and** today is strictly *below* it — the exact fingerprint of a downward crossing, and impossible to check without `previous`. (The very first guard, `if value is None: return False`, is the warm-up showing up again: during warm-up there's no z-score, so no rule can fire — the honest default.)

> **Short: why no `==`?** You'll spot an `==` branch here, but the operator is deliberately *not* offered in the UI. The comment in the source explains it: a computed indicator like a z-score is a float that essentially never lands on an *exact* value, so a rule like "z-score `== −2`" would silently never fire. Floats don't hit bullseyes. Thresholds and crossovers are the honest way to ask "has it passed this level," and they're what the interface exposes.

## 3.8 Worked example

Take a 6-close window and compute its rolling z-score by hand, then evaluate the rule "z `< −2`." (This is one full turn of the loop in `_zscore_series` with `window = 6`.)

```
window (last 6 closes):   101,  100,  102,  100,  101,   90
                          p_{t-5} ..................... p_t
```

**Step 1 — the window mean, `μ̂`:**

```
Σ = 101 + 100 + 102 + 100 + 101 + 90 = 594
μ̂ = 594 / 6 = 99.0
```

**Step 2 — deviations from `μ̂ = 99`, and their squares:**

```
101 − 99 =  2   →   4
100 − 99 =  1   →   1
102 − 99 =  3   →   9
100 − 99 =  1   →   1
101 − 99 =  2   →   4
 90 − 99 = −9   →  81
                   ---
Σ (x_i − μ̂)²  =    100
```

**Step 3 — sample variance and std, the `ddof=1` way (`n − 1 = 5`):**

```
σ̂² = 100 / (6 − 1) = 100 / 5 = 20
σ̂  = sqrt(20) ≈ 4.472
```

**Step 4 — the z-score of the latest close (`p_t = 90`):**

```
z_t = (p_t − μ̂) / σ̂ = (90 − 99) / 4.472 = −9 / 4.472 ≈ −2.012
```

**Step 5 — evaluate the rule `z < −2`:**

```
evaluate_condition("<", value=−2.012, previous=..., threshold=−2.0)
   →  −2.012 < −2.0  →  True     ✓  the rule FIRES
```

Today's close of 90 sits about 2.01 standard deviations below its recent mean of 99 — past the `−2` line — so a "z-score `< −2`" alert would fire. Whether you should *believe* it depends entirely on §3.5: if this series is mean-reverting, 90 is a bargain about to bounce; if it's the start of a trend, 90 is the first cheap-looking rung of a long ladder down.

> **Short: the short-window ceiling.** Notice how *extreme* this window had to look — a clean drop from 101 to 90 — just to nudge past `−2`. That's not an accident. For a window of `n` points, the largest possible `|z|` is `sqrt(n − 1)`; here `sqrt(5) ≈ 2.236`, so `−2.012` is already near the mathematical maximum a 6-day window can produce. Short windows *cannot* register truly extreme z-scores — there aren't enough points to be an outlier among. It's one more reason the default window is 20, not 6: bigger windows can actually *see* a 3-sigma event.

## 3.9 Problem set

1. **Compute and classify.** For the 5-close window `[50, 52, 51, 53, 45]` with `window = 5`, compute `μ̂`, `σ̂` (`ddof = 1`), and `z_t` for the latest close by hand. Does the rule "z `< −2`" fire? Then, using the 68–95–99.7 rule, state roughly how often a day this extreme (or more) should occur under the normal model, and note whether real markets tend to beat that frequency or fall short of it.

2. **The flat-window guard.** Hand `_zscore_series` the window `[70, 70, 70, 70, 70]`. Walk through the code: what is `w.std(ddof=1)`, which branch of the `0.0 if std == 0` guard executes, and what value comes out? Explain in one sentence why returning `0.0` (rather than, say, raising an error or returning `None`) is the *right* answer in terms of "surprise."

3. **A trend fools the z-score.** Consider a steadily declining series whose closes are `100, 98, 96, 94, 92, 90` (a 6-day window). (a) Compute `z_t` for the latest close. (b) Now slide the window forward one day to `98, 96, 94, 92, 90, 88` and compute the new `z_t`. (c) You'll find the z-score barely moves even though the price fell every single day. Explain, using stationarity and §3.5, why a "z `< −2`" mean-reversion rule is dangerous on this series, and name the concrete trader's error it would commit.

4. **Threshold vs. crossover.** Over five days the z-score reads `−1.5, −2.3, −2.1, −2.4, −1.8`. (a) On which days does the *threshold* rule `<` with threshold `−2` fire? (b) On which day(s) does `cross_below` at `−2` fire? Use the code's `previous >= threshold > value` logic explicitly, day by day. (c) In one sentence, say which operator you'd pick if you want to be alerted *once*, at the moment of dislocation, and why it needs `previous`.

5. **Comparability across assets.** Asset A (a utility) has recent mean price 40 with std 0.8; asset B (a biotech) has recent mean 40 with std 6.0. Both close today at 38.5. (a) Compute each asset's z-score. (b) The raw *dollar* drop is identical (−1.5) — why do the z-scores disagree so sharply, and which asset is having a genuinely unusual day? (c) Explain how this illustrates the claim in §3.1 that the z-score "divides out each asset's personality."

---

*Prev: [Chapter 2 — The statistics of returns](02-statistics-of-returns.md) · Next: [Chapter 4 — Trend & moving averages](04-trend-and-moving-averages.md)*

The z-score's fatal flaw was the trend it couldn't see. So next we build the tools that measure a trend head-on — and learn how they fool us in their own, opposite way. Onward to [Chapter 4 — Trend & moving averages](04-trend-and-moving-averages.md).
