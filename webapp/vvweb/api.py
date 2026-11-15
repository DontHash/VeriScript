"""FastAPI application: the VeriScript web studio.

- Serves the built frontend (webapp/frontend/dist) when present.
- POST   /api/jobs        → queue an upload; returns at once (202) with a job.
- GET    /api/jobs/{id}   → status, per-page progress, and the result when done.
- DELETE /api/jobs/{id}   → cancel; the job stops between pages.
- POST   /api/restore     → the same, waiting for the result (scripts, client).
- GET    /api/runs/{id}/files/{name} → artifacts of a finished run.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import threading
import time
import zipfile
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import (Body, Depends, FastAPI, File, Form, HTTPException, Request,
                     UploadFile, status)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .compression import SelectiveGZipMiddleware
from . import diagnostics as _diagnostics  # noqa: F401 - installs the recent-log handler
from .jobs import Job, JobCancelled, JobManager, JobRejected
from .pipeline import (PAGE_CAP, PipelineError, collect_run_summary,
                       pages_to_process, process_page)
from .security import (DailyKeyedQuota, DailyQuota, DesktopSessionMiddleware,
                       RateLimiter, SecurityHeadersMiddleware, client_key,
                       http_exception_handler, new_run_id, require_auth,
                       validate_upload)
from .storage import PUBLIC_FILES, RUN_ID_RE, RunStore

from veriscript.logging_setup import get_logger

_LOG = get_logger("web")

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP_DIR = os.path.dirname(HERE)
FRONTEND_DIST = os.path.join(WEBAPP_DIR, "frontend", "dist")
RUNS_DIR = settings.runs_dir or os.path.join(WEBAPP_DIR, "runs")

MAX_LANG = {"en", "ne", "hi"}
OCR_BACKENDS = {"auto", "rapidocr", "tesseract"}
#: Searchable-PDF size presets (veriscript.document.export.PDF_SIZES).
PDF_SIZES = ("standard", "small", "archive")


def _flag(value: str, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    return default


def _require_run_dir(run_id: str) -> str:
    """The run's directory, or a 404 when it expired / never existed."""
    manifest = store.read_manifest(run_id)
    try:
        run_dir = store.run_dir(run_id)
    except KeyError:
        run_dir = ""
    if manifest is None or not run_dir or not os.path.isdir(run_dir):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="This result has expired. Run the page again.")
    return run_dir


def _result_from_run(run_dir: str):
    """Rebuild the token objects from the run's current state.

    Corrections are cumulative: once `corrected.json` exists it is the truth,
    and the next batch applies on top of it (falling back to the canonical
    `ocr.json` before the first call).
    """
    from veriscript.document.corrections import result_from_ocr_json

    name = ("corrected.json"
            if os.path.isfile(os.path.join(run_dir, "corrected.json"))
            else "ocr.json")
    return result_from_ocr_json(os.path.join(run_dir, name))


def _previously_applied(run_dir: str) -> set:
    """(index, original, corrected, action) already in `corrections.json`."""
    try:
        with open(os.path.join(run_dir, "corrections.json"),
                  encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return set()
    out = set()
    for item in payload.get("applied") or []:
        if isinstance(item, dict):
            out.add((item.get("index"), item.get("original"),
                     item.get("corrected"), item.get("action")))
    return out


def _new_correction_entries(raw: list, parsed: list, seen: set) -> list:
    """Raw body entries for corrections not already in the run's record.

    `corrections.json` is the source of truth for dedupe; suggestion metadata
    (`suggested`) only exists in the raw body, so raw entries are matched back
    by index.
    """
    raw_by_index = {}
    for entry in raw:
        if isinstance(entry, dict) and entry.get("index") is not None:
            try:
                raw_by_index[int(entry["index"])] = entry
            except (TypeError, ValueError):
                continue
    fresh = []
    for c in parsed:
        if (c.index, c.original, c.corrected, c.action) in seen:
            continue
        fresh.append(raw_by_index.get(c.index, {
            "index": c.index, "original": c.original,
            "corrected": c.corrected, "action": c.action}))
    return fresh


def _memory_enabled() -> bool:
    from veriscript.document import memory as correction_memory

    return correction_memory.memory_enabled()


def _parse_corrections_body(body: Optional[Dict[str, Any]]):
    from veriscript.document.corrections import MAX_CORRECTIONS, load_corrections

    raw = (body or {}).get("corrections") or []
    if not isinstance(raw, list) or len(raw) > MAX_CORRECTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"corrections must be a list of at most {MAX_CORRECTIONS} entries")
    try:
        doc = load_corrections({"pages": {"*": raw}})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return doc.pages["*"]


def _count_pages(kind: str, path: str, all_pages: bool) -> int:
    """Quota units for one request: a 10-page PDF costs 10 pages, not 1 run."""
    return pages_to_process(path, kind, all_pages)


store = RunStore(RUNS_DIR, settings.run_ttl_seconds)
limiter = RateLimiter(settings.rate_window_s, settings.rate_max_in_window)
quota = DailyQuota(settings.daily_runs)
page_quota = DailyQuota(settings.daily_pages)
client_pages = DailyKeyedQuota(settings.pages_per_client)
_worker_sem = threading.Semaphore(settings.max_concurrent)
_worker_busy = threading.Event()
jobs = JobManager(_worker_sem, _worker_busy, max_queued=settings.max_queued_jobs)

VERSION = "0.1.0"


def _busy() -> bool:
    return _worker_busy.is_set()


async def _periodic_prune() -> None:
    while True:
        await asyncio.sleep(settings.prune_interval_s)
        store.prune()
        limiter.prune()


def _warm_lang() -> Optional[str]:
    """Language to warm at startup, mapped like a request (`en` → default)."""
    lang = (settings.warm_lang or "ne").strip().lower()
    if lang not in MAX_LANG:
        lang = "ne"
    return None if lang == "en" else lang


def _warm_pipeline() -> None:
    """Load the OCR engine in the background so the first visitor does not pay
    the model warm-up (including the one-time Devanagari model download).
    Best-effort; failures are non-fatal.

    The warm-up holds the worker slot like a real run. Initialising the OCR
    engine while a request uses it crashed the process natively (no Python
    traceback), so a request made during warm-up now queues behind it and
    /api/health reports busy until it finishes."""
    with _worker_sem:
        _worker_busy.set()
        try:
            import tempfile

            from veriscript.core import data as doc_data
            from veriscript.document.pipeline import run_document_pipeline

            page, _gt = doc_data.render_synthetic_invoice(seed=1, dpi=110)
            with tempfile.TemporaryDirectory(prefix="vv_warm_") as td:
                run_document_pipeline(page, backend=None, lang=_warm_lang(),
                                      out_dir=td,
                                      stem="warm", make_pdf=False, make_overlay=False,
                                      make_txt=False, make_json=False)
        except Exception:  # noqa: BLE001 - warm-up only
            pass
        finally:
            _worker_busy.clear()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    store.prune()
    _LOG.info("warming OCR in the background (lang=%s)", _warm_lang() or "default")
    threading.Thread(target=_warm_pipeline, daemon=True, name="vv-warmup").start()
    task = asyncio.create_task(_periodic_prune())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="VeriScript Studio", version=VERSION,
                  docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=_lifespan)

    # Starlette runs the last-added middleware first: the session gate sits
    # inside the security headers, so its 403s carry them too.
    if settings.desktop_token:
        app.add_middleware(DesktopSessionMiddleware, token=settings.desktop_token)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024,
                       compresslevel=6)
    app.add_exception_handler(HTTPException, http_exception_handler)

    # -- meta --------------------------------------------------------------
    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {
            "ok": True,
            "version": VERSION,
            "mode": settings.mode,
            "busy": _busy(),
            "limits": {
                "max_upload_mb": settings.max_upload_mb,
                "video_upload_mb": settings.video_upload_mb,
                "video_max_pages": settings.video_max_pages,
                "video_max_seconds": settings.video_max_seconds,
                "max_image_megapixels": settings.max_image_megapixels,
                "max_pages": PAGE_CAP,
                "ttl_minutes": max(0, settings.run_ttl_minutes),
                "queued": jobs.queued_count(),
                "rate_max": settings.rate_max_in_window,
                "rate_window_s": settings.rate_window_s,
                "auth": settings.auth_enabled,
                "max_connections": settings.max_connections,
                "daily_runs": quota.state()["limit"],
                "daily_used": quota.state()["used"],
                "daily_pages": page_quota.state()["limit"],
                "daily_pages_used": page_quota.state()["used"],
                "pages_per_client": settings.pages_per_client,
                "memory": _memory_enabled(),
            },
        }

    # -- diagnostics (desktop only) ------------------------------------------
    @app.get("/api/diagnostics", dependencies=[Depends(require_auth)])
    async def diagnostics() -> Dict[str, Any]:
        """Versions, limits, recent jobs and warnings for a bug report.

        Local mode only: on a shared demo the recent errors could belong to
        other visitors. Nothing is sent anywhere; the person copies it."""
        if settings.mode != "local":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Not available on the shared demo.")
        from . import diagnostics as diag

        data = diag.report(version=VERSION, settings=settings, jobs=jobs)
        return {**data, "text": diag.as_text(data)}

    # -- jobs --------------------------------------------------------------
    async def _submit(request: Request, file: UploadFile, *, lang: str,
                      deskew: str, ocr: str, overlay: str, pdf: str, txt: str,
                      md: str, all_pages: str, auto_rotate: str,
                      text_layer: str = "1", pdf_size: str = "standard") -> Job:
        """Validate, store and charge an upload, then queue it as a job.

        Never blocks the event loop: the job runs on the job worker, which
        holds the shared worker slot only while the pipeline really runs."""
        allowed, retry_after = limiter.check(client_key(request))
        if not allowed:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Rate limit reached. Try again shortly.",
                                headers={"Retry-After": str(retry_after)})

        lang = (lang or "ne").strip().lower()
        if lang not in MAX_LANG:
            lang = "ne"
        ocr = (ocr or "auto").strip().lower()
        if ocr not in OCR_BACKENDS:
            _LOG.warning("unknown OCR engine %r; using auto", ocr)
            ocr = "auto"
        deskew_flag = _flag(deskew, default=False)
        all_pages_flag = _flag(all_pages, default=False)

        # Stream the upload to disk with a hard cap (never trust the header).
        run_id = new_run_id()
        run_dir = store.create(run_id)
        upload_path = os.path.join(run_dir, ".upload")
        size = 0
        try:
            with open(upload_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File too large. The limit is "
                                   f"{settings.max_upload_mb} MB per page.")
                    f.write(chunk)

            with open(upload_path, "rb") as f:
                head = f.read(64)
            kind = validate_upload(file.filename, file.content_type, head,
                                   upload_path)
        except HTTPException:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Upload failed.")

        # Quotas are charged in pages (a 10-page PDF costs 10), now that the
        # upload is validated. Per-visitor first so a blocked visitor does not
        # consume the global budget.
        pages = _count_pages(kind, upload_path, all_pages_flag)
        allowed, retry_after = client_pages.check(client_key(request), pages)
        if not allowed:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"You've reached the free demo limit "
                       f"({settings.pages_per_client} pages per visitor per "
                       f"day). Try again after midnight UTC.",
                headers={"Retry-After": str(retry_after)})
        allowed, retry_after = page_quota.check(pages)
        if not allowed:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="The demo's daily page budget is used up. Try again "
                       "after midnight UTC.",
                headers={"Retry-After": str(retry_after)})
        allowed, retry_after = quota.check()
        if not allowed:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="The demo's daily budget is used up. Try again after midnight UTC.",
                headers={"Retry-After": str(retry_after)})

        options = dict(lang=None if lang == "en" else lang, deskew=deskew_flag,
                       kind=kind, ocr=ocr,
                       make_overlay=_flag(overlay), make_pdf=_flag(pdf),
                       make_txt=_flag(txt), make_md=_flag(md),
                       all_pages=all_pages_flag,
                       auto_rotate=_flag(auto_rotate),
                       use_text_layer=_flag(text_layer),
                       pdf_size=pdf_size if pdf_size in PDF_SIZES else "standard")

        # Library title: the uploaded file's name without its extension.
        title = os.path.splitext(os.path.basename(file.filename or ""))[0][:120]             or "Untitled"

        def work(job: Job) -> Dict[str, Any]:
            try:
                try:
                    payload = process_page(upload_path, run_dir, run_id,
                                           progress=job.progress,
                                           check=job.check, **options)
                except PipelineError as exc:
                    raise JobRejected(str(exc)) from exc
            finally:
                try:
                    os.remove(upload_path)
                except OSError:
                    pass
            store.write_manifest(run_id, {"meta": payload.get("meta", {}),
                                          "files": list(PUBLIC_FILES.keys()),
                                          "title": title,
                                          "created": int(time.time()),
                                          "status_line": payload.get("status_line", "")})
            payload["expires_in"] = settings.run_ttl_seconds
            return payload

        job = Job(id=run_id, run_dir=run_dir, work=work,
                  timeout_s=settings.process_timeout_s)
        job.pages = pages
        try:
            jobs.submit(job)
        except OverflowError:
            shutil.rmtree(run_dir, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="Too many files are waiting. Try again "
                                       "when some have finished.",
                                headers={"Retry-After": "10"})
        return job

    def _job_or_404(job_id: str) -> Job:
        job = jobs.get(job_id) if RUN_ID_RE.match(job_id or "") else None
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="No such job. It may have finished long ago; "
                                       "run the file again.")
        return job

    @app.post("/api/jobs", dependencies=[Depends(require_auth)],
              status_code=status.HTTP_202_ACCEPTED)
    async def create_job(request: Request,
                         file: UploadFile = File(...),
                         lang: str = Form("ne"),
                         deskew: str = Form("0"),
                         ocr: str = Form("auto"),
                         overlay: str = Form("1"),
                         pdf: str = Form("1"),
                         txt: str = Form("1"),
                         md: str = Form("1"),
                         all_pages: str = Form("0"),
                         auto_rotate: str = Form("1"),
                         text_layer: str = Form("1"),
                         pdf_size: str = Form("standard")) -> JSONResponse:
        job = await _submit(request, file, lang=lang, deskew=deskew, ocr=ocr,
                            overlay=overlay, pdf=pdf, txt=txt, md=md,
                            all_pages=all_pages, auto_rotate=auto_rotate,
                            text_layer=text_layer, pdf_size=pdf_size)
        return JSONResponse(job.public(jobs.position(job)),
                            status_code=status.HTTP_202_ACCEPTED,
                            headers={"Location": f"/api/jobs/{job.id}"})

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
    async def get_job(job_id: str) -> JSONResponse:
        job = _job_or_404(job_id)
        return JSONResponse(job.public(jobs.position(job)),
                            headers={"Cache-Control": "no-store"})

    @app.delete("/api/jobs/{job_id}", dependencies=[Depends(require_auth)])
    async def cancel_job(job_id: str) -> JSONResponse:
        job = jobs.cancel(_job_or_404(job_id).id)
        return JSONResponse(job.public(jobs.position(job)))

    @app.post("/api/restore", dependencies=[Depends(require_auth)])
    async def restore(request: Request,
                      file: UploadFile = File(...),
                      lang: str = Form("ne"),
                      deskew: str = Form("0"),
                      ocr: str = Form("auto"),
                      overlay: str = Form("1"),
                      pdf: str = Form("1"),
                      txt: str = Form("1"),
                      md: str = Form("1"),
                      all_pages: str = Form("0"),
                      auto_rotate: str = Form("1"),
                      text_layer: str = Form("1"),
                      pdf_size: str = Form("standard")) -> JSONResponse:
        """Queue the upload and wait for it (scripts and the typed client).

        Waiting polls the job without blocking the event loop. If the caller
        goes away, the job is cancelled; it then stops between pages."""
        job = await _submit(request, file, lang=lang, deskew=deskew, ocr=ocr,
                            overlay=overlay, pdf=pdf, txt=txt, md=md,
                            all_pages=all_pages, auto_rotate=auto_rotate,
                            text_layer=text_layer, pdf_size=pdf_size)
        try:
            while not job.done.is_set():
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            jobs.cancel(job.id)
            raise
        if job.status == "done":
            return JSONResponse(job.result)
        if job.status == "cancelled":
            raise HTTPException(status_code=499, detail="The run was cancelled.")
        if job.error_status == 504:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                                detail="Processing timed out for this page.")
        raise HTTPException(status_code=job.error_status,
                            detail=job.error or "The run failed.")

    # -- artifacts ---------------------------------------------------------
    @app.get("/api/runs/{run_id}/files.zip", dependencies=[Depends(require_auth)])
    async def run_files_zip(run_id: str) -> Response:
        """Every result file of a run in one archive ("Download all").

        The training export (corrections.zip) is left out: it is only ever
        shared by an explicit, separate choice."""
        if not RUN_ID_RE.match(run_id) or store.read_manifest(run_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="This result has expired. Run the page again.")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in PUBLIC_FILES:
                if name == "corrections.zip":
                    continue
                path = store.resolve_file(run_id, name)
                if path:
                    zf.write(path, arcname=PUBLIC_FILES[name]["download"])
        return Response(
            buf.getvalue(), media_type="application/zip",
            headers={"Content-Disposition":
                     f'attachment; filename="veriscript-{run_id}.zip"',
                     "Cache-Control": "private, no-store"})

    @app.get("/api/runs/{run_id}/files/{name}", dependencies=[Depends(require_auth)])
    async def run_file(run_id: str, name: str, download: int = 0) -> FileResponse:
        if name not in PUBLIC_FILES:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such file.")
        manifest = store.read_manifest(run_id)
        path = store.resolve_file(run_id, name)
        if manifest is None or path is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="This result has expired. Run the page again.")
        return FileResponse(
            path,
            media_type=PUBLIC_FILES[name]["media"],
            filename=PUBLIC_FILES[name]["download"] if download else None,
            headers={"Cache-Control": "private, max-age=300"},
        )

    # -- correction loop (docs/CORRECTIONS.md) ------------------------------
    @app.post("/api/runs/{run_id}/correct", dependencies=[Depends(require_auth)])
    async def correct(run_id: str, body: Dict[str, Any] = Body(...)) -> JSONResponse:
        import cv2

        from veriscript.document.corrections import (apply_and_export,
                                                     corrections_record,
                                                     write_corrections_record)

        run_dir = _require_run_dir(run_id)
        corrections = _parse_corrections_body(body)
        if not corrections:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="no corrections supplied")
        image = cv2.imread(os.path.join(run_dir, "restored.png"))
        if image is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The run image is no longer available. Run the page again.")
        result = _result_from_run(run_dir)
        snapshots = {i: (t.text, list(t.flags))
                     for i, t in enumerate(result.tokens)}
        seen = _previously_applied(run_dir)
        applied = apply_and_export(
            run_dir, "corrected", image, result, corrections,
            make_pdf=True, make_overlay=False, make_txt=True,
            make_json=True, make_md=True, overlay_source=image)
        stats = applied["stats"]
        page_stem = f"page_{run_id[:8]}"
        if stats["reviewed"]:
            write_corrections_record(
                os.path.join(run_dir, "corrections.json"),
                corrections_record(page_stem, corrections, stats, run_id))
            try:  # track D2: text-only local memory (best-effort)
                from veriscript.document import memory as correction_memory
                raw = (body or {}).get("corrections") or []
                fresh = _new_correction_entries(raw, corrections, seen)
                correction_memory.record_corrections(
                    fresh, snapshots, engine=result.backend)
            except Exception:  # noqa: BLE001
                pass
        summary = collect_run_summary(run_dir, run_id)
        return JSONResponse({"run_id": run_id, "stats": stats, **summary})

    @app.post("/api/runs/{run_id}/corrections/export",
              dependencies=[Depends(require_auth)])
    async def corrections_export(run_id: str,
                                 body: Dict[str, Any] = Body(...)) -> JSONResponse:
        import cv2

        from veriscript.document.corrections import build_corrections_zip

        run_dir = _require_run_dir(run_id)
        corrections = _parse_corrections_body(body)
        share_raw = (body or {}).get("share") or []
        if not isinstance(share_raw, list):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="share must be a list of indices")
        try:
            share = [int(i) for i in share_raw]
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="share must be a list of indices")
        known = {c.index for c in corrections}
        if not set(share) <= known:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="share contains indices that are not in corrections")
        image = cv2.imread(os.path.join(run_dir, "restored.png"))
        if image is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The run image is no longer available. Run the page again.")
        page_stem = f"page_{run_id[:8]}"
        build_corrections_zip(os.path.join(run_dir, "corrections.zip"),
                              image, page_stem, corrections, share)
        n_shared = sum(1 for c in corrections
                       if c.index in set(share) and c.bbox is not None)
        return JSONResponse({
            "run_id": run_id,
            "file": f"/api/runs/{run_id}/files/corrections.zip",
            "shared": n_shared,
        })

    # -- local correction memory (track D2, docs/HARNESS_PLAN.md) -----------
    @app.get("/api/memory", dependencies=[Depends(require_auth)])
    async def memory_status() -> Dict[str, Any]:
        from veriscript.document import memory as correction_memory

        return correction_memory.stats()

    @app.post("/api/memory/clear", dependencies=[Depends(require_auth)])
    async def memory_clear() -> Dict[str, Any]:
        from veriscript.document import memory as correction_memory

        return {"removed": correction_memory.clear(),
                "enabled": correction_memory.memory_enabled()}

    from .video import register_video_routes
    import sys
    register_video_routes(app, sys.modules[__name__])
    from .library import register_library_routes
    register_library_routes(app, sys.modules[__name__])

    # -- frontend ----------------------------------------------------------
    if os.path.isdir(FRONTEND_DIST):
        index = os.path.join(FRONTEND_DIST, "index.html")

        @app.get("/studio", include_in_schema=False)
        async def studio_page() -> FileResponse:
            return FileResponse(index)

        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="site")

    else:  # dev fallback: point the developer at the Vite dev server
        @app.get("/", include_in_schema=False)
        async def no_build() -> JSONResponse:
            return JSONResponse({
                "ok": True,
                "hint": "Frontend not built. Run `npm install && npm run build` in "
                        "webapp/frontend, or use the Vite dev server on :5173.",
            })

    return app
