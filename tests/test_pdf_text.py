"""
test_pdf_text.py — born-digital PDF pages keep their own text
(docs/TECH_UPGRADE_PLAN.md, E2; veriscript/document/pdf_text.py).

A page keeps its text layer only when it is trustworthy; scans, legacy
fonts, damaged Devanagari and other tools' OCR layers are OCR'd as before.
"""
from __future__ import annotations

import io
import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))

pypdfium2 = pytest.importorskip("pypdfium2")
from reportlab.pdfgen import canvas  # noqa: E402

from veriscript.document import pdf_text  # noqa: E402
from veriscript.document.export import unicode_pdf_font  # noqa: E402

ENGLISH = ["Invoice 12345 for Sarita Sharma", "Total: Rs. 3,000.00 due 2026/10/17",
           "Please check the amount before payment."]
NEPALI = ["नेपाल सरकार शिक्षा मन्त्रालय", "विद्यार्थी संख्या १२३४५ जना",
          "कुल रकम रु. १२,५००.७५ मात्र"]


def _pdf(path, pages):
    """pages: list of ("text", lines, font) | ("scan", None, None) | ("scan+text", lines, font)."""
    c = canvas.Canvas(str(path), pagesize=(595, 842))
    for kind, lines, font in pages:
        if kind.startswith("scan"):
            from PIL import Image
            from reportlab.lib.utils import ImageReader
            img = Image.new("RGB", (620, 877), (250, 250, 245))
            c.drawImage(ImageReader(img), 0, 0, width=595, height=842)
        if lines:
            t = c.beginText()
            if kind == "scan+text":
                t.setTextRenderMode(3)  # invisible, like another tool's OCR
            t.setFont(font or "Helvetica", 14)
            t.setTextOrigin(60, 760)
            for line in lines:
                t.textLine(line)
            c.drawText(t)
        c.showPage()
    c.save()
    return str(path)


def test_born_digital_english_page_is_kept_with_word_boxes(tmp_path):
    path = _pdf(tmp_path / "a.pdf", [("text", ENGLISH, None)])
    layer = pdf_text.check_pages(path, [0], lang=None)[0]
    assert layer.usable, layer.reason
    assert "Invoice 12345" in layer.text
    lines = [t.text for t in layer.tokens]
    assert lines == ENGLISH
    tok = layer.tokens[0]
    x0, y0, x1, y1 = tok.bbox
    # 60 pt from the left, near the top, at 200 DPI (scale 200/72).
    assert 150 < x0 < 180 and 180 < y0 < 260 and x1 > x0 and y1 > y0
    assert tok.backend == "pdf-text-layer" and not tok.flags


def test_unicode_nepali_page_is_kept(tmp_path):
    font = unicode_pdf_font()
    if not font:
        pytest.skip("no Devanagari font for reportlab")
    path = _pdf(tmp_path / "ne.pdf", [("text", NEPALI, font)])
    layer = pdf_text.check_pages(path, [0], lang="ne")[0]
    assert layer.usable, layer.reason
    assert "१२,५००.७५" in layer.text


def test_damaged_devanagari_is_ocrd(tmp_path):
    font = unicode_pdf_font()
    if not font:
        pytest.skip("no Devanagari font for reportlab")
    # Vowel signs before their consonant: what broken PDF extraction yields.
    damaged = ["िकताब पढ्न ेबानी", "ि वद्यालय ेको नाम", "ुल रकम रु. १२,५००"]
    path = _pdf(tmp_path / "bad.pdf", [("text", damaged * 2, font)])
    layer = pdf_text.check_pages(path, [0], lang="ne")[0]
    assert not layer.usable
    assert layer.reason.startswith("damaged Devanagari")


def test_latin_only_text_in_a_nepali_run_is_ocrd(tmp_path):
    # Preeti-style text: Devanagari typed as Latin letters.
    path = _pdf(tmp_path / "preeti.pdf", [("text", ["g]kfn ;/sf/ lzIff dGqfno", "ljBfyL{ ;+Vof"] * 2, None)])
    layer = pdf_text.check_pages(path, [0], lang="ne")[0]
    assert not layer.usable and "no Devanagari" in layer.reason
    # The same page in an English run is fine (no Devanagari expected).
    assert pdf_text.check_pages(path, [0], lang=None)[0].usable


def test_legacy_font_names_are_ocrd(tmp_path, monkeypatch):
    path = _pdf(tmp_path / "a.pdf", [("text", ENGLISH, None)])
    monkeypatch.setattr(pdf_text, "_font_names", lambda *a, **k: ["ABCDEE+Preeti"])
    layer = pdf_text.check_pages(path, [0], lang=None)[0]
    assert not layer.usable and layer.reason == "legacy font ABCDEE+Preeti"


def test_scans_with_or_without_a_text_layer_are_ocrd(tmp_path):
    path = _pdf(tmp_path / "s.pdf", [("scan", None, None), ("scan+text", ENGLISH, None)])
    layers = pdf_text.check_pages(path, [0, 1], lang=None)
    assert layers[0].reason == "no text layer (a scan)"
    assert layers[1].reason == "scanned page with another tool's text layer"
    assert not layers[0].usable and not layers[1].usable


def test_unreadable_file_falls_back_to_ocr(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"%PDF-1.4 nonsense")
    layer = pdf_text.check_pages(str(bad), [0], lang=None)[0]
    assert not layer.usable


# --- the studio pipeline ----------------------------------------------------

def _studio(monkeypatch, tmp_path):
    import vvweb.pipeline as web_pipeline
    from veriscript.document import pipeline as document_pipeline
    from test_webapp_api import _fake_pipeline

    calls: dict = {}
    fake = _fake_pipeline(calls)

    def fake_with_real_pdf(img, **kw):
        # The shared stub writes a placeholder PDF; merging needs a real one.
        result = fake(img, **kw)
        if "pdf" in result.outputs:
            c = canvas.Canvas(result.outputs["pdf"], pagesize=(240, 200))
            c.drawString(20, 170, "HELLO")
            c.showPage()
            c.save()
        return result

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", fake_with_real_pdf)
    monkeypatch.setattr(web_pipeline, "PAGE_CAP", 0)
    return web_pipeline, calls


def test_mixed_pdf_keeps_originals_and_ocrs_scans(tmp_path, monkeypatch):
    web_pipeline, calls = _studio(monkeypatch, tmp_path)
    src = _pdf(tmp_path / "mixed.pdf", [("text", ENGLISH, None), ("scan", None, None),
                                         ("text", ENGLISH[::-1], None)])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    payload = web_pipeline.process_page(src, str(run_dir), "0123456789abcdef",
                                        lang=None, deskew=False, kind="pdf",
                                        all_pages=True)
    meta = payload["meta"]
    assert meta["pages_processed"] == 3 and meta["pages_from_pdf_text"] == 2
    assert [p["kept"] for p in meta["text_layer"]] == [True, False, True]
    assert len(calls["calls"]) == 1                     # only the scan was OCR'd
    assert meta["backend"] == "pdf-text-layer"          # page 1 kept its text
    assert "Invoice 12345" in payload["transcript"]

    combined = pypdfium2.PdfDocument(str(run_dir / "combined.pdf"))
    assert len(combined) == 3
    # Original pages keep their real, visible text objects.
    assert "Invoice 12345" in combined[0].get_textpage().get_text_range()
    assert "HELLO" in combined[1].get_textpage().get_text_range()  # the fake OCR
    single = pypdfium2.PdfDocument(str(run_dir / "searchable.pdf"))
    assert "Total: Rs. 3,000.00" in single[0].get_textpage().get_text_range()


def test_text_layer_can_be_switched_off(tmp_path, monkeypatch):
    web_pipeline, calls = _studio(monkeypatch, tmp_path)
    src = _pdf(tmp_path / "a.pdf", [("text", ENGLISH, None)])
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    payload = web_pipeline.process_page(src, str(run_dir), "0123456789abcdef",
                                        lang=None, deskew=False, kind="pdf",
                                        use_text_layer=False)
    assert len(calls["calls"]) == 1
    assert payload["meta"]["pages_from_pdf_text"] == 0


def test_job_api_passes_the_option(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import vvweb.api as api_mod
    from vvweb.security import DailyKeyedQuota, RateLimiter
    from vvweb.storage import RunStore

    _web, calls = _studio(monkeypatch, tmp_path)
    monkeypatch.setattr(api_mod, "store", RunStore(str(tmp_path / "runs"), 60))
    monkeypatch.setattr(api_mod, "limiter", RateLimiter(120, 1000))
    monkeypatch.setattr(api_mod, "client_pages", DailyKeyedQuota(0))
    client = TestClient(api_mod.create_app())
    data = open(_pdf(tmp_path / "a.pdf", [("text", ENGLISH, None)]), "rb").read()
    # English: the studio's default Nepali run would rightly OCR a Latin-only layer.
    kept = client.post("/api/restore", data={"lang": "en"},
                       files={"file": ("a.pdf", data, "application/pdf")})
    assert kept.status_code == 200, kept.text
    assert kept.json()["meta"]["pages_from_pdf_text"] == 1 and "calls" not in calls
    off = client.post("/api/restore", data={"text_layer": "0", "lang": "en"},
                      files={"file": ("a.pdf", data, "application/pdf")})
    assert off.json()["meta"]["pages_from_pdf_text"] == 0 and len(calls["calls"]) == 1
