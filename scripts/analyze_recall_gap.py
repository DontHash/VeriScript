#!/usr/bin/env python3
"""analyze_recall_gap.py — one-off: what are the unflagged v2 content errors,
and which structural signals could flag them without drowning the queue.

One OCR pass (product defaults). For every digit token: features, flags, queue
rank, content-error status. Then candidate rules are simulated as extra flags
(weight 2.0) and scored against the v3 content metric:

  precision  = rule-fired tokens that are content errors / rule-fired tokens
  recall     = content errors flagged by the rule / all content errors
  recovered  = missed errors that enter the top-10 once the rule fires
  R@10/P@10  = counterfactual queue after adding the rule

Usage:
    python scripts/analyze_recall_gap.py --data-dir data/doc_eval/nepali_pdf_v2 \
        --json out/recall_gap_v2.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import (RISK_WEIGHTS, ocr_page,  # noqa: E402
                                     review_queue, token_risk)

_RULE_WEIGHT = 2.0
_DEVA = {chr(0x0966 + i): str(i) for i in range(10)}
_LETTERS_RE = re.compile(r"[\u0900-\u097fA-Za-z]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_LATIN_ADJ_RE = re.compile(r"[A-Za-z][0-9]|[0-9][A-Za-z]")
_SUSPECT_SEP_RE = re.compile(r"[|।]")
_ATOMS_RE = re.compile(r"[0-9]+")


def _norm(text: str) -> str:
    return "".join(_DEVA.get(c, c) for c in text or "")


def _features(text: str) -> Dict:
    norm = _norm(text)
    spans = [(m.start(), m.end()) for m in _ATOMS_RE.finditer(norm)]
    atoms = [norm[s:e] for s, e in spans]
    letters_between = any(
        _LETTERS_RE.search(norm[spans[i][1]:spans[i + 1][0]])
        for i in range(len(spans) - 1))
    return {
        "atoms": atoms,
        "n_atoms": len(atoms),
        "letters_between": letters_between,
        "has_latin": bool(_LATIN_RE.search(text or "")),
        "latin_adjacent": bool(_LATIN_ADJ_RE.search(norm)),
        "suspect_sep": bool(_SUSPECT_SEP_RE.search(text or "")),
        "text_len": len(text or ""),
    }


def _rule_fires(name: str, f: Dict) -> bool:
    if name == "mixed_letters":
        return f["n_atoms"] >= 2 and f["letters_between"]
    if name == "multi_atom_3":
        return f["n_atoms"] >= 3
    if name == "latin_adjacent":
        return f["latin_adjacent"]
    if name == "suspect_sep":
        return f["suspect_sep"] and f["n_atoms"] >= 1
    if name == "long_token":
        return f["text_len"] >= 40
    if name == "mixed_or_latin":
        return (f["n_atoms"] >= 2 and f["letters_between"]) \
            or f["latin_adjacent"]
    return False


RULES = ("mixed_letters", "multi_atom_3", "latin_adjacent", "suspect_sep",
         "long_token", "mixed_or_latin")


def run(data_dir: str, lang: str, limit: int, json_path: str) -> Dict:
    manifest = doc_data.load_dataset(data_dir)
    entries = manifest["entries"][: limit or None]

    tokens_out: List[Dict] = []
    per_page = []
    n_err = 0
    for e in entries:
        img = doc_data.imread_safe(e["_degraded_path"])
        if img is None:
            continue
        gt = open(e["_gt_path"], encoding="utf-8").read()
        res = ocr_page(img, backend="rapidocr", lang=lang, recheck_digits=True)
        rep = doc_content.content_errors(res.tokens, gt)
        errored = {id(res.tokens[i]) for i in rep["error_tokens"]}
        n_err += len(errored)
        queue = review_queue(res.tokens)
        rank = {id(t): i for i, t in enumerate(queue)}
        for t in res.tokens:
            if not t.has_digits:
                continue
            f = _features(t.text)
            r = rank.get(id(t))
            tokens_out.append({
                "page": e["id"], "text": t.text, "conf": round(t.conf, 2),
                "flags": list(t.flags), "repass_text": t.repass_text,
                "alt_text": t.alt_text, "rank": r, "is_err": id(t) in errored,
                **f,
            })
        per_page.append({"page": e["id"], "errors": len(errored)})

    missed = [t for t in tokens_out
              if t["is_err"] and (t["rank"] is None or t["rank"] >= 10)]
    print(f"content errors: {n_err} | in top-10: "
          f"{sum(1 for t in tokens_out if t['is_err'] and t['rank'] is not None and t['rank'] < 10)}"
          f" | missed: {len(missed)}")

    # candidate-rule arms: add the flag (weight 2.0) and re-rank
    def _risk(t: Dict, rule: str) -> float:
        base = sum(RISK_WEIGHTS.get(fl, 1.0) for fl in t["flags"])
        if t["repass_text"] is not None:
            d1 = "".join(_ATOMS_RE.findall(_norm(t["text"])))
            d2 = "".join(_ATOMS_RE.findall(_norm(t["repass_text"])))
            if d1 != d2:
                base += 2.0
        if t["alt_text"] is not None:
            base += 0.5
        if _rule_fires(rule, t):
            base += _RULE_WEIGHT
        return base

    arms = {}
    for rule in RULES:
        by_page: Dict[str, List[Dict]] = {}
        for t in tokens_out:
            by_page.setdefault(t["page"], []).append(t)
        slots = hits = fired = fired_err = 0
        for page, toks in by_page.items():
            risky = [t for t in toks if t["flags"]
                     or _rule_fires(rule, t)]
            risky.sort(key=lambda t: (-_risk(t, rule),
                                      t["rank"] if t["rank"] is not None else 0))
            top = risky[:10]
            slots += len(top)
            hits += sum(1 for t in top if t["is_err"])
            fired += sum(1 for t in toks if _rule_fires(rule, t))
            fired_err += sum(1 for t in toks
                             if _rule_fires(rule, t) and t["is_err"])
        arms[rule] = {
            "fired": fired, "fired_errors": fired_err,
            "precision": round(fired_err / fired, 4) if fired else None,
            "recall_of_errors": round(fired_err / n_err, 4) if n_err else None,
            "R@10": round(hits / n_err, 4) if n_err else None,
            "P@10": round(hits / slots, 4) if slots else None,
            "slots": slots,
        }

    print()
    print("missed errors (unfiltered detail):")
    for t in sorted(missed, key=lambda x: x["page"]):
        print(f"  {t['page'][:38]:38} conf {t['conf']:5}  "
              f"atoms={t['atoms']}  flags={t['flags']}  text={t['text'][:60]!r}")
    print()
    print("candidate-rule arms (added flag weight 2.0):")
    for k, v in arms.items():
        print(f"  {k:16} fired {v['fired']:4} prec {v['precision']} "
              f"rec {v['recall_of_errors']} R@10 {v['R@10']} "
              f"P@10 {v['P@10']} slots {v['slots']}")

    out = {"data_dir": data_dir, "errors": n_err,
           "missed": missed, "rules": arms}
    if json_path:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump({"summary": out, "tokens": tokens_out}, fh,
                      ensure_ascii=False, indent=1)
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
