"""qtest — QuantAI's suite runner.

Stdlib-only on purpose: it must run on a bare ``python3`` (3.9+) before any
virtualenv or node_modules exists, because its whole job is to figure out
which toolchains ARE available and route each suite to the right one.
"""
