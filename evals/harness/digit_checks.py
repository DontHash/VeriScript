"""Score the phone's digit re-checks (docs/TECH_UPGRADE_PLAN.md, D2).

Reads a comparison run made with `compare_ocr.py --digits both`: every
number line carries the same-engine verdict (`digitCheck`) and the
other-engine verdict (`digitCrossCheck`). A line is wrong when one of its
digit groups is not in the page's ground truth (by value, so Devanagari,
Bengali and ASCII digits compare equal). A check catches a wrong line when
it says conflict or unreadable; on a right line that is a false alarm.

python -m evals.harness.digit_checks build/ocr-comparison/c1d1 mobile_mlkit_d2
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

_DIGITS = re.compile(r"[0-9०-९০-৯]+")


def groups(text: str):
    out = []
    for m in _DIGITS.finditer(text or ""):
        out.append("".join(
            chr(ord(c) - 0x966 + 48) if "०" <= c <= "९" else
            chr(ord(c) - 0x9E6 + 48) if "০" <= c <= "৯" else c
            for c in m.group(0)))
    return out


def score(pack: Path, engine_dir: str) -> dict:
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))["entries"]
    tally = {m: collections.Counter() for m in ("same", "cross")}
    ms = {"same": [], "cross": []}
    for row in manifest:
        meta_path = pack / "outputs" / engine_dir / f"{row['id']}.json"
        if not meta_path.exists():
            continue
        gt = collections.Counter(groups((pack / row["gt"]).read_text(encoding="utf-8")))
        page = json.loads(meta_path.read_text(encoding="utf-8"))["page"]
        for line in page["lines"]:
            if "digitCrossCheck" not in line:
                continue
            first = groups(line.get("original", line["text"]))
            remaining = gt.copy()
            wrong = False
            for g in first:
                if remaining[g] > 0:
                    remaining[g] -= 1
                else:
                    wrong = True
            for method, key in (("same", "digitCheck"), ("cross", "digitCrossCheck")):
                flagged = line.get(key) in ("conflict", "unreadable")
                tally[method][("wrong" if wrong else "right", flagged)] += 1
            ms["same"].append(line.get("digitSameMs", 0))
            ms["cross"].append(line.get("digitCrossMs", 0))
    out = {}
    for method, t in tally.items():
        wrong = t[("wrong", True)] + t[("wrong", False)]
        right = t[("right", True)] + t[("right", False)]
        out[method] = {
            "wrong_lines": wrong, "caught": t[("wrong", True)],
            "recall": round(t[("wrong", True)] / wrong, 3) if wrong else None,
            "right_lines": right, "false_alarms": t[("right", True)],
            "false_alarm_rate": round(t[("right", True)] / right, 3) if right else None,
            "mean_ms_per_line": round(sum(ms[method]) / len(ms[method])) if ms[method] else None,
        }
    return out


if __name__ == "__main__":
    print(json.dumps(score(Path(sys.argv[1]), sys.argv[2]), indent=2))
