"""The suite registry — the single map from a behavior area to how it's tested.

A Suite names a *behavior of the application* (REST components, React
functionality, Celery/Redis semantics, PostgreSQL storage); the runner decides
*where* it executes (local venv, Docker, npm). Adding a coverage area =
adding a Suite here; ``qtest list`` and the README table both read this
registry, so it can't drift from what actually runs.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Suite:
    name: str            # CLI name: ./test/qtest run <name>
    kind: str            # "pytest" | "vitest"
    description: str
    marker: Optional[str] = None      # pytest -m <marker> (None = whole suite)
    paths: List[str] = field(default_factory=list)  # vitest file filters
    focus: bool = True   # a headline focus area (shown first in `qtest list`)


SUITES = [
    # --- The four focus areas -------------------------------------------- #
    Suite("rest", "pytest",
          "REST components: route-sweep auth, contracts, pagination, "
          "throttle scopes, tenant isolation, caching/ETag behavior",
          marker="rest"),
    Suite("react", "vitest",
          "ReactJS functionality: alert cache merges, reconnect backoff, "
          "cursor pagination, realtime user journeys, type/contract pins"),
    Suite("celery-redis", "pytest",
          "Celery/Redis behavior: sweep claim protocol, eval locking, "
          "delivery + reconciliation, beat schedule, retention, config "
          "invariants",
          marker="celery_redis"),
    Suite("postgres", "pytest",
          "PostgreSQL storage: JSONB, check constraints, cascades, row "
          "locks (SELECT FOR UPDATE), indexes, migration drift",
          marker="postgres"),
    # --- Supporting suites ------------------------------------------------ #
    Suite("indicators", "pytest",
          "Quant math: every indicator pinned to hand-derived numbers, plus "
          "bar caching and provider fallback honesty",
          marker="indicators", focus=False),
    Suite("journeys", "pytest",
          "End-to-end user journeys and the golden contract fixtures "
          "(backend half of the dual pin)",
          marker="journeys", focus=False),
    Suite("contracts", "vitest",
          "Frontend half of the contract dual pin (types.ts vs fixtures)",
          paths=["api/contracts.test.ts"], focus=False),
    Suite("backend", "pytest",
          "The entire backend pytest suite (all markers)", focus=False),
]


def get(name: str) -> Suite:
    for suite in SUITES:
        if suite.name == name:
            return suite
    known = ", ".join(s.name for s in SUITES)
    raise KeyError(f"unknown suite {name!r} — known suites: {known}")
