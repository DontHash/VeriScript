#!/usr/bin/env python3
"""eval_queue_composition.py — one-off diagnostic for the queue-noise work.

Runs the shipped flag path (product defaults: Devanagari repass + date flags),
computes v3 content errors, then answers:

1. What occupies the top-10 of the review queue? (content error / legacy
   digit error / clean token, by flag signature)
2. Which flags contribute content hits?
3. Counterfactual: drop one flag at a time from the queue (tokens whose only
   flags are dropped leave the queue; the rest re-rank) — how do v3 R@10,
   P@10 and slot count move on `nepali_pdf_v2`?

Usage:
    python scripts/eval_queue_composition.py \
        --data-dir data/doc_eval/nepali_pdf_v2 --json out/queue_composition_v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import metrics as doc_metrics  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import (RISK_WEIGHTS, ocr_page,  # noqa: E402
                                     review_queue, token_risk)

DEVA_DIGITS = {chr(0x0966 + i) for i in range(10)}
CANDIDATES = ("unknown_word", "low_conf", "script_mismatch",
              "invalid_sequence", "invalid_format", "digit_added")


def _digit_tokens(text: str) -> List[str]:
    return [t for t in doc_metrics.tokens_of(text)
            if any(c in DEVA_DIGITS or c.isdigit() for c in t)]


def _legacy_ids(tokens, gt: str) -> set:
    gt_digits = {doc_metrics.digit_string(t) for t in _digit_tokens(gt)}
    gt_digits.discard("")
    return {id(t) for t in tokens
            if t.has_digits
            and doc_metrics.digit_string(t.text)
            and doc_metrics.digit_string(t.text) not in gt_digits}


def _queue_with_drop(tokens, errored_ids: set, drop: Optional[str]):
    """Review queue with `drop` suppressed at the source.

    Tokens whose flags are all in {drop} leave the queue; the rest re-rank
    with `drop` removed from the weight sum. Repass/alt bonuses stay as
    `token_risk` defines them (the drop arms here target pure flag weights).
    """
    risky = []
    for t in tokens:
        remaining = [f for f in t.flags if f != drop]
        if not remaining:
            continue  # flag suppressed at the source -> not flagged at all
        risky.append((sum(RISK_WEIGHTS.get(f, 1.0) for f in remaining), t))
    risky.sort(key=lambda p: (-p[0], p[1].bbox[1], p[1].bbox[0]))
    top = [t for _, t in risky[:10]]
    hits = sum(1 for t in top if id(t) in errored_ids)
    return {"hits@10": hits, "top@10": len(top),
            "queue": len(risky)}


def run(data_dir: str, lang: str, limit: int, json_path: str) -> Dict:
    manifest = doc_data.load_dataset(data_dir)
    entries = manifest["entries"][: limit or None]

    # single OCR pass; keep tokens + error sets per page, then score all arms
    cache = []
    for e in entries:
        img = doc_data.imread_safe(e["_degraded_path"])
        if img is None:
            continue
        gt = open(e["_gt_path"], encoding="utf-8").read()
        res = ocr_page(img, backend="rapidocr", lang=lang, recheck_digits=True)
        rep = doc_content.content_errors(res.tokens, gt)
        errored = {id(res.tokens[i]) for i in rep["error_tokens"]}
        cache.append({"page": e["id"], "tokens": res.tokens, "gt": gt,
                      "errored": errored,
                      "legacy": _legacy_ids(res.tokens, gt)})

    agg = {"slots": 0, "hits": 0, "errors": 0}
    sig_counts: Counter = Counter()
    content_hit_flags: Counter = Counter()
    per_token = []
    for c in cache:
        queue = review_queue(c["tokens"])
        agg["errors"] += len(c["errored"])
        for t in queue[:10]:
            agg["slots"] += 1
            is_err = id(t) in c["errored"]
            agg["hits"] += 1 if is_err else 0
            sig = "+".join(sorted(t.flags)) or "(none)"
            kind = ("content" if is_err else
                    "legacy" if id(t) in c["legacy"] else "clean")
            sig_counts[(kind, sig)] += 1
            if is_err:
                content_hit_flags[sig] += 1
        per_token.append({"page": c["page"], "queue_len": len(queue),
                          "errors": len(c["errored"])})

    base = {"R@10": (round(agg["hits"] / agg["errors"], 4)
                     if agg["errors"] else None),
            "P@10": (round(agg["hits"] / agg["slots"], 4)
                     if agg["slots"] else None),
            "slots": agg["slots"], "hits": agg["hits"],
            "errors": agg["errors"]}

    # where are the missed errors: flagged-but-outranked, or unflagged?
    miss_flagged = miss_unflagged = 0
    for c in cache:
        top_ids = {id(t) for t in review_queue(c["tokens"])[:10]}
        for t in c["tokens"]:
            if id(t) in c["errored"] and id(t) not in top_ids:
                if t.flags:
                    miss_flagged += 1
                else:
                    miss_unflagged += 1
    base["missed_flagged_outranked"] = miss_flagged
    base["missed_unflagged"] = miss_unflagged

    arms = {}
    for drop in CANDIDATES:
        slots = hits = 0
        for c in cache:
            q = _queue_with_drop(c["tokens"], c["errored"], drop)
            slots += q["top@10"]
            hits += q["hits@10"]
        arms[drop] = {"R@10": (round(hits / base["errors"], 4)
                               if base["errors"] else None),
                      "P@10": round(hits / slots, 4) if slots else None,
                      "slots": slots, "hits": hits}

    # digit-first queue: rank only digit-bearing flagged tokens (product
    # reshape candidate; word flags stay visible elsewhere)
    slots = hits = 0
    for c in cache:
        risky = [t for t in c["tokens"] if t.flags and t.has_digits]
        risky.sort(key=lambda t: (-token_risk(t), t.bbox[1], t.bbox[0]))
        top = risky[:10]
        slots += len(top)
        hits += sum(1 for t in top if id(t) in c["errored"])
    arms["digit_only_queue"] = {
        "R@10": (round(hits / base["errors"], 4) if base["errors"] else None),
        "P@10": round(hits / slots, 4) if slots else None,
        "slots": slots, "hits": hits}

    out = {"data_dir": data_dir, "pages": len(per_token),
           "baseline": base, "drop_flag_arms": arms,
           "slot_composition": [
               {"kind": k, "flags": f, "slots": n}
               for (k, f), n in sig_counts.most_common()],
           "content_hit_flag_signatures": dict(content_hit_flags)}
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": out, "pages": per_token}, fh,
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
