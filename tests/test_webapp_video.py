"""Video routes: real upload/review/export, validation, budgets and cancellation."""
import asyncio
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "webapp"))
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
import vvweb.api as api
import vvweb.video as video
from vvweb.security import DailyKeyedQuota, DailyQuota, RateLimiter
from vvweb.storage import RunStore
from test_video_scan import _clip, _spread


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "store", RunStore(str(tmp_path / "runs"), 60))
    monkeypatch.setattr(api, "limiter", RateLimiter(120, 100))
    monkeypatch.setattr(api, "quota", DailyQuota(300))
    monkeypatch.setattr(api, "page_quota", DailyQuota(500))
    monkeypatch.setattr(api, "client_pages", DailyKeyedQuota(20))
    monkeypatch.setattr(api, "_worker_sem", threading.Semaphore(1))
    monkeypatch.setattr(api, "_worker_busy", threading.Event())
    return TestClient(api.create_app())


def scan(client, tmp_path):
    source = _clip(tmp_path / "book.avi", [_spread(1), _spread(2)])
    response = client.post("/api/video-scan", files={"file": ("book.avi", source.read_bytes())},
                           data={"layout": "spread"})
    assert response.status_code == 200, response.text
    return response.json()


def test_capture_preview_review_export_and_download(client, tmp_path):
    import pypdfium2 as pdfium
    result = scan(client, tmp_path)
    assert len(result["pages"]) == 4
    assert [p["side"] for p in result["pages"]] == ["left", "right"] * 2
    run = Path(api.store.run_dir(result["run_id"]))
    assert not (run / ".video-upload").exists()
    preview = client.get(result["pages"][0]["preview"])
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/runs/{result['run_id']}/video-pages/99").status_code == 404
    assert client.get(f"/api/runs/{result['run_id']}/files/capture.json").status_code == 404
    exported = client.post(f"/api/runs/{result['run_id']}/video-export",
                           json={"pages": [3, 0], "searchable": False})
    assert exported.status_code == 200, exported.text
    download = client.get(exported.json()["pdf"] + "?download=1")
    assert download.status_code == 200 and "book.pdf" in download.headers["content-disposition"]
    with pdfium.PdfDocument(download.content) as pdf:
        assert len(pdf) == 2
    assert api.client_pages.used("testclient") == 0


@pytest.mark.parametrize("name,data,layout,status", [
    ("page.png", b"anything", "auto", 400),
    ("book.mp4", b"", "auto", 400),
    ("book.mp4", b"not a container", "auto", 400),
    ("book.mp4", b"anything", "unknown", 400),
])
def test_invalid_uploads_leave_no_runs(client, name, data, layout, status):
    response = client.post("/api/video-scan", files={"file": (name, data)}, data={"layout": layout})
    assert response.status_code == status
    assert not list(Path(api.store.root).iterdir())


def test_upload_cap(client, monkeypatch):
    monkeypatch.setattr(video, "settings", replace(video.settings, video_upload_mb=1))
    response = client.post("/api/video-scan", files={"file": ("book.mp4", b"x" * (1024 * 1024 + 1))})
    assert response.status_code == 413
    assert not list(Path(api.store.root).iterdir())


def test_selection_validation_and_expiry(client, tmp_path):
    result = scan(client, tmp_path)
    url = f"/api/runs/{result['run_id']}/video-export"
    for body in ({"pages": []}, {"pages": [0, 0]}, {"pages": [True]},
                 {"pages": [99]}, {"pages": [0], "searchable": "yes"},
                 {"pages": [0], "lang": []}):
        assert client.post(url, json=body).status_code == 400
    run = Path(api.store.run_dir(result["run_id"]))
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["expires_at"] = 0
    (run / "manifest.json").write_text(json.dumps(manifest))
    assert client.get(result["pages"][0]["preview"]).status_code == 404
    assert client.post(url, json={"pages": [0]}).status_code == 404


def test_ocr_allowance_and_worker_busy(client, tmp_path, monkeypatch):
    result = scan(client, tmp_path)
    url = f"/api/runs/{result['run_id']}/video-export"
    monkeypatch.setattr(api, "client_pages", DailyKeyedQuota(1))
    assert client.post(url, json={"pages": [0, 1], "searchable": True}).status_code == 429
    # Image export remains available for a book larger than the OCR budget.
    assert client.post(url, json={"pages": [0, 1]}).status_code == 200
    assert api._worker_sem.acquire(blocking=False)
    try:
        assert client.post(url, json={"pages": [0]}).status_code == 503
    finally:
        api._worker_sem.release()


def test_timeout_retains_worker_until_cancelled_thread_exits(client, tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(video, "settings", replace(video.settings, video_timeout_s=.05))
    source = _clip(tmp_path / "book.avi", [_spread(1)])
    cancel_seen = threading.Event()
    finish = threading.Event()

    def slow(path, out, options, *, cancel):
        while not cancel():
            time.sleep(.005)
        cancel_seen.set()
        finish.wait(2)
        raise TimeoutError("cancelled")

    monkeypatch.setattr(video, "extract_video_pages", slow)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://test") as browser:
            response = await browser.post("/api/video-scan", files={"file": ("book.avi", source.read_bytes())})
            assert response.status_code == 504
            assert await asyncio.to_thread(cancel_seen.wait, 1)
            assert api._worker_busy.is_set()
            assert not api._worker_sem.acquire(blocking=False)
            finish.set()
            for _ in range(100):
                if not api._worker_busy.is_set():
                    break
                await asyncio.sleep(.01)
            assert not api._worker_busy.is_set()
            assert api._worker_sem.acquire(blocking=False)
            api._worker_sem.release()
            assert not list(Path(api.store.root).iterdir())

    asyncio.run(exercise())
