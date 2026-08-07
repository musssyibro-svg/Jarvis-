#!/usr/bin/env python3
"""
tools/mutate.py — break the code on purpose and see if the tests notice.

WHY THIS EXISTS. Jarvis has 185 tests and one rule above all others: never
report success unless it was verified. Those two facts have to be connected —
a test suite that goes green against deliberately broken code is making exactly
the claim this project forbids. "185 passed" would be a false Done ✓, and the
most expensive kind, because it is the thing you check before believing
everything else.

This is the code-level twin of tools/failure_injection.py. That harness breaks
the RUNTIME and asks whether Jarvis fails honestly. This one breaks the SOURCE
and asks whether the tests fail at all.

    mutation SURVIVED  -> the tests do not actually check that line
    mutation KILLED    -> a test caught it, which is what tests are for

Scoped deliberately. A full mutation run over 60 modules would take hours and
nobody would run it twice. This targets the TRUST-CRITICAL paths — the ones
that decide whether Jarvis tells you the truth — and runs only the tests that
could plausibly cover them, so the whole thing finishes in a couple of minutes.

    python tools/mutate.py              # the trust-critical set
    python tools/mutate.py --file backend/services/trace.py
    python tools/mutate.py --list       # what it would try, without running

Adapted from the standard mutation-testing approach (mutmut, cosmic-ray) rather
than depending on either: both want to own the whole test run and neither knows
which of this project's tests are offline-safe. This is ~200 lines and does the
one job.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The lines that decide whether Jarvis is believed. A surviving mutation here
# matters far more than one in a helper nobody reads.
TARGETS = {
    "backend/agents/desktop_agent.py": ["backend/tests/test_click_verification.py",
                                        "backend/tests/test_app_detection.py",
                                        "backend/tests/test_felt_behaviour.py"],
    "backend/services/trace.py":       ["backend/tests/test_profiling_and_failures.py"],
    "backend/agents/browser_agent.py": ["backend/tests/test_url_gate.py"],
    "backend/services/conversation.py": ["backend/tests/test_conversation.py"],
    "backend/services/experience.py":  ["backend/tests/test_felt_behaviour.py",
                                        "backend/tests/test_url_gate.py"],
    "backend/services/tool_registry.py": ["backend/tests/test_felt_behaviour.py",
                                          "backend/tests/test_decompose.py"],
}


class _Mutator(ast.NodeTransformer):
    """Applies exactly ONE mutation — the `nth` opportunity it finds."""

    def __init__(self, nth: int):
        self.nth = nth
        self.seen = 0
        self.applied = ""

    def _take(self, what: str) -> bool:
        hit = self.seen == self.nth
        self.seen += 1
        if hit:
            self.applied = what
        return hit

    # True <-> False. The single most relevant operator in this codebase:
    # `verified` and `success` are booleans, and flipping one is precisely the
    # bug the project is built to prevent.
    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            if self._take(f"{node.value} -> {not node.value} (line {node.lineno})"):
                return ast.copy_location(ast.Constant(value=not node.value), node)
        return node

    # Comparison flips catch off-by-one and threshold errors — the shape of the
    # "waited 8s instead of 9s" and "changed by 5 pixels not 6" bugs.
    _CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE,
            ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
            ast.In: ast.NotIn, ast.NotIn: ast.In,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is}

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) == 1:
            swap = self._CMP.get(type(node.ops[0]))
            if swap and self._take(
                    f"{type(node.ops[0]).__name__} -> {swap.__name__} "
                    f"(line {node.lineno})"):
                return ast.copy_location(
                    ast.Compare(left=node.left, ops=[swap()],
                                comparators=node.comparators), node)
        return node

    # and <-> or. Turns "blocked AND unverified" into "blocked OR unverified",
    # which is how a gate quietly stops gating.
    def visit_BoolOp(self, node):
        self.generic_visit(node)
        swap = ast.Or if isinstance(node.op, ast.And) else ast.And
        if self._take(f"{type(node.op).__name__} -> {swap.__name__} "
                      f"(line {node.lineno})"):
            return ast.copy_location(ast.BoolOp(op=swap(), values=node.values), node)
        return node


def _count_opportunities(tree: ast.AST) -> int:
    m = _Mutator(-1)
    m.visit(tree)
    return m.seen


def _mutate(source: str, nth: int) -> tuple[str, str]:
    tree = ast.parse(source)
    m = _Mutator(nth)
    tree = m.visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree), m.applied


def _run_tests(tests: list[str], timeout: int = 240) -> bool:
    """True when the suite PASSES (i.e. the mutation survived unnoticed)."""
    # PYTHONDONTWRITEBYTECODE, and it is not optional.
    #
    # CPython validates a cached .pyc by the source's mtime AND SIZE. Every
    # mutation here is a one-character edit — "or" to "and" — so successive
    # mutations produce files of IDENTICAL size, written within the same second
    # on a filesystem with 1-second mtime granularity. Python then decides the
    # previous .pyc is still valid and runs the PREVIOUS mutation.
    #
    # The result is a mutation tester that lies in both directions: harmless
    # mutations get reported as survivors, and real gaps get hidden behind a
    # stale "killed". This tool exists to stop the tests lying; it cannot be
    # the thing that lies.
    import os
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *tests, "-x", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT, capture_output=True, timeout=timeout, env=env)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        # A mutation that hangs the suite is caught, not survived — an infinite
        # loop is a failure the tests noticed in the most emphatic way.
        return False


def _drop_pycache(path: Path) -> None:
    """Remove any already-cached bytecode for the file we are about to mutate."""
    cache = path.parent / "__pycache__"
    if not cache.is_dir():
        return
    for pyc in cache.glob(f"{path.stem}.*.pyc"):
        try:
            pyc.unlink()
        except OSError:
            pass


def run_file(rel: str, tests: list[str], budget: int, quiet: bool) -> dict:
    path = ROOT / rel
    original = path.read_text(encoding="utf8")
    total = _count_opportunities(ast.parse(original))

    # Evenly spaced sample rather than the first N: the first N are all in the
    # module docstring region and constants, which prove nothing.
    step = max(1, total // budget)
    picks = list(range(0, total, step))[:budget]

    survived, killed, skipped = [], 0, 0
    print(f"\n  {rel}  ({total} mutable points, sampling {len(picks)})")
    try:
        for nth in picks:
            mutated, what = _mutate(original, nth)
            if not what:
                continue
            try:
                compile(mutated, rel, "exec")
            except SyntaxError:
                skipped += 1
                continue
            path.write_text(mutated, encoding="utf8")
            _drop_pycache(path)          # belt and braces; see _run_tests
            passed = _run_tests(tests)
            if passed:
                survived.append(what)
                print(f"    SURVIVED  {what}")
            else:
                killed += 1
                if not quiet:
                    print(f"    killed    {what}")
    finally:
        path.write_text(original, encoding="utf8")   # ALWAYS put it back

    return {"file": rel, "total": total, "tried": len(picks),
            "killed": killed, "survived": survived, "skipped": skipped}


def main() -> int:
    ap = argparse.ArgumentParser(description="Mutation testing for Jarvis")
    ap.add_argument("--file", help="one file (must be in TARGETS)")
    ap.add_argument("--budget", type=int, default=12,
                    help="mutations per file (default 12)")
    ap.add_argument("--list", action="store_true", help="show targets and exit")
    ap.add_argument("--quiet", action="store_true", help="only print survivors")
    args = ap.parse_args()

    if args.list:
        for f, t in TARGETS.items():
            print(f"{f}\n    tested by: {', '.join(t)}")
        return 0

    targets = ({args.file: TARGETS[args.file]} if args.file else TARGETS)
    if args.file and args.file not in TARGETS:
        print(f"{args.file} is not a trust-critical target. Add it to TARGETS "
              f"with the tests that should cover it.")
        return 2

    print("=" * 74)
    print("JARVIS — MUTATION TESTING")
    print("Breaking the code on purpose. A SURVIVED mutation means the tests")
    print("do not actually check that line.")
    print("=" * 74)

    started = time.time()
    reports = [run_file(f, t, args.budget, args.quiet) for f, t in targets.items()]

    total_surv = sum(len(r["survived"]) for r in reports)
    total_killed = sum(r["killed"] for r in reports)
    tried = total_surv + total_killed

    print("\n" + "=" * 74)
    print(f"  {total_killed}/{tried} mutations caught "
          f"({(total_killed / tried * 100) if tried else 0:.0f}% killed) "
          f"in {time.time() - started:.0f}s")
    if total_surv:
        print(f"\n  {total_surv} mutation(s) SURVIVED — these lines are not")
        print("  covered by any assertion. Each one is a place the tests would")
        print("  stay green while Jarvis misbehaved:\n")
        for r in reports:
            for s in r["survived"]:
                print(f"    {r['file']}: {s}")
        print("\n  Not every survivor needs a test — a flipped constant in a log")
        print("  message changes nothing that matters. Judge each on whether the")
        print("  MUTATION would have been a real bug.")
    else:
        print("\n  Every sampled mutation was caught.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
