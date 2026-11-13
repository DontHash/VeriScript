"""
test_webapp_desktop.py — the desktop app's local-server contract:
local/demo mode, the per-launch session token and the runs directory.
"""
from __future__ import annotations

import os
import sys

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))

pytest.importorskip("fastapi", reason="webapp dependencies not installed")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vvweb.config import Settings  # noqa: E402
from vvweb.security import (DESKTOP_COOKIE, DESKTOP_HEADER,  # noqa: E402
                            DESKTOP_SESSION_PATH, DesktopSessionMiddleware)

TOKEN = "t" * 48


@pytest.fixture()
def gated():
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/studio")
    def studio():
        return {"page": "studio"}

    app.add_middleware(DesktopSessionMiddleware, token=TOKEN)
    return TestClient(app)


def test_requests_without_the_token_are_refused(gated):
    assert gated.get("/api/health").status_code == 403
    assert gated.get("/studio").status_code == 403
    assert gated.get("/api/health", headers={DESKTOP_HEADER: "wrong"}).status_code == 403
    assert gated.get(f"{DESKTOP_SESSION_PATH}?token=wrong").status_code == 403
    assert gated.get(DESKTOP_SESSION_PATH).status_code == 403


def test_header_token_is_accepted_for_health_checks(gated):
    res = gated.get("/api/health", headers={DESKTOP_HEADER: TOKEN})
    assert res.status_code == 200 and res.json() == {"ok": True}


def test_session_link_sets_a_strict_httponly_cookie_and_redirects(gated):
    res = gated.get(f"{DESKTOP_SESSION_PATH}?token={TOKEN}", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/studio"
    cookie = res.headers["set-cookie"].lower()
    assert f"{DESKTOP_COOKIE}=" in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    # the client now carries the cookie: the page's own requests succeed
    assert gated.get("/studio").status_code == 200
    assert gated.get("/api/health").status_code == 200


def test_short_tokens_are_rejected():
    with pytest.raises(ValueError):
        DesktopSessionMiddleware(FastAPI(), token="short")


def test_mode_defaults_to_demo_and_accepts_local(monkeypatch):
    monkeypatch.delenv("VERISCRIPT_WEB_MODE", raising=False)
    assert Settings().mode == "demo"
    monkeypatch.setenv("VERISCRIPT_WEB_MODE", "Local")
    assert Settings().mode == "local"
    monkeypatch.setenv("VERISCRIPT_WEB_MODE", "anything-else")
    assert Settings().mode == "demo"


def test_desktop_settings_are_read_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VERISCRIPT_WEB_DESKTOP_TOKEN", TOKEN)
    monkeypatch.setenv("VERISCRIPT_WEB_RUNS_DIR", str(tmp_path))
    s = Settings()
    assert s.desktop_token == TOKEN
    assert s.runs_dir == str(tmp_path)


def test_health_reports_the_mode():
    import vvweb.api as api_mod
    res = TestClient(api_mod.create_app()).get("/api/health")
    assert res.status_code == 200
    assert res.json()["mode"] in {"demo", "local"}


def test_warm_up_holds_the_worker_slot(monkeypatch):
    """A request during warm-up must queue, not run OCR concurrently (that
    crashed the server natively on the first click after launch)."""
    import threading

    import vvweb.api as api_mod
    from veriscript.core import data as doc_data
    from veriscript.document import pipeline as doc_pipeline

    started, release = threading.Event(), threading.Event()

    def fake_pipeline(*_args, **_kwargs):
        started.set()
        assert release.wait(10)

    monkeypatch.setattr(doc_data, "render_synthetic_invoice", lambda **_kw: (None, None))
    monkeypatch.setattr(doc_pipeline, "run_document_pipeline", fake_pipeline)

    worker = threading.Thread(target=api_mod._warm_pipeline)
    worker.start()
    try:
        assert started.wait(10)
        assert api_mod._worker_busy.is_set()
        assert not api_mod._worker_sem.acquire(blocking=False)
    finally:
        release.set()
        worker.join(10)
    assert not api_mod._worker_busy.is_set()
    assert api_mod._worker_sem.acquire(blocking=False)
    api_mod._worker_sem.release()
