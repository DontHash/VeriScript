#!/usr/bin/env python3
"""eval_date_flags_v3.py — pre-registered re-adjudication of `date_flags`
under the corrected digit-content metric (v3). See docs/PLAN.md Appendix AN.

Both arms run the shipped flag path (`ocr_page`, Devanagari digit re-pass on);
the only difference is `date_flags` off/on. The target clauses are exactly the
ones pre-registered in Appendix AN *before* this script's first run:

    content_r10_plus3pp   v2 full-41 v3 R@10 >= off + 0.03
    flag_precision_ge_0.5 flagged digit tokens that are v3-corrupted >= 0.5
    nonzero_hits          the new flag adds >= 1 true content-error hit
    text_identical        0 changed pages (flag-only)
    latency_ok            <= +0.1 s/page
  non-target (--role other, Amendment A1):
    content_r10_not_worse, content_p10_not_worse, no_false_new_flags,
    text_identical, latency_ok

Usage:
    python scripts/eval_date_flags_v3.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --role target --json out/date_flags_v3_v2.json
    python scripts/eval_date_flags_v3.py --data-dir data/doc_eval/heidata_printed \
        --role other --json out/date_flags_v3_heidata.json
    python scripts/eval_date_flags_v3.py --data-dir data/doc_eval/cornell_real \
        --lang en --role other --json out/date_flags_v3_cornell_en.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import metrics as doc_metrics  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import ocr_page, review_queue  # noqa: E402

LATENCY_BUDGET_S = 0.1
DEVA_DIGITS = {chr(0x0966 + i) for i in range(10)}


def _digit_tokens(text: str) -> List[str]:
    return [t for t in doc_metrics.tokens_of(text)
            if any(c in DEVA_DIGITS or c.isdigit() for c in t)]


def _legacy_r10(tokens, gt: str) -> Dict:
    gt_digits = {doc_metrics.digit_string(t) for t in _digit_tokens(gt)}
    gt_digits.discard("")
    errs = []
    for t in tokens:
        if not t.has_digits:
            continue
        d = doc_metrics.digit_string(t.text)
        if d and d not in gt_digits:
            errs.append(t)
    queue = review_queue(tokens)
    top = queue[:10]
    hits = sum(1 for t in top if any(t is e for e in errs))
    return {
        "errors": len(errs),
        "hits@10": hits,
        "R@10": round(hits / len(errs), 4) if errs else None,
        "P@10": round(hits / len(top), 4) if top else None,
    }


def _load_rows(data_dir: str, limit: int = 0) -> List[Dict]:
    manifest = doc_data.load_dataset(data_dir)
    rows = []
    for e in manifest["entries"]:
        img = doc_data.imread_safe(e["_degraded_path"])
        if img is None:
            continue
        try:
            gt = open(e["_gt_path"], encoding="utf-8").read()
        except OSError:
            gt = ""
        rows.append({"page": e["id"], "img": img, "gt": gt})
        if limit and len(rows) >= limit:
            break
    return rows


def _run_arm(rows: List[Dict], lang: str, date_flags: bool) -> Dict:
    per_page = []
    for r in rows:
        t0 = time.time()
        res = ocr_page(r["img"], backend="rapidocr", lang=lang,
                       recheck_digits=True, date_flags=date_flags)
        seconds = time.time() - t0
        rep = doc_content.content_errors(res.tokens, r["gt"])
        stats = doc_content.queue_stats_from_report(res.tokens, rep)
        corrupt = {id(res.tokens[i]) for i in rep["error_tokens"]}
        flagged_digits = [t for t in res.tokens
                          if t.has_digits and "invalid_format" in t.flags]
        per_page.append({
            "page": r["page"], "text": res.text, "seconds": seconds,
            "content": stats,
            "legacy": _legacy_r10(res.tokens, r["gt"]),
            "flagged_digits": len(flagged_digits),
            "flagged_digits_corrupt": sum(1 for t in flagged_digits
                                          if id(t) in corrupt),
            "queue_len": len(review_queue(res.tokens)),
        })
    summary = {
        "content_errors": sum(p["content"]["errors"] for p in per_page),
        "missing_gt_atoms": sum(p["content"]["missing_gt_runs"]
                                for p in per_page),
        "queue_slots@10": sum(p["content"]["top@10"] for p in per_page),
        "flagged_digits": sum(p["flagged_digits"] for p in per_page),
        "flagged_digits_corrupt": sum(p["flagged_digits_corrupt"]
                                      for p in per_page),
        "queue_len": sum(p["queue_len"] for p in per_page),
        "seconds_per_page": (round(sum(p["seconds"] for p in per_page)
                                   / len(per_page), 3) if per_page else None),
    }
    for k in (5, 10):
        hits = sum(p["content"][f"hits@{k}"] for p in per_page)
        top = sum(p["content"][f"top@{k}"] for p in per_page)
        summary[f"content_R@{k}"] = (round(hits / summary["content_errors"], 4)
                                     if summary["content_errors"] else None)
        summary[f"content_P@{k}"] = round(hits / top, 4) if top else None
    legacy_errors = sum(p["legacy"]["errors"] for p in per_page)
    legacy_hits = sum(p["legacy"]["hits@10"] for p in per_page)
    summary["legacy_errors"] = legacy_errors
    summary["legacy_R@10"] = (round(legacy_hits / legacy_errors, 4)
                              if legacy_errors else None)
    summary["flag_precision"] = (
        round(summary["flagged_digits_corrupt"] / summary["flagged_digits"], 4)
        if summary["flagged_digits"] else None)
    return {"summary": summary, "pages": per_page}


def _gate(off: Dict, on: Dict, role: str) -> Dict:
    so, sn = off["summary"], on["summary"]
    changed = sum(1 for a, b in zip(off["pages"], on["pages"])
                  if a["text"] != b["text"])
    clauses = {
        "text_identical": bool(changed == 0),
        "latency_ok": bool(
            (sn["seconds_per_page"] - so["seconds_per_page"])
            <= LATENCY_BUDGET_S),
    }
    if role == "target":
        r10o, r10n = so["content_R@10"], sn["content_R@10"]
        hits_o = sum(p["content"]["hits@10"] for p in off["pages"])
        hits_n = sum(p["content"]["hits@10"] for p in on["pages"])
        clauses["content_r10_plus3pp"] = bool(
            r10o is not None and r10n is not None and r10n >= r10o + 0.03)
        clauses["flag_precision_ge_0.5"] = bool(
            sn["flag_precision"] is not None and sn["flag_precision"] >= 0.5)
        clauses["nonzero_hits"] = bool(hits_n - hits_o >= 1)
    else:
        r10o, r10n = so["content_R@10"], sn["content_R@10"]
        p10o, p10n = so["content_P@10"], sn["content_P@10"]
        false_new = sn["flagged_digits"] - sn["flagged_digits_corrupt"]
        clauses["content_r10_not_worse"] = bool(
            r10o is None or (r10n is not None and r10n >= r10o))
        clauses["content_p10_not_worse"] = bool(
            p10o is None or (p10n is not None and p10n >= p10o))
        clauses["no_false_new_flags"] = bool(false_new <= 0)
    clauses["pass"] = all(v for v in clauses.values()
                          if isinstance(v, bool))
    return {"changed_pages": changed, "clauses": clauses,
            "flagged_delta": sn["flagged_digits"] - so["flagged_digits"],
            "false_new_flags": (sn["flagged_digits"]
                                - sn["flagged_digits_corrupt"])
            if role != "target" else 0,
            "delta_content_R@10": (
                round(sn["content_R@10"] - so["content_R@10"], 4)
                if so["content_R@10"] is not None
                and sn["content_R@10"] is not None else None)}


def run(data_dir: str, lang: str, limit: int, role: str,
        json_path: str) -> Dict:
    rows = _load_rows(data_dir, limit)
    off = _run_arm(rows, lang, False)
    on = _run_arm(rows, lang, True)
    gate = _gate(off, on, role)
    out = {"data_dir": data_dir, "lang": lang, "pages": len(rows),
           "role": role, "off": off["summary"], "on": on["summary"],
           "gate": gate}
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": out, "off_pages": off["pages"],
                       "on_pages": on["pages"]}, fh,
                      ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=True, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--lang", default="ne")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--role", choices=("target", "other"), default="target")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    run(args.data_dir, args.lang, args.limit, args.role, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
