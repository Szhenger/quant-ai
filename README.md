# QuantAI

### An AI-powered quantitative-research workspace — *and* a course that teaches you the quant finance inside it, from first principles.

Alright. Here's the deal.

Most software you download is a black box. You run it, it does a thing, and if you ever open the hood you find ten thousand lines that assume you already know everything. QuantAI is the opposite. It is a **real, working application** — you can run it today, follow real markets, define real alerting rules, and get real AI-assisted notifications when those rules fire. But it is *also* a **textbook you can execute**. Every number the program computes, every formula in the code, is derived in these docs starting from something you already understand.

The promise is specific. If you are a **math undergraduate** who has seen

- basic **calculus** (derivatives, a little bit of limits, the idea of an exponential),
- **linear algebra** (vectors, dot products, means as sums),
- **elementary discrete probability** (outcomes, expectation, variance, independence),

and you have taken something like **[CS50x](https://cs50.harvard.edu/x/)** (you can read code, you know what a function and a loop and an HTTP request are), then by the end of this course you will understand quantitative finance the way a practitioner does: not as a bag of tricks, but as a small number of ideas about **randomness, information, and time**, made precise, made computable, and made safe to run in production.

We are going to earn every result. No formula appears without a reason. When the code writes `std_dev * sqrt(252)`, you will know *why* it's a square root and *why* it's 252, and you'll be able to re-derive it on a napkin.

---

## What you'll be able to do

By the last page you will be able to:

- **Read a price chart like a statistician** — decompose it into returns, model those returns as random variables, and reason about what is signal and what is noise.
- **Derive, from scratch, every indicator in the code** — the z-score, moving averages, RSI, MACD, and volatility — and explain the assumption each one quietly makes.
- **Quantify risk** — measure volatility and understand the famous "square-root-of-time" rule as a theorem, not a folk saying.
- **Think in probabilities about signals** — use conditional probability and base rates to understand why a raw trading signal is usually a lie, and why we bolt an AI on top of it.
- **Build the system that runs it all** — data feeds, a computation layer, a scheduler, a real-time alert channel — and make it **correct under concurrency**, which is where most "quant" code silently breaks.

That is genuinely most of what a junior quant researcher and the engineer sitting next to them need to know. The rest is practice.

---

## The syllabus

Read [**`docs/00-preface.md`**](docs/00-preface.md) first — it's five minutes, it sets the notation we use everywhere, and it explains how each chapter is built.

Then the course proper. Each chapter ends with the same three sections: **In the code** (the exact file and function that implements the idea), a **Worked example** (real numbers), and a **Problem set** (do these — that's how it sticks).

| # | Chapter | The question it answers | Code it unlocks |
|---|---|---|---|
| 0 | [Preface](docs/00-preface.md) | How do I read this, and what do I need? | — |
| 1 | [What is a market?](docs/01-what-is-a-market.md) | What *is* a price, and what does it mean for it to "go up"? | `feeder/providers.py`, `PCT_CHANGE` |
| 2 | [The statistics of returns](docs/02-statistics-of-returns.md) | If prices are random, what can we possibly know? | `numpy`, sample mean & std |
| 3 | [The z-score & mean reversion](docs/03-zscore-and-mean-reversion.md) | "This looks unusually cheap." Says who? | `Z_SCORE`, `_zscore_series` |
| 4 | [Trend & moving averages](docs/04-trend-and-moving-averages.md) | How do you measure a trend without fooling yourself? | `SMA_CROSS`, `_sma`, `_ema` |
| 5 | [Momentum: RSI & MACD](docs/05-momentum-rsi-macd.md) | Is this move exhausting itself or just getting started? | `RSI`, `MACD_HIST` |
| 6 | [Volatility & the square root of time](docs/06-volatility.md) | How much does this thing *usually* move, and over what horizon? | `VOLATILITY`, `_volatility_series` |
| 7 | [Signal vs. noise](docs/07-signal-vs-noise.md) | My rule just fired. Should I believe it? | cooldown, `ai/claude_client.py` |
| 8 | [From a formula to a system](docs/08-from-math-to-system.md) | How do you turn an equation into a service that runs forever? | the whole backend |
| 9 | [The API as a contract](docs/09-the-api-contract.md) | How do humans and machines talk to this safely? | `strategies/urls.py`, JWT, WebSockets |
| 10 | [Concurrency & safety](docs/10-concurrency-and-safety.md) | Why did it send the same alert twice, and how do we make it *never* happen? | `engine/tasks.py` |

Practical, in-the-same-voice guides for when you're actually hacking on it: [**`runtime/README.md`**](runtime/README.md) and [**`console/README.md`**](console/README.md).

---

## Run it (so the course has something to point at)

You do not need the app running to read the course — but it's more fun when the words on the page correspond to numbers on your screen. The fastest path:

```bash
docker compose up --build     # postgres, redis, the API (ASGI), a worker, a scheduler
```

Then, in another terminal, the web client:

```bash
cd console && npm install && npm run dev     # http://localhost:5173
```

Prefer no Docker? [`runtime/README.md`](runtime/README.md) has the local recipe, and everything runs offline against a deterministic **synthetic** market so you never need an API key or an internet connection to learn.

Want to see the machinery without the ceremony? The tests are a guided tour:

```bash
cd runtime && pip install -r requirements.txt && pytest    # 47 tests, all offline
```

---

## A note on honesty

This project started life as something else entirely and was rebuilt to do one thing well. The engineering docs describe **what the code actually does**, not what would be impressive to claim. When we cut a corner, we say so. When a technique has a known failure mode, we show you the failure first and the fix second — because that's the only way you actually learn it.

Turn to [the preface](docs/00-preface.md). Let's begin.
