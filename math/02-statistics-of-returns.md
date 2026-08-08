# Chapter 2 — The statistics of returns

*Prev: [Chapter 1 — What is a market?](01-what-is-a-market.md) · Next: [Chapter 3 — The z-score & mean reversion](03-zscore-and-mean-reversion.md)*

> **The question.** In Chapter 1 we decided prices are driven by randomness, and we even built a model that *generates* them from random wiggles. But if tomorrow's return is genuinely random — if we cannot predict it — then what on earth is there to know? Is quant finance just an elaborate way of admitting we don't know anything? Let's find out exactly what a random world lets us say.

---

## 2.1 One return is a coin flip; a thousand returns is a shape

Here is the reframe that makes everything else possible. A single return `r_t` is a **random variable** — it takes a value we can't know in advance, the way a coin flip takes heads or tails before you look. You are right to feel that predicting one flip is hopeless. It is.

But nobody serious tries to predict one flip. They ask a different question: *if I flip this coin a thousand times, what does the pile of results look like?* And that question has a crisp, stable answer even though every individual flip is a mystery. Roughly half heads. A predictable **shape** emerges from unpredictable **parts**.

So we stop asking "what is `r_t`?" and start asking "what is the *distribution* of returns?" A window of returns

```
x_1, x_2, ..., x_n          (n daily returns, our "sample")
```

is not a prophecy about any one day. It is a **sample** drawn from some underlying distribution, and from that sample we can estimate the distribution's **center** (where returns cluster) and its **spread** (how far they typically wander). Those two numbers — center and spread — are almost the entire game. Everything in Chapters 3 through 6 is built from them.

> **Short: sample vs. population.** The *population* is the true, usually-unknowable distribution the world draws from. The *sample* is the finite pile of data we actually have. We estimate population quantities from the sample and mark our estimates with a **hat**: `μ̂` (mu-hat) estimates the true mean `μ`; `σ̂` (sigma-hat) estimates the true std `σ`. The hat is a humility marker — it says "this is my best guess from limited data," not "this is the truth." Never drop the hat in your head, even when we drop it on the page.

## 2.2 The sample mean: the average drift

The **center** of our sample is the ordinary average — the **sample mean**:

```
μ̂ = (1/n) · Σ x_i = (x_1 + x_2 + ... + x_n) / n
```

That `Σ` is just "add them all up" (the Greek capital sigma from the notation box), and dividing by `n` gives the arithmetic average you have computed a thousand times. Nothing exotic yet.

But *interpret* it in our setting. Each `x_i` is a daily return, so `μ̂` is the **average daily return** over the window — the typical amount the thing drifts per day. This is the slow story from the golden thread, measured. If `μ̂ = 0.0004` (0.04% a day), the asset has a gentle upward drift; over 252 trading days that compounds into a meaningful climb. If `μ̂ ≈ 0`, the thing is going nowhere on average, however violently it thrashes day to day.

Recall the synthetic market from Chapter 1: `drift = rng.uniform(-0.0004, 0.0006)`. That `drift` is precisely the population mean `μ` we are now trying to *recover* from data with `μ̂`. The code that made the prices, and the statistics that read them back, are two ends of the same rope.

## 2.3 Spread: deviation, variance, and standard deviation

The mean tells you where returns cluster. It says nothing about how *tightly*. Two assets can share a mean of `0` while one barely twitches and the other lurches ±5% a day. We need to measure spread.

Start with the honest raw material: the **deviation** of each point from the mean,

```
d_i = x_i − μ̂
```

— how far above or below average that day was. You might think to just average the deviations. Don't: they always sum to exactly zero (the positives and negatives cancel — that's what "mean" means), so their average is a useless `0` every time. The signs are sabotaging us.

The fix is to kill the signs by **squaring** before averaging. The **sample variance** is (almost) the average squared deviation:

```
σ̂² = (1/(n−1)) · Σ (x_i − μ̂)²
```

Squaring makes every term non-negative, so they can no longer cancel; a big deviation (in either direction) contributes a big square. The variance is therefore a genuine measure of spread — small when points hug the mean, large when they scatter. (Why we divide by `n−1` and not `n` is the subject of §2.4 — hold that thought.)

Variance has one cosmetic problem: its units are *squared*. If `x_i` is a return in percent, `σ̂²` is in percent-squared, which means nothing to a human. So we take the square root to get back to normal units — the **standard deviation**:

```
σ̂ = sqrt(σ̂²) = sqrt( (1/(n−1)) · Σ (x_i − μ̂)² )
```

Read `σ̂` as **the typical distance of a data point from the mean**, in the very same units as the data. That is the sentence to memorize. If daily returns have `σ̂ = 1.5%`, then "a normal day" moves the price about 1.5% away from its average drift, up or down. In finance `σ̂` of returns has a special name — **volatility** — and it gets its own chapter (Chapter 6). For now it is simply *spread, in honest units*.

> **Short: why squares and not absolute values?** You *could* measure spread with the average of `|x_i − μ̂|` (the "mean absolute deviation"), and it's perfectly sensible. Squaring wins for two deep reasons we'll cash in later: squared errors have clean *derivatives* (calculus loves them — the mean is literally the number that minimizes total squared deviation), and variance has the magical additivity property of §2.5 that absolute deviation lacks. The whole edifice of Chapter 6's "square-root-of-time" rule stands on that additivity. So we pay the small price of squaring now to collect a large reward later.

## 2.4 Why n − 1? Bessel's correction, derived by intuition

Look again at the variance formula and notice something suspicious: we divide by `n − 1`, not `n`. An "average" of `n` squared deviations that divides by `n − 1`? That is not an average. Why the sabotage?

Here is the honest reason, and it is worth slowing down for because it recurs everywhere in statistics. To compute each deviation `x_i − μ̂`, we needed the mean. But we didn't know the *true* mean `μ` — we used `μ̂`, which we **computed from the very same data** we're now measuring deviations against. And `μ̂` is not just any number: it is, by construction, the number that sits as close as possible to *these specific* data points. The sample mean is the center of gravity of the sample.

So the deviations we measure — distances from `μ̂` — are, on average, **slightly smaller** than the distances from the true mean `μ` would have been. Our sample was, in effect, allowed to move the target to wherever it was already clustered. Measuring spread from that home-field target flatters us. If we divided by `n`, we would systematically **underestimate** the true spread — a *bias*, a error that doesn't wash out no matter how you draw the sample.

Dividing by `n − 1` instead of `n` inflates the estimate by exactly the right amount to cancel that bias. The slogan:

> **You spent one degree of freedom estimating the mean, so you have `n − 1` left to estimate the spread.**

The "degrees of freedom" picture makes it concrete. Suppose I tell you `n = 3` returns have mean `μ̂ = 0`, and I reveal the first two: `x_1 = 2`, `x_2 = −5`. You do not need me to tell you `x_3` — it is *forced* to be `+3`, because the three must average to `0`. Once the mean is fixed, only `n − 1` of the data points are free to vary; the last one is determined. There are genuinely only `n − 1` independent pieces of spread-information in the sample, so we divide by `n − 1`.

> **Short: does it matter in practice?** For a 3-day window, dividing by 2 instead of 3 changes the variance by 50% — enormous. For a 250-day window, `n` vs. `n−1` differ by less than half a percent — negligible. Bessel's correction matters most exactly when data is scarce, which is when you can least afford to fool yourself. In our worked example (§2.6) the two answers visibly disagree; on a year of data they'd round to the same thing. This is why the code doesn't gamble on it — it always uses the unbiased version.

And the code does exactly this. `numpy`'s standard-deviation function takes an argument `ddof` — "delta degrees of freedom" — and `ddof=1` means "divide by `n − 1`." You will see `.std(ddof=1)` on every spread computation in QuantAI. That single argument is Bessel's correction, made real. When you spot it in §2.7, you'll know it isn't decoration; it's the difference between an honest estimate and a flattering one.

## 2.5 Three rules you will reuse forever

We need a small algebra of expectation and variance. These come straight from the discrete-probability toolbox in the preface; we state them, and we *derive* the one that matters most. Here `E[·]` is expectation (the long-run average) and `Var(·) = E[(X − E[X])²]` is the true variance.

**Rule 1 — Linearity of expectation.** For constants `a, b`,

```
E[aX + b] = a·E[X] + b
```

Scaling and shifting a random variable scales and shifts its average the same way. If you double every return and add 1, the mean doubles and gains 1. Intuitive, and always true — even when variables are *dependent*, which makes linearity of expectation quietly one of the most powerful tools in probability.

**Rule 2 — Variance ignores shifts and squares scales.** For constants `a, b`,

```
Var(aX + b) = a²·Var(X)
```

Adding a constant `b` slides the whole distribution sideways without changing its spread, so `b` vanishes. Multiplying by `a` stretches every deviation by `a`, and since variance is built from *squared* deviations, it grows by `a²`. (Take square roots: `std(aX + b) = |a|·std(X)` — spread scales linearly. This exact fact powers the square-root-of-time rule in Chapter 6.)

**Rule 3 — the keystone: variances of independent things add.** This is the one Chapter 6 is built on, so we earn it in full. Take two random variables `X` and `Y` and ask for the variance of their sum. Write `μ_X = E[X]`, `μ_Y = E[Y]`. By definition,

```
Var(X + Y) = E[ ( (X + Y) − (μ_X + μ_Y) )² ]
           = E[ ( (X − μ_X) + (Y − μ_Y) )² ]
```

Now expand the square with `(a + b)² = a² + 2ab + b²`, where `a = X − μ_X` and `b = Y − μ_Y`, and push the expectation through each term (linearity, Rule 1):

```
Var(X + Y) = E[(X − μ_X)²] + 2·E[(X − μ_X)(Y − μ_Y)] + E[(Y − μ_Y)²]
           = Var(X)  +  2·Cov(X, Y)  +  Var(Y)
```

The middle term has a name — the **covariance** `Cov(X, Y) = E[(X − μ_X)(Y − μ_Y)]` — and it measures whether `X` and `Y` tend to stray from their means *together* (positive) or in opposition (negative). We have derived, with no skipped steps, the completely general fact:

```
Var(X + Y) = Var(X) + Var(Y) + 2·Cov(X, Y)
```

Now apply the hypothesis that makes finance tractable. If `X` and `Y` are **independent** — if knowing one tells you nothing about the other — then they don't co-move at all, and `Cov(X, Y) = 0`. The cross term evaporates:

```
Var(X + Y) = Var(X) + Var(Y)          (X, Y independent)
```

**Variances of independent random variables add.** Read it, box it, keep it. Stack `n` independent daily returns and the variance of their sum is `n` times a single day's variance — and *that* single sentence, square-rooted, is the entire "square root of time" rule of volatility. Chapter 6 does nothing but cash in this line. We are foreshadowing hard on purpose: when you get there, you should feel you already own the theorem.

## 2.6-preview — why the bell curve keeps showing up

We have a center (`μ̂`) and a spread (`σ̂`). To say anything about *probabilities* — "how often does a return exceed 3%?" — we need a **shape** for the distribution. The workhorse shape is the **normal distribution**, the bell curve:

```
          ▁▂▃▅▇█▇▅▃▂▁
      −3σ  −2σ  −σ   μ̂   σ   2σ  3σ
```

Symmetric, single-humped, centered at `μ̂`, with a width set by `σ̂`. Its most useful feature is the **68–95–99.7 rule**: for normally-distributed data,

```
about 68%  of values fall within  1σ  of the mean   (μ̂ ± 1σ̂)
about 95%  of values fall within  2σ  of the mean   (μ̂ ± 2σ̂)
about 99.7% of values fall within 3σ  of the mean   (μ̂ ± 3σ̂)
```

So under the normal model, landing more than `2σ̂` from the mean happens only ~5% of the time, and more than `3σ̂` only ~0.3% — genuinely rare. This table is the backbone of the *next* chapter: it's what lets us call a day "unusual" with a number instead of a shrug.

But *why* should returns be normal at all? We didn't assume it. The answer is one of the most remarkable theorems in mathematics.

**The Central Limit Theorem (CLT), stated informally but correctly.** Add up many independent random variables, each of comparable size and none dominating the rest, and the distribution of their *sum* approaches a normal distribution — **regardless of the shape of the individual variables**. The pieces can be lopsided, discrete, weird; the sum smooths out into a bell anyway. It is why so many measured quantities in nature — heights, errors, noise — are bell-shaped: they are each a sum of many small independent contributions.

Now recall Chapter 1's punchline: **log returns add across time.** A monthly log return is the sum of ~21 daily log returns. If those daily returns are roughly independent and comparably sized, the CLT says the monthly return should look approximately normal — *even if a single day's return is not*. This is the deep reason professionals reach for log returns and lean on the normal model: adding is exactly the operation the CLT rewards. Chapter 1 turned "prices multiply" into "log returns add"; the CLT turns "log returns add" into "sums look bell-shaped." The two chapters click together here.

> **Short: the normal model is a model, not a law.** Real returns have **fatter tails** than the bell curve — crashes of `−5σ`, which the normal model says should essentially never occur, happen far too often to be a coincidence. The 1987 crash was, by the normal model, an event so unlikely it shouldn't happen once in billions of years. It happened on a Monday. So we use the normal distribution the way a physicist uses a frictionless plane: as a clean, computable *first* model whose failures are themselves informative. Chapter 7 is largely about respecting those failures. Trust the bell curve for the middle of the distribution; distrust it in the tails.

## 2.7-preview — the Law of Large Numbers, and the tension it hides

One more theorem, and it justifies the whole enterprise of collecting data. The **Law of Large Numbers (LLN)** says:

```
as n grows,   μ̂  →  μ        (the sample mean converges to the true mean)
```

The more independent samples you average, the closer your estimate gets to the truth, and the estimate stops jumping around. This is why more data sharpens `μ̂` and `σ̂`: each new day shrinks the wobble in your estimate. If the world held still, you would simply gather more and more data and know `μ` to any precision you liked.

But markets do **not** hold still — and here is the tension that separates textbook statistics from real quant work. The LLN promises convergence *only if every sample is drawn from the same distribution*. Estimate `μ̂` from ten years of data and you get a beautifully precise number... about a company, an economy, and a regime that **may no longer exist**. A long window is more statistically *accurate* about a world that might be gone. A short window tracks today's world but is *noisy* — few samples, wide wobble, weak LLN.

That trade-off — long-and-stale versus short-and-noisy — has no clean solution, and choosing a window length is one of the genuinely hard, genuinely judgment-laden decisions in the field. Every indicator in this codebase takes a `window` parameter, and now you know that parameter is not a detail: it is a bet about how fast the world is changing. Hold this tension; we return to it every time we pick a number of days.

## 2.8 Standardization — a one-line preview of Chapter 3

We now have everything we need to answer "is this an unusual day?" Combine the center and the spread into a single unit-free score by measuring *how many standard deviations from the mean* a value sits:

```
z = (x − μ̂) / σ̂
```

Subtract the mean to center it, divide by the std to rescale it into units of "sigmas." A `z` of `−2` means "two standard deviations below average" — which, by the 68–95–99.7 rule, happens on only about 2.5% of days. That is the **z-score**, it is the first real indicator in the code, and it gets the whole of the next chapter.

## 2.9 In the code

Open [`backend/marketdata/indicators.py`](../backend/marketdata/indicators.py). The library is built on `numpy` for exactly one reason: it gives us `.mean()` and `.std(ddof=1)` — the sample mean of §2.2 and the Bessel-corrected sample standard deviation of §2.3–2.4 — as fast, correct, one-line primitives, so the indicator code reads like the math.

Here is the z-score builder. Ignore the surrounding loop for now (that's Chapter 3's rolling window) and watch the two statistics land on lines that mirror the formulas exactly:

```python
def _zscore_series(closes: List[float], window: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        w = np.asarray(closes[i - window + 1:i + 1], dtype=float)
        std = w.std(ddof=1)
        out[i] = 0.0 if std == 0 else float((closes[i] - w.mean()) / std)
    return out
```

`w.mean()` is `μ̂ = (1/n)·Σ x_i`. `w.std(ddof=1)` is `σ̂ = sqrt( (1/(n−1))·Σ(x_i − μ̂)² )` — and that `ddof=1` **is** Bessel's correction from §2.4, the difference between an honest estimate and a flattering one, expressed as a single keyword argument. The last line is the standardization `z = (x − μ̂)/σ̂` from §2.8. (The `std == 0` guard handles a perfectly flat window; we'll dwell on it next chapter.)

The same `.std(ddof=1)` appears wherever spread is measured. Here it is again in the volatility builder, which we'll unpack fully in Chapter 6 but can already read the heart of:

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

`np.diff(closes_arr) / closes_arr[:-1]` builds the simple returns `r_t` from Chapter 1, then `np.std(w, ddof=1)` is the sample standard deviation of those returns — spread of returns, i.e. volatility. The `* np.sqrt(252)` is the square-root-of-time rule you now know is coming (Rule 3, §2.5, square-rooted), and `* 100` puts it in percent. Every character of that line is a theorem from this chapter or its sequel. That is the payoff of doing the math first: the code stops being a black box and becomes a sentence you can read aloud.

## 2.10 Worked example

Take five daily returns, in percent, and compute the center and spread by hand.

```
x_1 = +2,   x_2 = −1,   x_3 = +3,   x_4 = −2,   x_5 = +3      (n = 5)
```

**Step 1 — the mean.** Add and divide by `n`:

```
Σ x_i = 2 + (−1) + 3 + (−2) + 3 = 5
μ̂ = 5 / 5 = 1.0        (a +1.0% average daily drift)
```

**Step 2 — the deviations, and a sanity check.** Subtract `μ̂ = 1` from each:

```
d_1 = 2 − 1 =  1
d_2 = −1 − 1 = −2
d_3 = 3 − 1 =  2
d_4 = −2 − 1 = −3
d_5 = 3 − 1 =  2
check: Σ d_i = 1 − 2 + 2 − 3 + 2 = 0   ✓   (deviations must sum to zero)
```

The check confirms why we can't just average deviations — they cancel to `0`. So we square.

**Step 3 — squared deviations, summed:**

```
Σ d_i² = 1² + (−2)² + 2² + (−3)² + 2² = 1 + 4 + 4 + 9 + 4 = 22
```

**Step 4 — variance and std, the honest (n−1) way:**

```
σ̂² = 22 / (n − 1) = 22 / 4 = 5.50            (percent-squared — units nobody feels)
σ̂  = sqrt(5.50) = 2.345                       (percent — "a typical day is ~2.3% off the drift")
```

**Step 5 — see Bessel's correction bite.** Compute the naïve (divide-by-`n`) version and compare:

```
naïve variance = 22 / 5 = 4.40     →   naïve std = sqrt(4.40) = 2.098
honest variance = 22 / 4 = 5.50    →   honest std = sqrt(5.50) = 2.345
```

The naïve version is smaller — it *underestimates* the spread, exactly the bias §2.4 warned about — and with only `n = 5` points the gap is large (2.098 vs. 2.345, about 12% on the std). The code's `ddof=1` chooses the honest 2.345 every time. On a 250-day window the two would agree to three decimals; here, where data is scarce, choosing correctly matters most.

## 2.11 Problem set

1. **n vs. n−1 on a tiny sample.** Take the three returns `x = [4, 0, 2]` (percent). Compute `μ̂`, then compute the variance *both* ways — dividing by `n = 3` and by `n − 1 = 2` — and the two standard deviations. By what percentage does the honest (n−1) std exceed the naïve one? Explain in one sentence, using the degrees-of-freedom idea, why the gap is so large here and would be tiny for a 200-day window.

2. **The 68–95–99.7 rule in action.** Suppose daily returns are normal with `μ̂ = 0.05%` and `σ̂ = 1.2%`. (a) Give the interval that should contain about 95% of days. (b) A day posts a `−2.6%` return. How many standard deviations below the mean is that (compute the `z`), and roughly how surprising is it under the normal model? (c) In one sentence, explain why a real market posts such days far more often than the normal model predicts, and name the chapter that takes that seriously.

3. **The variance keystone, applied.** Let `X` and `Y` be two independent daily log returns, each with variance `σ² = (1.5%)²`. Use Rule 3 to find the variance and then the standard deviation of the two-day return `X + Y`. By what factor did the *std* grow going from one day to two? Now redo it assuming instead `Cov(X, Y) = +0.5·σ²` (the days move together): does the two-day std grow by more or less? What does that tell you about diversification?

4. **Linearity and scaling.** A colleague reports returns as *fractions* (`0.02`) but you want them in *percent* (`2`), i.e. you multiply every `x_i` by 100. Using Rules 1 and 2, state exactly what happens to `μ̂`, to `σ̂²`, and to `σ̂` under this rescaling — and confirm your answers are consistent with what you'd get by just recomputing from scratch. Why does this make the *z*-score (§2.8) immune to the choice of units?

5. **In the code.** Read `_zscore_series` in [`indicators.py`](../backend/marketdata/indicators.py). Feed it the six closes `[101, 100, 102, 100, 101, 90]` with `window = 6` and predict the single non-`None` value it returns *before* running it (you may peek ahead to Chapter 3, or just apply §2.2–2.8 directly). Then change `ddof=1` to `ddof=0` in a scratch copy and recompute: does the magnitude of the z-score go up or down, and why does that match the direction of the bias you found in Problem 1?

---

*Prev: [Chapter 1 — What is a market?](01-what-is-a-market.md) · Next: [Chapter 3 — The z-score & mean reversion](03-zscore-and-mean-reversion.md)*

We can now put a number on "the center" and "the spread." Next we combine them into the first real trading signal — and meet the assumption that can quietly wreck it. Onward to [Chapter 3 — The z-score & mean reversion](03-zscore-and-mean-reversion.md).
