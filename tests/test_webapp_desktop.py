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
