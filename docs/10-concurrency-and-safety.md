# Chapter 10 — Concurrency & safety

> **The question.** It sent me the same alert twice. Same ticker, same z-score, two emails thirty seconds apart. I only have *one* rule. Nothing in my code says "send it twice." So where did the second one come from — and how do we make it *never* happen again?

---

This is the capstone. Everything so far — the math, the layers, the pipeline — assumed one thing runs at a time. It doesn't. The moment you have more than one worker, or two scheduler ticks whose work overlaps, "correct" stops meaning "the logic is right" and starts meaning "the logic is right *no matter how the timing falls*." That last clause is where real money and real bugs live, and it's what this chapter is about.

## 10.1 Concurrency, and the race condition

**Concurrency** is just this: more than one thing happening at once. In our system there are two sources of it, both from Chapter 8:

- **Multiple workers.** `CELERY_WORKER_CONCURRENCY = 4` means four workers pull from the queue in parallel. Two of them can be running `evaluate_strategy` at the same instant.
- **Overlapping ticks.** Beat fires `sweep_due_strategies` every 60 seconds *unconditionally* — it does not wait for the previous batch of evaluations to finish. If an evaluation takes 90 seconds (an AI call can be slow), the next sweep starts while the last one's work is still in flight.

When two things run at once and *share state* — here, rows in the database — you can get a **race condition**: a bug where **correctness depends on timing.** The program is right if the operations happen to interleave one way and wrong if they interleave another. It'll pass every test you run by hand (you only ever run it one way) and then misbehave in production one time in a thousand, which is the worst kind of bug: rare, timing-dependent, and unreproducible on demand.

The specific shape we hit is the oldest one in the book: the **read-modify-write hazard.**

```
read   the current state
modify it in your head
write  the new state back
```

If two runners both **read** before either **writes**, they both decide based on the *old* state, and the second write clobbers — or duplicates — the first. Hold that pattern; it's the villain of the entire chapter.

## 10.2 The bug, as a timeline

Let's watch the duplicate alert happen. Strategy `X` fires when its condition holds; it has a 60-minute cooldown ([Chapter 7](07-signal-vs-noise.md)) so it shouldn't alert more than once an hour. Here is the naïve pipeline — no claim, no lock — with two things going wrong at once.

```
t = 0s    Beat sweep #1 runs. Strategy X is due (last_evaluated_at is old).
          Sweep enqueues task A for X.
t = 1s    Worker 1 picks up task A. It fetches prices, computes the indicator,
          the condition holds. Now it makes the AI call — which is SLOW.
          A is going to sit in ClaudeClient().assess(...) for ~90 seconds.
          Crucially: A has NOT yet written last_evaluated_at or last_triggered_at.

t = 60s   Beat sweep #2 runs. It reads X from the database. last_evaluated_at
          is STILL the old value (A hasn't written anything back yet), so X
          still looks DUE. Sweep enqueues task B for X.
t = 61s   Worker 2 picks up task B. Prices, indicator, condition holds. AI call.

t = 90s   Task A's AI call returns: verdict.trigger = True.
          A reads last_triggered_at  ->  None. Cooldown check passes.
          A creates Alert #1. A stamps last_triggered_at = now. A delivers.
          -> email #1, webhook #1, WebSocket #1.

t = 92s   Task B's AI call returns: verdict.trigger = True.
          B reads last_triggered_at  ->  it read it EARLIER, at t=61s, as None.
          Cooldown check passes (B is working from a stale read).
          B creates Alert #2. B stamps last_triggered_at = now. B delivers.
          -> email #2, webhook #2, WebSocket #2.
```

Two alerts. Two emails. Two webhooks. One rule. There are actually **two** independent races stacked here:

1. **At the sweep:** sweep #2 enqueued `X` a second time because `last_evaluated_at` hadn't been updated yet — an enqueue-level duplicate.
2. **At evaluation:** even setting the sweep aside, tasks A and B both **read** `last_triggered_at = None` before either **wrote** it. Classic read-modify-write. Both passed the cooldown gate.

> **Short: the cooldown is dedup in TIME, not in SIMULTANEITY.** It's tempting to think "but the cooldown prevents duplicate alerts!" It prevents them *across time* — a second alert *a minute later* is suppressed because the first stamped `last_triggered_at`. But the cooldown check is itself a read-modify-write, and it offers **zero** protection when two runners execute it *simultaneously*, because neither has written the stamp the other needs to see. Cooldown answers "should this fire again *later*?" It cannot answer "are two of me firing *right now*?" Different question, different tool.

The fix is a discipline with a name: **exactly once.** Not at-least-once (that's the duplicate). Not at-most-once (that could drop a real alert). *Exactly* once per due window. It takes three mechanisms, each plugging a different hole, and we'll build all three from first principles.

## 10.3 Fix 1 — the atomic claim at sweep

Kill the first race: stop two sweeps from enqueuing the same strategy. The naïve sweep does read-modify-write across two statements — *read* the strategy, then (much later) *write* `last_evaluated_at`. The gap between them is the vulnerability.

The fix collapses read and write into **one atomic database operation**: a conditional `UPDATE`. From [`runtime/engine/tasks.py`](../runtime/engine/tasks.py):

```python
        # Atomically claim: only enqueue if THIS row still has the last_evaluated_at
        # we read. A concurrent sweep that already claimed it updates 0 rows here,
        # so the strategy is enqueued exactly once per due window.
        claimed = Strategy.objects.filter(
            pk=strategy.pk, last_evaluated_at=strategy.last_evaluated_at
        ).update(last_evaluated_at=now)
        if claimed:
            evaluate_strategy.delay(str(strategy.pk))
            queued += 1
```

Read the SQL this generates out loud:

```sql
UPDATE strategy
   SET last_evaluated_at = <now>
 WHERE pk = X
   AND last_evaluated_at = <the exact value we read a moment ago>;
```

This is **compare-and-set** (CAS), the atomic primitive underneath almost all concurrency control. The database processes each `UPDATE` as one indivisible step and guarantees the `WHERE` is checked and the row is written *without any other transaction slipping in between*. So picture two sweeps racing on `X`, both having read `last_evaluated_at = T_old`:

- Sweep #1's UPDATE runs first. The `WHERE last_evaluated_at = T_old` matches. It writes `now`. It **updates 1 row.** `.update()` returns `1`. `claimed` is truthy → enqueue.
- Sweep #2's UPDATE runs next. But the value is no longer `T_old` — sweep #1 changed it to `now`. The `WHERE` matches **nothing.** It **updates 0 rows.** `.update()` returns `0`. `claimed` is falsy → **do not enqueue.**

The database, not our Python, decides the winner — and it can only pick one, because only one `UPDATE` can find the row in its expected state. The `last_evaluated_at` we read doubles as a *version stamp*: "enqueue only if nobody has touched this since I looked." A strategy is enqueued **exactly once per due window.** The regression test `test_sweep_claims_each_strategy_once` pins exactly this: two back-to-back sweeps, `first["queued"] == 1`, `second["queued"] == 0`.

> **Short: why not `if not due: continue` — isn't that enough?** No. That check reads `last_evaluated_at` and decides *outside* the database. Between your `if` and your `enqueue`, another sweep can do the same check on the same old value. The whole point of CAS is to fold the check and the write into *one* step the database serialises. "Check then act" across two statements is a race; "check-and-act" as one atomic UPDATE is not.

## 10.4 Fix 2 — a distributed lock

The claim stops *duplicate enqueues*. But a strategy can still be evaluated concurrently for other reasons — a manual `POST /evaluate/` (Chapter 9) racing a scheduled run, or a retried task overlapping its original. We want a stronger promise: **`evaluate_strategy` never runs concurrently with itself, fleet-wide.**

That calls for a **lock**: a token only one holder can possess at a time. But a plain in-process lock (a `threading.Lock`) is useless here — our runners are in *different processes on possibly different machines*. Worker 1 and Worker 2 don't share memory. The lock has to live somewhere *both* can see. That's a **distributed lock**, and ours lives in Redis, via the cache:

```python
@shared_task
def evaluate_strategy(strategy_id: str):
    """Evaluate one strategy under a per-strategy lock (idempotent w.r.t. itself)."""
    key = _lock_key(strategy_id)
    # cache.add is atomic (Redis SET NX): only one holder at a time, fleet-wide.
    if not cache.add(key, "1", EVAL_LOCK_TTL):
        return {"status": "locked", "strategy_id": strategy_id}
    try:
        return _run_evaluation(strategy_id)
    finally:
        cache.delete(key)
```

Everything about this is deliberate. Let's take it apart.

**`cache.add` is atomic — it's Redis `SET key value NX`.** The `NX` flag means "set **only if** the key does **N**ot e**X**ist." Redis performs the test ("does it exist?") and the set ("write it") as one indivisible operation. So if fifty workers call `cache.add` on the same key at the same microsecond, Redis hands `True` to **exactly one** of them and `False` to the other forty-nine. That is a **test-and-set**, the atomic heartbeat of every lock. The winner enters `_run_evaluation`; everyone else hits `return {"status": "locked", ...}` and no-ops. Notice this is the *same idea* as the CAS in Fix 1 — "act only if the state is what I expect, atomically" — just wearing a different hat (a cache key instead of a row).

**Why the cache MUST be shared (Redis), not per-process.** A lock only works if all contenders can see it. Django's `LocMemCache` lives in one process's memory — Worker 2 literally cannot see a key Worker 1 set. That would make the lock invisible across the fleet and therefore no lock at all. This is spelled out, as a warning, right in [`runtime/config/settings.py`](../runtime/config/settings.py):

```python
# --- Cache (shared across api/worker/beat — backs the per-strategy eval lock) -
# MUST be a shared backend (Redis), not per-process LocMem, or the lock that
# serialises strategy evaluation would not be visible across worker processes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
```

**The TTL is a dead-man's-switch.** `cache.add(key, "1", EVAL_LOCK_TTL)` where `EVAL_LOCK_TTL = 300` sets the key to expire in 300 seconds. Why expire it at all — doesn't the `finally: cache.delete(key)` release it? Yes, *when the worker survives*. But what if the worker is killed mid-evaluation — OOM, deploy, power loss — and never reaches its `finally`? Without a TTL the key would sit in Redis forever and that strategy would be **locked permanently, never evaluating again.** A silent, permanent outage for one rule. The TTL guarantees the lock *self-heals*: even in the worst case, it evaporates after 300 seconds (chosen comfortably longer than one evaluation, price fetch plus AI call, so it never expires out from under a *healthy* run) and evaluation resumes. A lock you can't leak.

**This is idempotency.** A function is **idempotent** if running it twice has the same effect as running it once. The lock makes `evaluate_strategy` idempotent *with respect to itself*: fire it twice concurrently and the second call is a clean no-op, so the observable result — one evaluation, at most one alert — is identical to firing it once. That word, idempotent, is the whole goal of this chapter said in Latin.

## 10.5 Fix 3 — a transaction (and keeping I/O out of it)

Two holes plugged. One left, and it's about *crashes*, not concurrency. When the condition finally fires we do two writes that **must both happen or neither**:

1. Create the `Alert` row.
2. Stamp `last_triggered_at = now` (which arms the cooldown).

Suppose we did them as two separate statements and the process died *between* them: an `Alert` exists, but `last_triggered_at` was never stamped. On the next evaluation the cooldown check sees `last_triggered_at` unchanged and — fires **again.** A crash at the wrong instant becomes a duplicate alert. We need both writes to be **all-or-nothing**, and that is exactly what a **transaction** guarantees. From [`runtime/engine/tasks.py`](../runtime/engine/tasks.py):

```python
        # S2: create the alert AND stamp the trigger in one transaction, so a crash
        # can never leave an alert without its cooldown stamp. select_for_update is
        # belt-and-suspenders on top of the cache lock (a no-op on sqlite in tests).
        with transaction.atomic():
            locked = Strategy.objects.select_for_update().get(id=strategy_id)
            if locked.last_triggered_at and (now - locked.last_triggered_at) < timedelta(
                minutes=locked.cooldown_minutes
            ):
                _persist_eval(locked, value, now)
                return {"status": "cooldown", "value": value}
            alert = Alert.objects.create(
                workspace=locked.workspace,
                strategy=locked,
                ticker=locked.ticker,
                indicator=locked.indicator,
                operator=locked.operator,
                threshold=locked.threshold,
                metric_value=value,
                ai_used=verdict.ai_used,
                ai_rationale=verdict.rationale,
                message=message,
            )
            locked.last_triggered_at = now
            locked.last_metric_value = value
            locked.last_evaluated_at = now
            locked.last_error = ""
            locked.save(update_fields=[
                "last_triggered_at", "last_metric_value", "last_evaluated_at", "last_error",
            ])

        # Deliver AFTER commit — network I/O must not hold a DB lock/transaction open.
        deliver_alert(alert, locked)
```

`with transaction.atomic():` wraps the alert-create and the stamp in one database transaction. Either the whole block commits — alert *and* stamp land together — or, on any exception, the whole block **rolls back** and *neither* lands. There is no in-between state a crash can leave behind. It even re-checks the cooldown *inside* the transaction against a freshly `select_for_update()`-locked row (a second, database-level belt over the cache-lock suspenders, so even without Redis two runners would serialise here).

Now the subtle, senior-engineer part — the comment on the last line. **The AI call and `deliver_alert` are deliberately OUTSIDE the transaction.** Look back at `_run_evaluation`: `ClaudeClient().assess(...)` happens *before* `with transaction.atomic()`, and `deliver_alert(...)` happens *after* it, past the commit. Why is that not an accident?

Because **holding a database lock across a slow network call is a mistake** — one of the most common ways to melt a system under load. A transaction holds locks on the rows it touches for its entire duration. If you made a 90-second AI call *inside* the transaction, you'd pin those database locks open for 90 seconds. Every other worker needing that row (or the connection, or a slot in the pool) would queue behind you. A handful of slow AI calls and the whole database seizes — locks piled up waiting on the network. The rule is iron: **do your I/O first, gather everything you need, then open the transaction, do the pure-database work as fast as possible, commit, and only then do more I/O.** The transaction is a sprint; the network is a stroll; never make the sprint wait on the stroll. Delivery after commit also means a flaky mail server can never roll back a correctly-recorded alert — the alert *is a fact* the moment it commits.

## 10.6 Tie it together — three holes, three plugs

"Correct under concurrency" for us means one thing: **exactly once.** And it genuinely needs all three mechanisms, because each closes a hole the others can't reach:

| Mechanism | Hole it closes | Primitive |
|---|---|---|
| **Atomic claim** (sweep) | Two sweeps *enqueuing* the same strategy | Compare-and-set: conditional `UPDATE ... WHERE last_evaluated_at = <read value>` |
| **Distributed lock** (evaluate) | Two runs *executing* at once (manual + scheduled, retries) | Test-and-set: `cache.add` = Redis `SET NX`, with a TTL dead-man's-switch |
| **Transaction** (persist) | A *crash* splitting alert-create from cooldown-stamp | All-or-nothing `transaction.atomic()`, with I/O kept outside |

Pull any one and a duplicate (or a wedged strategy, or an orphaned alert) creeps back in. The claim narrows the entry; the lock enforces single execution; the transaction makes the write indivisible. Three layers of defense for one promise — because in concurrent systems, one layer is a coincidence and three is a guarantee. This is the last third of the golden thread from the preface: *quant engineering is the discipline of doing it correctly, on time, and **exactly once**.*

## 10.7 In the code — the regression test

Concurrency bugs are famously hard to test — you can't reliably make two threads collide on cue. The trick the suite uses is to **simulate the collision**: seize the shared resource yourself, then prove the code no-ops instead of double-firing. From [`runtime/test/test_evaluation.py`](../runtime/test/test_evaluation.py):

```python
def test_lock_prevents_concurrent_evaluation(workspace):
    """S1/S3: if the per-strategy lock is already held, evaluation is a no-op —
    no second alert. Simulates a concurrent runner holding the lock."""
    s = _strategy(workspace)  # PRICE > 0 would otherwise alert
    cache.add(_lock_key(str(s.id)), "1", 300)  # pretend another worker holds it
    result = evaluate_strategy(str(s.id))
    assert result["status"] == "locked"
    assert Alert.objects.count() == 0
    # Once released, it evaluates normally and fires exactly one alert.
    cache.delete(_lock_key(str(s.id)))
    assert evaluate_strategy(str(s.id))["status"] == "alerted"
    assert Alert.objects.count() == 1
```

No threads, no timing luck. The test *becomes* the other worker: it grabs the lock key first, then calls `evaluate_strategy` and asserts the return is `"locked"` and **zero** alerts were created — the second runner backed off. Then it releases the lock and shows the *same* call now fires exactly *one* alert. That's the lock's contract, made deterministic and repeatable. Its sibling, `test_back_to_back_evaluation_fires_once`, pins Fix 3: two evaluations in one cooldown window yield `"alerted"` then `"cooldown"` and exactly one `Alert`.

## 10.8 Worked walkthrough — replay the bug, then replay the fix

**Without the lock** (the §10.2 timeline, distilled). Tasks A and B both reach evaluation for strategy `X`:

```
A: read last_triggered_at -> None    B: read last_triggered_at -> None
A: cooldown check passes             B: cooldown check passes
A: create Alert #1                   B: create Alert #2
A: stamp last_triggered_at           B: stamp last_triggered_at
A: deliver (email #1)                B: deliver (email #2)
```

Both read `None` before either wrote — read-modify-write — so both sail through the cooldown gate. **Two alerts.**

**With the lock** (Fix 2 in force). Same two tasks, same instant, but now `evaluate_strategy` guards the door:

```
A: cache.add("quantai:eval-lock:X") -> True   (A wins the SET NX)
B: cache.add("quantai:eval-lock:X") -> False  (key already exists)
                                              B: return {"status": "locked"}   <-- no-op, done
A: _run_evaluation(...)  -> condition holds, AI says trigger
A: transaction.atomic(): create Alert #1, stamp last_triggered_at  (commit)
A: deliver (email #1)
A: finally -> cache.delete("quantai:eval-lock:X")   (release)
```

`B` never fetches a price, never calls the AI, never touches an `Alert` — it hit the locked door and turned around. **One alert.** And note the ordering that makes it safe: `A` stamps `last_triggered_at` *inside its transaction, before releasing the lock*, so if a **third** task `C` arrives after `A` releases, `C` wins the lock, runs, but now reads the freshly-committed `last_triggered_at` and stops at the cooldown gate. The lock serialises the runners; the committed stamp is what the next serialised runner sees. Claim, lock, transaction — each doing its job, exactly once out the other end.

## 10.9 Problem set

1. **Why isn't the cooldown enough?** In one paragraph, explain why the Chapter 7 cooldown — which *does* stop a second alert a minute later — fails to stop the two simultaneous alerts of §10.2. Use the words "read-modify-write" and "stale read." Then state the general rule: a check-then-act is safe against *sequential* repeats but not against *concurrent* ones. Why?

2. **Design a regression test.** Suppose a well-meaning teammate "simplifies" `sweep_due_strategies` by replacing the conditional-`UPDATE` claim with a plain `strategy.save()` after enqueue. Describe a test — in the style of `test_sweep_claims_each_strategy_once` — that would *fail* on their version and *pass* on the original. What exactly do you assert, and how do you simulate the second sweep without real threads?

3. **CAS vs. lock.** Fix 1 (compare-and-set on a row) and Fix 2 (test-and-set on a cache key) are the *same* atomic idea — "act only if the state is what I expect." Yet the code uses both, in different places. Explain what each is protecting that the other is not. Could you replace the sweep's CAS with the Redis lock? Could you replace the Redis lock with a CAS? Discuss the trade-offs.

4. **The dead-man's-switch.** Set `EVAL_LOCK_TTL` to `None` (never expires) in your head and trace what happens when a worker is `kill -9`'d after `cache.add` but before `finally`. Now restore the TTL and explain precisely which failure it prevents. Then argue: why is `300` the number, and what breaks if you set it to `1`? What breaks if you set it to `86400`?

5. **I/O inside the transaction.** Move the `ClaudeClient().assess(...)` call to *inside* the `with transaction.atomic():` block. Nothing about single-request correctness changes — so why is this a serious bug under load? Describe, mechanically, how a dozen slow AI calls could bring the *database* to its knees, and connect it to the phrase "holding a lock across a network call."

6. **Exactly-once, end to end.** A strategy is due; a manual `POST /evaluate/` fires at the same instant as a scheduled run; the worker handling one of them crashes mid-transaction. Walk all three mechanisms and show that the user still receives *exactly one* alert (or a clean retry that yields one), never zero and never two. Which mechanism catches which part of this scenario?

7. **The honest limit.** The `select_for_update()` inside the transaction is "a no-op on sqlite in tests" (per the comment). What does that tell you about the difference between the test environment and production? Name one concurrency guarantee that the test suite *cannot* fully exercise on sqlite, and describe how you'd gain confidence in it before trusting real money to the system.

---

Previous: [Chapter 9 — The API as a contract](09-the-api-contract.md) · This is the last chapter. You started at "what is a price?" and you've arrived at "why did it send the same alert twice, and how do we make it never happen" — from the meaning of a number on a screen to the discipline of exactly-once delivery under concurrency. That arc *is* the golden thread: separate the slow story from the fast noise, doubt your separation, then run it as a system that won't lie to you or double-count. Back to the [README](../README.md) for the map of where each idea lives in the code — and then go read the source, because now you can.
