"""
test_webapp_library.py — the desktop document library (docs/TECH_UPGRADE_PLAN.md, B1).

Local mode lists, searches, reopens, renames and deletes kept runs; the shared
demo exposes none of it.
"""
from __future__ import annotations

import dataclasses
import os
import sys
import threading

import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "webapp"))

pytest.importorskip("fastapi", reason="webapp dependencies not installed")
from fastapi.testclient import TestClient  # noqa: E402

import vvweb.api as api_mod  # noqa: E402
from vvweb.jobs import JobManager  # noqa: E402
from vvweb.security import DailyKeyedQuota, DailyQuota, RateLimiter  # noqa: E402
from vvweb.storage import RunStore  # noqa: E402

from test_webapp_api import _fake_pipeline, _png_bytes  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from veriscript.document import pipeline as document_pipeline

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", _fake_pipeline())
    monkeypatch.setattr(api_mod, "store", RunStore(str(tmp_path / "runs"), 0))
    monkeypatch.setattr(api_mod, "limiter", RateLimiter(120, 1000))
    monkeypatch.setattr(api_mod, "client_pages", DailyKeyedQuota(0))
    monkeypatch.setattr(api_mod, "page_quota", DailyQuota(0))
    monkeypatch.setattr(api_mod, "quota", DailyQuota(0))
    sem, busy = threading.Semaphore(1), threading.Event()
    monkeypatch.setattr(api_mod, "_worker_sem", sem)
    monkeypatch.setattr(api_mod, "_worker_busy", busy)
    monkeypatch.setattr(api_mod, "jobs", JobManager(sem, busy))
    monkeypatch.setattr(api_mod, "settings",
                        dataclasses.replace(api_mod.settings, mode="local", run_ttl_minutes=0))
    return TestClient(api_mod.create_app())


def _upload(client, name):
    r = client.post("/api/restore", files={"file": (name, _png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def test_library_lists_newest_first_with_titles(client, monkeypatch):
    import time
    first = _upload(client, "land record 2081.png")
    time.sleep(1.1)
    second = _upload(client, "invoice.jpg")
    docs = client.get("/api/library").json()["documents"]
    assert [d["run_id"] for d in docs] == [second, first]
    assert docs[1]["title"] == "land record 2081"
    assert docs[0]["pages"] == 1 and docs[0]["input_kind"] == "image"


def test_search_matches_title_and_text(client):
    rid = _upload(client, "receipt.png")       # the fake OCR reads "HELLO"
    _upload(client, "other.png")
    assert [d["run_id"] for d in client.get("/api/library?q=receipt").json()["documents"]] == [rid]
    assert len(client.get("/api/library?q=hello").json()["documents"]) == 2
    assert client.get("/api/library?q=hello%20nothing").json()["documents"] == []


def test_reopen_rename_and_delete(client):
    rid = _upload(client, "receipt.png")
    summary = client.get(f"/api/runs/{rid}/summary").json()
    assert summary["run_id"] == rid and summary["title"] == "receipt"
    assert summary["transcript"].strip() == "HELLO"
    assert summary["expires_in"] == 0 and "md" in summary["files"]

    r = client.patch(f"/api/runs/{rid}", json={"title": "  Ward 7   receipt "})
    assert r.json()["title"] == "Ward 7 receipt"
    assert client.get("/api/library").json()["documents"][0]["title"] == "Ward 7 receipt"
    assert client.patch(f"/api/runs/{rid}", json={"title": "  "}).status_code == 400

    assert client.delete(f"/api/runs/{rid}").json()["deleted"] is True
    assert client.get("/api/library").json()["documents"] == []
    assert client.get(f"/api/runs/{rid}/summary").status_code == 404
    assert client.delete(f"/api/runs/{rid}").status_code == 404


def test_bad_ids_are_404(client):
    assert client.get("/api/runs/..%2F..%2Fetc/summary").status_code == 404
    assert client.delete("/api/runs/not-a-run").status_code == 404


def test_demo_mode_exposes_nothing(client, monkeypatch):
    rid = _upload(client, "receipt.png")
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, mode="demo"))
    assert client.get("/api/library").status_code == 404
    assert client.get(f"/api/runs/{rid}/summary").status_code == 404
    assert client.patch(f"/api/runs/{rid}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/api/runs/{rid}").status_code == 404
    assert os.path.isdir(api_mod.store.run_dir(rid))
