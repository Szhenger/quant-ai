"""Toolchain detection and suite execution.

The runner's contract: a suite either PASSES, FAILS, or is honestly reported
UNAVAILABLE (the toolchain it needs doesn't exist on this machine) — it never
silently skips work. Backend suites prefer the local venv (fast, needs the dev
Postgres from ``make db-start``) and fall back to the Docker test stack (CI
parity, needs Docker); frontend suites need node/npm.
"""
import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from .suites import Suite

REPO = Path(__file__).resolve().parent.parent.parent

PASS, FAIL, UNAVAILABLE = "pass", "fail", "unavailable"


@dataclass
class Outcome:
    suite: str
    status: str
    seconds: float
    detail: str = ""


def _venv_pytest() -> Optional[Path]:
    candidate = REPO / "backend" / ".venv" / "bin" / "pytest"
    return candidate if candidate.exists() else None


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd: List[str], cwd: Path) -> int:
    print(f"\n$ {' '.join(cmd)}   (in {cwd.relative_to(REPO) if cwd != REPO else '.'})")
    return subprocess.call(cmd, cwd=str(cwd))


def _pytest_args(suite: Suite, extra: List[str]) -> List[str]:
    args = ["-q"]
    if suite.marker:
        args += ["-m", suite.marker]
    return args + extra


def run_pytest_suite(suite: Suite, extra: List[str], prefer: str) -> Outcome:
    started = time.monotonic()
    venv = _venv_pytest()
    if prefer != "docker" and venv is not None:
        code = _run([str(venv)] + _pytest_args(suite, extra), REPO / "backend")
        return Outcome(suite.name, PASS if code == 0 else FAIL,
                       time.monotonic() - started, "local venv + dev Postgres")
    if prefer != "local" and _have("docker"):
        code = _run(
            ["docker", "compose", "-f", "runtime/docker-compose.test.yml",
             "run", "--rm", "--build", "test", "pytest"]
            + _pytest_args(suite, extra),
            REPO,
        )
        return Outcome(suite.name, PASS if code == 0 else FAIL,
                       time.monotonic() - started, "docker compose test stack")
    return Outcome(
        suite.name, UNAVAILABLE, time.monotonic() - started,
        "needs backend/.venv (make venv + make db-start) or Docker "
        "(make test-docker); on this machine, push and let CI run it",
    )


def run_vitest_suite(suite: Suite, extra: List[str]) -> Outcome:
    started = time.monotonic()
    if not _have("npm"):
        return Outcome(suite.name, UNAVAILABLE, time.monotonic() - started,
                       "needs node 20+ / npm (frontend/README.md)")
    cmd = ["npm", "test", "--"] + suite.paths + extra
    code = _run(cmd, REPO / "frontend")
    return Outcome(suite.name, PASS if code == 0 else FAIL,
                   time.monotonic() - started, "vitest via frontend/node_modules")


def run_suite(suite: Suite, extra: List[str], prefer: str = "auto") -> Outcome:
    if suite.kind == "pytest":
        return run_pytest_suite(suite, extra, prefer)
    return run_vitest_suite(suite, extra)


def summarize(outcomes: List[Outcome], report_path: Optional[str] = None) -> int:
    icon = {PASS: "ok", FAIL: "FAIL", UNAVAILABLE: "----"}
    width = max(len(o.suite) for o in outcomes)
    print("\n" + "=" * 60)
    for o in outcomes:
        print(f"  {o.suite:<{width}}  {icon[o.status]:>4}  {o.seconds:6.1f}s  {o.detail}")
    print("=" * 60)
    if report_path:
        Path(report_path).write_text(
            json.dumps([asdict(o) for o in outcomes], indent=2) + "\n"
        )
        print(f"report written to {report_path}")
    if any(o.status == FAIL for o in outcomes):
        return 1
    if any(o.status == UNAVAILABLE for o in outcomes):
        return 2  # nothing failed, but not everything requested could run
    return 0
