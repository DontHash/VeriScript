"""
test_text_layer_alignment.py — the searchable PDF's hidden text covers the
printed words (docs/TECH_UPGRADE_PLAN.md, E1).

Each token's invisible text is stretched to its box; the extracted
characters' boxes must overlap the token box (IoU >= 0.7) and the text must
round-trip exactly, Devanagari included.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pdfium = pytest.importorskip("pypdfium2")

from veriscript.document.export import unicode_pdf_font, write_searchable_pdf  # noqa: E402
from veriscript.document.ocr import Token  # noqa: E402


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


@pytest.mark.parametrize("texts", [
    ["Invoice 12345", "Total: Rs. 3,000.00", "Ref 9", "WWWWWW"],
    ["नेपाल सरकार", "कुल रकम रु. १२,५००.७५", "पृष्ठ नम्बर १२३"],
])
def test_hidden_text_fills_each_token_box(tmp_path, texts):
    if any(ord(ch) > 0x900 for t in texts for ch in t) and not unicode_pdf_font():
        pytest.skip("no Devanagari font for reportlab")
    image = np.full((1400, 1000, 3), 255, np.uint8)
    # Deliberately mismatched widths: a long box for short text and a short
    # box for long text, as OCR boxes often are.
    widths = [700, 300, 500, 150]
    tokens = [Token(text=t, conf=95, bbox=(80, 100 + i * 120, 80 + widths[i % 4], 150 + i * 120))
              for i, t in enumerate(texts)]
    path = write_searchable_pdf(str(tmp_path / "p.pdf"), image, tokens, dpi=150)

    doc = pdfium.PdfDocument(path)
    page = doc[0]
    _, ph = page.get_size()
    textpage = page.get_textpage()
    count = textpage.count_chars()
    full = textpage.get_text_range()
    px2pt = 72.0 / 150
    cursor = 0
    for tok in tokens:
        assert tok.text in full[cursor:]              # exact round trip, in order
        start = full.index(tok.text, cursor)
        cursor = start + len(tok.text)
        # Loose boxes (font ascent to descent) are what selection highlights.
        boxes = [textpage.get_charbox(i, loose=True) for i in range(start, start + len(tok.text))
                 if i < count and not full[i].isspace()]
        boxes = [b for b in boxes if b[2] > b[0]]
        left = min(b[0] for b in boxes); right = max(b[2] for b in boxes)
        bottom = min(b[1] for b in boxes); top = max(b[3] for b in boxes)
        got = (left, ph - top, right, ph - bottom)
        x0, y0, x1, y1 = tok.bbox
        want = (x0 * px2pt, y0 * px2pt, x1 * px2pt, y1 * px2pt)
        assert _iou(got, want) >= 0.7, (tok.text, got, want)
