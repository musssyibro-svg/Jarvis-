"""
run_all_tests.py — Jarvis V8 complete verification runner (final).

Usage:
    python run_all_tests.py              # all tests
    python run_all_tests.py --quick      # skip network/Playwright-heavy tests
    python run_all_tests.py test_health  # single test
    python run_all_tests.py --clean 7   # clean artifacts older than 7 days first
"""
import sys
import json
import argparse
import importlib
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _harness import dump_ollama_status, RESULTS, ARTIFACTS, cleanup_old_artifacts

ALL_TESTS = [
    "test_health",
    "test_hubstaff",
    "test_clickworker",
    "test_zuodao",
    "test_desktop",
    "test_browser_profile",
    "test_executor",
    "test_llava",
    "test_chat_persistence",
    "test_sse",
    "test_playwright_recovery",
    "test_v85_wiring",
    "test_v9_stage1",
]

HEAVY = {
    "test_hubstaff","test_clickworker","test_zuodao",
    "test_browser_profile","test_executor",
    "test_chat_persistence","test_sse","test_playwright_recovery",
}


def main():
    parser = argparse.ArgumentParser(description="Jarvis V8 Verification Suite")
    parser.add_argument("tests", nargs="*", help="specific test names to run")
    parser.add_argument("--quick", action="store_true",
                        help="skip network/Playwright-heavy tests")
    parser.add_argument("--clean", type=int, metavar="DAYS",
                        help="delete artifacts older than DAYS days before running")
    args = parser.parse_args()

    if args.clean:
        removed = cleanup_old_artifacts(args.clean)
        print(f"  Cleaned {removed} old artifact(s) (>{args.clean} days)")

    tests_to_run = args.tests if args.tests else ALL_TESTS
    if args.quick:
        tests_to_run = [t for t in tests_to_run if t not in HEAVY]
        print("  [--quick] network/Playwright tests skipped")

    print("=" * 68)
    print("  JARVIS V8 — VERIFICATION SUITE (Final)")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 68)

    ollama_dump = dump_ollama_status()
    print(f"  Ollama/RAM dump: {Path(ollama_dump).name}")

    reports = []
    for name in tests_to_run:
        print(f"\n▶  {name}")
        print("-" * 68)
        try:
            mod    = importlib.import_module(name)
            report = mod.run()
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"   [CRASH] {name}: {e}")
            report = {
                "test":        name,
                "result":      "FAIL",
                "skip_reason": "",
                "checks":      [],
                "artifacts":   [],
                "logs":        [f"CRASH: {e}", tb],
            }
            (RESULTS / f"{name}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        reports.append(report)

    passed  = sum(1 for r in reports if r.get("result") == "PASS")
    failed  = sum(1 for r in reports if r.get("result") == "FAIL")
    skipped = sum(1 for r in reports if r.get("result") == "SKIP")

    final = {
        "suite":        "jarvis_v8_verification_final",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total":        len(reports),
        "passed":       passed,
        "failed":       failed,
        "skipped":      skipped,
        "results": [
            {
                "test":        r.get("test"),
                "result":      r.get("result"),
                "skip_reason": r.get("skip_reason",""),
                "checks_run":  len(r.get("checks",[])),
                "artifacts":   r.get("artifacts",[]),
            }
            for r in reports
        ],
        "detail_files": [f"results/{r.get('test')}.json" for r in reports],
        "artifacts_dir": str(ARTIFACTS),
    }

    out = RESULTS / "final_report.json"
    out.write_text(json.dumps(final, indent=2), encoding="utf-8")

    print("\n" + "=" * 68)
    print(f"  RESULT: {passed} PASS  {failed} FAIL  {skipped} SKIP"
          f"  ({len(reports)} total)")
    symbols = {"PASS":"✓","FAIL":"✗","SKIP":"—"}
    for r in reports:
        sym  = symbols.get(r.get("result","?"),"?")
        skip = f"  ({r['skip_reason'][:55]})" if r.get("skip_reason") else ""
        print(f"  {sym}  {r.get('result','?'):4}  {r.get('test')}{skip}")
    print(f"\n  Report  → {out}")
    print(f"  Artifacts → {ARTIFACTS}")
    print("=" * 68)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
