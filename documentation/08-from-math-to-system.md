# Chapter 8 — From a formula to a system

> **The question.** I have an equation. On day `t`, a 20-day z-score is `z_t = (p_t − μ̂) / σ̂`, and when it drops below −2 I want to know. I can write that in five lines of Python and run it once. But I don't want to run it once — I want a *thing* that watches the market for me, forever, while I sleep, for me and for a thousand other people, and never falls over. How does a formula become *that*?

---

## 8.1 The gap between a formula and a product

Here is the five-line version. It is correct. It is also useless as a product:

```python
closes = get_prices("AAPL", days=40)
z = zscore(closes, window=20)
if z[-1] < -2:
    print("AAPL looks cheap")
```

Run it and you get one answer, once, on your laptop, in your terminal, for one ticker, for you. A **product** has to do the same computation but with a list of properties the script quietly ignores:

- **On a schedule** — re-check every 15 minutes, not once when you happen to run it.
- **Forever** — for months, surviving restarts, deploys, and the occasional crash.
- **Without a human** — nobody types `python check.py`; the system decides *when*.
- **For many users at once** — a thousand people, each with their own rules, sharing one database, never seeing each other's data.
- **Reliably** — a hiccup in the data feed must not take the whole thing down.
- **Exactly once** — when the condition fires, you get *one* alert, not zero, not two.

None of those are *math*. Every one of them is *engineering*. And the way you get all of them is not by writing one very clever function — it's by splitting the work into **layers**, each of which does one job and does it well. That principle has a name we'll return to until you're sick of it: **separation of concerns.**

> **Short: why layers and not one big function?** Because each property above has a different *reason to change*. The data source changes when Yahoo has an outage. The schedule changes when a user picks a different poll interval. The math changes when you add a new indicator. If those live in one function, every change risks breaking the others. Layers let you change one thing without touching the rest — and, just as importantly, **test** one thing without standing up the rest.

## 8.2 The pipeline, named

Here is the whole system as a sentence, and it is worth memorising because every remaining chapter is a zoom-in on one word:

> **Define a Strategy → schedule it → evaluate it → compute an indicator → check a condition → ask the AI → create an Alert → deliver it.**

Read left to right, that's a **pipeline**: data flows through a series of stages, and each stage hands its output to the next. Our job in this chapter is to walk every stage, ask *why it has to exist as its own layer*, and name the real file that implements it. Let's go bottom-up, from the raw material to the finished alert.

## 8.3 The DATA layer — and why it's allowed to fail

Everything starts with prices, and prices come from the outside world, which is the least reliable thing in any system. Yahoo Finance has outages. Your network drops. A ticker gets delisted. If a data hiccup could crash strategy evaluation, then one bad afternoon at Yahoo would silence *everyone's* alerts.

So the data layer is built around a single idea: **degrade, don't crash.** In [`backend/feeder/providers.py`](../backend/feeder/providers.py) there are two providers behind one interface — `YFinanceProvider` (real data) and `SyntheticProvider` (the deterministic random walk from [Chapter 1](../math/01-what-is-a-market.md)) — and a wrapper that ties them together:

```python
class ResilientProvider(BaseProvider):
    """Try the primary provider; on any failure fall back to synthetic data."""

    def history(self, ticker: str, days: int = 180) -> PriceSeries:
        try:
            return self.primary.history(ticker, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Provider %s failed for %s (%s); using synthetic fallback",
                           self.primary.name, ticker, exc)
            return self.fallback.history(ticker, days)
```

That `try/except` is the whole philosophy in four lines. When the real feed fails, we don't raise, we don't page anyone at 3am — we log a warning and hand back *synthetic* data so the pipeline keeps flowing. It's a **fallback**, the software equivalent of a spare tyre: you'd rather be on the real one, but the point of the car is to keep moving.

> **Short: isn't fake data worse than an error?** For *this* system, no — and the reason is specific. The synthetic provider is deterministic and statistically plausible, so a strategy that degrades to it still exercises the entire downstream pipeline (indicator → condition → alert → delivery) rather than blowing a hole in it. The alternative — one ticker's outage crashing a worker mid-batch — could strand *other* users' evaluations queued behind it. Contain the blast radius. (In a system trading real money you'd instead mark the evaluation `stale` and skip it; the honest note in the README applies — we tell you what the code does, and this is a learning system built to always have something to point at.)

## 8.4 The COMPUTATION layer — pure functions

Now the math from Chapters 3–6. In [`backend/feeder/indicators.py`](../backend/feeder/indicators.py), every indicator is a **pure function**: it takes a list of closes and some parameters, and it returns numbers. No database. No network. No clock. No "side effects."

```python
def _zscore_series(closes, window):
    # ... returns a list of z-scores, one per day, None during warm-up
```

Why insist on purity? Three payoffs, and they're the reason this layer is the easiest in the whole system to trust:

1. **Testable.** A pure function is a table of inputs and expected outputs. You can check `z_t = −2.1` on a fixed price series with no database, no Redis, no mocking — which is exactly how the worked examples in Chapters 3–6 are verifiable on your laptop.
2. **No hidden state.** Call it twice with the same input, get the same output twice. Nothing accumulates between calls, so there's no "it worked yesterday" mystery.
3. **Reusable.** The same `_zscore_series` runs inside the live evaluation task *and* inside the market-analysis dashboard *and* inside a test. One definition, three callers, zero drift between what the chart shows and what the alert fires on.

The golden thread again: the computation layer is where the *math* lives, and keeping it pure is what stops the math and the system from ever drifting apart.

## 8.5 The PERSISTENCE layer — and multi-tenancy from scratch

A formula is stateless. A product has to *remember* — remember your rules while you're offline, remember which alerts already fired, remember whose data is whose. That memory is the database, and in Django it's shaped by **models**. Three matter here.

**`Workspace`** — the isolation boundary. From [`backend/identity/models.py`](../backend/identity/models.py):

```python
class Workspace(models.Model):
    """A tenant boundary. A user owns one or more workspaces; all strategies,
    watchlists and alerts belong to exactly one workspace."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, ...)
```

**`Strategy`** — a saved rule, from [`backend/engine/models.py`](../backend/engine/models.py). It is exactly the pipeline, frozen as columns: which `ticker`, which `indicator`, which `operator` and `threshold`, whether `ai_enabled`, which delivery channels, plus the scheduling bookkeeping (`poll_interval_minutes`, `cooldown_minutes`, `last_evaluated_at`, `last_triggered_at`). Every field is a decision the pipeline will later read back.

**`Alert`** — a fired event. One row per time a strategy's conditions were met. It records the value that fired it, the AI's rationale, and — crucially — a `delivery` JSON field recording what happened on each channel.

Now, the big idea hiding in `Workspace`. **Multi-tenancy** means many customers ("tenants") share one running system and one database, but each must see *only their own data*. There is no separate database per user — that wouldn't scale to a thousand users. Instead, every row carries a `workspace` foreign key, and isolation is a *discipline*: **every query is scoped to the caller's workspace.**

Where does the system learn *which* workspace you are? From a request header. In [`backend/identity/workspaces.py`](../backend/identity/workspaces.py):

```python
WORKSPACE_HEADER = "HTTP_X_WORKSPACE_ID"

def resolve_active_workspace(request) -> Workspace:
    workspace_id = request.META.get(WORKSPACE_HEADER)
    if not workspace_id:
        raise PermissionDenied("Missing X-Workspace-ID header.")
    try:
        return Workspace.objects.get(id=workspace_id, owner=request.user)
    except (Workspace.DoesNotExist, ValidationError, ValueError):
        raise NotFound("Workspace not found or not owned by the current user.")
```

Look closely at that `.get(id=workspace_id, owner=request.user)`. It doesn't just look up the workspace you named — it demands that *you own it*. If you send someone else's workspace ID, you get a 404, not their strategies. And then every list view scopes through the resolved workspace, e.g. in [`backend/engine/views.py`](../backend/engine/views.py):

```python
return Strategy.objects.filter(workspace=workspace)
```

That one `filter(...)` is the tenancy boundary, enforced at the application layer. Isolation is a **safety property**: it's not a feature users ask for, it's a promise that a bug in it is a *breach*, not a mere inconvenience. The way you keep such a promise is by making the scoping *unavoidable* — a single choke-point (`resolve_active_workspace`) that every entry point flows through, so no individual view can forget.

> **Short: authentication vs. authorization.** JWT (Chapter 9) proves *who you are* — authentication. The workspace check proves *what you're allowed to touch* — authorization. They're different questions, and you need both: knowing you're logged in as a real user says nothing about whether *this* workspace is yours.

## 8.6 The SCHEDULING layer — why you can't "just poll in the request"

Here's a tempting shortcut a beginner reaches for: "When the user opens the page, run the check." Or worse: "When they create the strategy, compute the indicator right there in the POST handler."

Both are wrong, and the reason is a hard fact about HTTP: **a web request must return in milliseconds.** A browser (and every proxy between it and your server) will give up after a few seconds. A user waiting on a spinner is a user leaving. But a *market watch* is the opposite of a fast request — it runs **forever**, on a clock, whether or not anyone is looking at the page. You cannot pin an infinite, clock-driven job onto a request that must finish before the user blinks. They live on different timescales.

So you need a component whose entire job is the clock: a **scheduler**. Ours is **Celery Beat**, and its instruction is one entry in [`backend/config/settings.py`](../backend/config/settings.py):

```python
CELERY_BEAT_SCHEDULE = {
    "sweep-due-strategies-every-minute": {
        "task": "strategies.tasks.sweep_due_strategies",
        "schedule": 60.0,
    },
}
```

Every 60 seconds, no matter what, Beat kicks off one function: `sweep_due_strategies`. That's the heartbeat of the whole system. Note what Beat does *not* do — it doesn't fetch prices or compute anything. It just fires a task on a timer. One concern: *when*.

## 8.7 The EXECUTION layer — a queue and workers

`sweep_due_strategies` finds the strategies that are due — and then what? It could evaluate them right there in a loop. But imagine 5,000 due strategies, each needing a price fetch and maybe a slow AI call. Beat would be stuck for minutes, miss its next tick, and any single hung ticker would block all the rest. Back to the blast-radius problem.

The fix is a second separation: the scheduler decides *what to do*, but *doing it* happens somewhere else, through a **task queue**. Beat doesn't run the work; it *enqueues* it. Look at the last line of the sweep loop in [`backend/engine/tasks.py`](../backend/engine/tasks.py):

```python
if claimed:
    evaluate_strategy.delay(str(strategy.pk))
    queued += 1
```

`.delay(...)` doesn't run `evaluate_strategy` — it drops a little message ("please evaluate strategy `X`") onto a queue backed by Redis. Somewhere else entirely, a pool of **workers** (`CELERY_WORKER_CONCURRENCY = 4` by default) pulls messages off that queue and actually runs them. Why is this decoupling worth a whole extra moving part?

- **Absorb bursts.** If 5,000 strategies come due at once, the queue holds 5,000 messages and the workers chew through them at their own pace. Nothing is dropped; nothing blocks the scheduler.
- **Retry.** A message that fails can be redelivered. `evaluate_strategy` runs with `acks_late=True`, so the queue only forgets a message after the task *finishes* — a worker that dies mid-evaluation gets the message redelivered rather than losing the run. (Safe to redeliver: the per-strategy lock and the cooldown transaction in Chapter 10 make evaluation idempotent.)
- **Scale independently.** Too slow? Add workers. You don't touch Beat, the API, or the database schema — you turn one knob.

This is the **producer/consumer** pattern: Beat produces work, workers consume it, and the queue in the middle lets them run at different speeds without knowing about each other. (That "run at different speeds" is exactly where Chapter 10's bug will crawl in — hold that thought.)

## 8.8 The DELIVERY layer — separated on purpose

A worker runs `evaluate_strategy`, the condition holds, the AI blesses it, an `Alert` row is born. The user still doesn't know. **Delivery** is its own final stage, in [`backend/engine/delivery.py`](../backend/engine/delivery.py), and it fans out across three channels:

```python
def deliver_alert(alert, strategy) -> dict:
    results = {}
    if strategy.notify_in_app:
        results["in_app"] = _push_ws(alert)          # real-time WebSocket
    if strategy.notify_email:
        results["email"] = _send_email(alert, strategy)
    if strategy.webhook_url:
        results["webhook"] = _post_webhook(alert, strategy)
    alert.delivery = results
    alert.save(update_fields=["delivery"])
    return results
```

Three channels — an in-app **WebSocket** push (the browser lights up instantly, via the Redis-backed channel layer), an **email**, an outbound **webhook** (an HTTP POST to some other system) — and each records its *own* `{ok, detail}` status into `alert.delivery`. Email can fail while the WebSocket succeeds; you'll see exactly that in the JSON.

Why is delivery a separate layer from evaluation at all? Because *deciding an alert is real* and *getting it to a human* are different jobs with different failure modes. Evaluation is CPU and a database. Delivery is the flaky outside world again — SMTP servers, someone's webhook endpoint that's down. If those were tangled together, a dead mail server could roll back a correctly-computed alert. Keeping them apart means the alert *exists and is recorded* the instant it's decided, and delivery is a best-effort layer on top that reports its own successes and failures without endangering the record. (Chapter 10 makes this precise: delivery happens *after* the database commit, never inside it.)

## 8.9 In the code

Two functions carry the spine of this chapter. First, the scheduler's sweep — the thing Beat calls every 60 seconds — from [`backend/engine/tasks.py`](../backend/engine/tasks.py):

```python
@shared_task
def sweep_due_strategies():
    now = timezone.now()
    queued = 0
    active = Strategy.objects.filter(status=Strategy.Status.ACTIVE).only(
        "id", "last_evaluated_at", "poll_interval_minutes"
    )
    for strategy in active:
        due = (
            strategy.last_evaluated_at is None
            or (now - strategy.last_evaluated_at) >= timedelta(minutes=strategy.poll_interval_minutes)
        )
        if not due:
            continue
        # Atomically claim: only enqueue if THIS row still has the last_evaluated_at
        # we read. A concurrent sweep that already claimed it updates 0 rows here,
        # so the strategy is enqueued exactly once per due window.
        claimed = Strategy.objects.filter(
            pk=strategy.pk, last_evaluated_at=strategy.last_evaluated_at
        ).update(last_evaluated_at=now)
        if claimed:
            evaluate_strategy.delay(str(strategy.pk))
            queued += 1
    return {"queued": queued}
```

For now, read it as: *find the active strategies, keep the ones whose poll interval has elapsed, and enqueue each.* That `claimed = ... .update(...)` line looks like an odd way to say "enqueue it" — and it is. It's the atomic claim, and it exists entirely to defend against a concurrency bug. We are *deliberately* leaving it mysterious; unpacking it is the whole job of [Chapter 10](10-concurrency-and-safety.md).

And the shape of the worker task, `_run_evaluation` (the same file), which is the pipeline made literal — read the *comments*, they narrate every stage:

```python
def _run_evaluation(strategy_id: str):
    strategy = Strategy.objects.get(id=strategy_id)          # PERSISTENCE: load the rule
    now = timezone.now()
    provider = get_provider()                                # DATA: resilient provider
    series = provider.history(strategy.ticker, days=lookback_days(...))
    result = compute_indicator(strategy.indicator, series.closes, strategy.params)  # COMPUTATION
    value = result["value"]

    if not evaluate_condition(strategy.operator, value, ..., strategy.threshold):    # CONDITION
        _persist_eval(strategy, value, now)
        return {"status": "quant_not_met", "value": value}

    # ... cooldown check (Chapter 7) ...

    if strategy.ai_enabled:                                   # AI (Chapter 7)
        verdict = ClaudeClient().assess(...)
    # ...
    with transaction.atomic():                               # PERSISTENCE: create Alert + stamp
        alert = Alert.objects.create(...)
        # ... stamp last_triggered_at ...
    deliver_alert(alert, locked)                             # DELIVERY: fan out to 3 channels
    return {"status": "alerted", "alert_id": str(alert.id), "value": value}
```

(That's a lightly-trimmed reading; the real function has the safety machinery Chapter 10 dissects line by line.) Every stage from §8.2 is right there, in order, each a call into a different layer. The function *reads like the pipeline sentence* — that's separation of concerns paying off. And here's the scheduler's marching order once more, the config that starts the whole clock, from [`backend/config/settings.py`](../backend/config/settings.py):

```python
CELERY_BEAT_SCHEDULE = {
    "sweep-due-strategies-every-minute": {
        "task": "strategies.tasks.sweep_due_strategies",
        "schedule": 60.0,
    },
}
```

## 8.10 Worked walkthrough — one strategy, cradle to alert

Let's trace a single strategy through every file, so the layers stop being abstract.

1. **Creation (persistence).** You POST to create a strategy: *"AAPL, 20-day z-score, `<`, −2, AI on, notify in-app and email."* The request carries your `X-Workspace-ID` header; [`core/workspaces.py`](../backend/identity/workspaces.py) resolves and *authorizes* your workspace, and a `Strategy` row is written by the view in [`strategies/views.py`](../backend/engine/views.py). Its `last_evaluated_at` is `None`. The POST returns in milliseconds. **Nothing is computed yet** — and §8.11 asks you to defend that choice.

2. **A tick (scheduling).** Up to 60 seconds later, Celery Beat fires `sweep_due_strategies` ([`engine/tasks.py`](../backend/engine/tasks.py)). Your strategy has `last_evaluated_at is None`, so it's due. The sweep claims it and calls `evaluate_strategy.delay("...")` — a message onto the Redis queue.

3. **Pickup (execution).** A free worker pulls the message and runs `evaluate_strategy` → `_run_evaluation`.

4. **Prices (data).** `get_provider().history("AAPL", days=...)` returns 40-ish closes — from Yahoo if it's up, from the synthetic fallback if not ([`feeder/providers.py`](../backend/feeder/providers.py)).

5. **The number (computation).** `compute_indicator("Z_SCORE", closes, {"window": 20})` calls the pure `_zscore_series` ([`feeder/indicators.py`](../backend/feeder/indicators.py)) and returns, say, `value = −2.31`.

6. **The condition.** `evaluate_condition("<", −2.31, ..., −2.0)` → `True`. It cleared the quant gate.

7. **The AI (Chapter 7).** `ClaudeClient().assess(...)` reads the value and some headlines and returns a `verdict` with `trigger=True` and a rationale.

8. **The record (persistence).** Inside `transaction.atomic()`, an `Alert` row is created — scoped to *your* workspace — and `last_triggered_at` is stamped, together, atomically.

9. **The knock on the door (delivery).** `deliver_alert(alert, strategy)` ([`strategies/delivery.py`](../backend/engine/delivery.py)) pushes over the WebSocket (your browser pops a toast) and sends the email. Each result is recorded in `alert.delivery`.

Nine steps, six files, five layers — and *you* did none of it. That's the difference between a formula and a system.

## 8.11 Problem set

1. **Why not compute in the POST?** When a user creates a strategy, why does the code *not* fetch prices and compute the indicator inside that HTTP POST handler? Give two independent reasons — one about *latency* (what the user experiences) and one about *lifetime* (what the job actually is). Then: what single thing *would* it be reasonable to do synchronously in the POST, and why is that one cheap?

2. **The tenancy boundary.** Suppose a malicious user is authenticated (their JWT is valid) but sends someone else's `X-Workspace-ID`. Trace `resolve_active_workspace` line by line and state exactly where and why they're stopped. Now suppose a *developer* adds a new list endpoint and forgets the `.filter(workspace=workspace)`. What breaks, and what does this tell you about where isolation should be enforced — in each view, or in one shared place? Propose a design that makes forgetting it impossible.

3. **Fallback ethics.** The `ResilientProvider` silently substitutes synthetic data on a real-feed failure. Describe a scenario where that silence is *dangerous*, and modify the design so an alert fired on fallback data is *marked as such* end-to-end (which model field, which delivery detail). Why might a real trading system prefer to skip the evaluation entirely instead?

4. **Purity, tested.** The indicator layer is pure. Write, in words, a test for `_zscore_series` that needs *no* database, *no* Redis, and *no* network — just a fixed list of closes and an expected output. Then explain why you could *not* write such a clean test for `deliver_alert`, and what you'd have to fake (mock) to test it at all. What does that difference tell you about which layers are "expensive" to test?

5. **Draw the pipeline.** Sketch the eight boxes of §8.2 and, next to each, write the real file and function that implements it. Circle the two boundaries where work crosses from one *process* to another (hint: one is a queue, one is the network to the user). Those crossings are where Chapter 10's bugs live — why would a *process boundary* be more dangerous than a function call?

6. **A knob, not a rewrite.** Alerts are arriving 10 minutes late at peak because there aren't enough workers. Which single configuration value do you change, and in which file? Explain why this change touches neither Beat, nor the API, nor the database — and connect that to separation of concerns.

---

Previous: [Chapter 7 — Signal vs. noise](../math/07-signal-vs-noise.md) · Next: the pipeline is only as good as the door people knock on. How do humans and machines talk to this system *safely* — tokens, permissions, real-time sockets? That's [Chapter 9 — The API as a contract](09-the-api-contract.md).
