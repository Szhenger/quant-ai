# Chapter 1 — What is a market?

> **The question.** A number on a screen went from 150 to 165. Everyone says the stock "went up 10%." Up from what, measured how, and why should a *change* matter more than the *price*? Let's refuse to take any of it for granted.

---

## 1.1 A price is an agreement, not a property

Start with the thing itself. A **price** is not a property of a company the way mass is a property of a rock. A price is simply **the amount of money at which the most recent buyer and seller agreed to trade one share.** That's it. When you see `AAPL = 165.20`, it means: a moment ago, *someone* sold a share to *someone else* for \$165.20, and both walked away satisfied.

This has an immediate and underrated consequence: a price is a **timestamp of a human decision**, so a *sequence* of prices is a record of how a crowd's collective opinion changed. In this project a market is exactly that — a list of closing prices, one per trading day:

```
p_0, p_1, p_2, ..., p_t          (oldest to newest)
```

We only ever use **closing** prices — the last agreed price of each day — because they're the cleanest daily summary. Everything in QuantAI, every indicator in Chapters 3–6, is a function of this one list.

> **Short: why not use the price directly?** Because the price of one share is an accident of history — Apple could do a 10-for-1 split tomorrow and `165` becomes `16.50` with *nothing* about the company having changed. Any quantity we care about must be **invariant to that kind of relabeling.** Returns, which we build next, are. Prices are not. This is the single most important reason quant finance is built on returns.

## 1.2 From prices to returns

"It went up 10%" is a claim about a **ratio**, not a difference. The **simple return** from day `t−1` to day `t` is

```
r_t = (p_t − p_{t-1}) / p_{t-1}
```

Read it as: *the change, as a fraction of where we started.* If `p_{t-1} = 150` and `p_t = 165`, then `r_t = 15/150 = 0.10`, i.e. 10%. Notice what just happened — the answer, `0.10`, doesn't care whether we were counting in dollars, cents, or post-split dimes. We've thrown away the accidental units and kept the meaning. That's the invariance we demanded in the short above.

A percent change over a longer window `w` is the same idea, just comparing `p_t` to `p_{t-w}`:

```
percent change over w days = (p_t − p_{t-w}) / p_{t-w} × 100
```

**This is literally an indicator in the code** — `PCT_CHANGE` — and it is the simplest one we have, which is why we meet it first.

## 1.3 The log return, and why professionals prefer it

Here is a small puzzle. Suppose a stock rises 10% one day and falls 10% the next. Are you back where you started?

```
150  →  ×1.10  →  165  →  ×0.90  →  148.5
```

No — you're down to 148.5. Simple returns **don't add up**; a +10% and a −10% do not cancel, because they're percentages of different starting points. This is annoying, and over many days it becomes more than annoying. We'd love a notion of "return" that **adds**.

Enter the **log return**:

```
ℓ_t = ln( p_t / p_{t-1} ) = ln(p_t) − ln(p_{t-1})
```

Why does this help? Because logarithms turn multiplication into addition. Watch the whole window telescope:

```
ℓ_1 + ℓ_2 + ... + ℓ_t
   = [ln p_1 − ln p_0] + [ln p_2 − ln p_1] + ... + [ln p_t − ln p_{t-1}]
   = ln p_t − ln p_0
   = ln( p_t / p_0 )
```

The middle terms cancel in a perfect chain (a **telescoping sum**), and the total log return over any stretch is just the log of the final ratio. Log returns **add across time** — which is exactly the property simple returns lacked.

> **Short: aren't they basically the same number?** For small moves, yes. Calculus tells us `ln(1 + x) ≈ x` when `x` is small (it's the first term of the Taylor series). A daily move is usually a percent or two, so `ℓ_t ≈ r_t` to a very good approximation. The two agree on small days and *disagree, usefully,* on big ones — and the log version is the one that adds. Keep both in your head: **simple returns for a single step, log returns for chaining steps.**

There's a second reason professionals reach for log returns, and it's the whole reason Chapter 2 exists: **sums of independent random things become predictable.** If daily log returns are roughly independent, then a monthly log return is a *sum* of ~21 of them, and sums of independent random variables have a beautiful, known behavior (the Central Limit Theorem — Chapter 2). You cannot say that cleanly about *products* of simple returns. Turning "prices multiply" into "log returns add" is what makes the statistics tractable.

## 1.4 So what generates the prices? A model of randomness

If a price records a human decision, and humans are unpredictable, then prices contain **randomness**. Quant finance does not pretend to remove the randomness — it **models** it. The simplest honest model, and the one this project uses to generate its offline test market, is the **geometric random walk**:

```
p_t = p_{t-1} × (1 + shock_t)        where each shock_t is a small random number
```

Each day, multiply yesterday's price by "1 plus a little random wiggle." Take logs and it becomes the cleaner statement `ln p_t = ln p_{t-1} + (a small random number)` — a **random walk** in log-price. Prices don't move by adding random dollars; they move by multiplying by random percentages. That single modeling choice — *multiplicative, not additive* — is why finance lives in log-space, and it's why our synthetic prices can never go negative (you can't reach zero by repeatedly multiplying by positive numbers).

## 1.5 In the code

Open [`backend/feeder/providers.py`](../backend/feeder/providers.py). A market is this dataclass — a list of closes and their dates, nothing more:

```python
@dataclass
class PriceSeries:
    ticker: str
    closes: List[float]   # p_0 .. p_t, oldest to newest
    dates: List[str]
```

And here is the geometric random walk from §1.4, made real in the `SyntheticProvider` so the whole course runs offline and *deterministically* (the same ticker always produces the same history — we seed the randomness from a hash of the ticker symbol):

```python
rng = random.Random(self._seed(ticker))     # deterministic per ticker
price = 20.0 + (self._seed(ticker) % 480)    # a starting price
drift = rng.uniform(-0.0004, 0.0006)         # a tiny daily bias
vol   = rng.uniform(0.008, 0.03)             # how big the wiggles are
for _ in range(days):
    shock = rng.gauss(drift, vol)            # today's random wiggle
    price = max(0.5, price * (1 + shock))    # p_t = p_{t-1} × (1 + shock_t)
    closes.append(round(price, 2))
```

Line for line, that's `p_t = p_{t-1} × (1 + shock_t)`. The `drift` is a small average push (Chapter 4's "trend"); `vol` is the size of the noise (Chapter 6's "volatility"). You are looking at the two halves of the golden thread — *slow story plus fast noise* — as two variables in a loop.

Now the percent-change indicator, in [`backend/feeder/indicators.py`](../backend/feeder/indicators.py) — §1.2 verbatim:

```python
def _pct_change_series(closes, window):
    out = [None] * len(closes)
    for i in range(window, len(closes)):
        prev = closes[i - window]
        if prev:
            out[i] = float((closes[i] - prev) / prev * 100)   # (p_t − p_{t-w})/p_{t-w} × 100
    return out
```

The first `window` entries are `None` — the **warm-up** from the preface. You cannot compute a 20-day change on day 5; there's no day −15 to compare to. Every indicator has a warm-up, and handling it honestly (rather than fabricating a number) is a small mark of a serious system.

## 1.6 Worked example

Take a five-day close series and compute both returns by hand.

```
day:      0     1     2     3     4
close:  100   102    99   101   110
```

Simple returns:

```
r_1 = (102−100)/100 =  0.0200  =  +2.00%
r_2 = ( 99−102)/102 = −0.0294  =  −2.94%
r_3 = (101− 99)/ 99 =  0.0202  =  +2.02%
r_4 = (110−101)/101 =  0.0891  =  +8.91%
```

Log returns, and the telescoping check:

```
ℓ_1 = ln(102/100) =  0.01980
ℓ_2 = ln( 99/102) = −0.02985
ℓ_3 = ln(101/ 99) =  0.02000
ℓ_4 = ln(110/101) =  0.08536
                     ---------
sum               =  0.09531
check: ln(110/100) =  0.09531   ✓  (adds up to the whole-window log return)
```

The log returns sum to the total; the simple returns do not (try adding them — you get 0.0819, which is *not* `(110−100)/100 = 0.10`). The four-day `PCT_CHANGE` is the simple version: `(110−100)/100 × 100 = 10%`.

## 1.7 Problem set

1. **Invariance.** A stock trades at 80. It does a 4-for-1 split (price → 20, you now own 4× the shares). Show that the day's *return* is unchanged while the *price difference* is not. Why does this make returns the right unit for a rule that must work across all stocks?
2. **When do the two returns disagree?** Compute `r_t` and `ℓ_t` for a single day that goes from 100 to 200. How far apart are they? Now do 100 to 105. State in one sentence when you must be careful to use log returns.
3. **Telescoping.** Prove that `ℓ_1 + … + ℓ_t = ln(p_t / p_0)` for any prices, by writing out the sum as in §1.3. Where exactly did independence get used? (Trick question — it didn't; this is pure algebra. Independence shows up in Chapter 2, when we start taking *expectations* of these sums.)
4. **In the code.** Run the synthetic provider for two different tickers and confirm you get two different but *reproducible* price paths. Then implement a `_log_return_series` alongside `_pct_change_series` and check numerically that its cumulative sum equals `ln(p_t/p_0)`.
5. **A price that can't die.** Explain, using the multiplicative model of §1.4, why `SyntheticProvider` prices never hit zero. What would you have to change to allow bankruptcy, and why might that make the log-return model break down?

---

Next: prices are random, so a single return tells you almost nothing. What can we say about *many* of them? That's statistics, and it's [Chapter 2 — The statistics of returns](02-statistics-of-returns.md).
