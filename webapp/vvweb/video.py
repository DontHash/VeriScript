"""Video capture/review/export routes, sharing the studio worker and storage."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from pathlib import Path

from fastapi import Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from veriscript.document.video import (VIDEO_EXTENSIONS, VideoOptions,
                                       export_video_pdf, extract_video_pages)
from .config import settings
from .security import DailyKeyedQuota, client_key, new_run_id, require_auth


def register_video_routes(app, state):
    client_budget = DailyKeyedQuota(settings.video_pages_per_client)

    def rate_limit(request):
        allowed, retry = state.limiter.check(client_key(request))
        if not allowed:
            raise HTTPException(429, "Rate limit reached. Try again shortly.",
                                headers={"Retry-After": str(retry)})

    def load_capture(run_id):
        run_dir = state._require_run_dir(run_id)
        manifest = state.store.read_manifest(run_id)
        if not manifest or manifest.get("expires_at", 0) <= time.time():
            raise HTTPException(404, "Video capture has expired. Scan the video again.")
        try:
            with open(Path(run_dir) / "capture.json", encoding="utf-8") as f:
                return run_dir, json.load(f)
        except (OSError, ValueError):
            raise HTTPException(404, "No video capture for this run.")

    async def work(operation, *, cleanup=None):
        # A timed-out thread still owns the semaphore until it exits. Cancel
        # cooperatively between frames/pages, so subsequent runs cannot overlap.
        if not state._worker_sem.acquire(blocking=False):
            raise HTTPException(503, "The worker is busy. Try again shortly.",
                                headers={"Retry-After": "10"})
        state._worker_busy.set()
        cancel = threading.Event()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, lambda: operation(cancel.is_set))

        def release(done):
            try:
                done.exception()  # consume exceptions after a timeout/disconnect
            finally:
                try:
                    if cancel.is_set() and cleanup:
                        cleanup()
                finally:
                    state._worker_busy.clear()
                    state._worker_sem.release()

        future.add_done_callback(release)
        try:
            return await asyncio.wait_for(asyncio.shield(future), settings.video_timeout_s)
        except asyncio.TimeoutError:
            cancel.set()
            raise HTTPException(504, "Video processing timed out. Try a shorter recording.")
        except asyncio.CancelledError:
            cancel.set()
            raise
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        except Exception:
            state._LOG.exception("video processing failed")
            raise HTTPException(500, "Video processing failed. Try another recording.")

    @app.post("/api/video-scan", dependencies=[Depends(require_auth)])
    async def scan(request: Request, file: UploadFile = File(...),
                   layout: str = Form("auto"),
                   clean_fingers: str = Form("0")):
        rate_limit(request)
        if layout not in {"auto", "single", "spread"}:
            raise HTTPException(400, "Choose auto, single, or spread layout.")
        extension = Path(file.filename or "").suffix.lower()
        if extension not in VIDEO_EXTENSIONS:
            raise HTTPException(400, "Upload an MP4, MOV, M4V, AVI, or WebM video.")
        allowed, retry = state.quota.check()
        if not allowed:
            raise HTTPException(429, "The daily run budget is used up.",
                                headers={"Retry-After": str(retry)})
        run_id = new_run_id()
        run_dir = state.store.create(run_id)
        upload = str(Path(run_dir) / ".video-upload")
        deferred_cleanup = False
        try:
            size = 0
            with open(upload, "wb") as f:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.video_upload_mb * 1024 * 1024:
                        raise HTTPException(413, f"Video exceeds {settings.video_upload_mb} MB.")
                    f.write(chunk)
            if size == 0:
                raise HTTPException(400, "The uploaded video is empty.")
            # Check container magic as well as extension; decoding validates the
            # stream. Keep the decoder local (only a generated filesystem path).
            with open(upload, "rb") as f:
                head = f.read(64)
            valid = ((extension in {".mp4", ".mov", ".m4v"} and head[4:8] == b"ftyp")
                     or (extension == ".avi" and head[:4] == b"RIFF" and head[8:12] == b"AVI ")
                     or (extension == ".webm" and head[:4] == b"\x1a\x45\xdf\xa3"))
            if not valid:
                raise HTTPException(400, "Video container does not match its filename.")
            try:
                capture = await work(lambda cancel: extract_video_pages(
                    upload, run_dir, VideoOptions(layout=layout,
                        max_pages=settings.video_max_pages,
                        max_seconds=settings.video_max_seconds,
                        max_megapixels=settings.max_image_megapixels,
                        clean_fingers=clean_fingers == "1"), cancel=cancel),
                    cleanup=lambda: shutil.rmtree(run_dir, ignore_errors=True))
            except HTTPException as exc:
                deferred_cleanup = exc.status_code == 504
                raise
            except asyncio.CancelledError:
                deferred_cleanup = True
                raise
            count = len(capture["pages"])
            for budget, units in ((client_budget, count), (state.page_quota, count)):
                allowed, retry = (budget.check(client_key(request), units)
                                  if budget is client_budget else budget.check(units))
                if not allowed:
                    raise HTTPException(429, "The daily video page budget is used up.",
                                        headers={"Retry-After": str(retry)})
            state.store.write_manifest(run_id, {"kind": "video", "pages": count})
            return {"run_id": run_id, "pages": [
                {**page, "preview": f"/api/runs/{run_id}/video-pages/{page['id']}"}
                for page in capture["pages"]], "warnings": capture["warnings"],
                "capped": capture["capped"], "expires_in": settings.run_ttl_seconds}
        except BaseException:
            if not deferred_cleanup:
                shutil.rmtree(run_dir, ignore_errors=True)
            raise
        finally:
            await file.close()
            if not deferred_cleanup and os.path.exists(upload):
                os.remove(upload)

    @app.get("/api/runs/{run_id}/video-pages/{page_id}", dependencies=[Depends(require_auth)])
    async def preview(run_id: str, page_id: int):
        run_dir, capture = load_capture(run_id)
        page = next((p for p in capture["pages"] if p["id"] == page_id), None)
        if page is None:
            raise HTTPException(404, "No such captured page.")
        path = Path(run_dir) / page["file"]
        if not path.is_file():
            raise HTTPException(404, "Captured page has expired.")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/runs/{run_id}/video-export", dependencies=[Depends(require_auth)])
    async def export(request: Request, run_id: str, body: dict = Body(...)):
        rate_limit(request)
        run_dir, capture = load_capture(run_id)
        ids = body.get("pages")
        if (not isinstance(ids, list) or not ids or len(ids) > settings.video_max_pages
                or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids)):
            raise HTTPException(400, "Select a nonempty list of unique page IDs in export order.")
        known = {p["id"]: p for p in capture["pages"]}
        if any(i not in known for i in ids):
            raise HTTPException(400, "Selection contains an unknown page.")
        searchable = body.get("searchable", False)
        if type(searchable) is not bool:
            raise HTTPException(400, "searchable must be true or false.")
        pdf_kind = body.get("pdf") or ("searchable" if searchable else "clean")
        if pdf_kind not in {"clean", "searchable", "digital"}:
            raise HTTPException(400, "Choose pdf: clean, searchable, or digital.")
        digital = pdf_kind == "digital"
        searchable = searchable or pdf_kind == "searchable"
        lang = body.get("lang", "en")
        if not isinstance(lang, str) or lang not in {"en", "ne", "hi"}:
            raise HTTPException(400, "Choose English, Nepali, or Hindi.")
        # OCR modes consume the expensive per-client OCR allowance. Image-PDF
        # assembly uses the already charged, separate capture-page budget.
        if searchable or digital:
            allowed, retry = state.client_pages.check(client_key(request), len(ids))
            if not allowed:
                raise HTTPException(429, "OCR page budget exceeded. Export an image PDF or raise the local OCR allowance.",
                                    headers={"Retry-After": str(retry)})
            allowed, retry = state.page_quota.check(len(ids))
            if not allowed:
                raise HTTPException(429, "The daily processing page budget is used up.",
                                    headers={"Retry-After": str(retry)})
        selected = [known[i] for i in ids]
        await work(lambda cancel: export_video_pdf(
            run_dir, selected, searchable=searchable, digital=digital,
            lang=None if lang == "en" else lang, cancel=cancel))
        return {"run_id": run_id, "pages_exported": len(selected),
                "searchable": searchable or digital, "digital": digital,
                "pdf": f"/api/runs/{run_id}/files/book.pdf"}
