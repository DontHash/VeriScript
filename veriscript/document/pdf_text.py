"""Born-digital PDF pages keep their own text (docs/TECH_UPGRADE_PLAN.md, E2).

A PDF made by a word processor already holds exact Unicode text, fonts and
vector shapes. Rasterising it and reading it again can only lose: the output
gets the OCR's errors and a picture instead of crisp text. So each page is
checked first, and its text layer is kept only when it is trustworthy:

* enough text (otherwise it is a scan);
* not a scan that another tool already OCR'd (one image covering most of the
  page): that text is someone else's unchecked reading, and VeriScript's
  digit review must see it;
* no legacy Nepali/Hindi font (Preeti, Kantipur, Kruti Dev ...), which store
  Devanagari as Latin letters ("g]kfn" for "नेपाल");
* for a Devanagari run, the layer actually contains Devanagari;
* at most 2% damaged Devanagari words (`devanagari_validity`, the same gate
  the harvest and GT audit use): many government PDFs extract with reordered
  vowel signs and broken conjuncts, and those pages are OCR'd.

Pages that pass become a `DocumentResult` whose tokens come from the PDF
(`backend="pdf-text-layer"`, no flags: there is nothing uncertain to review),
and whose PDF output is the original page itself. Everything else is OCR'd
exactly as before.
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np

from veriscript.core.metrics import devanagari_validity
from veriscript.document.ocr import OCRResult, Token

#: Fewer visible characters than this: treat the page as a scan.
MIN_CHARS = 30
#: Damaged-Devanagari share above this: OCR the page instead.
MAX_INVALID_RATE = 0.02
#: One image covering at least this share of the page: a scan.
SCAN_IMAGE_SHARE = 0.75

#: Legacy (non-Unicode) Devanagari fonts, lower-case substrings of font names.
LEGACY_FONTS = (
    "preeti", "kantipur", "sagarmatha", "himali", "himalb", "fontasy",
    "aakriti", "ganess", "kanchan", "shangrila", "pcs nepali", "navjeevan",
    "kruti", "devlys", "chanakya", "aalekh", "shusha", "agra", "akruti",
)

_DEVA = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")


@dataclass
class TextLayerPage:
    index: int
    usable: bool
    reason: str
    text: str = ""
    tokens: List[Token] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)


def _font_names(textpage, count: int, samples: int = 400) -> List[str]:
    """Distinct font names over up to `samples` evenly spaced characters."""
    import pypdfium2.raw as pdfium_c

    names = set()
    if count <= 0:
        return []
    step = max(1, count // samples)
    buf = ctypes.create_string_buffer(256)
    flags = ctypes.c_int()
    for i in range(0, count, step):
        n = pdfium_c.FPDFText_GetFontInfo(textpage.raw, i, buf, 256, ctypes.byref(flags))
        if n:
            names.add(buf.value.decode("utf-8", "replace"))
    return sorted(names)


def _largest_image_share(page) -> float:
    """Area share of the page covered by its largest image object."""
    import pypdfium2.raw as pdfium_c

    width, height = page.get_size()
    area = max(width * height, 1.0)
    best = 0.0
    for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=2):
        left, bottom, right, top = obj.get_bounds()
        best = max(best, max(0.0, right - left) * max(0.0, top - bottom) / area)
    return min(best, 1.0)


def _line_tokens(textpage, count: int, page_height: float, scale: float) -> List[Token]:
    """Lines from the text layer (its own line breaks), boxes in pixels of a
    render at `scale`. One token per line, as the transcript writers expect."""
    tokens: List[Token] = []
    line: List[str] = []
    box = None

    def flush():
        nonlocal line, box
        text = "".join(line).strip()
        if text and box is not None:
            x0, y0, x1, y1 = box
            tokens.append(Token(
                text=text, conf=100.0,
                bbox=(int(x0 * scale), int((page_height - y1) * scale),
                      int(np.ceil(x1 * scale)), int(np.ceil((page_height - y0) * scale))),
                granularity="line", backend="pdf-text-layer", text_source="pdf"))
        line, box = [], None

    for i in range(count):
        ch = textpage.get_text_range(i, 1)
        if ch in ("\r", "\n", "\r\n"):
            flush()
            continue
        line.append(ch)
        if not ch or ch.isspace():
            continue
        left, bottom, right, top = textpage.get_charbox(i)
        if right <= left or top <= bottom:  # generated chars carry no box
            continue
        box = ((left, bottom, right, top) if box is None else
               (min(box[0], left), min(box[1], bottom), max(box[2], right), max(box[3], top)))
    flush()
    return tokens


def check_page(pdf, index: int, lang: Optional[str], scale: float) -> TextLayerPage:
    """Decide whether page `index` keeps its own text (see the module doc)."""
    page = pdf[index]
    try:
        textpage = page.get_textpage()
        try:
            count = textpage.count_chars()
            text = textpage.get_text_range() if count else ""
            visible = sum(1 for ch in text if not ch.isspace())
            stats: Dict = {"chars": visible}
            if visible < MIN_CHARS:
                return TextLayerPage(index, False, "no text layer (a scan)", stats=stats)
            share = _largest_image_share(page)
            stats["image_share"] = round(share, 3)
            if share >= SCAN_IMAGE_SHARE:
                return TextLayerPage(index, False,
                                     "scanned page with another tool's text layer",
                                     stats=stats)
            fonts = _font_names(textpage, count)
            stats["fonts"] = fonts
            legacy = [f for f in fonts if any(k in f.lower() for k in LEGACY_FONTS)]
            if legacy:
                return TextLayerPage(index, False, f"legacy font {legacy[0]}", stats=stats)
            validity = devanagari_validity(text)
            stats["devanagari_tokens"] = validity["devanagari_tokens"]
            stats["invalid_rate"] = validity["invalid_token_rate"]
            devanagari_run = (lang or "").lower() in ("ne", "hi")
            if devanagari_run and not _DEVA.search(text) and len(_LATIN.findall(text)) >= MIN_CHARS:
                return TextLayerPage(index, False,
                                     "no Devanagari in the text layer (likely a legacy font)",
                                     stats=stats)
            if validity["invalid_token_rate"] > MAX_INVALID_RATE:
                return TextLayerPage(
                    index, False,
                    f"damaged Devanagari text ({validity['invalid_token_rate']:.0%} of words)",
                    stats=stats)
            _, height = page.get_size()
            tokens = _line_tokens(textpage, count, height, scale)
            return TextLayerPage(index, True, "text taken from the PDF",
                                 text=text.replace("\r\n", "\n").strip() + "\n",
                                 tokens=tokens, stats=stats)
        finally:
            textpage.close()
    finally:
        page.close()


def check_pages(pdf_path: str, indices: Sequence[int], lang: Optional[str],
                dpi: int = 200) -> Dict[int, TextLayerPage]:
    """`check_page` for each index; never raises (unreadable = OCR it)."""
    import pypdfium2 as pdfium

    out: Dict[int, TextLayerPage] = {}
    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception:  # noqa: BLE001 - the OCR path reports unreadable files
        return {i: TextLayerPage(i, False, "could not read the text layer") for i in indices}
    try:
        for i in indices:
            try:
                out[i] = check_page(pdf, i, lang, dpi / 72.0)
            except Exception as exc:  # noqa: BLE001 - per page, fall back to OCR
                out[i] = TextLayerPage(i, False, f"could not read the text layer ({type(exc).__name__})")
    finally:
        pdf.close()
    return out


def write_original_page(pdf_path: str, index: int, out_path: str) -> str:
    """The source page itself as a one-page PDF (vector text, fonts, links)."""
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(pdf_path)
    dst = pdfium.PdfDocument.new()
    try:
        dst.import_pages(src, [index])
        part = out_path + ".part"
        dst.save(part)
        os.replace(part, out_path)
    finally:
        dst.close()
        src.close()
    return out_path


def merge_pdfs(out_path: str, parts: Sequence, password: Optional[str] = None) -> str:
    """Concatenate PDFs in order.

    A part is a path (the whole file) or `(source_path, page_index)`. Runs of
    consecutive pages from the same source are imported in one call so they
    share fonts and images instead of copying them per page. With
    `password` (E5), whole-file parts written with that password are opened
    with it and the result is protected with it too.
    """
    import pypdfium2 as pdfium

    runs: List[list] = []  # [path, [indices] | None]
    for part in parts:
        if isinstance(part, tuple):
            path, index = part
            if runs and runs[-1][0] == path and runs[-1][1] is not None:
                runs[-1][1].append(index)
            else:
                runs.append([path, [index]])
        else:
            runs.append([part, None])
    dst = pdfium.PdfDocument.new()
    try:
        for path, indices in runs:
            src = pdfium.PdfDocument(path, password=password if indices is None else None)
            try:
                dst.import_pages(src, indices)
            finally:
                src.close()
        part = out_path + ".part"
        dst.save(part)
        if password:
            from veriscript.document.protect import protect_pdf
            try:
                protect_pdf(part, out_path, password)
            finally:
                if os.path.exists(part):
                    os.remove(part)
        else:
            os.replace(part, out_path)
    finally:
        dst.close()
    return out_path


def document_result(layer: TextLayerPage, image_bgr: np.ndarray, pdf_path: str, *,
                    out_dir: str, stem: str, make_pdf: bool = True,
                    make_overlay: bool = True, make_txt: bool = True,
                    make_json: bool = True, make_md: bool = True):
    """Outputs for a page that keeps its own text, as a DocumentResult."""
    from veriscript.document.export import export_document_outputs
    from veriscript.document.pipeline import DocumentResult

    started = time.time()
    ocr = OCRResult(text=layer.text, tokens=layer.tokens, backend="pdf-text-layer",
                    meta={"text_source": "pdf", "text_layer": layer.stats,
                          "reason": layer.reason, "page_index": layer.index})
    outputs = export_document_outputs(out_dir, stem, image_bgr, ocr, make_pdf=False,
                                      make_overlay=make_overlay, make_txt=make_txt,
                                      make_json=make_json, make_md=make_md)
    if make_pdf:
        outputs["pdf"] = write_original_page(pdf_path, layer.index,
                                             os.path.join(out_dir, f"{stem}.pdf"))
    meta = {"seconds": round(time.time() - started, 2), "backend": "pdf-text-layer",
            "text_source": "pdf", "primary_stream": None, "skew_angle": 0.0,
            "resized": False, "digit_conflicts": 0}
    return DocumentResult(display_bgr=image_bgr, ocr=ocr, meta=meta, outputs=outputs)
