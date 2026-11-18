"""Performance budgets (docs/TECH_UPGRADE_PLAN.md G): a regression fails CI.

Budgets live in perf_budgets.json at the repository root.

  python scripts/perf_budget.py desktop-page            # measure + check
  python scripts/perf_budget.py apk NAME path/to.apk    # size in MB + check
  python scripts/perf_budget.py startup NAME PACKAGE/.Activity [--adb adb]
  python scripts/perf_budget.py check NAME VALUE        # any measured value
  python scripts/perf_budget.py from-log FILE           # every "CI_METRIC name=value" line

Each check prints "name: value (budget max)" and exits 1 when over budget.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
BUDGETS = os.path.join(ROOT, "perf_budgets.json")


def budgets() -> dict:
    with open(BUDGETS, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def check(name: str, value: float) -> bool:
    entry = budgets().get(name)
    if entry is None:
        raise SystemExit(f"no budget named {name!r} in perf_budgets.json")
    ok = value <= entry["max"]
    print(f"{name}: {value:.2f} (budget {entry['max']}){'' if ok else '  OVER BUDGET'}")
    # GitHub Actions job summary, when available.
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"| {name} | {value:.2f} | {entry['max']} | {'ok' if ok else '**over**'} |\n")
    return ok


def desktop_page() -> float:
    """Seconds for one generated text page, model loaded, median of 3."""
    import cv2
    import numpy as np

    from veriscript.document.pipeline import run_document_pipeline

    rng = np.random.default_rng(1)
    img = np.full((2400, 1700, 3), 245, np.uint8)
    img += rng.integers(0, 8, img.shape, dtype=np.uint8)
    for i in range(30):
        cv2.putText(img, f"Line {i} total 12,500.75 ref 98412{i:02d} ward 7", (80, 120 + i * 72),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 3)
    kwargs = dict(make_pdf=False, make_overlay=False, make_txt=False, make_json=False, make_md=False)
    run_document_pipeline(img, **kwargs)  # warm-up: model loading is not page time
    times = []
    for _ in range(3):
        start = time.perf_counter()
        run_document_pipeline(img, **kwargs)
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def startup(component: str, adb: str) -> float:
    """Cold start TotalTime (ms) of an installed app, median of 3."""
    package = component.split("/")[0]
    times = []
    for _ in range(3):
        subprocess.run([adb, "shell", "am", "force-stop", package], check=True)
        time.sleep(2)
        out = subprocess.run([adb, "shell", "am", "start", "-W", "-n", component],
                             capture_output=True, text=True, check=True).stdout
        m = re.search(r"TotalTime:\s*(\d+)", out)
        if not m:
            raise SystemExit(f"no TotalTime in:\n{out}")
        times.append(int(m.group(1)))
    return float(statistics.median(times))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("desktop-page")
    a = sub.add_parser("apk")
    a.add_argument("name")
    a.add_argument("path")
    s = sub.add_parser("startup")
    s.add_argument("name")
    s.add_argument("component")
    s.add_argument("--adb", default="adb")
    c = sub.add_parser("check")
    c.add_argument("name")
    c.add_argument("value", type=float)
    lg = sub.add_parser("from-log")
    lg.add_argument("file")
    args = ap.parse_args()

    if args.cmd == "desktop-page":
        ok = check("desktop_page_seconds", desktop_page())
    elif args.cmd == "apk":
        ok = check(args.name, os.path.getsize(args.path) / 1e6)
    elif args.cmd == "startup":
        ok = check(args.name, startup(args.component, args.adb))
    elif args.cmd == "check":
        ok = check(args.name, args.value)
    else:
        found = re.findall(r"CI_METRIC (\w+)=([\d.]+)", open(args.file, encoding="utf-8", errors="replace").read())
        if not found:
            raise SystemExit("no CI_METRIC lines found")
        ok = all([check(name, float(value)) for name, value in found])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
