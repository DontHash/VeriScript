"""testpdfs — re-typeset text PDF from OCR results (the "word-type" export).

The image PDF keeps the capture (pristine pixels + optional invisible text);
this module rebuilds the page as real flowing text: paragraphs from line
geometry (gaps + indents), centred headings, justified body. It looks and
behaves like a word-processed document, not a photographed page.

API:
    write_text_pdf(path, results, title=None) -> str

`results` is an iterable of OCRResult (tokens in reading order, bbox in
display coordinates, granularity "line" or "word"). Registration geometry
from video captures is used only for layout hints; the output is A4.
"""
from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from veriscript.document.ocr import OCRResult, Token
from veriscript.document.export import unicode_pdf_font

_BODY_FONT_SIZE = 10.5
_LEADING = 1.45
_A4_W, _A4_H = A4
_MARGIN = 64.0
_BODY_W = _A4_W - 2 * _MARGIN


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def _to_lines(tokens: Sequence[Token]) -> List[dict]:
    """Group tokens into visual rows: word granules join, line granules pass.

    Rows are recorded top-to-bottom (tokens arrive in reading order already),
    each carrying text, height, left/right extent.
    """
    rows: List[dict] = []
    for tok in tokens:
        text = (tok.text or "").strip()
        if not text:
            continue
        x0, y0, x1, y1 = tok.bbox
        height = max(1, y1 - y0)
        yc = (y0 + y1) / 2
        placed = False
        # Word granules from one sentence share a row; fold into the row
        # whose centre is closest within a half-height tolerance.
        if tok.granularity == "word" and rows:
            best = min(rows, key=lambda r: abs(r["yc"] - yc), default=None)
            if best and abs(best["yc"] - yc) <= 0.6 * max(best["height"], height):
                best["text"].append((x0, text))
                best["x0"] = min(best["x0"], x0)
                best["x1"] = max(best["x1"], x1)
                best["yc"] = (best["yc"] * (best["n"]) + yc) / (best["n"] + 1)
                best["height"] = max(best["height"], height)
                best["n"] += 1
                placed = True
        if not placed:
            rows.append({"yc": yc, "height": height, "x0": x0, "x1": x1,
                         "n": 1, "text": [(x0, text)]})
    for row in rows:
        row["text"] = " ".join(t for _, t in sorted(row["text"], key=lambda p: p[0]))
    return rows


def _classify(rows: List[dict]) -> List[dict]:
    """Paragraph grouping + heading hints from geometry alone."""
    heights = sorted(r["height"] for r in rows)
    med_h = heights[len(heights) // 2] if heights else 12
    body_left = _median([r["x0"] for r in rows])
    body_span = _median([r["x1"] - r["x0"] for r in rows]) or 1
    blocks: List[dict] = []
    current: Optional[dict] = None
    for row in rows:
        centre = (row["x0"] + row["x1"]) / 2
        page_c = (_BODY_W / 2)  # degree of centring matters, not pixels
        left_gap = row["x0"] - body_left
        indented = left_gap > 0.55 * med_h
        centred = (abs(centre - centre) >= 0 and      # placeholder; size test below
                   row["x1"] - row["x0"] < 0.62 * body_span and
                   left_gap > 1.4 * med_h)
        caps = row["text"].isupper() and len(row["text"]) <= 40
        new_block = (current is None or row["yc"] - current["bottom"] > 1.6 * med_h
                     or indented or centred or caps)
        if new_block:
            current = {"rows": [row], "bottom": row["height"] and row["yc"],
                       "heading": centred or caps,
                       "top": row["yc"]}
            blocks.append(current)
        else:
            current["rows"].append(row)
            current["bottom"] = row["yc"]
    return blocks


def _median(values) -> float:
    xs = sorted(values)
    return xs[len(xs) // 2] if xs else 0.0


def write_text_pdf(path: str, results: Iterable[OCRResult],
                   title: Optional[str] = None) -> str:
    """Word-style PDF: re-typeset OCR text, no page images."""
    font = unicode_pdf_font() or "Helvetica"
    body = ParagraphStyle("body", fontName=font, fontSize=_BODY_FONT_SIZE,
                          leading=_BODY_FONT_SIZE * _LEADING,
                          alignment=TA_JUSTIFY, spaceAfter=5.5)
    heading = ParagraphStyle("heading", fontName=font,
                             fontSize=_BODY_FONT_SIZE + 3.5,
                             leading=(_BODY_FONT_SIZE + 3.5) * 1.35,
                             alignment=TA_CENTER, spaceBefore=13, spaceAfter=9)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=_MARGIN,
                            rightMargin=_MARGIN, topMargin=_MARGIN + 8,
                            bottomMargin=_MARGIN, title=title or "Captured book")
    story: List = []
    for result in results:
        rows = _to_lines(result.tokens)
        for block in _classify(rows):
            para = Paragraph(_escape(block["rows"][0]["text"])
                             if len(block["rows"]) == 1 else
                             _escape(" ".join(r["text"] for r in block["rows"])),
                             heading if block["heading"] else body)
            story.append(para)
    if not story:
        raise ValueError("No text recognized. Export the clean image PDF instead.")
    doc.build(story)
    return path


if __name__ == "__main__":
    from veriscript.document.ocr import Token

    tokens = [
        Token("SEVEN", 99, (200, 40, 340, 70), "line"),
        Token("A PUNCH IN THE FACE", 99, (150, 80, 390, 105), "line"),
        Token('"Where you think you\'re going?" I asked lazily', 99,
              (40, 160, 500, 186), "line"),
        Token("from my lawn chair parked in the middle of the lane.", 99,
              (40, 190, 500, 216), "line"),
        Token('"Should I know I\'d find you here," Nash said.', 99,
              (60, 250, 500, 276), "line"),
    ]
    out = write_text_pdf("out/api_check/textpdf_demo.pdf",
                         [OCRResult(tokens=tokens, backend="demo", text="")])
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(out) as pdf:
        text = pdf[0].get_textpage().get_text_range()
    print("pages text:", text[:200].replace("\r\n", " | "))
    print("textpdf OK")
