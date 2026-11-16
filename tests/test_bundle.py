"""
test_bundle.py — phone -> desktop document bundles (docs/TECH_UPGRADE_PLAN.md, B4).

A bundle is untrusted input: damaged, hostile or oversized bundles are
refused with a plain reason, and only known line fields survive. The
desktop reads every page; the shared demo refuses bundles.
"""
from __future__ import annotations

import dataclasses
import io
import json
import os
import sys
import threading
import zipfile

import numpy as np
import pytest
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))

from veriscript.document import bundle  # noqa: E402


def _jpeg(w=320, h=480, exif_rotate=False) -> bytes:
    img = Image.new("RGB", (w, h), "white")
    img.paste((0, 0, 0), (20, 20, 120, 40))
    buf = io.BytesIO()
    if exif_rotate:
        exif = Image.Exif()
        exif[0x0112] = 6  # stored sideways: rotate 90 degrees on display
        img.save(buf, "JPEG", exif=exif)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


LINES = [
    {"text": "कुल रकम १२,५००", "original": "कुल रकम १२,६००", "reviewed": True,
     "confidence": 0.91, "bbox": [10, 20, 300, 60], "secret": "dropped"},
    {"text": "Ward 7", "original": "Ward 7", "reviewed": True, "confidence": True},
    {"text": "plain"},
    {"no_text": 1},
]


def _write(path, manifest=None, files=None, compress=zipfile.ZIP_STORED):
    manifest = manifest if manifest is not None else {
        "format": "veriscript-bundle", "version": 1, "title": "Ward 7 record",
        "created": "2026-11-16T10:00:00Z", "source": "VeriScript Android",
        "pages": [{"image": "pages/0001.jpg", "width": 320, "height": 480,
                   "recognized": True, "note": "", "lines": LINES},
                  {"image": "pages/0002.jpg", "width": 480, "height": 320,
                   "recognized": False, "note": "torn corner", "lines": []}]}
    files = files if files is not None else {"pages/0001.jpg": _jpeg(),
                                             "pages/0002.jpg": _jpeg(exif_rotate=True)}
    with zipfile.ZipFile(path, "w", compress) as zf:
        if manifest is not False:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, data in files.items():
            zf.writestr(name, data)
    return str(path)


def test_reads_pages_and_keeps_only_known_line_fields(tmp_path):
    b = bundle.open_bundle(_write(tmp_path / "doc.veriscript"))
    assert b.title == "Ward 7 record" and len(b.pages) == 2
    lines = b.pages[0].lines
    assert len(lines) == 3  # the line without text is dropped
    assert "secret" not in lines[0] and lines[0]["bbox"] == [10.0, 20.0, 300.0, 60.0]
    assert "confidence" not in lines[1]  # a bool is not a confidence
    reading = b.phone_reading()
    assert (reading["corrected_lines"], reading["confirmed_lines"]) == (1, 1)
    assert reading["pages"][1]["note"] == "torn corner"


def test_pages_decode_one_at_a_time_upright(tmp_path):
    b = bundle.open_bundle(_write(tmp_path / "doc.veriscript"))
    pages = list(bundle.iter_images(b))
    assert [i for i, _ in pages] == [0, 1]
    assert pages[0][1].shape == (480, 320, 3)
    assert pages[1][1].shape == (320, 480, 3)  # EXIF orientation applied
    assert len(list(bundle.iter_images(b, limit=1))) == 1


@pytest.mark.parametrize("case, message", [
    ("not_zip", "not a VeriScript bundle"),
    ("no_manifest", "no manifest"),
    ("wrong_format", "not a VeriScript bundle"),
    ("newer", "newer app version"),
    ("missing_image", "missing or invalid image"),
    ("traversal", "missing or invalid image"),
    ("no_pages", "no pages"),
    ("bad_width", "damaged"),
    ("bomb", "too large"),
])
def test_damaged_or_hostile_bundles_are_refused(tmp_path, case, message):
    path = tmp_path / "x.veriscript"
    good = {"format": "veriscript-bundle", "version": 1, "title": "t",
            "pages": [{"image": "pages/0001.jpg", "width": 10, "height": 10}]}
    page = {"pages/0001.jpg": _jpeg()}
    if case == "not_zip":
        path.write_bytes(b"%PDF-1.7 not a zip")
    elif case == "no_manifest":
        _write(path, manifest=False, files=page)
    elif case == "wrong_format":
        _write(path, manifest={**good, "format": "other"}, files=page)
    elif case == "newer":
        _write(path, manifest={**good, "version": 2}, files=page)
    elif case == "missing_image":
        _write(path, manifest=good, files={})
    elif case == "traversal":
        _write(path, manifest={**good, "pages": [{"image": "../../evil.jpg", "width": 1, "height": 1}]},
               files={"../../evil.jpg": _jpeg()})
    elif case == "no_pages":
        _write(path, manifest={**good, "pages": []}, files=page)
    elif case == "bad_width":
        _write(path, manifest={**good, "pages": [{"image": "pages/0001.jpg", "width": True, "height": 1}]},
               files=page)
    elif case == "bomb":
        _write(path, manifest=good, files={"pages/0001.jpg": b"\0" * (8 * 1024 * 1024)},
               compress=zipfile.ZIP_DEFLATED)
    with pytest.raises(bundle.BundleError, match=message):
        bundle.open_bundle(str(path))


def test_oversized_or_non_image_pages_are_refused_on_decode(tmp_path):
    good = {"format": "veriscript-bundle", "version": 1,
            "pages": [{"image": "pages/0001.png", "width": 10, "height": 10}]}
    buf = io.BytesIO()
    Image.new("L", (3000, 2000)).save(buf, "PNG")
    b = bundle.open_bundle(_write(tmp_path / "big.veriscript", good, {"pages/0001.png": buf.getvalue()}))
    with pytest.raises(bundle.BundleError, match="megapixels"):
        list(bundle.iter_images(b, max_megapixels=5))
    b = bundle.open_bundle(_write(tmp_path / "txt.veriscript", good, {"pages/0001.png": b"hello"}))
    with pytest.raises(bundle.BundleError, match="could not be read"):
        list(bundle.iter_images(b))


# --- desktop studio ---------------------------------------------------------

@pytest.fixture()
def studio(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import vvweb.api as api_mod
    import vvweb.security as security_mod
    from vvweb.jobs import JobManager
    from vvweb.security import DailyKeyedQuota, DailyQuota, RateLimiter
    from vvweb.storage import RunStore
    from veriscript.document import pipeline as document_pipeline
    from test_webapp_api import _fake_pipeline

    seen = []
    fake = _fake_pipeline()

    def capture(img, **kw):
        seen.append(img.shape)
        return fake(img, **kw)

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", capture)
    monkeypatch.setattr(api_mod, "store", RunStore(str(tmp_path / "runs"), 0))
    monkeypatch.setattr(api_mod, "limiter", RateLimiter(120, 1000))
    monkeypatch.setattr(api_mod, "client_pages", DailyKeyedQuota(0))
    monkeypatch.setattr(api_mod, "page_quota", DailyQuota(0))
    monkeypatch.setattr(api_mod, "quota", DailyQuota(0))
    sem, busy = threading.Semaphore(1), threading.Event()
    monkeypatch.setattr(api_mod, "_worker_sem", sem)
    monkeypatch.setattr(api_mod, "_worker_busy", busy)
    monkeypatch.setattr(api_mod, "jobs", JobManager(sem, busy))

    def make(mode):
        local = dataclasses.replace(api_mod.settings, mode=mode, run_ttl_minutes=0)
        monkeypatch.setattr(api_mod, "settings", local)
        monkeypatch.setattr(security_mod, "settings", local)
        return TestClient(api_mod.create_app())
    return make, seen


def test_desktop_reads_every_page_of_a_bundle(tmp_path, studio):
    make, seen = studio
    client = make("local")
    data = open(_write(tmp_path / "doc.veriscript"), "rb").read()
    r = client.post("/api/restore", files={"file": ("phone.veriscript", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["input_kind"] == "bundle" and meta["pages_processed"] == 2
    assert meta["from_phone"] == {"pages": 2, "corrected_lines": 1, "confirmed_lines": 1}
    assert seen == [(480, 320, 3), (320, 480, 3)]
    run = r.json()["run_id"]
    phone = client.get(f"/api/runs/{run}/files/phone_reading.json")
    assert phone.status_code == 200 and phone.json()["title"] == "Ward 7 record"
    docs = client.get("/api/library").json()["documents"]
    assert docs[0]["title"] == "Ward 7 record"


def test_damaged_bundle_is_refused_with_a_reason(tmp_path, studio):
    make, _ = studio
    client = make("local")
    r = client.post("/api/restore", files={"file": ("x.veriscript", b"PK\x03\x04junk", "application/zip")})
    assert r.status_code == 400 and "bundle" in r.json()["error"]


def test_demo_refuses_bundles(tmp_path, studio):
    make, _ = studio
    client = make("demo")
    data = open(_write(tmp_path / "doc.veriscript"), "rb").read()
    r = client.post("/api/restore", files={"file": ("phone.veriscript", data, "application/zip")})
    assert r.status_code == 400 and "Desktop" in r.json()["error"]
