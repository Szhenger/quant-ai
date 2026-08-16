# QuantAI — Math (the quant course)

This folder is the mathematical heart of the project: eight chapters that build
quantitative finance **from first principles**, in the spirit of CS50 — no step skipped
because it's "standard", every formula derived before it's used, and every derivation
pointing at the exact line of code in [`backend/feeder/indicators.py`](../backend/feeder/indicators.py)
that computes it.

You need nothing beyond CS50x plus three pieces of undergraduate math: basic calculus,
vectors-and-averages linear algebra, and discrete probability. [Chapter 0](00-preface.md)
states precisely what's assumed and fixes the notation used everywhere else — read it
first, it's five minutes.

## The chapters

| # | Chapter | The question it answers |
|---|---|---|
| 0 | [Preface](00-preface.md) | How do I read this, and what do I need? |
| 1 | [What is a market?](01-what-is-a-market.md) | What *is* a price, and what does it mean for it to "go up"? |
| 2 | [The statistics of returns](02-statistics-of-returns.md) | If prices are random, what can we possibly know? |
| 3 | [The z-score & mean reversion](03-zscore-and-mean-reversion.md) | "This looks unusually cheap." Says who? |
| 4 | [Trend & moving averages](04-trend-and-moving-averages.md) | How do you measure a trend without fooling yourself? |
| 5 | [Momentum: RSI & MACD](05-momentum-rsi-macd.md) | Is this move exhausting itself or just getting started? |
| 6 | [Volatility & the square root of time](06-volatility.md) | How much does this thing *usually* move, and over what horizon? |
| 7 | [Signal vs. noise](07-signal-vs-noise.md) | My rule just fired. Should I believe it? |

Every chapter ends the same way: **In the code** (the file and function implementing the
idea), a **Worked example** with real numbers you can reproduce offline against the
synthetic market, and a **Problem set**. Do the problem sets — reading math is like
watching someone else lift weights.

## Where the course goes next

The math stops here; the *system* that runs it continues in
[`documentation/`](../documentation/README.md):

- [Chapter 8 — From a formula to a system](../documentation/08-from-math-to-system.md)
- [Chapter 9 — The API as a contract](../documentation/09-the-api-contract.md)
- [Chapter 10 — Concurrency & safety](../documentation/10-concurrency-and-safety.md)

That ordering is the golden thread of the whole project: chapters 1–6 separate the slow
story (trend) from fast noise, chapter 7 teaches you to doubt the separation, and 8–10
teach you to run it as a service that won't lie to you or double-count.
