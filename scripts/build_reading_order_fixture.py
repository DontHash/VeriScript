"""Parity fixture for the Android reading-order port (docs/TECH_UPGRADE_PLAN.md D4).

Runs the desktop OCR engine (engine order, no layout) on a few pages of each
layout eval set, then records what `veriscript.document.layout.sort_reading_order`
does with those boxes. The Dart port in mobile/lib/layout.dart must reproduce
every order exactly (mobile/test/layout_test.dart).

Only geometry is stored. Text is masked (digits -> "0", other characters ->
"a", spaces kept), which preserves the digit ratio the algorithm reads and
none of the content: the eval corpora are not redistributed.

python scripts/build_reading_order_fixture.py
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "mobile", "test", "fixtures", "reading_order_parity.json")
SETS = {  # eval set -> (pages, OCR language)
    "real_two_column": (6, None),
    "real_sroie": (6, None),
    "real_cord": (4, None),
    "nepali_pdf_v2": (5, "ne"),
    "heidata_holdout": (4, "hi"),
}


def mask(text: str) -> str:
    return re.sub(r"\S", lambda m: "0" if m.group(0).isdigit() else "a", text)


def synthetic_cases():
    """Hand-made layouts that exercise each branch of the algorithm."""
    def tok(x0, y0, x1, y1, text="aaaa aaaa"):
        return {"text": text, "bbox": [x0, y0, x1, y1]}

    cases = {}
    two = []
    for i in range(8):
        y = 120 + i * 60
        two.append(tok(620, y, 1100, y + 30 + (i % 3)))   # right first (engine row order)
        two.append(tok(60, y, 540 - (i % 4) * 20, y + 30))
    cases["two_columns"] = two
    cases["title_then_columns"] = [tok(60, 30, 1100, 80, "aaaaa aaaaa aaaaa")] + two
    cases["single_column"] = [tok(60, 100 + i * 50, 900 - (i % 5) * 60, 130 + i * 50) for i in range(14)]
    receipt = []
    for i in range(10):
        y = 100 + i * 45
        receipt.append(tok(60, y, 420, y + 28, "aaaaaa aaaa"))
        receipt.append(tok(820, y, 980, y + 28, "00.00"))
    cases["receipt_label_values"] = receipt
    grid = []
    for r in range(5):
        for line in range(2):
            for c in range(6):
                y = 100 + r * 140 + line * 30
                grid.append(tok(60 + c * 170, y, 160 + c * 170, y + 24, "aa 00"))
    cases["table_grid"] = grid
    toc = []
    for r in range(12):
        y = 100 + r * 36
        toc.append(tok(60, y, 140, y + 24, "00"))
        toc.append(tok(300, y, 380, y + 24, "aaaa"))
        toc.append(tok(600, y, 660, y + 24, "000"))
    cases["dense_toc"] = toc
    return cases


def main() -> None:
    from veriscript.document.layout import sort_reading_order
    from veriscript.document.ocr import Token, ocr_page
    from veriscript.document.orientation import load_image_bgr

    cases = {}
    for name, toks in synthetic_cases().items():
        cases[f"synthetic/{name}"] = toks
    for eval_set, (count, lang) in SETS.items():
        pages = sorted(glob.glob(os.path.join(ROOT, "data", "doc_eval", eval_set, "pages", "*")))[:count]
        for path in pages:
            img = load_image_bgr(path)
            if img is None:
                continue
            result = ocr_page(img, lang=lang)
            cases[f"{eval_set}/{os.path.splitext(os.path.basename(path))[0]}"] = [
                {"text": mask(t.text), "bbox": [int(v) for v in t.bbox]} for t in result.tokens]
            print(f"  {eval_set}: {os.path.basename(path)} ({len(result.tokens)} tokens)", flush=True)

    fixture = {"version": 1, "source": "scripts/build_reading_order_fixture.py", "cases": []}
    for name, toks in cases.items():
        objs = [Token(text=t["text"], conf=90.0, bbox=tuple(t["bbox"])) for t in toks]
        stats: dict = {}
        order = sort_reading_order(objs, stats=stats)
        index = {id(t): i for i, t in enumerate(objs)}
        fixture["cases"].append({
            "name": name, "tokens": toks, "expected": [index[id(t)] for t in order],
            "stats": {k: stats.get(k, 0) for k in ("splits", "tables", "dense_tables")},
        })
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(fixture, f, separators=(",", ":"))
    changed = sum(1 for c in fixture["cases"] if c["expected"] != list(range(len(c["tokens"]))))
    print(f"{len(fixture['cases'])} cases ({changed} reordered) -> {OUT}")


if __name__ == "__main__":
    main()
