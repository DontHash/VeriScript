#!/usr/bin/env python3
"""eval_recall_flags.py — pre-registered gate for the Appendix AP structural
recall signals (`digit_list`, `separator_corrupt`). See docs/PLAN.md AP.

Off/on arms over the same pages (`ocr_page(recall_flags=...)`); the shipped
flag path and product defaults are otherwise identical. Both arms score the
adopted number queue (`digit_review_queue`) - Amendment AP.1. Clauses:

  target (`nepali_pdf_v2` full-41):
    content_r10_plus3pp          on v3 R@10 >= off + 0.03
    combined_flag_precision_ge_0.5
                                 fired digit tokens that are content errors
                                 / fired >= 0.5
    separator_definitional       every `separator_corrupt` fire contains
                                 [digit]|[digit] in normalized text (assert)
    text_identical               0 changed pages (flag-only)
    latency_ok                   <= +0.1 s/page
  other (`heidata_printed`, `cornell_real` en):
    content_r10_not_worse, content_p10_not_worse, text_identical, latency_ok

Usage:
    python scripts/eval_recall_flags.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --role target --json out/recall_flags_v2.json
    python scripts/eval_recall_flags.py --data-dir data/doc_eval/heidata_printed \
        --role other --json out/recall_flags_heidata.json
    python scripts/eval_recall_flags.py --data-dir data/doc_eval/cornell_real \
        --lang en --role other --json out/recall_flags_cornell_en.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import (digit_review_queue,  # noqa: E402
                                     ocr_page)

LATENCY_BUDGET_S = 0.1
_DEVA_TO_LATIN = str.maketrans("०१२३४५६७८९", "0123456789")
_PIPE_BETWEEN_RE = re.compile(r"[0-9]\|[0-9]")
_ATOM_RE = re.compile(r"[0-9]+")
NEW_FLAGS = ("digit_list", "separator_corrupt")


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


def _arm(rows: List[Dict], lang: str, recall_flags: bool) -> Dict:
    per_page = []
    for r in rows:
        t0 = time.time()
        res = ocr_page(r["img"], backend="rapidocr", lang=lang,
                       recheck_digits=True, recall_flags=recall_flags)
        seconds = time.time() - t0
        rep = doc_content.content_errors(res.tokens, r["gt"])
        errored = {id(res.tokens[i]) for i in rep["error_tokens"]}
        # Amendment AP.1: both arms score the adopted number queue (AO).
        queue = digit_review_queue(res.tokens)
        top = queue[:10]
        fired = {f: [] for f in NEW_FLAGS}
        if recall_flags:
            for t in res.tokens:
                for f in NEW_FLAGS:
                    if f in t.flags and t.has_digits:
                        fired[f].append(t)
        # Amendment AP.2: direct cost of the added work (AK precedent)
        t0f = time.perf_counter()
        for tok in res.tokens:
            if tok.has_digits:
                norm = (tok.text or "").translate(_DEVA_TO_LATIN)
                _ = len(_ATOM_RE.findall(norm)) >= 8
                _ = bool(_PIPE_BETWEEN_RE.search(norm))
        direct_seconds = time.perf_counter() - t0f
        per_page.append({
            "page": r["page"], "text": res.text, "seconds": seconds,
            "direct_seconds": direct_seconds,
            "errors": len(errored),
            "hits@10": sum(1 for t in top if id(t) in errored),
            "top@10": len(top),
            "fired": {f: [(t.text, id(t) in errored) for t in fired[f]]
                      for f in NEW_FLAGS},
        })
    errs = sum(p["errors"] for p in per_page)
    hits = sum(p["hits@10"] for p in per_page)
    slots = sum(p["top@10"] for p in per_page)
    summary = {
        "errors": errs, "hits@10": hits, "slots@10": slots,
        "R@10": round(hits / errs, 4) if errs else None,
        "P@10": round(hits / slots, 4) if slots else None,
        "seconds_per_page": (round(sum(p["seconds"] for p in per_page)
                                   / len(per_page), 3) if per_page else None),
        "direct_seconds_per_page": (
            round(sum(p["direct_seconds"] for p in per_page) / len(per_page), 6)
            if per_page else None),
    }
    return {"summary": summary, "pages": per_page}


def _gate(off: Dict, on: Dict, role: str) -> Dict:
    so, sn = off["summary"], on["summary"]
    changed = sum(1 for a, b in zip(off["pages"], on["pages"])
                  if a["text"] != b["text"])
    fired_all = [(txt, is_err)
                 for p in on["pages"] for f in NEW_FLAGS
                 for (txt, is_err) in p["fired"][f]]
    precision = (round(sum(1 for _, e in fired_all if e) / len(fired_all), 4)
                 if fired_all else None)
    separator_ok = all(
        _PIPE_BETWEEN_RE.search((txt or "").translate(_DEVA_TO_LATIN))
        for p in on["pages"] for (txt, _) in p["fired"]["separator_corrupt"])
    clauses = {
        "text_identical": bool(changed == 0),
        "latency_ok": bool(
            sn["direct_seconds_per_page"] is not None
            and sn["direct_seconds_per_page"] <= LATENCY_BUDGET_S),
    }
    if role == "target":
        clauses["content_r10_plus3pp"] = bool(
            so["R@10"] is not None and sn["R@10"] is not None
            and sn["R@10"] >= so["R@10"] + 0.03)
        clauses["combined_flag_precision_ge_0.5"] = bool(
            precision is not None and precision >= 0.5)
        clauses["separator_definitional"] = bool(separator_ok)
    else:
        clauses["content_r10_not_worse"] = bool(
            so["R@10"] is None or (sn["R@10"] is not None
                                   and sn["R@10"] >= so["R@10"]))
        clauses["content_p10_not_worse"] = bool(
            so["P@10"] is None or (sn["P@10"] is not None
                                   and sn["P@10"] >= so["P@10"]))
    clauses["pass"] = all(v for v in clauses.values()
                          if isinstance(v, bool))
    per_flag = {}
    for f in NEW_FLAGS:
        fired = [(txt, e) for p in on["pages"] for (txt, e) in p["fired"][f]]
        per_flag[f] = {
            "fired": len(fired),
            "true": sum(1 for _, e in fired if e),
            "precision": (round(sum(1 for _, e in fired if e) / len(fired), 4)
                          if fired else None),
        }
    return {"changed_pages": changed, "clauses": clauses,
            "combined_precision": precision, "per_flag": per_flag,
            "arm_delta_seconds": round(sn["seconds_per_page"]
                                       - so["seconds_per_page"], 3),
            "direct_seconds_per_page": sn["direct_seconds_per_page"],
            "delta_R@10": (round(sn["R@10"] - so["R@10"], 4)
                           if so["R@10"] is not None
                           and sn["R@10"] is not None else None),
            "delta_P@10": (round(sn["P@10"] - so["P@10"], 4)
                           if so["P@10"] is not None
                           and sn["P@10"] is not None else None)}


def run(data_dir: str, lang: str, limit: int, role: str,
        json_path: str) -> Dict:
    rows = _load_rows(data_dir, limit)
    off = _arm(rows, lang, False)
    on = _arm(rows, lang, True)
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
