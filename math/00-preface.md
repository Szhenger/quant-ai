# Chapter 0 — Preface: how to read this

*Five minutes. Read it once, refer back to the notation box forever.*

---

## Who this is for

You can read code and you remember what a function, a loop, and an HTTP request are — CS50x gave you that. From math you have three tools:

- **Calculus** — you know a derivative is a rate of change, and you're comfortable with `e^x` and `ln(x)` being inverses.
- **Linear algebra** — a vector is a list of numbers; a dot product multiplies two lists elementwise and adds them up; an average is a sum divided by a count.
- **Discrete probability** — a random variable takes values with probabilities; **expectation** `E[X]` is the long-run average; **variance** `Var(X) = E[(X − E[X])²]` measures spread; two variables are **independent** if knowing one tells you nothing about the other.

That is the whole toolbox. We will not assume measure theory, stochastic calculus, or that you've ever seen a Greek letter used in anger. Every time we need something bigger, we build it here.

## How each chapter is built

Every chapter follows the same rhythm, on purpose:

1. **A question a human would actually ask.** Not "define the RSI." More like "is this rally running out of steam?" The math exists to answer human questions; we lead with the question.
2. **First principles.** We start from something you already believe and take small, honest steps. No step is skipped because it's "standard."
3. **The math, made precise.** We write the formula and, crucially, we *derive* it. A formula you can re-derive is a formula you own.
4. **In the code.** We open the actual QuantAI source file that implements the idea and read it together. The math and the code are never allowed to drift apart.
5. **A worked example.** Real numbers in, real number out, computed by hand so you can check the machine.
6. **A problem set.** A few exercises. Do them. Reading math is like watching someone lift weights.

> **Asides** in boxes like this one are the "shorts" — a quick intuition, a warning about a common mistake, or a bit of history. Skippable, but usually the part you'll remember.

## Notation (the one box to bookmark)

We keep symbols consistent across all ten chapters. When in doubt, come back here.

```
Prices and time
  p_t            closing price on trading day t   (t = 0, 1, 2, ...)
  p_0            the oldest price in our window
  n, w           a "window" length in days (e.g. a 20-day window)

Returns  (Chapter 1)
  r_t            simple return   = (p_t − p_{t-1}) / p_{t-1}
  ℓ_t            log return      = ln(p_t / p_{t-1})

Statistics  (Chapter 2)     — the "hat" means "estimated from data"
  μ̂  (mu-hat)    sample mean      = (1/n) · Σ x_i
  σ̂  (sigma-hat) sample std. dev. = sqrt( (1/(n−1)) · Σ (x_i − μ̂)² )
  σ̂²             sample variance
  Σ              "sum of" (Greek capital sigma)

Indicators
  z_t            z-score          (Chapter 3)
  SMA_w, EMA_w   moving averages  (Chapter 4)
  RSI, MACD      momentum         (Chapter 5)

Trading calendar
  252            trading days in a year (markets are closed weekends/holidays)
```

Two conventions worth stating once:

- **We use *sample* statistics, dividing variance by `n − 1`, not `n`.** There's a real reason (Chapter 2), and the code does exactly this: `numpy`'s `.std(ddof=1)`. Watch for it.
- **A "window" looks backward.** A 20-day z-score on day `t` uses days `t−19 … t`. The most recent day is included. The code fills the earliest days with `None` (there isn't enough history yet) — we call this the **warm-up**.

## The golden thread

If you forget everything else, keep this sentence:

> **A price is the sum of a slow story (the trend) and fast noise (randomness); quant finance is the art of separating the two, and quant *engineering* is the discipline of doing it correctly, on time, and exactly once.**

Chapters 1–6 teach you to separate story from noise. Chapter 7 teaches you to *doubt* your separation. Chapters 8–10 teach you to run it as a system that won't lie to you or double-count. That last part — "exactly once" — is not a footnote; it's Chapter 10, and it's where real money and real bugs live.

## A word on running the numbers yourself

Everything here is computed offline by a **synthetic** market (a deterministic random walk keyed to each ticker — Chapter 1 explains it). That means every worked example is reproducible on your laptop with no API key and no internet. When we say "for `AAPL` the 20-day z-score is −2.1," you can make the code say it too. Trust, but verify — that's the whole spirit of the field.

Onward to [Chapter 1 — What is a market?](01-what-is-a-market.md)
