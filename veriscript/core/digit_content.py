#!/usr/bin/env python3
"""Digit-content scoring: the corrected queue-error definition (v3).

Why this exists (measured 2026-10-09, `out/attrib_digit_errors_v2*.json`):
under the legacy queue metric an OCR token errors when its joined digit string
is absent from the page's *word-level* GT digit set. On `nepali_pdf_v2` that
counts **126 of 156 (81%)** "errors" that are grouping artifacts: a line-level
OCR token joins several correctly-read numbers and the word-level set can
never match it (docs/PLAN.md Appendix AM flagged the inflation; Appendix AN
quantifies it).

Definition (v3). Normalize Devanagari digits to ASCII, drop every separator,
and take **maximal digit atoms**. Compare the page's OCR atom multiset against
the GT atom multiset:

* **corrupted atom** = an OCR atom whose (value, multiplicity) is not covered
  by the GT multiset -> charge it to the token that produced it. These are the
  queue's error tokens; grouping, token boundaries, separator style, run
  splits and reading-order divergence cannot create an error.
* **missing atom** = a GT atom the OCR never produced anywhere on the page.
  No token exists to flag it; reported separately, outside the recall
  denominator (the queue is a token-review surface; undetected text is a
  different failure class).

A transposition (39 vs 93) still surfaces: atoms are units, not characters.

Nothing here modifies tokens; the review queue and its ranking are untouched.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Sequence

_ATOM_RE = re.compile(r"[0-9]+")
_DEVA_DIGIT_MAP = {chr(0x0966 + i): str(i) for i in range(10)}


def atoms(text: str) -> List[str]:
    """Maximal digit atoms of `text` (Devanagari normalized, separators gone)."""
    norm = "".join(_DEVA_DIGIT_MAP.get(c, c) for c in text or "")
    return _ATOM_RE.findall(norm)


def content_errors(tokens: Sequence, gt_text: str) -> Dict:
    """Multiset atom diff; charge corrupted OCR atoms to their tokens.

    Returns `error_tokens` (indices into `tokens`), `corrupted_atoms`,
    `missing_gt_atoms` (list, multiplicity kept), and atom counts.
    """
    ocr_atoms: List[tuple] = []          # (token_index, atom)
    for ti, tok in enumerate(tokens):
        for a in atoms(getattr(tok, "text", "")):
            ocr_atoms.append((ti, a))
    gt_atoms = atoms(gt_text)

    gt_counter = Counter(gt_atoms)
    ocr_counter = Counter(a for _, a in ocr_atoms)
    corrupted = ocr_counter - gt_counter          # OCR side, multiplicity kept
    missing = gt_counter - ocr_counter            # GT side, multiplicity kept

    charged: set = set()
    remaining = Counter(corrupted)
    for ti, a in ocr_atoms:
        if remaining.get(a, 0) > 0:
            remaining[a] -= 1
            charged.add(ti)

    missing_list: List[str] = []
    for a, n in sorted(missing.items()):
        missing_list.extend([a] * n)
    return {
        "error_tokens": sorted(charged),
        "corrupted_atoms": sum(corrupted.values()),
        "missing_gt_atoms": missing_list,
        "missing_gt_runs": missing_list,   # back-compat alias (eval script)
        "extra_runs": sum(corrupted.values()),
        "substituted_runs": sum(corrupted.values()),
        "ocr_runs": len(ocr_atoms),
        "gt_runs": len(gt_atoms),
    }


def queue_stats_from_report(tokens: Sequence, rep: Dict,
                            top_k: Sequence[int] = (5, 10)) -> Dict:
    """Queue recall/precision from a `content_errors` report (v3).

    Same queue/ranking as the legacy metric (`review_queue`); only the error
    set changes. `recall@K` = share of corrupted tokens inside the top K;
    `precision@K` = share of the top K that are corrupted. The top-slot
    denominator sums `min(K, queue length)` over pages so it matches the
    `_queue_metrics` convention (scripts/eval_number_split.py).
    """
    from veriscript.document.ocr import review_queue

    errored = set(rep["error_tokens"])
    errored_ids = {id(tokens[i]) for i in errored}
    queue = review_queue(tokens)
    out: Dict = {
        "errors": len(errored),
        "missing_gt_runs": len(rep["missing_gt_atoms"]),
        "substituted_runs": rep["corrupted_atoms"],
        "extra_runs": rep["corrupted_atoms"],
        "queue": len(queue),
    }
    for k in top_k:
        top = queue[:k]
        hits = sum(1 for t in top if id(t) in errored_ids)
        out[f"hits@{k}"] = hits
        out[f"top@{k}"] = len(top)
        out[f"recall@{k}"] = (round(hits / len(errored), 4)
                              if errored else None)
        out[f"precision@{k}"] = (round(hits / len(top), 4) if top else None)
    return out


def content_queue_stats(tokens: Sequence, gt_text: str,
                        top_k: Sequence[int] = (5, 10)) -> Dict:
    """`queue_stats_from_report` (+ `content_errors`) in one call."""
    return queue_stats_from_report(tokens, content_errors(tokens, gt_text),
                                   top_k)
