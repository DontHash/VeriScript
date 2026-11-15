"""Document library for the desktop app (docs/TECH_UPGRADE_PLAN.md, B1).

The desktop keeps every run (TTL 0) in the user's app-data folder. These
routes turn those runs into a library: list with text search, reopen in the
studio, rename and delete.

Local mode only. On a shared demo the runs belong to different visitors, so
every route answers 404 there and nothing can be listed or touched.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List

from fastapi import Body, Depends, HTTPException, status

_TEXT_FILES = ("corrected.txt", "combined.txt", "transcript.txt")


def register_library_routes(app, state) -> None:
    store = lambda: state.store  # noqa: E731 - tests swap the module's store

    def local_only() -> None:
        if state.settings.mode != "local":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="The library is part of the desktop app.")

    deps = [Depends(state.require_auth), Depends(local_only)]

    def _documents() -> List[Dict[str, Any]]:
        root = store().root
        out = []
        try:
            entries = os.listdir(root)
        except OSError:
            return out
        for run_id in entries:
            if not state.RUN_ID_RE.match(run_id):
                continue
            manifest = store().read_manifest(run_id)
            meta = (manifest or {}).get("meta") or {}
            if not manifest or "input_kind" not in meta:
                continue  # unfinished uploads and video captures
            run_dir = store().run_dir(run_id)
            try:
                created = int(manifest.get("created") or os.path.getmtime(run_dir))
            except OSError:
                continue
            out.append({
                "run_id": run_id,
                "title": manifest.get("title") or "Untitled",
                "created": created,
                "pages": meta.get("pages_processed", 1),
                "flagged": meta.get("flagged", 0),
                "input_kind": meta.get("input_kind"),
                "lang": meta.get("lang"),
                "corrected": os.path.isfile(os.path.join(run_dir, "corrected.json")),
            })
        out.sort(key=lambda d: d["created"], reverse=True)
        return out

    def _text(run_id: str) -> str:
        run_dir = store().run_dir(run_id)
        for name in _TEXT_FILES:
            try:
                with open(os.path.join(run_dir, name), encoding="utf-8") as f:
                    return f.read()
            except OSError:
                continue
        return ""

    def _require(run_id: str) -> Dict[str, Any]:
        if not state.RUN_ID_RE.match(run_id or ""):
            raise HTTPException(status_code=404, detail="No such document.")
        manifest = store().read_manifest(run_id)
        if manifest is None or not os.path.isdir(store().run_dir(run_id)):
            raise HTTPException(status_code=404, detail="No such document.")
        return manifest

    @app.get("/api/library", dependencies=deps)
    async def library(q: str = "") -> Dict[str, Any]:
        """Documents, newest first. `q` matches every word against the title
        and the recognised (or corrected) text, case-insensitively."""
        docs = _documents()
        terms = [t for t in q.lower().split() if t]
        if terms:
            docs = [d for d in docs
                    if all(t in (d["title"] + "\n" + _text(d["run_id"])).lower()
                           for t in terms)]
        return {"documents": docs, "query": q}

    @app.get("/api/runs/{run_id}/summary", dependencies=deps)
    async def summary(run_id: str) -> Dict[str, Any]:
        """Everything the studio needs to show a kept result again."""
        manifest = _require(run_id)
        run_dir = store().run_dir(run_id)
        data = state.collect_run_summary(run_dir, run_id)
        return {"run_id": run_id, "meta": manifest.get("meta") or {},
                "flags_summary": data["flags_summary"], "review": data["review"],
                "transcript": data["transcript"],
                "status_line": manifest.get("status_line", ""),
                "files": data["files"], "expires_in": state.settings.run_ttl_seconds,
                "title": manifest.get("title") or "Untitled"}

    @app.patch("/api/runs/{run_id}", dependencies=deps)
    async def rename(run_id: str, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
        manifest = _require(run_id)
        title = " ".join(str((body or {}).get("title") or "").split())[:120]
        if not title:
            raise HTTPException(status_code=400, detail="A document needs a name.")
        manifest["title"] = title
        path = os.path.join(store().run_dir(run_id), "manifest.json")
        part = path + ".part"
        with open(part, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        os.replace(part, path)
        return {"run_id": run_id, "title": title}

    @app.delete("/api/runs/{run_id}", dependencies=deps)
    async def delete(run_id: str) -> Dict[str, Any]:
        _require(run_id)
        job = state.jobs.get(run_id)
        if job is not None and job.status in ("queued", "running"):
            raise HTTPException(status_code=409,
                                detail="This document is still being read. Cancel it first.")
        shutil.rmtree(store().run_dir(run_id), ignore_errors=True)
        return {"run_id": run_id, "deleted": True}
