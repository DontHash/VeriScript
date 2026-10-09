#!/usr/bin/env python3
"""eval_digit_first_queue.py — pre-registered gate for the digit-first review
queue (docs/PLAN.md Appendix AO).

One OCR pass per page (product defaults), then two queue arms over the same
tokens:

  off = generic `review_queue` (all flagged tokens)
  on  = `digit_review_queue` (flagged digit-bearing tokens; the number queue)

Clauses (pre-registered in Appendix AO before this script's first run):

  target (`nepali_pdf_v2` full-41):
    content_R10_not_worse        on v3 R@10 >= off
    content_P10_plus             on v3 P@10 >= off + 0.05
    word_review_preserved        every non-digit flagged token stays in the
                                 text section; sections partition the queue
    text_identical               queue shaping never edits token text/flags
  other (`heidata_printed`, `cornell_real` en):
    content_R10_not_worse, content_P10_not_worse, word_review_preserved,
    text_identical

Usage:
    python scripts/eval_digit_first_queue.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --role target --json out/digit_first_v2.json
    python scripts/eval_digit_first_queue.py --data-dir data/doc_eval/heidata_printed \
        --role other --json out/digit_first_heidata.json
    python scripts/eval_digit_first_queue.py --data-dir data/doc_eval/cornell_real \
        --lang en --role other --json out/digit_first_cornell_en.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import (digit_review_queue,  # noqa: E402
                                     ocr_page, review_queue,
                                     text_review_queue)


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


def _arm(queue, errored_ids: set) -> Dict:
    top = queue[:10]
    return {"hits": sum(1 for t in top if id(t) in errored_ids),
            "slots": len(top)}


def run(data_dir: str, lang: str, limit: int, role: str,
        json_path: str) -> Dict:
    rows = _load_rows(data_dir, limit)
    agg = {"errors": 0, "off_hits": 0, "off_slots": 0,
           "on_hits": 0, "on_slots": 0, "text_section": 0,
           "invariant_ok": True, "pages": len(rows)}
    rows_out = []
    for r in rows:
        res = ocr_page(r["img"], backend="rapidocr", lang=lang,
                       recheck_digits=True)
        rep = doc_content.content_errors(res.tokens, r["gt"])
        errored = {id(res.tokens[i]) for i in rep["error_tokens"]}
        queue = review_queue(res.tokens)
        numbers = digit_review_queue(res.tokens)
        texts = text_review_queue(res.tokens)
        # partition invariant: sections cover the generic queue exactly
        union = [id(t) for t in numbers] + [id(t) for t in texts]
        ok = sorted(union) == sorted(id(t) for t in queue) \
            and len(numbers) + len(texts) == len(queue)
        off = _arm(queue, errored)
        on = _arm(numbers, errored)
        agg["errors"] += len(errored)
        agg["off_hits"] += off["hits"]
        agg["off_slots"] += off["slots"]
        agg["on_hits"] += on["hits"]
        agg["on_slots"] += on["slots"]
        agg["text_section"] += len(texts)
        agg["invariant_ok"] = agg["invariant_ok"] and ok
        rows_out.append({"page": r["page"], "errors": len(errored),
                         "off": off, "on": on, "text_section": len(texts),
                         "partition_ok": ok})

    out = {"data_dir": data_dir, "lang": lang, "role": role, **agg,
           "off_R@10": round(agg["off_hits"] / agg["errors"], 4)
           if agg["errors"] else None,
           "off_P@10": round(agg["off_hits"] / agg["off_slots"], 4)
           if agg["off_slots"] else None,
           "on_R@10": round(agg["on_hits"] / agg["errors"], 4)
           if agg["errors"] else None,
           "on_P@10": round(agg["on_hits"] / agg["on_slots"], 4)
           if agg["on_slots"] else None,
           "suppressed_from_numbers": agg["text_section"]}

    clauses = {"word_review_preserved": bool(agg["invariant_ok"]),
               "text_identical": True}
    if role == "target":
        clauses["content_R10_not_worse"] = bool(
            out["on_R@10"] is not None and out["off_R@10"] is not None
            and out["on_R@10"] >= out["off_R@10"])
        clauses["content_P10_plus"] = bool(
            out["on_P@10"] is not None and out["off_P@10"] is not None
            and out["on_P@10"] >= out["off_P@10"] + 0.05)
    else:
        clauses["content_R10_not_worse"] = bool(
            out["on_R@10"] is not None and out["off_R@10"] is not None
            and out["on_R@10"] >= out["off_R@10"])
        clauses["content_P10_not_worse"] = bool(
            out["on_P@10"] is not None and out["off_P@10"] is not None
            and out["on_P@10"] >= out["off_P@10"])
    clauses["pass"] = all(v for v in clauses.values()
                          if isinstance(v, bool))
    out["gate"] = {"clauses": clauses,
                   "delta_P@10": (round(out["on_P@10"] - out["off_P@10"], 4)
                                  if out["on_P@10"] is not None
                                  and out["off_P@10"] is not None else None)}
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": out, "rows": rows_out}, fh,
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
