# Chapter 4 — Trend & moving averages

> **The question.** A price wiggles up and down every single day. Some of that wiggle is a *trend* — the slow story, the thing actually changing — and some is just noise, the crowd's daily indecision. How do you measure the trend **without fooling yourself** into seeing one in pure noise? That's the whole game, and the moving average is our first honest tool for it.

---

## 4.1 The golden thread, one more time

The preface gave you a sentence to keep:

> A price is the sum of a **slow story** (the trend) and **fast noise** (randomness).

Say it as a little equation. On day `t`,

```
p_t  =  trend_t  +  noise_t
```

where `trend_t` drifts slowly and smoothly, and `noise_t` is a small, roughly-independent random jolt each day — mean zero, no memory of yesterday. We can't see the two pieces separately; we only ever see their sum. The job of this chapter is to **recover the slow part and throw away the fast part** — and to know *why* the tool we use actually does that, rather than trusting it because everyone else does.

## 4.2 Why averaging is a noise filter (this is the real reason)

Here is the key idea, and it comes straight out of Chapter 2. Suppose I take the last `w` days and just **average their prices**:

```
A_t  =  (1/w) · ( p_{t−w+1} + p_{t−w+2} + ... + p_t )
```

Plug in `p_i = trend_i + noise_i` and split the sum:

```
A_t  =  (1/w) · Σ trend_i   +   (1/w) · Σ noise_i
        \_______________/       \_______________/
         average of the trend     average of the noise
```

Look at the two pieces separately.

**The trend piece survives.** Over a short window the trend is *nearly constant* — that's what "slow" means. Averaging a bunch of nearly-equal numbers gives you back roughly that same number. So `(1/w) · Σ trend_i ≈ trend_t`. The slow story passes through the filter almost untouched.

**The noise piece shrinks.** This is the beautiful part, and it's Chapter 2's variance-of-a-mean result cashed in. The `noise_i` are roughly independent, each with the same standard deviation `σ`. The **mean of `w` independent random variables** has variance `σ²/w`, hence standard deviation

```
std( average of w noises )  =  σ / sqrt(w)
```

> **Short: where does the `1/sqrt(w)` come from?** For independent variables, *variances add*. The sum of `w` of them has variance `w·σ²`. Dividing the sum by `w` divides the variance by `w²` (variance scales by the square of a constant), leaving `w·σ² / w² = σ²/w`. Take the square root for the standard deviation: `σ/sqrt(w)`. This single fact — noise shrinks like `1/sqrt(w)` while the signal stays put — is *why* averaging works. It is the same `sqrt` that will return, transformed, as the square-root-of-time rule in [Chapter 6](06-volatility.md).

So averaging `w` days does two things at once: it leaves the trend alone and it shrinks the noise by a factor of `sqrt(w)`. Average 4 days and the noise halves. Average 16 days and it's cut to a quarter. A moving average is not a superstition — it is a **noise filter with a provable amount of filtering**.

## 4.3 The simple moving average (SMA)

That average `A_t` above, computed fresh each day over a sliding `w`-day window, *is* the **simple moving average**:

```
SMA_w(t)  =  (1/w) · Σ_{i = t−w+1}^{t}  p_i
```

Flat weights: every one of the last `w` closes counts exactly `1/w`. Slide the window forward one day, drop the oldest price, add the newest, re-average. The bigger the `w`, the smoother the line — and, by §4.2, the more noise you've killed.

But smoothness is never free. Here is the bill.

**Lag.** The SMA weights a 20-day-old price *exactly as much* as today's. So the SMA doesn't report "the trend today" — it reports the trend **at the center of its window**, which for a `w`-day window is about `w/2` days in the past. If the real trend is genuinely rising in a straight line, the SMA sits below it, trailing by roughly `w/2` days' worth of climb.

> **Short: the lag is the price of the smoothing.** You cannot escape it by being clever with a flat average. More smoothing (bigger `w`) means more noise cancelled *and* more lag — they rise together. Every trend tool in existence lives on this trade-off; the EMA in the next section just buys a slightly better exchange rate.

## 4.4 The exponential moving average (EMA)

The SMA's flat weighting is what causes the lag: a price from three weeks ago drags on today's number with full force. The natural fix is to **weight recent prices more** and let old ones fade. The cleanest way to do that is a one-line recurrence:

```
EMA_t  =  α · p_t  +  (1 − α) · EMA_{t−1}
```

with `α` (alpha) a number between 0 and 1 called the **smoothing factor**. Read it as: today's EMA is a blend — a fraction `α` of today's fresh price, plus a fraction `(1 − α)` of "everything I believed yesterday." When `α` is large the EMA is jumpy and hugs the price; when `α` is small it's sluggish and smooth.

Why is this "exponential"? Expand the recurrence by substituting `EMA_{t−1}`, then `EMA_{t−2}`, and so on:

```
EMA_t = α·p_t + (1−α)·EMA_{t−1}
      = α·p_t + (1−α)·[ α·p_{t−1} + (1−α)·EMA_{t−2} ]
      = α·p_t + α(1−α)·p_{t−1} + α(1−α)²·p_{t−2} + α(1−α)³·p_{t−3} + ...
```

The weight on the price `k` days back is

```
weight on p_{t−k}  =  α · (1 − α)^k
```

a **geometric decay**. Today's price gets weight `α`, yesterday's `α(1−α)`, the day before `α(1−α)²`, and so on — each older day multiplied by another factor of `(1−α)`. Old prices never get fully forgotten; they just fade smoothly toward zero. (And the weights are honest: they sum to `α · Σ_{k≥0}(1−α)^k = α · 1/(1−(1−α)) = α · 1/α = 1`, a proper weighted average.)

## 4.5 Deriving `α = 2/(span + 1)`

Now the question that trips everyone up: if I want an EMA that's "about as smooth as a 20-day SMA," what `α` do I use? The code answers with `alpha = 2/(span+1)`. Let's *derive* that, so it stops being magic.

The honest way to compare an SMA and an EMA is by their **average age** — the average number of days old a price is, weighted by how much the filter cares about it. Two filters with the same average age react to new information at about the same speed.

**Average age of the EMA.** Using the weights from §4.4, the price `k` days back has weight `α(1−α)^k`, so

```
avg age(EMA)  =  Σ_{k ≥ 0}  k · α(1−α)^k  =  α · Σ_{k ≥ 0} k·(1−α)^k
```

We need the identity `Σ_{k ≥ 0} k·x^k = x / (1−x)²` (valid for `|x| < 1`). With `x = (1 − α)`, so that `1 − x = α`:

```
avg age(EMA)  =  α · (1−α) / (1 − (1−α))²
              =  α · (1−α) / α²
              =  (1 − α) / α
```

**Average age of the SMA.** An SMA of length `span` weights the last `span` prices equally, so their ages `0, 1, 2, …, span−1` each carry weight `1/span`. The average age is just the average of those integers:

```
avg age(SMA)  =  (1/span) · (0 + 1 + ... + (span−1))
              =  (1/span) · (span−1)·span/2
              =  (span − 1) / 2
```

**Match them.** Set the two average ages equal and solve for `α`:

```
(1 − α) / α  =  (span − 1) / 2

2(1 − α)     =  α (span − 1)          multiply both sides by 2α
2 − 2α       =  α·span − α
2            =  α·span − α + 2α
2            =  α·span + α
2            =  α (span + 1)
α            =  2 / (span + 1)          ✓
```

There it is. `α = 2/(span+1)` is exactly the `α` that makes an EMA carry the *same average age* as an SMA of length `span`. That is why a "12-day EMA" is a meaningful phrase, and it is precisely the line `alpha = 2.0/(span+1.0)` you'll read in the code below.

> **Short: sanity-check it.** `span = 1` gives `α = 1` — the EMA is just the raw price (average age 0, no smoothing at all). A big `span` gives a tiny `α`, a long memory, a sluggish line. Both extremes match your intuition, which is how you know the algebra didn't lie.

## 4.6 Crossovers: turning two averages into a signal

A single moving average tells you where the trend has been. To catch the trend **turning**, compare a **fast** average (small window, low lag, twitchy) against a **slow** one (big window, high lag, calm). Their difference is one number:

```
SMA_CROSS(t)  =  SMA_fast(t)  −  SMA_slow(t)
```

Think about its sign. When the fast average is **above** the slow one, recent prices are pulling ahead of the longer-term average — momentum is upward. When it's **below**, recent prices are sagging beneath the long-term line.

The interesting events are the **crossings of zero**:

- `SMA_CROSS` goes from negative to positive → the fast line rises *through* the slow line → a **golden cross**, the classic "a new uptrend may be starting" signal.
- `SMA_CROSS` goes from positive to negative → the fast line drops *through* the slow line → a **death cross**, the downtrend flag.

Notice what "crossing" requires: you cannot tell a crossing from a mere positive value using **today alone**. `SMA_CROSS = +0.2` today could be a fresh golden cross (it was negative yesterday) or just the boring middle of an uptrend (it was `+0.5` yesterday). You must compare **today's value against yesterday's**. That is the entire reason the operators `cross_above` and `cross_below` exist in the engine, and why they demand a `previous` value — we'll see that machinery in the code.

## 4.7 In the code

Open [`backend/marketdata/indicators.py`](../backend/marketdata/indicators.py). Here is the simple moving average — §4.3, a sliding flat average, with the first `window−1` slots left as `None` for the warm-up:

```python
def _sma(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        out[i] = float(np.mean(closes[i - window + 1:i + 1]))
    return out
```

The slice `closes[i - window + 1 : i + 1]` is exactly the window `p_{i−w+1} … p_i`, and `np.mean` is the `(1/w)·Σ`. Nothing hidden.

Now the exponential moving average — the §4.4 recurrence, seeded with the first price and carrying `α = 2/(span+1)` straight from §4.5:

```python
def _ema(values: List[float], span: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return arr
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(arr)
    out[0] = arr[0]
    for i in range(1, arr.size):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out
```

That middle line, `out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]`, is `EMA_t = α·p_t + (1−α)·EMA_{t−1}` character for character. And `alpha = 2.0 / (span + 1.0)` is the number we sweated to derive — now you can never be told it's arbitrary.

Finally the crossover series — §4.6, one fast SMA minus one slow SMA, with `None` wherever either isn't warmed up yet:

```python
def _sma_cross_series(closes: List[float], fast: int, slow: int) -> List[Optional[float]]:
    f = _sma(closes, fast)
    s = _sma(closes, slow)
    return [(fv - sv) if (fv is not None and sv is not None) else None for fv, sv in zip(f, s)]
```

The *sign* of this series is the trend's direction; the *moment it changes sign* is the golden or death cross. The `cross_above` / `cross_below` operators (in `evaluate_condition`, and the reason each carries a `previous`) are what fire on exactly that moment.

## 4.8 Worked example

Take a seven-day close series that dips and then recovers:

```
day:      0     1     2     3     4     5     6
close:   20    18    16    15    18    19    22
```

**A 3-day SMA** (`window = 3`; valid from day 2 on):

```
SMA_3(2) = (20+18+16)/3 = 54/3 = 18.000
SMA_3(3) = (18+16+15)/3 = 49/3 = 16.333
SMA_3(4) = (16+15+18)/3 = 49/3 = 16.333
SMA_3(5) = (15+18+19)/3 = 52/3 = 17.333
SMA_3(6) = (18+19+22)/3 = 59/3 = 19.667
```

**A small EMA**, `span = 3`, so `α = 2/(3+1) = 0.5` (seed with the first price):

```
EMA(0) = 20                                (seed)
EMA(1) = 0.5·18 + 0.5·20      = 19.000
EMA(2) = 0.5·16 + 0.5·19.000  = 17.500
EMA(3) = 0.5·15 + 0.5·17.500  = 16.250
EMA(4) = 0.5·18 + 0.5·16.250  = 17.125
EMA(5) = 0.5·19 + 0.5·17.125  = 18.063
EMA(6) = 0.5·22 + 0.5·18.063  = 20.031
```

Notice on day 6: the price jumped to 22, and the EMA (`20.03`) has already climbed higher than the SMA (`19.67`) — the EMA weights that fresh jump more, so it reacts faster. That's the lower lag we paid the geometric weights for.

**A crossover.** Now watch a **fast 2-day** SMA against a **slow 3-day** SMA:

```
day:            2       3       4       5       6
SMA_2:       17.000  15.500  16.500  18.500  20.500
SMA_3:       18.000  16.333  16.333  17.333  19.667
SMA_CROSS:   −1.000  −0.833  +0.167  +1.167  +0.833
             (fast − slow)
```

Between day 3 and day 4 the spread goes from `−0.833` to `+0.167` — it **crosses above zero**. That's a **golden cross** on day 4: the fast average has risen up through the slow one, flagging the turn from the dip back to strength. And see why you needed yesterday: on day 4 the value is only `+0.167`, but it's the *jump from a negative previous* that makes it a cross rather than routine. `cross_above` checks exactly `previous ≤ 0 < value`, i.e. `−0.833 ≤ 0 < 0.167` — true. On day 5 the value is a bigger `+1.167`, but `previous` was already positive, so it is *not* a fresh cross.

## 4.9 Problem set

1. **The average-age identity.** Prove `Σ_{k ≥ 0} k·x^k = x/(1−x)²` for `|x| < 1`. (Hint: start from the geometric series `Σ x^k = 1/(1−x)`, and differentiate both sides with respect to `x`; then multiply by `x`.) This is the one fact §4.5 leaned on — own it and the `α = 2/(span+1)` derivation is yours forever.

2. **SMA lag, made concrete.** Suppose the *true* trend rises in a perfectly straight line, `trend_t = 100 + t`, with no noise at all. Show that `SMA_w(t) = 100 + t − (w−1)/2`, i.e. the SMA trails the true line by exactly `(w−1)/2`. (Compute the average of `100+(t−w+1), …, 100+t`.) Explain in one sentence why *more smoothing must mean more lag*.

3. **Noise shrinkage.** Chapter 2 gave you `std(mean of w independent noises) = σ/sqrt(w)`. If a single day's noise has `σ = $1.00`, how many days must you average to cut the noise standard deviation to `$0.25`? What does §4.3's lag argument say that costs you?

4. **EMA never forgets.** Using `weight on p_{t−k} = α(1−α)^k` with `α = 0.5`, compute the total weight resting on all prices *older than 3 days* (i.e. `k ≥ 4`). (Hint: it's a geometric tail, `Σ_{k≥4} α(1−α)^k = (1−α)^4`.) Is it zero? What does that tell you about how an EMA differs from an SMA, which forgets everything past `w` days instantly?

5. **Build a crossover by hand.** Take `closes = [10, 11, 13, 12, 10, 9, 11, 14]`. Compute a fast 2-day and slow 4-day SMA, form `SMA_CROSS`, and find every day on which `cross_above 0` or `cross_below 0` fires. For each, name it a golden or death cross and state the `previous` and `value` that made `evaluate_condition` return `True`.

---

Previous: [Chapter 3 — The z-score & mean reversion](03-zscore-and-mean-reversion.md) · Next: prices don't just trend — trends *exhaust themselves*, and there's a way to feel that momentum draining. That's [Chapter 5 — Momentum: RSI & MACD](05-momentum-rsi-macd.md).
