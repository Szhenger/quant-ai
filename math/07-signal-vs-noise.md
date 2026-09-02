# Chapter 7 — Signal vs. noise

> **The question.** You built a rule. You picked an indicator, a threshold, an operator. This morning it *fired* — the z-score crossed −2, the moving averages crossed, the volatility spiked. Your first instinct is to believe it. **Should you?** This is the most important chapter in the course, because the answer is almost always *"less than you think,"* and knowing *how much* less is the difference between a trader and a gambler.

---

## 7.1 A firing rule is evidence, not proof

Everything in Chapters 3–6 taught you to build **conditions**: precise, computable statements about a price series that are either true or false right now. That was the easy part. The hard part is what a firing condition actually *means*.

Here is the trap. A rule firing feels like a *verdict* — "this is a real opportunity." It is not. A firing rule is **evidence** — a nudge to your belief, not a proof. To see why, stop thinking of your rule as an oracle and start thinking of it as a **classifier**: a machine that looks at the world and shouts "REAL!" or stays quiet, and *sometimes gets it wrong in both directions*:

- A **false positive** — it fires, but nothing real is there. The z-score hit −2 because of one weird tick, not because the stock is genuinely mispriced. Noise dressed up as signal.
- A **false negative** — something real happens, but the rule stays quiet because the move didn't quite cross your threshold. A missed opportunity.

Every rule you will ever write lives on this spectrum. There is no threshold that eliminates both errors at once — tighten it to kill false positives and you create false negatives, loosen it to catch everything and you drown in noise. So "should I believe it?" is not a yes/no question. It is a **probability** question: *given that my rule fired, what's the chance something real is actually there?* And to answer a question shaped like that, we need the one tool from your discrete-probability toolbox that was built for exactly it.

## 7.2 Conditional probability, from the definition

Start from what you already have. From the preface: a random variable takes values with probabilities, and `P(A)` is the long-run fraction of the time event `A` happens. We need one more idea: **conditional probability** — the probability of `A` *given that you already know* `B` happened. Written `P(A | B)`, read "P of A given B." Its definition is almost embarrassingly simple:

```
P(A | B) = P(A and B) / P(B)
```

In words: *of all the times `B` happens, what fraction also have `A`?* You restrict the world to the `B`-cases (the denominator), then ask how many of those are also `A`-cases (the numerator). That's the whole definition — a fraction of a fraction.

Now write that same identity two ways, because `"A and B"` is the same event as `"B and A"`:

```
P(A and B) = P(A | B) · P(B)          (rearranging the definition)
P(A and B) = P(B | A) · P(A)          (same event, other order)
```

Both equal `P(A and B)`, so they equal each other:

```
P(A | B) · P(B) = P(B | A) · P(A)
```

Divide both sides by `P(B)` and you have derived, from nothing but the definition, the most useful formula in applied probability:

> **Bayes' theorem.**
> ```
> P(A | B) = P(B | A) · P(A) / P(B)
> ```

There is no magic here — it is the definition of conditional probability, written twice and divided. But it does something profound: it lets you **flip a conditional.** You often *know* `P(B | A)` — how often the evidence shows up when the thing is real — and you *want* `P(A | B)` — how likely the thing is real given the evidence. Bayes is the bridge between them.

## 7.3 The question, in Bayes' language

Map our problem onto the formula. Let `real` be the event "there is a genuine, tradable signal" and `fired` be the event "my rule fired." We want:

```
P(real | fired) = P(fired | real) · P(real) / P(fired)
```

Look at what each piece is:

- **`P(real)`** — the **base rate.** How often is there genuinely something worth trading, *before* you look at any rule? This is the number everyone forgets, and it is usually *small*.
- **`P(fired | real)`** — the rule's **sensitivity** (or recall): when something real is happening, how often does the rule catch it?
- **`P(fired)`** — how often the rule fires *at all*, real or not. We compute it by adding up the two ways it can fire (the [law of total probability](https://en.wikipedia.org/wiki/Law_of_total_probability)):
  ```
  P(fired) = P(fired | real)·P(real) + P(fired | not real)·P(not real)
  ```

The last term, `P(fired | not real)`, is the **false-positive rate** — how often the rule cries wolf. And the entire drama of this chapter is about to come from the fact that `P(not real)` is large (because `P(real)` is small), so even a *small* false-positive rate, multiplied by a *large* `P(not real)`, can flood you with false alarms. Let's put numbers on it.

## 7.4 The base-rate fallacy, with real arithmetic

Here is the scenario, with plausible numbers. Genuine tradable events are **rare**, your rule is **good but not perfect**, and it occasionally fires on noise:

```
P(real)            = 0.05     genuine signals are rare — 5% of firings-worth of moments
P(fired | real)    = 0.80     when it's real, the rule catches it 80% of the time
P(fired | not real)= 0.20     when it's noise, the rule still fires 20% of the time
```

Those are the numbers of a *good* rule: it catches most real events and only cries wolf a fifth of the time. Intuition says "80% sensitive, only 20% false alarms — if it fires, I should be ~80% confident." Watch intuition be wrong.

**First, `P(fired)` — how often it fires at all**, via total probability. Note `P(not real) = 1 − 0.05 = 0.95`:

```
P(fired) = P(fired | real)·P(real) + P(fired | not real)·P(not real)
         = 0.80 × 0.05      +      0.20 × 0.95
         = 0.04             +      0.19
         = 0.23
```

**Now Bayes:**

```
P(real | fired) = P(fired | real)·P(real) / P(fired)
                = (0.80 × 0.05) / 0.23
                = 0.04 / 0.23
                = 0.1739…
                ≈ 17%
```

**Seventeen percent.** Your "80% accurate" rule fired, and there is only about a **1-in-6** chance anything real is behind it. Most alerts from a genuinely good rule are *false.* Read that twice, because it is the reason this entire course exists.

Where did the intuition go wrong? It ignored the **base rate.** Let the confusion matrix make it physical. Imagine 1000 moments where the rule *could* fire:

```
                          │  really REAL     │  really NOISE    │  row total
    ──────────────────────┼──────────────────┼──────────────────┼───────────
    of 1000 moments:      │       50         │       950        │   1000
    ──────────────────────┼──────────────────┼──────────────────┼───────────
    rule FIRES            │  40  (TP)        │  190  (FP)       │   230
    rule SILENT           │  10  (FN)        │  760  (TN)       │   770
```

- Of the **50** real moments (`5% × 1000`), the rule catches `80% → 40` (true positives, **TP**).
- Of the **950** noise moments, the rule *still fires on* `20% → 190` (false positives, **FP**).
- So the rule fires **230** times total — and only **40** of those are real.

```
P(real | fired) = TP / (TP + FP) = 40 / (40 + 190) = 40 / 230 = 0.174 ≈ 17%
```

Same 17%, now as a count you can see. The **190 false alarms swamp the 40 true ones**, not because the rule is bad, but because there were *so many more* chances to be wrong (950) than to be right (50). When the thing you're hunting is rare, even a good detector spends most of its firings on the common, boring, wrong case. **This is why a raw quant trigger is usually a lie** — and why QuantAI never alerts you on the quant condition alone if it can help it. It needs to *raise the base rate* before it bothers you. It has two ways to do that.

> **Short: precision is the number that matters.** `P(real | fired)` has a name — **precision**: of the times you shouted, how often were you right. The rule's headline "80%" was its *recall* (`P(fired | real)`), a different animal. High recall with low precision is the signature of a rare-event detector, and it is a trap. Everything below is a fight to raise precision.

## 7.5 Defense #1 — the cooldown (deduplication in time)

The first defense is almost embarrassingly simple, and it attacks a specific kind of false alert. Suppose your condition is `z-score < −2`, and the stock stays cheap for a week. The strategy is evaluated every few minutes. Without protection, it would fire **on every single evaluation** — hundreds of identical alerts for *one* underlying event. That's not new evidence; it's the same evidence, stuttered.

The **cooldown** suppresses re-alerts within a time window. Once a strategy fires, it goes quiet for `cooldown_minutes` before it is allowed to fire again. In [`backend/strategies/tasks.py`](../backend/strategies/tasks.py), inside `_run_evaluation`, right after the quant condition passes:

```python
# Respect the cooldown so a persistent condition doesn't spam the user.
if strategy.last_triggered_at and (now - strategy.last_triggered_at) < timedelta(
    minutes=strategy.cooldown_minutes
):
    _persist_eval(strategy, value, now)
    return {"status": "cooldown", "value": value}
```

Read it plainly: *if we fired recently — less than `cooldown_minutes` ago — record the evaluation but do not alert again.* `strategy.last_triggered_at` is the timestamp of the last real alert; `Strategy.cooldown_minutes` is the user-configured quiet window. This is **deduplication in time**: collapsing one persistent real-world condition into one alert instead of a hundred.

> **Short: two different "dedup"s — don't confuse them.** The cooldown dedupes *across time* — the same condition staying true for a while should tell you *once*. That is a different problem from dedupe *across concurrency* — two workers evaluating the *same* strategy at the *same instant* and both trying to alert. That second problem (locks, atomic claims, "exactly once") is real and subtle and gets its own treatment in [Chapter 10 — Concurrency & safety](../documentation/10-concurrency-and-safety.md). Here we only mean: *don't re-tell me the same story every minute.*

The cooldown doesn't touch precision directly — a persistent *false* alarm is still false. What it does is stop one event, true or false, from *multiplying*. It makes each alert correspond to (at most) one real-world occurrence, which is the precondition for the second, sharper defense to mean anything.

## 7.6 Defense #2 — a second, independent classifier

Now the real move. Section 7.4 showed that one rule, however good, gives you ~17% precision on a rare event. What raises it? **A second, roughly independent classifier that has to agree.**

The quant condition is **necessary but not sufficient**: it's a filter that must pass, but passing it isn't enough. QuantAI's second opinion is an LLM. When the quant condition fires (and clears cooldown), `ClaudeClient.assess` reads *recent news and context* — information the price-based indicator never saw — and returns a verdict: should this actually alert, or is it noise? Crucially, it can **suppress** a firing the quant rule was ready to send. Here's how `_run_evaluation` uses it:

```python
if strategy.ai_enabled:
    news = provider.news(strategy.ticker, limit=5)
    verdict = ClaudeClient().assess(
        ticker=strategy.ticker,
        indicator=strategy.indicator,
        operator=strategy.operator,
        threshold=strategy.threshold,
        metric_value=value,
        user_prompt=strategy.ai_prompt,
        news=news,
    )
else:
    verdict = AlertVerdict(
        trigger=True,
        rationale="Quantitative condition met (AI contextualisation disabled).",
        confidence=1.0,
        ai_used=False,
    )

if not verdict.trigger:
    _persist_eval(strategy, value, now)
    return {"status": "ai_suppressed", "value": value, "rationale": verdict.rationale}
```

That `if not verdict.trigger:` branch is the whole point: **the AI can veto.** A quant firing that the AI judges to be noise never becomes an alert — it returns `"ai_suppressed"` and stays silent. You now require **two independent signals to agree** before you're disturbed: the math *and* the context.

Why does agreement help so much? Because independent evidence **multiplies.** Redo §7.4 with a second check. Say the AI, given that quant already fired, is itself an 80%/20% classifier — `P(AI yes | real) = 0.80`, `P(AI yes | not real) = 0.20` — and roughly independent of the quant rule given the truth. We already updated our belief from the base rate `5%` up to `17.4%` after the quant fired. Now feed *that* in as the new prior and update again on the AI's agreement:

```
Start (after quant fired):  P(real) = 0.174,  P(not real) = 0.826

P(AI yes) = 0.80 × 0.174 + 0.20 × 0.826
          = 0.1392 + 0.1652 = 0.3044

P(real | AI yes) = (0.80 × 0.174) / 0.3044
                 = 0.1392 / 0.3044
                 = 0.457  ≈ 46%
```

Precision climbs from **17% → 46%** just by demanding a second independent yes. (Same answer straight from the base rate: `P(both fire | real) = 0.8×0.8 = 0.64`, `P(both | not real) = 0.2×0.2 = 0.04`, so `P(real | both) = (0.64×0.05) / (0.64×0.05 + 0.04×0.95) = 0.032 / 0.070 = 0.457`.) Two mediocre-but-independent checks that agree are dramatically better than either alone — because to fool *both*, noise has to get lucky *twice*, and `0.20 × 0.20 = 0.04` is a much smaller door than `0.20`.

**But there is a cost, and honesty requires naming it: the precision/recall trade-off.** Requiring two yeses raises **precision** (fewer false alarms get through) but lowers **recall** (some *real* events get filtered out, because sometimes the AI says no to a genuine signal — `20%` of the time in our numbers). You catch fewer real events but you *trust* the ones you surface far more. That's usually the right trade for a tool that pings a human: an alert you can believe half the time beats an alert you can believe a sixth of the time, even if you miss a few. But it *is* a trade — there is no free lunch, only a dial between "miss nothing" and "cry wolf less."

> **Short: independence is the load-bearing word.** The multiplication `0.2 × 0.2 = 0.04` only holds if the two checks fail *independently*. If the AI just re-derived the same z-score from the same prices, it would fail on exactly the same days as the quant rule — zero new information, no precision gain. The AI helps *because* it reads something else (news, context) that the price series doesn't contain. Stacking two checks that make correlated mistakes buys you almost nothing; the value is entirely in their *independence*.

And the honest engineering, right there in the code: this only works when there's an LLM to call. With no API key, the system doesn't pretend. Open [`backend/advisor/claude_client.py`](../backend/advisor/claude_client.py) — the very first thing `ClaudeClient.assess` does:

```python
if not self.enabled:
    return AlertVerdict(
        trigger=True,
        rationale=(
            "AI layer disabled (no ANTHROPIC_API_KEY). Alert fired on the "
            "quantitative condition only."
        ),
        confidence=0.5,
        ai_used=False,
    )
```

With no `ANTHROPIC_API_KEY`, `assess` **degrades gracefully**: it returns `trigger=True` and fires on the quant condition alone — and it *says so* in the rationale (`ai_used=False`, "fired on the quantitative condition only"). That is the second defense switching off cleanly, documented rather than hidden. You're back to the ~17% single-classifier world, but the pipeline still runs end-to-end offline, and — this is the point — **the alert tells you it did so**, so you know exactly how much to trust it. A system that lies about its own confidence is worse than no system; this one confesses.

## 7.7 Worked example

The full Bayes computation of §7.4, start to finish, in one place — the calculation every one of these defenses is fighting to improve.

**Given** a "good" rule and a rare target:

```
P(real)             = 0.05
P(fired | real)     = 0.80      (sensitivity / recall)
P(fired | not real) = 0.20      (false-positive rate)
```

**Step 1 — how often the rule fires at all** (law of total probability):

```
P(fired) = 0.80 × 0.05  +  0.20 × 0.95
         = 0.04         +  0.19
         = 0.23
```

**Step 2 — flip it with Bayes** to get what you actually want:

```
P(real | fired) = P(fired | real) · P(real) / P(fired)
                = (0.80 × 0.05) / 0.23
                = 0.04 / 0.23
                = 0.174
                ≈ 17%
```

**Step 3 — sanity-check with counts** (per 1000 moments): `40` true positives, `190` false positives, `40 / 230 = 17.4%`. A good rule, fired, and it's still *wrong 5 times out of 6*. **Step 4** (the fix): add a second independent 80/20 check that must also agree, and precision rises to `40/230 → ~46%` (§7.6). The cooldown, meanwhile, guarantees each real event is counted **once** so these probabilities describe *distinct* alerts rather than a stuttering repeat of one.

## 7.8 Problem set

1. **Rarer still.** Redo the §7.7 Bayes computation with an even rarer base rate, `P(real) = 0.01`, keeping `P(fired | real) = 0.80` and `P(fired | not real) = 0.20`. What is `P(real | fired)` now? State in one sentence what happens to a fixed-quality rule's precision as the thing it hunts gets rarer, and why that is the base-rate fallacy in one number.

2. **Two independent checks beat one.** Take two checks, each with `P(yes | real) = 0.80` and `P(yes | not real) = 0.20`, that fail *independently given the truth*, on a base rate `P(real) = 0.05`. Compute `P(real | both say yes)` directly: form `P(both | real) = 0.8²` and `P(both | not real) = 0.2²`, then apply Bayes. Confirm you get ~46%. Then argue in words why the *independence* assumption is doing all the work — what precision would you get if the second check were a perfect copy of the first?

3. **Precision vs. recall, by the numbers.** Using the confusion-matrix counts from §7.4 (`TP=40, FP=190, FN=10, TN=760`), compute the single rule's **recall** `TP/(TP+FN)` and its **precision** `TP/(TP+FP)`. Now suppose the AI veto removes 8 of the 40 true positives along with 170 of the 190 false positives. Recompute both. Which went up, which went down, and is that the trade you'd want for a tool that pings a human?

4. **Cooldown arithmetic.** A strategy with `cooldown_minutes = 60` is evaluated every 5 minutes, and its z-score condition stays true for a solid 3 hours. Without a cooldown, how many alerts fire? With the cooldown, how many? Then explain why this is *deduplication in time* and not the *concurrency* dedup of Chapter 10 — what different failure is each one preventing?

5. **Graceful degradation.** Trace what `_run_evaluation` does end-to-end when `ANTHROPIC_API_KEY` is unset and the quant condition fires: which branch of `assess` runs, what `AlertVerdict` comes back, and does an alert get created? Now argue why it is *more* honest for the alert to fire-and-confess (`"fired on the quantitative condition only"`, `ai_used=False`) than to either silently fire as if the AI approved, or silently suppress. What would each of those dishonest alternatives cost the user's trust?

---

Previous: [Chapter 6 — Volatility & the square root of time](06-volatility.md) · Next: we've built the math and learned to doubt it — now we turn a formula into a service that runs forever, on time, and exactly once. [Chapter 8 — From a formula to a system](../documentation/08-from-math-to-system.md).
