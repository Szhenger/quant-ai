# QuantAI — Runtime (the running instances)

CS50 taught you to write a program, run it, and watch it exit. A web application is a
different animal: it is a **set of programs that never exit**, running at the same time,
talking to each other over the network. This folder is about *that* — not what the code
says (that's [`backend/`](../backend/README.md) and [`frontend/`](../frontend/README.md)),
but what is actually **running** when QuantAI is alive, and the files that start it all.

## The cast of processes

When QuantAI is up, five long-lived processes exist. Each one is a program you could start
by hand in its own terminal; the files in this folder just start them for you and keep them
alive.

| Process | Program | What it does all day |
|---|---|---|
| **db** | PostgreSQL 16 | Remembers everything: users, workspaces, strategies, alerts. The only place state survives a restart. Think of it as `SQL` from CS50's finance pset, grown up. |
| **redis** | Redis 7 | A very fast shared scratchpad in memory. Three tenants share it: the Celery **broker** (the queue of "evaluate strategy #42" jobs), the **channel layer** (how a worker tells the API "push this alert down the WebSocket"), and the **cache/locks** (the "exactly-once" locks of [Chapter 10](../documentation/10-concurrency-and-safety.md)). |
| **api** | Daphne running Django (`config.asgi`) | The front door. Answers every HTTP request *and* holds every live WebSocket open. |
| **worker** | Celery worker | The muscle. Pulls evaluation jobs off the Redis queue and runs the math from [`math/`](../math/README.md) against fresh market bars. |
| **beat** | Celery beat | The heartbeat. Once a minute it asks "which strategies are due?" and enqueues a job for each. It does no work itself — it only schedules. |

Why not one program? Because these jobs have different shapes. The API must answer in
milliseconds and must never block; an evaluation may take seconds and may retry. Put them
in one process and a slow evaluation freezes the UI for everyone. Split them, and each can
crash, restart, and **scale** (run more copies of just the worker) independently. That
split is the whole idea of this folder.

## The files here

- **`docker-compose.yml`** — the local development stack. One command from the repo root
  starts all five processes, wired together on a private network:

  ```bash
  docker compose -f runtime/docker-compose.yml up --build
  ```

  Each service in the file names its program, its environment, and — importantly — its
  **healthcheck**: a small command Docker runs on a loop ("can Postgres accept a
  connection?", "does `/healthz/` answer?"). The `depends_on … condition: service_healthy`
  lines use those to start things in the right order: the API doesn't launch until the
  database is genuinely ready, not merely started. Postgres and Redis are published on
  **127.0.0.1 only**, because the dev credentials are public knowledge — see
  [`network/`](../network/README.md) for why loopback-only matters.

- **`docker-compose.test.yml`** — the CI stack, deliberately tiny: one throwaway Postgres
  and one container that runs `pytest` against it, then both vanish. No Redis (tests run
  Celery **eagerly** — jobs execute inline — and use an in-memory channel layer), no ports
  published at all. This is exactly what GitHub Actions runs:

  ```bash
  docker compose -f runtime/docker-compose.test.yml run --rm --build test
  ```

- **`render.yml`** — the same five-process story, but for production on
  [Render](https://render.com): the API as a `web` service, worker and beat as `worker`
  services, managed Postgres and Redis, plus the frontend as a static site. What compose
  does with containers on your laptop, this does with managed services in a datacenter.
  The shape is identical on purpose — dev/prod parity means the bug you see locally is the
  bug production has.

  > **Note:** Render's Blueprint sync feature looks for `render.yaml` at the **repo
  > root**. This file lives here so all "running instance" configuration is in one place;
  > if you deploy via Blueprint sync, point Render at this path (or copy it to the root as
  > `render.yaml`).

## One image, three services

Look closely at `docker-compose.yml`: **api**, **worker**, and **beat** all say
`build: ../backend`. They are the *same program* — the same Docker image built from
[`backend/Dockerfile`](../backend/Dockerfile) — started with three different commands
(`daphne …`, `celery … worker`, `celery … beat`). That's not laziness; it's a guarantee.
All three see the same code, the same models, the same settings, so a strategy the API
saves is exactly the strategy the worker evaluates.

## Where the state lives (and doesn't)

A container's filesystem is disposable — `down` and it's gone. Anything that must survive
lives in exactly two places:

- the named volume `quantai_pg` (Postgres's data directory), and
- nowhere else. Redis is treated as *rebuildable*: queues drain, caches refill, locks
  expire. If that ever stops being true, it's a bug (and Chapter 10 explains why).

So `docker compose -f runtime/docker-compose.yml down` is always safe, and
`down -v` is the "erase my dev database" move.

## No Docker?

Every process here can be run by hand — [`backend/README.md`](../backend/README.md) has
the recipe (venv + `daphne` + two `celery` commands), and
[`tool/devdb.sh`](../tool/devdb.sh) stands up the local Postgres without Docker. This
folder automates the choreography; it doesn't hide it.
