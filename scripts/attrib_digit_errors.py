#!/usr/bin/env python3
"""attrib_digit_errors.py — one-off forensic attribution of the v2 digit errors.

Answers, mechanically (no guessing):
  1. What is each GT digit error made of (matching Appendix AM taxonomy)?
  2. Which errors are already flagged / in the top-10 (i.e. counted by R@10)?
  3. How many are *merge-only* — every individual digit run matches a GT run,
     but the joined string does not (metric says error; splitting would fix it)?
  4. What would a structural mixed-content flag (no model) buy: precision,
     recall, and the counterfactual queue R@10 / P@10 after re-ranking?

Usage:
    python scripts/attrib_digit_errors.py \
        --data-dir data/doc_eval/nepali_pdf_v2 \
        --json out/attrib_digit_errors_v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import metrics as doc_metrics  # noqa: E402
from veriscript.document.ocr import ocr_page, review_queue, token_risk  # noqa: E402

DEVA_DIGITS = {chr(0x0966 + i) for i in range(10)}
_DEVA_DIGIT_MAP = {chr(0x0966 + i): str(i) for i in range(10)}
_RUN_RE = re.compile(r"[0-9\u0966-\u096f](?:[0-9\u0966-\u096f.,:/-]*[0-9\u0966-\u096f])?")
_LETTER_RE = re.compile(r"[\u0900-\u097fA-Za-z]")


def _digit_tokens(text: str) -> List[str]:
    return [t for t in doc_metrics.tokens_of(text)
            if any(c in DEVA_DIGITS or c.isdigit() for c in t)]


def _norm_run(run: str) -> str:
    return "".join(_DEVA_DIGIT_MAP.get(c, c) for c in run)


def _runs(text: str) -> List[Tuple[int, int, str]]:
    """(start, end, normalized run) for each digit run in text."""
    return [(m.start(), m.end(), _norm_run(m.group(0)))
            for m in _RUN_RE.finditer(text)]


def _lev_ops(a: str, b: str) -> Tuple[int, int, int, int]:
    """Levenshtein distance + (subs, inserts, dels) of one best alignment.

    inserts = chars in `a` missing from `b`; dels = chars in `b` extra.
    Small strings (digit runs), so the O(nm) table is fine.
    """
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    op = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0], op[i][0] = i, "DEL"      # delete from a
    for j in range(1, m + 1):
        dp[0][j], op[0][j] = j, "INS"      # insert into a
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j], op[i][j] = dp[i - 1][j - 1], "OK"
                continue
            cand = (dp[i - 1][j - 1] + 1, "SUB", dp[i - 1][j] + 1, "DEL",
                    dp[i][j - 1] + 1, "INS")
            best = min((cand[0], cand[1]), (cand[2], cand[3]), (cand[4], cand[5]))
            dp[i][j], op[i][j] = best[0], best[1]
    i, j = n, m
    subs = ins = dels = 0
    while i > 0 or j > 0:
        o = op[i][j]
        if o == "OK":
            i, j = i - 1, j - 1
        elif o == "SUB":
            subs += 1
            i, j = i - 1, j - 1
        elif o == "DEL":
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return dp[n][m], subs, ins, dels


def _mixed_flags(text: str) -> Dict[str, bool]:
    """Structural candidate rules (flag-only, engine-free)."""
    runs = _runs(text)
    multi = len(runs) >= 2
    letters_between = False
    for (_, e1, _), (s2, _, _) in zip(runs, runs[1:]):
        if _LETTER_RE.search(text[e1:s2]):
            letters_between = True
            break
    marker = bool(re.match(r"^[0-9\u0966-\u096f]{1,2}[.)।]", text.strip())
                  and multi)
    return {
        "mixed_letters": multi and letters_between,
        "marker_merge": marker,
        "any_multi_run": multi,
        "mixed_or_marker": (multi and letters_between) or marker,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/doc_eval/nepali_pdf_v2")
    ap.add_argument("--lang", default="ne")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="out/attrib_digit_errors_v2.json")
    args = ap.parse_args()

    manifest = doc_data.load_dataset(args.data_dir)
    entries = manifest["entries"]
    if args.limit:
        entries = entries[: args.limit]

    all_errors: List[Dict] = []
    all_tokens: List[Dict] = []
    page_rows: List[Dict] = []
    rules = ("mixed_letters", "marker_merge", "any_multi_run", "mixed_or_marker")
    rule_stats = {r: {"flagged_digit": 0, "true_flagged": 0} for r in rules}
    rule_queue: Dict[str, List[Dict]] = {r: [] for r in rules}

    for e in entries:
        img = doc_data.imread_safe(e["_degraded_path"])
        if img is None:
            continue
        try:
            gt = open(e["_gt_path"], encoding="utf-8").read()
        except OSError:
            gt = ""
        res = ocr_page(img, backend="rapidocr", lang=args.lang,
                       recheck_digits=True)
        gt_tok_digits = {doc_metrics.digit_string(t) for t in _digit_tokens(gt)}
        gt_tok_digits.discard("")
        gt_runs: List[str] = []
        for t in _digit_tokens(gt):
            gt_runs.extend(_norm_run(m.group(0)) for m in _RUN_RE.finditer(t))

        queue = review_queue(res.tokens)
        rank = {id(t): i for i, t in enumerate(queue)}
        page_errors = []
        for t in res.tokens:
            if not t.has_digits:
                continue
            d = doc_metrics.digit_string(t.text)
            if not d or d in gt_tok_digits:
                continue
            # ---- this token is counted as a digit error ----
            rec = {
                "page": e["id"], "text": t.text, "digits": d,
                "conf": t.conf, "flags": list(t.flags),
                "repass_text": t.repass_text, "alt_text": t.alt_text,
                "risk": round(token_risk(t), 2),
                "queue_rank": rank.get(id(t)),
            }
            # taxonomy vs closest page GT value
            best = min(gt_tok_digits, key=lambda g: _lev_ops(d, g)[0],
                       default=None)
            if best is None:
                rec["class"] = "unmatched"
            else:
                dist, subs, ins, dels = _lev_ops(d, best)
                if dist > 2:
                    rec["class"] = "unmatched"
                elif subs and (ins or dels):
                    rec["class"] = "complex"
                elif subs:
                    rec["class"] = "substitution"
                else:
                    rec["class"] = "insert" if ins else "delete"
                rec["gt_closest"] = best
                rec["edit_dist"] = dist
            # grouping artifact: every raw run (separators included) exists in
            # the page GT runs with matching multiplicity -> the token joins
            # separately-correct numbers (line-level token vs word-level GT)
            tok_runs = [r for _, _, r in _runs(t.text)]
            rec["runs_in_gt"] = not (Counter(tok_runs) - Counter(gt_runs))
            # structural candidate rules
            mr = _mixed_flags(t.text)
            rec["rules"] = mr
            for r in rules:
                if mr[r]:
                    rule_stats[r]["flagged_digit"] += 1
                    rule_stats[r]["true_flagged"] += 1  # it IS an error
            page_errors.append(rec)

        # per-token rule firing over ALL digit tokens (for flag precision)
        for t in res.tokens:
            if not t.has_digits:
                continue
            d = doc_metrics.digit_string(t.text)
            is_err = bool(d) and d not in gt_tok_digits
            mr = _mixed_flags(t.text)
            all_tokens.append({"page": e["id"], "is_err": is_err, "rules": mr})
            for r in rules:
                if mr[r] and not is_err:
                    rule_stats[r]["flagged_digit"] += 1  # fired, not an error

        # counterfactual queue per rule: base risk + weight for rule-fired tokens
        for r in rules:
            fired_any = False
            risky: List[Tuple[float, object]] = []
            for t in res.tokens:
                fired = _mixed_flags(t.text)[r]
                if fired or t.flags:
                    fired_any = fired_any or fired
                    risk = token_risk(t) + (2.0 if fired else 0.0)
                    risky.append((risk, t))
            if not fired_any:
                continue
            risky.sort(key=lambda p: (-p[0], p[1].bbox[1], p[1].bbox[0]))
            top = [t for _, t in risky[:10]]
            hits = sum(
                1 for t in top
                if t.has_digits
                and doc_metrics.digit_string(t.text)
                and doc_metrics.digit_string(t.text) not in gt_tok_digits
            )
            rule_queue[r].append({
                "page": e["id"], "hits@10": hits, "top@10": len(top),
                "errors": len(page_errors),
            })

        all_errors.extend(page_errors)
        page_rows.append({
            "page": e["id"], "errors": len(page_errors),
            "flagged_errors": sum(1 for r in page_errors if r["flags"]),
            "queue_len": len(queue),
        })

    errs_total = len(all_errors)
    cls_counts: Dict[str, int] = {}
    for r in all_errors:
        cls_counts[r["class"]] = cls_counts.get(r["class"], 0) + 1
    flagged = sum(1 for r in all_errors if r["flags"])
    in_top10 = sum(1 for r in all_errors
                   if r["queue_rank"] is not None and r["queue_rank"] < 10)
    # A: every raw run appears in the page GT runs (grouping/length artifact
    #    under the word-level GT convention); B: real digit-content residual.
    artifact = [r for r in all_errors if r["runs_in_gt"]]
    residual = [r for r in all_errors if not r["runs_in_gt"]]
    artifact_top10 = sum(1 for r in artifact
                         if r["queue_rank"] is not None and r["queue_rank"] < 10)
    residual_top10 = sum(1 for r in residual
                         if r["queue_rank"] is not None and r["queue_rank"] < 10)

    # baseline queue metrics (exact harness convention)
    hits = in_top10
    top_slots = sum(min(10, p["queue_len"]) for p in page_rows)

    rule_summary = {}
    for r in rules:
        st = rule_stats[r]
        rq = rule_queue[r]
        cf_hits = sum(p["hits@10"] for p in rq)
        cf_top = sum(p["top@10"] for p in rq)
        rule_summary[r] = {
            "flagged_digit_tokens": st["flagged_digit"],
            "true_errors_flagged": st["true_flagged"],
            "precision": (round(st["true_flagged"] / st["flagged_digit"], 4)
                          if st["flagged_digit"] else None),
            "recall_of_errors": (round(st["true_flagged"] / errs_total, 4)
                                 if errs_total else None),
            "counterfactual_R@10": (round(cf_hits / errs_total, 4)
                                    if rq and errs_total else None),
            "counterfactual_P@10": (round(cf_hits / cf_top, 4)
                                    if cf_top else None),
        }

    summary = {
        "pages": len(page_rows),
        "digit_errors": errs_total,
        "flagged_errors": flagged,
        "errors_in_top10": in_top10,
        "baseline_R@10": (round(hits / errs_total, 4) if errs_total else None),
        "baseline_P@10": (round(hits / top_slots, 4) if top_slots else None),
        "queue_slots": top_slots,
        "class_counts": cls_counts,
        "grouping_artifact_errors": len(artifact),
        "grouping_artifact_in_top10": artifact_top10,
        "residual_errors": len(residual),
        "residual_in_top10": residual_top10,
        "residual_R@10": (round(residual_top10 / len(residual), 4)
                          if residual else None),
        "rule_summary": rule_summary,
    }

    if args.json:
        os.makedirs(os.path.dirname(args.json) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "pages": page_rows,
                       "errors": all_errors,
                       "tokens": all_tokens}, fh,
                      ensure_ascii=False, indent=1)

    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
