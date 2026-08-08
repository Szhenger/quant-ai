# Chapter 6 — Volatility & the square root of time

> **The question.** You are about to put money on something that moves. Before you ask *which way* it will move, ask the more basic question: **how much does this thing usually move at all — and over what horizon?** A stock that drifts a tenth of a percent a day and one that swings five percent a day are different animals, even if both are "flat" on average. That "how much it moves" number has a name — **volatility** — and it turns out to be the single most important number in all of risk. Let's build it, and then derive the one rule everyone quotes and almost nobody proves: *volatility grows with the square root of time.*

---

## 6.1 Size, not direction

Go back to returns (Chapter 1). A daily return `r_t` has two pieces of information tangled together: a **sign** (up or down) and a **magnitude** (how far). Everything in Chapters 3–5 was, one way or another, about the *sign* — is it cheap, is it trending, is momentum fading. Volatility throws the sign away and keeps only the magnitude. It answers: **on a typical day, how far does this thing travel, regardless of direction?**

The honest way to measure "typical distance from the center" is something you already own from Chapter 2: the **standard deviation**. So here is the whole definition, in one line:

> **Volatility is the standard deviation of returns.**

That's it. `VOLATILITY` is not a new statistic; it is Chapter 2's `σ̂` applied to the return series instead of the price series. If daily returns are `r_1, …, r_n`, the **daily volatility** is

```
σ_d = sqrt( (1/(n−1)) · Σ (r_i − r̄)² )        (sample std, ddof=1)
```

the sample standard deviation — dividing by `n − 1`, exactly as the preface warned and exactly as `numpy`'s `.std(ddof=1)` does. It measures the **size of the noise**, and it is blind to direction: a run of `+2%, −2%, +2%, −2%` and a run of `+2%, +2%, +2%, +2%` have very different trends but can have similar volatility, because volatility only cares how far each day strays from the average day.

> **Short: volatility is a per-period width.** Picture the daily returns as a cloud of dots scattered around their mean. Volatility is the *width* of that cloud. A wide cloud (big `σ_d`) means wild days; a tight cloud means sleepy ones. Nothing about the width tells you whether tomorrow is up or down — only how *big* tomorrow is likely to be.

## 6.2 A horizon problem

Here is where it gets interesting, and where beginners get burned. You measured a daily volatility of, say, `σ_d = 1.8%`. Fine. But nobody holds a position for exactly one day and nobody quotes risk in days. A pension fund thinks in years. An options desk thinks in the weeks to expiry. So the real question is:

> If a stock moves `1.8%` on a typical *day*, how much does it move on a typical *year*?

The naive answer is "multiply by the number of days" — `1.8% × 252 ≈ 454%`. That is spectacularly wrong, and understanding *why* it is wrong is the whole chapter. The mistake is treating **randomness** the way you'd treat a steady drift. If a car moves 60 miles every hour in the same direction, then over 10 hours it moves 600 miles — distances add. But random daily wiggles **don't all point the same way.** Some days are up, some down; they partially cancel. So a year's worth of accumulated randomness is *much less* than 252 times a single day's. The question is: how much less, exactly?

To answer it precisely we need one clean fact from Chapter 2 about how variance behaves when you **add** random things.

## 6.3 The keystone: variance adds for independent sums

Recall from Chapter 2 the rule for the variance of a sum. For any two random variables:

```
Var(X + Y) = Var(X) + Var(Y) + 2·Cov(X, Y)
```

and the special, beautiful case: **when `X` and `Y` are independent, `Cov(X, Y) = 0`**, so the cross-term vanishes and variances simply add:

```
Var(X + Y) = Var(X) + Var(Y)            (independent case)
```

Hold onto that. It's the entire engine. Now we connect it to returns using the one property Chapter 1 fought so hard to establish: **log returns add across time.**

Set up the model as cleanly as we can. Assume the daily (log) returns

```
ℓ_1, ℓ_2, …, ℓ_T
```

are **independent and identically distributed** — "i.i.d." — each with the same variance `σ_d²`. "Independent" means one day's wiggle tells you nothing about the next day's. "Identically distributed" means every day is drawn from the same cloud of the same width. (Both assumptions are *approximately* true and *importantly* false; §6.6 is where we pay that debt honestly.)

Now — the total return over `T` days is the **sum** of the daily returns (Chapter 1, the telescoping property):

```
R_T = ℓ_1 + ℓ_2 + … + ℓ_T
```

Take the variance of both sides. Because the `ℓ_i` are independent, variance adds — `T` copies of it:

```
Var(R_T) = Var(ℓ_1) + Var(ℓ_2) + … + Var(ℓ_T)
         = σ_d² + σ_d² + … + σ_d²        (T identical terms)
         = T · σ_d²
```

Variance grows **linearly** with time. But volatility is a *standard deviation*, not a variance — so take the square root of both sides:

```
σ_T = sqrt( Var(R_T) ) = sqrt( T · σ_d² ) = σ_d · sqrt(T)
```

There it is. Frame it as what it is — a theorem, not a proverb:

> **The square-root-of-time rule.** If daily returns are i.i.d. with daily volatility `σ_d`, then the volatility over `T` days is
> ```
> σ_T = σ_d · sqrt(T)
> ```

The square root is not decoration and not a convention someone chose. It falls out with no freedom at all: **variance adds** (that's the linear `T`), and **volatility is the square root of variance** (that turns the `T` into `sqrt(T)`). The `sqrt` is the fingerprint of *independent randomness accumulating* — the partial cancellation we hand-waved in §6.2, made exact.

> **Short: why the naive answer was so wrong.** Multiplying by `T` (getting `454%`) implicitly assumes the year's return is `T` times a single day *pointing the same way* — i.e. it added the *sizes* as if they never cancel. That is what you'd do for a **drift**. Randomness accumulates as `sqrt(T)`, not `T`. For `T = 252`, that's the difference between `sqrt(252) ≈ 15.9` and `252` — nearly a **16×** overstatement of risk. Confusing "adds like a trend" with "adds like noise" is one of the most expensive mistakes in finance.

## 6.4 Annualizing: why 252

`sqrt(T)` lets us move volatility to any horizon we like. The market's favorite horizon is **one year**, because that's how returns and risk are conventionally quoted. From the preface's notation box: a year has about **252 trading days** (roughly 365 minus weekends and market holidays — the market is only open on business days, so *trading* days are what accumulate risk, not calendar days). Set `T = 252` in the theorem:

```
σ_annual = σ_d · sqrt(252)        (≈ σ_d · 15.87)
```

So a daily volatility of `1.8%` becomes an **annualized volatility** of `1.8% × 15.87 ≈ 28.6%`. Read that as: "a typical year for this asset has a one-standard-deviation swing of about 29%." That single number — annualized vol — is how the whole industry compares the riskiness of wildly different assets on one common scale. A sleepy utility might annualize to 15%; a hot growth stock to 60%; a meme coin to 150%. The horizon is standardized so the *asset* is what varies.

> **Short: the same trick, any horizon.** Want *monthly* volatility from daily? A month is ~21 trading days, so `σ_month = σ_d · sqrt(21)`. Want to go the *other* way — daily from annual? Divide: `σ_d = σ_annual / sqrt(252)`. The rule runs in both directions because it's just algebra on `sqrt(T)`.

## 6.5 Volatility is the denominator of risk

Why crown volatility the master risk number? Because almost every quantity a quant actually uses is a **move measured in units of volatility.** Once you have `σ`, everything gets divided by it:

- **The z-score (Chapter 3)** is `(x − μ) / σ` — a distance from the mean *expressed in volatilities.* "Two standard deviations cheap" only means something because `σ` set the ruler.
- **Sharpe-like comparisons.** "Is this return good?" is unanswerable until you ask "good *relative to how much it bounced around*?" Return per unit of volatility (`return / σ`) is how you compare a calm 8% to a wild 8% — the wild one is worse, because you took more risk to get the same reward.
- **Position sizing.** If you want every position to carry the *same* risk, you buy *less* of the volatile thing and *more* of the calm thing — sizing each position `∝ 1 / σ`. Volatility is literally in the denominator of how many shares you buy.

In every one of these, `σ` sits underneath — it is the **denominator of risk**, the unit that turns raw dollar moves into comparable, dimensionless statements about how surprised you should be. That is why it earns its own chapter and its own indicator.

## 6.6 What breaks it — and it does break

Reread the derivation in §6.3 and notice the exact plank the whole thing stands on: **independence.** The step `Var(R_T) = T · σ_d²` used `Cov = 0` between days. Drop that and the whole result is the general formula, cross-terms and all:

```
Var(R_T) = Σ Var(ℓ_i)  +  2 · Σ_{i<j} Cov(ℓ_i, ℓ_j)
```

The `sqrt(T)` rule is precisely the **`Cov = 0` special case** of this. So the honest question is: are real daily returns actually independent? **No.** And the way they fail is famous enough to have a name.

Real markets show **volatility clustering**: calm days bunch together and stormy days bunch together. After a wild day, the next day tends to be wild; after a sleepy stretch, more sleep. You can see it with your eyes on any price chart — the turbulence comes in patches, not sprinkled evenly. Formally, while the *signed* returns are close to uncorrelated (you genuinely can't predict tomorrow's direction from today's — that's Chapter 7's whole point), the **magnitudes** `|ℓ_i|` are strongly **autocorrelated** across days. Big begets big.

That means `Cov(ℓ_i, ℓ_j) ≠ 0` for the sizes, so `Var(R_T) ≠ T · σ_d²` exactly, and the square-root-of-time rule becomes an **approximation** rather than a law:

- In a **calm-into-storm** regime, positive covariance makes true multi-day variance *larger* than `T · σ_d²`, so `σ_d · sqrt(T)` **understates** the real horizon risk — the dangerous direction.
- Estimated inside one regime, it can **overstate** the risk for a period that stays calm.

None of this makes the rule useless — it makes it a **model**, with a stated assumption you can now check. That is the entire posture of this course: we derived `sqrt(T)` from independence honestly, so the moment independence fails we know *exactly* which term we dropped (the covariance) and *which direction* the error runs. A folk saying can't tell you that; a theorem can.

> **Short: the assumption is the product.** Whole subfields (GARCH models, realized-volatility estimators) exist to put the clustering back in — to model `Cov(ℓ_i, ℓ_j)` instead of assuming it away. You don't need them yet. You need to know that when you type `× sqrt(252)`, you have *assumed independence*, and that this assumption is the first thing to doubt when the market turns.

## 6.7 In the code

Open [`backend/marketdata/indicators.py`](../backend/marketdata/indicators.py). Here is the entire volatility builder — read it against the theorem:

```python
def _volatility_series(closes: List[float], window: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < window + 1:
        return out
    closes_arr = np.asarray(closes, dtype=float)
    rets = np.diff(closes_arr) / closes_arr[:-1]  # length n-1, rets[i] is return into bar i+1
    for i in range(window, n):
        w = rets[i - window:i]
        out[i] = float(np.std(w, ddof=1) * np.sqrt(252) * 100)
    return out
```

Read it in three moves, and it is *exactly* the math above:

1. **`rets = np.diff(closes_arr) / closes_arr[:-1]`** — this is the return series, `(p_t − p_{t-1}) / p_{t-1}`, the **simple** daily returns from Chapter 1 (`np.diff` gives the numerators `p_t − p_{t-1}`, dividing by `closes[:-1]` gives the denominators `p_{t-1}`). One shorter than `closes`, as it must be — the oldest day has nothing before it.
2. **`np.std(w, ddof=1)`** — the daily volatility `σ_d`, over the trailing `window` returns, with `ddof=1` (the sample standard deviation the preface promised). This is `σ_d`, nothing more.
3. **`* np.sqrt(252) * 100`** — and *there* is the theorem: annualize by `sqrt(252)` (that's `σ_d · sqrt(T)` with `T = 252`, §6.4), then `× 100` to state it as a percent. The code annualizes **exactly as we derived it** — not by some tuned constant, but by the square root of the trading year.

Two honest footnotes. First, the code uses **simple** returns, while the clean derivation used **log** returns (which add exactly). For the small daily moves that dominate here, `ℓ_t ≈ r_t` to well under a tenth of a percent (Chapter 1's `ln(1+x) ≈ x`), so `σ_d` is essentially identical either way — the approximation is invisible at daily scale. Second, the `if n < window + 1: return out` and the `range(window, n)` are the **warm-up**: you need `window` returns before you can report a number, so the early entries stay `None` rather than lie. And note the guard in the spec — `VOLATILITY` has a parameter minimum of `window: 2`, because a single return has no spread and `ddof=1` would divide by zero.

```python
"VOLATILITY": {"label": "Volatility (annualized)", "unit": "%", "defaults": {"window": 20},
               "help": "Annualized standard deviation of daily returns."},
```

The label says it out loud — *annualized standard deviation of daily returns* — which is now a sentence you can derive from scratch on a napkin.

## 6.8 Worked example

Take a tiny return series — four daily returns, chosen so the arithmetic is clean:

```
r_1 = +0.01     (+1%)
r_2 = −0.01     (−1%)
r_3 = +0.02     (+2%)
r_4 = −0.02     (−2%)
```

**Step 1 — the mean.** `r̄ = (0.01 − 0.01 + 0.02 − 0.02) / 4 = 0`. (We picked it that way; the average day is flat, so volatility is purely about the spread.)

**Step 2 — sum of squared deviations.** Since the mean is 0, each deviation *is* the return:

```
(0.01)² + (−0.01)² + (0.02)² + (−0.02)²
  = 0.0001 + 0.0001 + 0.0004 + 0.0004
  = 0.0010
```

**Step 3 — sample variance (ddof = 1).** Divide by `n − 1 = 3`, *not* by 4 — this is the preface's convention and the code's `ddof=1`:

```
σ_d² = 0.0010 / 3 = 0.00033333
```

**Step 4 — daily volatility.** Take the square root:

```
σ_d = sqrt(0.00033333) = 0.018257 = 1.8257%
```

**Step 5 — annualize with the theorem.** Multiply by `sqrt(252) ≈ 15.8745`:

```
σ_annual = 0.018257 × 15.8745 = 0.28983
```

and `× 100` for percent: **≈ 28.98%**, call it ~29%. That is exactly what `_volatility_series` returns for these four returns: `np.std(w, ddof=1)` gives `0.018257`, times `np.sqrt(252)` times `100` gives `28.98`. Four sleepy ±1–2% days imply a stock that swings about 29% in a typical *year* — because randomness accumulates as `sqrt(252)`, not `252`. If you had (wrongly) scaled by `252`, you'd have "predicted" a 460% annual swing, which is nonsense. The square root is doing real work.

## 6.9 Problem set

1. **Derive `sqrt(T)` for `T = 2` from scratch.** Start from `Var(X + Y) = Var(X) + Var(Y) + 2·Cov(X, Y)`. Let `X = ℓ_1` and `Y = ℓ_2` be two independent daily returns, each with variance `σ_d²`. Show `Var(ℓ_1 + ℓ_2) = 2σ_d²`, and therefore that the two-day volatility is `σ_d · sqrt(2)`. Where *exactly* in your derivation did you use independence? What is the two-day volatility if instead `Cov(ℓ_1, ℓ_2) = σ_d² / 2` (positively correlated days)?

2. **Clustering breaks the assumption.** Suppose a stock has one calm week (daily returns near `±0.5%`) followed by one stormy week (daily returns near `±3%`). Argue in words why the *magnitudes* `|ℓ_i|` are autocorrelated here even though the *signs* look random. Then explain which way `σ_d · sqrt(252)`, estimated over the calm week alone, will mislead you about the coming storm — over- or under-state the risk? Tie your answer to the dropped `Cov` term in §6.6.

3. **Both directions of the rule.** An asset has annualized volatility of 40%. (a) What is its daily volatility? (b) Its weekly (5-trading-day) volatility? (c) Its monthly (21-day) volatility? Show the `sqrt(T)` scaling in each and confirm your daily answer re-annualizes back to 40%.

4. **In the code.** By hand (or in a Python shell), run `_volatility_series` on the close series `[100, 102, 101, 103, 102]` with `window = 4`. Compute the four simple returns via `np.diff(closes)/closes[:-1]`, take `np.std(..., ddof=1)`, and multiply by `np.sqrt(252) * 100`. Why is only the *last* entry of the output non-`None`? What is the warm-up length, and why is it `window` and not `window + 1`?

5. **Log vs. simple.** For a single monstrous day from `100 → 130`, compute both the simple return `r` and the log return `ℓ`. How far apart are they? Now argue why, for the *20-day* windows the code actually uses, the choice between simple and log returns changes `σ_d` by a negligible amount — but why you should still reach for log returns the moment you start *chaining* returns across a long horizon (Chapter 1's telescoping).

---

Previous: [Chapter 5 — Momentum: RSI & MACD](05-momentum-rsi-macd.md) · Next: your indicator fired. Should you *believe* it? Volatility told you how big the noise is; now we learn to doubt a signal buried in it — [Chapter 7 — Signal vs. noise](07-signal-vs-noise.md).
