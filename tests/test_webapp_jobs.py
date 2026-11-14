"""
test_webapp_jobs.py — the studio's background job model (docs/TECH_UPGRADE_PLAN.md, A1/A2).

Guards the defects the job model fixes:
- the server keeps answering while a page is being read (no event-loop block);
- Cancel and timeouts really stop the work, and the worker slot is released
  only once the work has stopped, so two pipeline runs never overlap;
- a cancelled run leaves no files behind;
- the page cap can be lifted (desktop) and runs can be kept (TTL 0).

The OCR pipeline is stubbed, as in test_webapp_api.py.
"""
from __future__ import annotations

import os
import sys
import threading
import time

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
def env(tmp_path, monkeypatch):
    """A fresh store, worker slot and job manager per test."""
    sem = threading.Semaphore(1)
    busy = threading.Event()
    manager = JobManager(sem, busy, max_queued=5)
    monkeypatch.setattr(api_mod, "store", RunStore(str(tmp_path / "runs"), 60))
    monkeypatch.setattr(api_mod, "limiter", RateLimiter(120, 1000))
    monkeypatch.setattr(api_mod, "_worker_sem", sem)
    monkeypatch.setattr(api_mod, "_worker_busy", busy)
    monkeypatch.setattr(api_mod, "jobs", manager)
    # Demo quotas are module state shared by every test; switch them off.
    monkeypatch.setattr(api_mod, "client_pages", DailyKeyedQuota(0))
    monkeypatch.setattr(api_mod, "page_quota", DailyQuota(0))
    monkeypatch.setattr(api_mod, "quota", DailyQuota(0))
    yield TestClient(api_mod.create_app()), manager, tmp_path
    # Never let a job outlive its test (it would run against the next
    # test's patches).
    _wait(lambda: all(j.done.is_set() for j in list(manager._jobs.values())))


class Gate:
    """A stub pipeline that blocks on each page until released, and records
    how many pipeline calls ever ran at the same time."""

    def __init__(self):
        self.fake = _fake_pipeline({})
        self.lock = threading.Lock()
        self.running = 0
        self.max_running = 0
        self.calls = 0
        self.entered = threading.Semaphore(0)
        self.release = threading.Semaphore(0)

    def __call__(self, img, **kw):
        with self.lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.calls += 1
        self.entered.release()
        try:
            assert self.release.acquire(timeout=10), "test never released the page"
            return self.fake(img, **kw)
        finally:
            with self.lock:
                self.running -= 1

    def let_through(self, n: int = 1):
        for _ in range(n):
            self.release.release()


def _pdf(tmp_path, pages: int, name: str = "doc.pdf") -> bytes:
    from reportlab.pdfgen import canvas

    path = tmp_path / name
    c = canvas.Canvas(str(path), pagesize=(240, 200))
    for i in range(pages):
        c.drawString(20, 170, f"PAGE {i}")
        c.showPage()
    c.save()
    return path.read_bytes()


def _Settings(**overrides):
    import dataclasses
    return dataclasses.replace(api_mod.settings, **overrides)


def _wait(predicate, timeout: float = 10.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def _poll_until_finished(client, job_id: str) -> dict:
    end = time.time() + 15
    while time.time() < end:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_job_runs_in_the_background_and_returns_the_result(env, monkeypatch):
    client, _manager, _tmp = env
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", _fake_pipeline())

    r = client.post("/api/jobs", files={"file": ("p.png", _png_bytes(), "image/png")})
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in ("queued", "running", "done")
    assert r.headers["location"] == f"/api/jobs/{job['job_id']}"

    done = _poll_until_finished(client, job["job_id"])
    assert done["status"] == "done"
    result = done["result"]
    assert result["run_id"] == job["job_id"]
    assert client.get(result["files"]["md"]).status_code == 200


def test_server_answers_while_a_page_is_read(env, monkeypatch):
    """The old endpoint blocked the event loop while waiting for the worker."""
    client, manager, _tmp = env
    gate = Gate()
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", gate)

    first = client.post("/api/jobs", files={"file": ("a.png", _png_bytes(), "image/png")}).json()
    assert gate.entered.acquire(timeout=10)
    # A second upload queues instead of hanging the server.
    started = time.time()
    second = client.post("/api/jobs", files={"file": ("b.png", _png_bytes(), "image/png")})
    assert second.status_code == 202
    assert second.json()["position"] == 1
    health = client.get("/api/health").json()
    assert time.time() - started < 2.0
    assert health["busy"] is True and health["limits"]["queued"] == 1

    gate.let_through(2)
    assert _poll_until_finished(client, first["job_id"])["status"] == "done"
    assert _poll_until_finished(client, second.json()["job_id"])["status"] == "done"
    assert gate.max_running == 1


def test_cancel_stops_between_pages_and_frees_the_slot_only_after(env, monkeypatch):
    client, manager, tmp_path = env
    gate = Gate()
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", gate)

    job = client.post("/api/jobs", data={"all_pages": "1", "lang": "en"},
                      files={"file": ("d.pdf", _pdf(tmp_path, 6), "application/pdf")}).json()
    assert job["pages"] == 6
    run_dir = api_mod.store.run_dir(job["job_id"])

    assert gate.entered.acquire(timeout=10)      # page 1 is being read
    status = client.get(f"/api/jobs/{job['job_id']}").json()
    assert status["status"] == "running" and status["page"] == 1
    assert status["stage"] == "Reading page 1 of 6"

    cancel = client.delete(f"/api/jobs/{job['job_id']}").json()
    assert cancel["cancel_requested"] is True and cancel["status"] == "running"
    # The page in flight still owns the slot: nothing else may start.
    assert api_mod._worker_busy.is_set()
    assert not api_mod._worker_sem.acquire(blocking=False)

    gate.let_through(1)                          # finish page 1 only
    final = _poll_until_finished(client, job["job_id"])
    assert final["status"] == "cancelled"
    assert gate.calls == 1                       # pages 2-6 never ran
    _wait(lambda: not api_mod._worker_busy.is_set())
    assert not os.path.exists(run_dir)           # no half-written run left
    assert api_mod._worker_sem.acquire(blocking=False)
    api_mod._worker_sem.release()


def test_cancelling_a_queued_job_never_runs_it(env, monkeypatch):
    client, manager, _tmp = env
    gate = Gate()
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", gate)

    first = client.post("/api/jobs", files={"file": ("a.png", _png_bytes(), "image/png")}).json()
    assert gate.entered.acquire(timeout=10)
    queued = client.post("/api/jobs", files={"file": ("b.png", _png_bytes(), "image/png")}).json()
    assert queued["status"] == "queued"

    cancelled = client.delete(f"/api/jobs/{queued['job_id']}").json()
    assert cancelled["status"] == "cancelled"
    assert not os.path.exists(api_mod.store.run_dir(queued["job_id"]))

    gate.let_through(1)
    assert _poll_until_finished(client, first["job_id"])["status"] == "done"
    time.sleep(0.2)
    assert gate.calls == 1


def test_timeout_stops_the_job_and_reports_it(env, monkeypatch):
    client, manager, tmp_path = env
    from veriscript.document import pipeline as document_pipeline
    fake = _fake_pipeline()

    def slow(img, **kw):
        time.sleep(0.3)
        return fake(img, **kw)

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", slow)
    monkeypatch.setattr(api_mod, "settings", _Settings(process_timeout_s=0.1))
    job = client.post("/api/jobs", data={"all_pages": "1"},
                      files={"file": ("d.pdf", _pdf(tmp_path, 4), "application/pdf")}).json()
    final = _poll_until_finished(client, job["job_id"])
    assert final["status"] == "failed"
    assert final["error_status"] == 504
    assert final["page"] == 1


def test_restore_still_waits_for_the_result(env, monkeypatch):
    """The synchronous endpoint (scripts, typed client) rides on the queue."""
    client, _manager, _tmp = env
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", _fake_pipeline())
    r = client.post("/api/restore", files={"file": ("p.png", _png_bytes(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["transcript"].strip() == "HELLO"


def test_queue_is_bounded(env, monkeypatch):
    client, manager, _tmp = env
    gate = Gate()
    from veriscript.document import pipeline as document_pipeline
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", gate)
    manager.max_queued = 1

    client.post("/api/jobs", files={"file": ("a.png", _png_bytes(), "image/png")})
    assert gate.entered.acquire(timeout=10)
    assert client.post("/api/jobs", files={"file": ("b.png", _png_bytes(), "image/png")}).status_code == 202
    third = client.post("/api/jobs", files={"file": ("c.png", _png_bytes(), "image/png")})
    assert third.status_code == 503
    gate.let_through(2)
    _wait(lambda: all(j.done.is_set() for j in list(manager._jobs.values())))


def test_unknown_job_is_404(env):
    client, _manager, _tmp = env
    assert client.get("/api/jobs/0123456789abcdef").status_code == 404
    assert client.get("/api/jobs/not-a-job").status_code == 404


def test_page_cap_zero_reads_every_page(env, monkeypatch):
    """Desktop: VERISCRIPT_WEB_PAGE_CAP=0 lifts the 10-page demo cap."""
    client, _manager, tmp_path = env
    from veriscript.document import pipeline as document_pipeline
    import vvweb.pipeline as web_pipeline

    captured: dict = {}
    monkeypatch.setattr(document_pipeline, "run_document_pipeline", _fake_pipeline(captured))
    monkeypatch.setattr(web_pipeline, "PAGE_CAP", 0)
    r = client.post("/api/restore", data={"all_pages": "1", "lang": "en"},
                    files={"file": ("d.pdf", _pdf(tmp_path, 12), "application/pdf")})
    assert r.status_code == 200, r.text
    meta = r.json()["meta"]
    assert meta["pages_processed"] == 12 and meta["pages_capped"] is False
    assert len(captured["calls"]) == 12
    combined = r.json()["files"]["combined_pdf"]
    import pypdfium2 as pdfium
    path = os.path.join(api_mod.store.run_dir(r.json()["run_id"]), "combined.pdf")
    assert client.get(combined).status_code == 200
    assert len(pdfium.PdfDocument(path)) == 12


def test_default_cap_still_applies(env, monkeypatch):
    client, _manager, tmp_path = env
    from veriscript.document import pipeline as document_pipeline
    import vvweb.pipeline as web_pipeline

    monkeypatch.setattr(document_pipeline, "run_document_pipeline", _fake_pipeline())
    monkeypatch.setattr(web_pipeline, "PAGE_CAP", 3)
    r = client.post("/api/restore", data={"all_pages": "1"},
                    files={"file": ("d.pdf", _pdf(tmp_path, 5), "application/pdf")})
    meta = r.json()["meta"]
    assert meta["pages_processed"] == 3 and meta["pages_capped"] is True


def test_ttl_zero_keeps_runs(tmp_path):
    store = RunStore(str(tmp_path / "runs"), 0)
    store.create("0123456789abcdef")
    store.write_manifest("0123456789abcdef", {"meta": {}})
    assert store.read_manifest("0123456789abcdef")["expires_at"] is None
    old = time.time() - 365 * 86400
    os.utime(store.run_dir("0123456789abcdef"), (old, old))
    assert store.prune() == 0
    # An abandoned upload (no manifest) older than a day is still cleaned up.
    store.create("fedcba9876543210")
    os.utime(store.run_dir("fedcba9876543210"), (old, old))
    assert store.prune() == 1
    assert os.path.isdir(store.run_dir("0123456789abcdef"))


def test_diagnostics_are_local_only_and_strip_paths(env, monkeypatch):
    client, _manager, _tmp = env
    assert client.get("/api/diagnostics").status_code == 404   # demo mode
    import dataclasses
    import logging
    monkeypatch.setattr(api_mod, "settings",
                        dataclasses.replace(api_mod.settings, mode="local"))
    logging.getLogger("vectovecto.web").warning(
        r"could not read C:\Users\someone\Documents\land_record.pdf here")
    body = client.get("/api/diagnostics").json()
    assert body["app"].startswith("VeriScript")
    assert "Recent jobs:" in body["text"]
    assert any("<path>" in r for r in body["log"])
    assert "someone" not in body["text"]
