"""
test_pdf_size.py — searchable-PDF size presets (docs/TECH_UPGRADE_PLAN.md, E3).

The page picture changes with the preset; the invisible text layer must not.
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))

pdfium = pytest.importorskip("pypdfium2")

from veriscript.document.export import (PDF_SIZES, SearchablePdfWriter,  # noqa: E402
                                        _is_grey, write_searchable_pdf)
from veriscript.document.ocr import Token  # noqa: E402


def _page(colour: bool = False) -> np.ndarray:
    rng = np.random.default_rng(3)
    img = np.full((2400, 1700, 3), 245, np.uint8)
    img += rng.integers(0, 8, img.shape, dtype=np.uint8)  # paper texture
    for i in range(30):
        cv2.putText(img, f"Line {i} total 12,500.75 ref 98412{i:02d}", (80, 120 + i * 72),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 3)
    if colour:
        cv2.rectangle(img, (1200, 60), (1600, 400), (30, 30, 200), -1)  # a red stamp
    return img


TOKENS = [Token(text="Line 0 total 12,500.75", conf=95, bbox=(80, 90, 900, 130)),
          Token(text="नेपाल १२३", conf=95, bbox=(80, 200, 400, 240))]


def _text(path):
    return pdfium.PdfDocument(path)[0].get_textpage().get_text_range()


def test_presets_shrink_the_file_but_not_the_text(tmp_path):
    img = _page()
    sizes, texts = {}, {}
    for preset in ("archive", "standard", "small"):
        path = write_searchable_pdf(str(tmp_path / f"{preset}.pdf"), img, TOKENS, size=preset)
        sizes[preset] = os.path.getsize(path)
        texts[preset] = _text(path)
    assert sizes["archive"] > sizes["standard"] > sizes["small"]
    assert sizes["standard"] < sizes["archive"] / 2
    assert texts["archive"] == texts["standard"] == texts["small"]
    assert "12,500.75" in texts["small"]
    # Page geometry is the same physical size in every preset.
    dims = {p: pdfium.PdfDocument(str(tmp_path / f"{p}.pdf"))[0].get_size() for p in sizes}
    assert dims["archive"] == dims["standard"] == dims["small"]


def test_grey_pages_are_stored_grey_and_colour_is_kept(tmp_path):
    assert _is_grey(_page()) and not _is_grey(_page(colour=True))
    for colour in (False, True):
        path = write_searchable_pdf(str(tmp_path / f"c{colour}.pdf"), _page(colour), TOKENS)
        raw = open(path, "rb").read()
        assert (b"/DeviceGray" in raw) is (not colour)
        assert b"/DCTDecode" in raw


def test_small_caps_resolution_at_150_dpi(tmp_path):
    path = write_searchable_pdf(str(tmp_path / "s.pdf"), _page(), TOKENS, dpi=300, size="small")
    page = pdfium.PdfDocument(path)[0]
    images = [o for o in page.get_objects() if isinstance(o, pdfium.PdfImage)]
    w, _h = images[0].get_px_size()
    assert w == round(1700 * 150 / 300)


def test_unknown_preset_is_refused(tmp_path):
    with pytest.raises(ValueError):
        SearchablePdfWriter(str(tmp_path / "x.pdf"), size="tiny")
    assert set(PDF_SIZES) == {"archive", "standard", "small"}


def test_studio_passes_the_preset(tmp_path, monkeypatch):
    import io

    from fastapi.testclient import TestClient
    from PIL import Image

    import vvweb.api as api_mod
    from vvweb.security import DailyKeyedQuota, RateLimiter
    from vvweb.storage import RunStore
    from veriscript.document import pipeline as document_pipeline
    from test_webapp_api import _fake_pipeline

    seen = {}
    fake = _fake_pipeline()

    def capture(img, **kw):
        seen["pdf_size"] = kw.get("pdf_size")
        return fake(img, **kw)

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", capture)
    monkeypatch.setattr(api_mod, "store", RunStore(str(tmp_path / "runs"), 60))
    monkeypatch.setattr(api_mod, "limiter", RateLimiter(120, 1000))
    monkeypatch.setattr(api_mod, "client_pages", DailyKeyedQuota(0))
    client = TestClient(api_mod.create_app())
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    for asked, used in (("small", "small"), ("bogus", "standard")):
        r = client.post("/api/restore", data={"pdf_size": asked},
                        files={"file": ("p.png", buf.getvalue(), "image/png")})
        assert r.status_code == 200, r.text
        assert seen["pdf_size"] == used and r.json()["meta"]["pdf_size"] == used


def test_archive_preset_is_pdfa_2b():
    """E4: archive PDFs pass veraPDF's PDF/A-2b profile (local tool;
    skipped where it is not installed, see docs/EXTERNAL_ASSETS.md)."""
    sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))
    import check_pdfa

    if not os.path.isfile(check_pdfa.verapdf()):
        pytest.skip("veraPDF not installed")
    assert check_pdfa.main([]) == 0


def test_archive_text_still_extracts(tmp_path):
    path = write_searchable_pdf(str(tmp_path / "a.pdf"), _page(), TOKENS, size="archive",
                                title="Ward 7 record")
    doc = pdfium.PdfDocument(path)
    assert "12,500.75" in doc[0].get_textpage().get_text_range()
    assert doc.get_metadata_dict()["Title"] == "Ward 7 record"
    raw = open(path, "rb").read()
    assert b"/OutputIntents" in raw and b"pdfaid:part>2<" in raw
