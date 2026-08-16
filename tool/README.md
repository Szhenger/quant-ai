# QuantAI — Tool (external dependencies & local helpers)

Nothing in this repo runs on air. This folder is the honest inventory of everything
QuantAI **depends on but does not contain** — the interpreters, servers, and packages
that come from outside — plus the scripts that stand those things up on a bare machine.

## The dependency manifests (where "install the stuff" is defined)

CS50 gave you `pip install`; a real project pins *what* gets installed, per subsystem:

| Manifest | Installs | Consumed by |
|---|---|---|
| [`backend/requirements.txt`](../backend/requirements.txt) | Django, Channels, Celery, DRF, numpy, psycopg, … | Your venv (`make venv`), the [`backend/Dockerfile`](../backend/Dockerfile), and Render's build step |
| [`frontend/package.json`](../frontend/package.json) + `package-lock.json` | React, TypeScript, Vite, React Query, axios, … | `npm ci` locally, in CI, and on Render. The **lock file** is the point: everyone installs byte-identical versions |
| [`requirements.txt`](../requirements.txt) (repo root) | Nothing itself — one `-r backend/requirements.txt` line | Tooling that expects a top-level Python manifest (dependency scanners, some editors) |

## The programs you install once

These are not Python or npm packages; they're infrastructure the app talks to over the
network ([`network/`](../network/README.md) explains each conversation):

- **Python 3.12** — the backend interpreter (`backend/Dockerfile` pins `python:3.12-slim`).
- **Node 20+** — builds and serves the frontend in development.
- **PostgreSQL 16** — the database. Via Docker (`runtime/docker-compose.yml`), or locally
  with the script below.
- **Redis 7** — broker, channel layer, cache. Via Docker, or `brew install redis`.
- **Docker** (optional but easiest) — runs all of the above without installing any of it.

## `devdb.sh` — a local Postgres without Docker

Some machines can't run Docker. [`devdb.sh`](devdb.sh) builds a **self-contained
PostgreSQL 16 cluster inside the repo** (data in `.devdb/`, gitignored) using Homebrew's
`postgresql@16`, listening on `127.0.0.1` only:

```bash
tool/devdb.sh init     # first time: create the cluster + the quantai database
tool/devdb.sh start    # start it
tool/devdb.sh stop     # stop it
tool/devdb.sh status   # is it running?
```

(Or the same via `make db-init` / `db-start` / `db-stop` / `db-status`.)

Two deliberate choices in that script worth reading, because they're the kind of thing
that bites in real life: it is **TCP-only** (unix sockets disabled, so a deeply nested
repo path can't overflow the kernel's 103-byte socket-path limit), and it uses **trust
auth on loopback** — fine for a laptop, never for anything reachable from a network.

## One rule for this folder

Scripts here may **set up** external things; they must never contain application logic.
If a helper starts making decisions about strategies, alerts, or markets, it belongs in
[`backend/`](../backend/README.md) where the tests can see it.
