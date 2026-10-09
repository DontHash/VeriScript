#!/usr/bin/env python3
"""build_audit_sheet.py — human audit sheet for the v2 digit residual.

One OCR pass over `nepali_pdf_v2` with the shipped product defaults (Devanagari
re-pass + date flags + recall flags + digit-first number queue), then writes:

  out/audit_v2/audit.html     viewer: crops, token details, GT context
  out/audit_v2/labels.tsv     one row per item; fill `verdict` + `notes`
  out/audit_v2/crops/*.png    content-error token crops (2x)
  out/audit_v2/pages/*.png    page thumbnails (for contextual checks)

Section A: content errors (wrong digit content - is it a real product error or
a metric/GT edge?). Section B: missing atoms (a GT number the OCR never
produced anywhere - is the GT atom real, and did the OCR drop text?).

Usage:
    python scripts/build_audit_sheet.py --data-dir data/doc_eval/nepali_pdf_v2
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from typing import Dict, List, Tuple

import cv2

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from veriscript.core import data as doc_data  # noqa: E402
from veriscript.core import digit_content as doc_content  # noqa: E402
from veriscript.document.ocr import (_crop_with_pad,  # noqa: E402
                                     digit_review_queue, ocr_page)

_DEVA_TO_LATIN = str.maketrans("०१२३४५६७८९", "0123456789")


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _gt_context(gt: str, needle: str, width: int = 90) -> str:
    """Context window around `needle`; search normalized, display raw.

    `_DEVA_TO_LATIN` is a 1:1 character translation, so indices align.
    """
    idx = gt.translate(_DEVA_TO_LATIN).find(needle)
    if idx < 0:
        return ""
    return gt[max(0, idx - width): idx + len(needle) + width].replace("\n", " ")


def _sanitize(s: str) -> str:
    return (s or "").replace("\t", " ").replace("\n", " ").strip()


def run(data_dir: str, lang: str, out_dir: str) -> Dict:
    manifest = doc_data.load_dataset(data_dir)
    os.makedirs(os.path.join(out_dir, "crops"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)

    errors: List[Dict] = []
    missing: List[Dict] = []
    for e in manifest["entries"]:
        img = doc_data.imread_safe(e["_degraded_path"])
        if img is None:
            continue
        gt = open(e["_gt_path"], encoding="utf-8").read()
        res = ocr_page(img, backend="rapidocr", lang=lang, recheck_digits=True)
        rep = doc_content.content_errors(res.tokens, gt)
        gt_atoms = doc_content.atoms(gt)
        queue = digit_review_queue(res.tokens)
        rank = {id(t): i for i, t in enumerate(queue)}

        thumb = os.path.join(out_dir, "pages", f"{e['id']}.png")
        h, w = img.shape[:2]
        if w > 1000:
            img_small = cv2.resize(img, (1000, int(h * 1000 / w)))
        else:
            img_small = img
        doc_data.imwrite_safe(thumb, img_small)

        for i in rep["error_tokens"]:
            tok = res.tokens[i]
            ocr_atoms = doc_content.atoms(tok.text)
            # charged atoms = OCR-side multiset surplus
            surplus = []
            remaining = {}
            for a in ocr_atoms:
                remaining[a] = remaining.get(a, 0) + 1
            for a in gt_atoms:
                if remaining.get(a, 0) > 0:
                    remaining[a] -= 1
            for a, n in remaining.items():
                surplus.extend([a] * n)
            contexts = []
            for atom in surplus[:2]:
                if not gt_atoms:
                    continue
                nearest = min(gt_atoms, key=lambda g: _lev(atom, g))
                ctx = _gt_context(gt, nearest)
                if ctx and ctx not in contexts:
                    contexts.append(ctx)
            crop = _crop_with_pad(img, tok.bbox, pad_ratio=0.03)
            crop_path = ""
            if crop.size and min(crop.shape[:2]) >= 6:
                big = cv2.resize(crop, None, fx=2.0, fy=2.0,
                                 interpolation=cv2.INTER_LANCZOS4)
                crop_path = os.path.join(out_dir, "crops",
                                         f"err_{len(errors):03d}.png")
                doc_data.imwrite_safe(crop_path, big)
            r = rank.get(id(tok))
            errors.append({
                "kind": "content_error", "page": e["id"],
                "text": tok.text, "atoms": " ".join(ocr_atoms),
                "flags": ",".join(tok.flags), "rank": "" if r is None else r,
                "missed_top10": r is None or r >= 10,
                "gt_context": " || ".join(contexts),
                "crop": crop_path, "page_png": thumb,
            })
        for atom in rep["missing_gt_atoms"]:
            missing.append({
                "kind": "missing_atom", "page": e["id"], "text": atom,
                "atoms": atom, "flags": "", "rank": "", "missed_top10": None,
                "gt_context": _gt_context(gt, atom),
                "crop": "", "page_png": thumb,
            })

    rows = errors + missing
    tsv = os.path.join(out_dir, "labels.tsv")
    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write("id\tkind\tpage\ttext\tatoms\tflags\tqueue_rank\t"
                 "missed_top10\tgt_context\tcrop\tpage_png\tverdict\tnotes\n")
        for i, r in enumerate(rows):
            fh.write("\t".join([
                str(i), r["kind"], _sanitize(r["page"]), _sanitize(r["text"]),
                _sanitize(r["atoms"]), r["flags"], str(r["rank"]),
                "" if r["missed_top10"] is None
                else ("yes" if r["missed_top10"] else "no"),
                _sanitize(r["gt_context"]),
                os.path.relpath(r["crop"], out_dir) if r["crop"] else "",
                os.path.relpath(r["page_png"], out_dir),
                "", ""]) + "\n")

    def _table(items: List[Dict], start: int = 0) -> str:
        out = []
        for i, r in enumerate(items):
            crop = (f'<a href="{os.path.relpath(r["crop"], out_dir)}">'
                    f'<img src="{os.path.relpath(r["crop"], out_dir)}" '
                    f'style="max-height:44px"></a>') if r["crop"] else "—"
            rank = "missed" if r["missed_top10"] else r["rank"]
            out.append(
                f'<tr><td>{start + i}</td><td class="mono">'
                f'{html.escape(r["text"])}'
                f'</td><td>{html.escape(r["atoms"])}</td>'
                f'<td class="mono">{html.escape(r["flags"])}</td>'
                f'<td>{rank}</td><td>{crop}</td>'
                f'<td class="mono small">{html.escape(r["gt_context"])}</td>'
                f'<td><a href="{os.path.relpath(r["page_png"], out_dir)}">'
                f'page</a></td></tr>')
        return "\n".join(out)

    doc = f"""<!doctype html><meta charset="utf-8">
<title>v2 digit residual audit</title>
<style>
 body {{ font: 14px/1.45 system-ui, sans-serif; margin: 24px; }}
 table {{ border-collapse: collapse; width: 100%; }}
 td, th {{ border-bottom: 1px solid #ddd; padding: 4px 6px; text-align: left;
           vertical-align: top; }}
 .mono {{ font-family: ui-monospace, monospace; }}
 .small {{ font-size: 12px; color: #444; max-width: 560px; }}
 h2 {{ margin-top: 28px; }}
</style>
<h1>nepali_pdf_v2 &mdash; digit residual audit</h1>
<p>Fill <b>verdict</b> (+ notes) in <code>labels.tsv</code>:
 <b>real</b> = the output is wrong for a user; <b>noise</b> = metric/GT edge
 (e.g. GT anchor artifact, count-level artifact) and the output is fine.</p>
<h2>Section A &mdash; content errors ({len(errors)})</h2>
<table><tr><th>#</th><th>token</th><th>atoms</th><th>flags</th>
<th>queue rank</th><th>crop</th><th>closest GT context</th><th>page</th></tr>
{_table(errors, 0)}
</table>
<h2>Section B &mdash; missing atoms ({len(missing)})</h2>
<p>GT numbers the OCR never produced anywhere. Is the GT atom real, and did
the OCR drop text? (abbreviation marks misread as digits and page furniture
are known GT noises.)</p>
<table><tr><th>#</th><th>atom</th><th>atoms</th><th>flags</th>
<th>queue rank</th><th>crop</th><th>GT context</th><th>page</th></tr>
{_table(missing, len(errors))}
</table>
"""
    with open(os.path.join(out_dir, "audit.html"), "w",
              encoding="utf-8") as fh:
        fh.write(doc)

    summary = {"content_errors": len(errors),
               "missing_atoms": len(missing),
               "missed_top10": sum(1 for r in errors if r["missed_top10"]),
               "out_dir": out_dir}
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/doc_eval/nepali_pdf_v2")
    ap.add_argument("--lang", default="ne")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "out",
                                                  "audit_v2"))
    args = ap.parse_args()
    run(args.data_dir, args.lang, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
