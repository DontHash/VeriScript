#!/usr/bin/env python3
"""eval_digit_content.py — corrected (v3) digit-content queue baselines.

Re-measures a frozen set with the run-level content definition
(`veriscript/core/digit_content.py`) next to the legacy token-vs-GT-set metric,
so the 2026-10-09 measurement fix (docs/PLAN.md Appendix AN) is verifiable.

Legacy definitions mirrored from `scripts/eval_number_split.py` `_queue_metrics`
(the AG/AH gate convention): a digit token errors when `digit_string(text)` is
absent from the page's word-level GT digit set.

Usage:
    python scripts/eval_digit_content.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --json out/digit_content/v2_full.json
    python scripts/eval_digit_content.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --limit 10
    python scripts/eval_digit_content.py --data-dir data/doc_eval/heidata_printed
    python scripts/eval_digit_content.py --data-dir data/doc_eval/cornell_real
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

DEVA_DIGITS = {chr(0x0966 + i) for i in range(10)}


def _digit_tokens(text: str) -> List[str]:
    return [t for t in doc_metrics.tokens_of(text)
            if any(c in DEVA_DIGITS or c.isdigit() for c in t)]


def _legacy_queue_metrics(tokens, gt: str) -> Dict:
    """Exact `eval_number_split._queue_metrics` (AG/AH gate convention)."""
    gt_digits = {doc_metrics.digit_string(t) for t in _digit_tokens(gt)}
    gt_digits.discard("")
    errs, digit_total = [], 0
    for t in tokens:
        if not t.has_digits:
            continue
        digit_total += 1
        d = doc_metrics.digit_string(t.text)
        if d and d not in gt_digits:
            errs.append(t)
    queue = review_queue(tokens)
    out = {"digit_tokens": digit_total, "errors": len(errs),
           "queue": len(queue)}
    for k in (5, 10):
        top = queue[:k]
        out[f"hits@{k}"] = sum(1 for t in top if any(t is e for e in errs))
        out[f"top@{k}"] = len(top)
    return out


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


def run(data_dir: str, lang: str, limit: int, json_path: str) -> Dict:
    rows = _load_rows(data_dir, limit)
    per_page = []
    for r in rows:
        t0 = time.time()
        res = ocr_page(r["img"], backend="rapidocr", lang=lang,
                       recheck_digits=True)
        seconds = time.time() - t0
        legacy = _legacy_queue_metrics(res.tokens, r["gt"])
        rep = doc_content.content_errors(res.tokens, r["gt"])
        content = doc_content.queue_stats_from_report(res.tokens, rep)
        # legacy errors that are content-clean = the grouping artifact mass
        gt_digits = {doc_metrics.digit_string(t)
                     for t in _digit_tokens(r["gt"])}
        gt_digits.discard("")
        legacy_ids = {id(t) for t in res.tokens
                      if t.has_digits
                      and doc_metrics.digit_string(t.text)
                      and doc_metrics.digit_string(t.text) not in gt_digits}
        content_ids = {id(res.tokens[i]) for i in rep["error_tokens"]}
        per_page.append({
            "page": r["page"],
            "legacy": legacy,
            "content": content,
            "grouping_clean_legacy_errors": len(legacy_ids - content_ids),
            "content_only_errors": len(content_ids - legacy_ids),
            "seconds": round(seconds, 3),
        })
    n = len(per_page)
    out = {
        "data_dir": data_dir, "lang": lang, "pages": n,
        "legacy": {},
        "content": {},
    }
    lerr = sum(p["legacy"]["errors"] for p in per_page)
    for k in (5, 10):
        hits = sum(p["legacy"][f"hits@{k}"] for p in per_page)
        top = sum(p["legacy"][f"top@{k}"] for p in per_page)
        out["legacy"][f"R@{k}"] = round(hits / lerr, 4) if lerr else None
        out["legacy"][f"P@{k}"] = round(hits / top, 4) if top else None
    chits = {k: sum(p["content"][f"hits@{k}"] for p in per_page)
             for k in (5, 10)}
    ctop = {k: sum(p["content"][f"top@{k}"] for p in per_page)
            for k in (5, 10)}
    cerr = sum(p["content"]["errors"] for p in per_page)
    out["legacy"]["errors"] = lerr
    out["legacy"]["queue_slots@10"] = ctop[10]
    out["content"]["errors"] = cerr
    out["content"]["missing_gt_runs"] = sum(
        p["content"]["missing_gt_runs"] for p in per_page)
    out["content"]["queue_slots@10"] = ctop[10]
    for k in (5, 10):
        out["content"][f"R@{k}"] = (round(chits[k] / cerr, 4)
                                    if cerr else None)
        out["content"][f"P@{k}"] = (round(chits[k] / ctop[k], 4)
                                    if ctop[k] else None)
    out["grouping_clean_legacy_errors"] = sum(
        p["grouping_clean_legacy_errors"] for p in per_page)
    out["content_only_errors"] = sum(p["content_only_errors"]
                                     for p in per_page)
    out["seconds_per_page"] = round(sum(p["seconds"] for p in per_page) / n, 2)
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": out, "rows": per_page}, fh,
                      ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=True, indent=2))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--lang", default="ne")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    run(args.data_dir, args.lang, args.limit, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
