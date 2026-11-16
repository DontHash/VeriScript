"""
test_pdf_password.py — password-protected PDFs (docs/TECH_UPGRADE_PLAN.md, E5).

AES-256 with security handler revision 6; the file opens only with the
password, and then copy and search return the exact text.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

pdfium = pytest.importorskip("pypdfium2")
pypdf = pytest.importorskip("pypdf")
pytest.importorskip("cryptography")

from veriscript.document.export import (SearchablePdfWriter,  # noqa: E402
                                        write_searchable_pdf_pages)
from veriscript.document.ocr import Token  # noqa: E402
from veriscript.document.protect import PasswordError, protect_pdf  # noqa: E402

TOKENS = [Token(text="Total 12,500.75", conf=95, bbox=(80, 90, 600, 130)),
          Token(text="नेपाल १२३", conf=95, bbox=(80, 200, 400, 240))]
PASSWORD = "ward-7 रकम"


def _page():
    return np.full((1200, 900, 3), 240, np.uint8)


def _write(path, password=PASSWORD, size="standard"):
    return write_searchable_pdf_pages(str(path), [(_page(), TOKENS, 150)] * 2,
                                      title="Ward 7", size=size, password=password)


def test_needs_the_password_and_keeps_the_text(tmp_path):
    path = _write(tmp_path / "locked.pdf")
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(path)
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(path, password="wrong password")
    doc = pdfium.PdfDocument(path, password=PASSWORD)
    assert len(doc) == 2
    text = doc[0].get_textpage().get_text_range()
    assert "12,500.75" in text and "नेपाल १२३" in text
    assert not os.path.exists(path + ".part")


def test_uses_aes_256_revision_6(tmp_path):
    path = _write(tmp_path / "locked.pdf")
    reader = pypdf.PdfReader(path)
    assert reader.is_encrypted
    enc = reader.trailer["/Encrypt"]
    assert enc["/V"] == 5 and enc["/R"] == 6
    assert enc["/CF"]["/StdCF"]["/CFM"] == "/AESV3"
    # Raw bytes never carry the text or the password in the clear.
    raw = open(path, "rb").read()
    assert b"12,500.75" not in raw and PASSWORD.encode() not in raw


def test_archive_and_weak_passwords_are_refused(tmp_path):
    with pytest.raises(PasswordError, match="PDF/A"):
        SearchablePdfWriter(str(tmp_path / "a.pdf"), size="archive", password=PASSWORD)
    for bad in ("short", "x" * 200, "tab\there"):
        with pytest.raises(PasswordError):
            SearchablePdfWriter(str(tmp_path / "b.pdf"), password=bad)


def test_protect_an_existing_pdf_drops_pdfa_claims(tmp_path):
    plain = write_searchable_pdf_pages(str(tmp_path / "plain.pdf"), [(_page(), TOKENS, 150)],
                                       size="archive")
    out = protect_pdf(plain, str(tmp_path / "locked.pdf"), PASSWORD)
    reader = pypdf.PdfReader(out)
    reader.decrypt(PASSWORD)
    assert "/OutputIntents" not in reader.trailer["/Root"]
    with pytest.raises(PasswordError, match="already protected"):
        protect_pdf(out, str(tmp_path / "again.pdf"), PASSWORD)


# --- Studio: "Download a PDF with a password" -------------------------------

def test_studio_returns_a_protected_copy_and_keeps_nothing(tmp_path, monkeypatch):
    import dataclasses
    import uuid

    pytest.importorskip("fastapi")
    sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))
    from fastapi.testclient import TestClient

    import vvweb.api as api_mod
    from vvweb.storage import RunStore

    store = RunStore(str(tmp_path / "runs"), 0)
    monkeypatch.setattr(api_mod, "store", store)
    monkeypatch.setattr(api_mod, "settings",
                        dataclasses.replace(api_mod.settings, mode="local", run_ttl_minutes=0))
    client = TestClient(api_mod.create_app())
    # A finished run with a searchable PDF.
    run_id = uuid.uuid4().hex[:16]
    run_dir = store.create(run_id)
    store.write_manifest(run_id, {"run_id": run_id})
    write_searchable_pdf_pages(os.path.join(run_dir, "searchable.pdf"),
                               [(_page(), TOKENS, 150)], title="Ward 7")
    before = sorted(os.listdir(run_dir))

    r = client.post(f"/api/runs/{run_id}/protect", json={"file": "searchable.pdf", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].endswith('searchable-protected.pdf"')
    out = tmp_path / "dl.pdf"
    out.write_bytes(r.content)
    with pytest.raises(pdfium.PdfiumError):
        pdfium.PdfDocument(str(out))
    assert "12,500.75" in pdfium.PdfDocument(str(out), password=PASSWORD)[0].get_textpage().get_text_range()
    assert sorted(os.listdir(run_dir)) == before  # nothing written into the run

    assert client.post(f"/api/runs/{run_id}/protect",
                       json={"file": "searchable.pdf", "password": "short"}).status_code == 400
    assert client.post(f"/api/runs/{run_id}/protect",
                       json={"file": "transcript.txt", "password": PASSWORD}).status_code == 400
