# QuantAI — Documentation (the subsystems, from first principles)

The [`math/`](../math/README.md) chapters end with a formula you can trust. This folder
answers the next CS50-style question: **how does a formula become software you can
trust?** These are the engineering chapters and reference docs — written, like the math,
assuming nothing beyond CS50x: if you know what a function, a route, and an HTTP request
are, every idea here is built up from that.

## The engineering chapters (read in order)

| Chapter | The question it answers |
|---|---|
| [8 — From a formula to a system](08-from-math-to-system.md) | How do you turn an equation into a service that runs forever? Data feeds, workspaces, the evaluation pipeline, delivery. |
| [9 — The API as a contract](09-the-api-contract.md) | How do humans and machines talk to this safely? Routes, JWT identity, workspace tenancy, WebSockets — the promises both sides keep. |
| [10 — Concurrency & safety](10-concurrency-and-safety.md) | Why did it send the same alert twice, and how do we make it *never* happen? Locks, idempotency, exactly-once delivery. |

Chapter 10 is the payoff of the entire project. "Exactly once" is where real money and
real bugs live, and it cannot be bolted on afterward.

## The reference docs

- [**`abstractions.md`**](abstractions.md) — the project's language-and-layers map: which
  language each subsystem speaks and why, and the abstraction each folder is allowed to
  assume about the others.

## The subsystem guides

Each subsystem folder carries its own README in the same voice — the *where* to these
chapters' *why*:

| Folder | Subsystem |
|---|---|
| [`backend/`](../backend/README.md) | The engine room — Django apps, the worker fleet, the test suite and UX-invariant framework. |
| [`frontend/`](../frontend/README.md) | The cockpit — the React/TypeScript client, its API layer, and the live-alert socket. |
| [`runtime/`](../runtime/README.md) | The running instances — the five processes, Docker Compose stacks, and the production blueprint. |
| [`network/`](../network/README.md) | The wire — every protocol between the pieces: DNS to TLS to HTTP to WebSockets to Redis. |
| [`math/`](../math/README.md) | The course — chapters 0–7, the quant math itself. |
| [`tool/`](../tool/README.md) | External dependencies and local-machine helpers. |

## How the docs stay honest

Two mechanisms keep these pages from drifting into fiction:

1. **Every claim points at code.** Chapters link to the exact file and function; if the
   link breaks, the doc is wrong and the PR that broke it should fix it.
2. **The contract is executable.** Chapter 9's wire shapes are pinned by golden fixtures
   in `backend/test/journeys/fixtures/`, enforced from the backend by
   `test_contract_fixtures.py` and from the frontend at compile time by
   `frontend/src/api/contracts.test.ts`. The prose describes a contract that tests refuse
   to let either side break silently.
