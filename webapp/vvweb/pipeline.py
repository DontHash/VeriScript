"""Run the document pipeline for one uploaded page (or a whole PDF).

The web studio's document entry point: canonical file names, a curated meta
block, the review queue, a flags summary, and the transcript. PDFs default to
the first page; with ``all_pages`` every page is processed (capped) and a
combined PDF/TXT/MD is written next to the page-1 artifacts.
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, Iterator, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys  # noqa: E402

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

#: PDF pages processed per run when ``all_pages`` is on (keeps the single
#: heavy worker bounded on a shared demo; the response reports what was
#: processed). ``0`` means no cap: the desktop app sets VERISCRIPT_WEB_PAGE_CAP=0.
from .config import settings  # noqa: E402

PAGE_CAP = settings.page_cap

CANONICAL = {
    "restored.png": "image/png",
    "overlay.png": "image/png",
    "searchable.pdf": "application/pdf",
    "transcript.txt": "text/plain; charset=utf-8",
    "transcript.md": "text/markdown; charset=utf-8",
    "combined.pdf": "application/pdf",
    "combined.txt": "text/plain; charset=utf-8",
    "combined.md": "text/markdown; charset=utf-8",
    "ocr.json": "application/json",
}


class PipelineError(RuntimeError):
    pass


def _is_pdf(path: str, kind: Optional[str]) -> bool:
    return kind == "pdf" if kind else path.lower().endswith(".pdf")


def count_pdf_pages(path: str) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


def pages_to_process(path: str, kind: Optional[str], all_pages: bool,
                     page_cap: Optional[int] = None) -> int:
    """How many pages a run will read (quota units and the progress total)."""
    if kind == "bundle":
        from veriscript.document.bundle import open_bundle
        n = len(open_bundle(path).pages)
        cap = PAGE_CAP if page_cap is None else page_cap
        return min(n, cap) if cap else n  # a bundle is always the whole document
    if not _is_pdf(path, kind) or not all_pages:
        return 1
    cap = PAGE_CAP if page_cap is None else page_cap
    try:
        n = max(1, count_pdf_pages(path))
    except Exception:  # noqa: BLE001 - validation reports unreadable files
        return max(1, cap)
    return min(n, cap) if cap else n


def _iter_pages(path: str, kind: Optional[str], all_pages: bool,
                page_cap: Optional[int] = None
                ) -> Iterator[Tuple[int, "object"]]:
    """Yield (page_index, BGR page) one at a time.

    `kind` ("image" | "pdf", from the upload validator) wins over the file
    extension: streamed uploads land on disk without one. PDFs default to the
    first page; ``all_pages`` expands to every page up to the cap (0 = no
    cap). Pages are rendered lazily so a long PDF never sits in memory.
    """
    if kind == "bundle":
        from veriscript.document import bundle as doc_bundle
        cap = PAGE_CAP if page_cap is None else page_cap
        try:
            yield from doc_bundle.iter_images(doc_bundle.open_bundle(path), limit=cap or None)
        except doc_bundle.BundleError as exc:
            raise PipelineError(str(exc)) from None
        return
    if _is_pdf(path, kind):
        from veriscript.core import data as doc_data
        cap = PAGE_CAP if page_cap is None else page_cap
        limit = (cap or None) if all_pages else 1
        n = 0
        for idx, img_bgr, _gt in doc_data.pdf_to_pages(path, dpi=200):
            yield idx, img_bgr
            n += 1
            if limit is not None and n >= limit:
                break
        if n == 0:
            raise PipelineError("Could not read that PDF.")
        return

    from veriscript.document.orientation import load_image_bgr
    img_bgr = load_image_bgr(path)
    if img_bgr is None:
        raise PipelineError("Could not read that image.")
    yield 0, img_bgr


def _load_pages(path: str, kind: Optional[str],
                all_pages: bool) -> Tuple[List[Tuple[int, "object"]], str]:
    """Eager form of `_iter_pages` (kept for callers that want a list)."""
    return list(_iter_pages(path, kind, all_pages)), (
        "pdf" if _is_pdf(path, kind) else "image")


def _copy_or_text(run_dir: str, name: str, src: Optional[str],
                  fallback_text: Optional[str] = None) -> Optional[str]:
    """Move a pipeline output to its canonical name; returns the final path."""
    dst = os.path.join(run_dir, name)
    if src and os.path.isfile(src):
        if os.path.abspath(src) != os.path.abspath(dst):
            os.replace(src, dst)
        return dst
    if fallback_text is not None:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(fallback_text)
        return dst
    return None


KEY_MAP = {
    "restored.png": "restored",
    "overlay.png": "overlay",
    "searchable.pdf": "pdf",
    "transcript.txt": "txt",
    "transcript.md": "md",
    "ocr.json": "json",
    "corrected.pdf": "corrected_pdf",
    "corrected.txt": "corrected_txt",
    "corrected.md": "corrected_md",
    "corrected.json": "corrected_json",
    "corrections.json": "corrections_json",
    "corrections.zip": "corrections_zip",
    "combined.pdf": "combined_pdf",
    "combined.txt": "combined_txt",
    "combined.md": "combined_md",
    "tables.xlsx": "tables_xlsx",
    "tables.csv": "tables_csv",
    "phone_reading.json": "phone_reading",
}


def collect_run_summary(run_dir: str, run_id: str) -> Dict:
    """Review queue, flags, transcript and file links from the run directory.

    The written `ocr.json` is the single source for the queue; `files` lists
    every canonical artifact that exists, including the corrected ones after
    the correction loop has run (docs/CORRECTIONS.md).
    """
    review: List[Dict] = []
    flags_summary: Dict[str, int] = {}
    n_tokens = 0
    # After the correction loop has run, the corrected record is the truth
    # (the originals stay downloadable under their own names).
    ocr_name = ("corrected.json"
                if os.path.isfile(os.path.join(run_dir, "corrected.json"))
                else "ocr.json")
    try:
        with open(os.path.join(run_dir, ocr_name), encoding="utf-8") as f:
            payload = json.load(f)
        n_tokens = len(payload.get("tokens", []))
        for item in payload.get("review", []):
            entry = {
                "index": item.get("index"),
                "text": item.get("text", ""),
                "alt_text": item.get("alt_text"),
                "flags": item.get("flags", []),
                "conf": item.get("conf"),
                "risk": item.get("risk"),
                "bbox": item.get("bbox"),
                "suggestions": item.get("suggestions") or [],
                "section": item.get("section"),
            }
            review.append(entry)
            for flag in entry["flags"]:
                flags_summary[flag] = flags_summary.get(flag, 0) + 1
    except (OSError, ValueError):
        pass

    try:  # track D2: local correction memory suggestions (best-effort)
        from veriscript.document import memory as correction_memory
        correction_memory.augment_review(review)
    except Exception:  # noqa: BLE001
        pass

    # B4: what the phone's user corrected or confirmed, beside the desktop's
    # reading of the same words (never copied into it).
    phone_path = os.path.join(run_dir, "phone_reading.json")
    if review and os.path.isfile(phone_path):
        try:
            from veriscript.document.bundle import augment_review_with_phone
            with open(phone_path, encoding="utf-8") as f:
                augment_review_with_phone(review, json.load(f))
        except (OSError, ValueError):
            pass

    transcript = ""
    transcript_name = ("corrected.txt"
                       if os.path.isfile(os.path.join(run_dir, "corrected.txt"))
                       else "transcript.txt")
    try:
        with open(os.path.join(run_dir, transcript_name),
                  encoding="utf-8") as f:
            transcript = f.read()
    except OSError:
        pass

    files = {key: f"/api/runs/{run_id}/files/{name}"
             for name, key in KEY_MAP.items()
             if os.path.isfile(os.path.join(run_dir, name))}
    return {"review": review, "flags_summary": flags_summary,
            "transcript": transcript, "files": files, "n_tokens": n_tokens}


def process_page(upload_path: str, run_dir: str, run_id: str, *,
                 lang: Optional[str], deskew: bool,
                 kind: Optional[str] = None, ocr: Optional[str] = None,
                 make_overlay: bool = True, make_pdf: bool = True,
                 make_txt: bool = True, make_md: bool = True,
                 all_pages: bool = False,
                 auto_rotate: bool = True,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 check: Optional[Callable[[], None]] = None,
                 page_cap: Optional[int] = None,
                 use_text_layer: bool = True,
                 pdf_size: str = "standard",
                 flatten: bool = False,
                 title: Optional[str] = None) -> Dict:
    """Run restore+OCR and write canonical artifacts into run_dir.

    With `use_text_layer` (default), born-digital PDF pages whose own text
    passes the checks in `veriscript.document.pdf_text` keep that text and
    their original page; only the others are OCR'd.

    `progress(page, pages, stage)` is called before each page; `check()` is
    called between pages and may raise to stop the run (jobs.JobCancelled).
    Pages are read one at a time: only page 1's result and every page's OCR
    tokens are kept, so long PDFs do not pile up page images in memory.
    """
    import cv2

    from veriscript.document.export import (SearchablePdfWriter,
                                 write_combined_transcript_md)
    from veriscript.document import pdf_text
    from veriscript.document import tables as doc_tables
    from veriscript.document.pipeline import run_document_pipeline

    started = time.time()
    phone = None
    if kind == "bundle":
        # Phone -> desktop (B4): the phone's readings and corrections are kept
        # next to the desktop's own reading; the desktop never copies text from them.
        from veriscript.document.bundle import BundleError, open_bundle
        try:
            phone = open_bundle(upload_path).phone_reading()
        except BundleError as exc:
            raise PipelineError(str(exc)) from None
        title = phone["title"] or title
        with open(os.path.join(run_dir, "phone_reading.json"), "w", encoding="utf-8") as f:
            json.dump(phone, f, ensure_ascii=False, indent=1)
    else:
        kind = "pdf" if _is_pdf(upload_path, kind) else "image"
    total = pages_to_process(upload_path, kind, all_pages, page_cap)
    backend = None if ocr in (None, "auto") else ocr
    # CLI parity: image pages get the line reader under the measured `auto`
    # gate (running text + aged paper only); PDF pages keep the engine
    # reading, mirroring the CLI's deliberate auto->off mapping for PDFs.
    deva_lines = "auto" if kind in ("image", "bundle") else "off"

    stem = f"page_{run_id[:8]}"
    cap = PAGE_CAP if page_cap is None else page_cap
    layers = (pdf_text.check_pages(upload_path, range(total), lang)
              if kind == "pdf" and use_text_layer else {})
    kept = {i for i, layer in layers.items() if layer.usable}
    # With any original page kept, the combined PDF is assembled from the
    # per-page PDFs (originals + OCR'd scans) instead of re-drawn.
    merge = bool(kept) and total > 1
    page_pdfs: List = []
    page_tables = []      # tables found on any page (F2)
    first = None          # page 1's DocumentResult (its image is restored.png)
    ocr_results = []      # every page's OCRResult, in order
    combined = None       # SearchablePdfWriter once a second page exists
    combined_path = os.path.join(run_dir, "combined.pdf")
    try:
        for n, (idx, img_bgr) in enumerate(
                _iter_pages(upload_path, kind, all_pages, page_cap), start=1):
            if check:
                check()
            if progress:
                progress(n, total, f"Reading page {n} of {total}"
                         if total > 1 else "Reading the page")
            page_stem = stem if n == 1 else f"{stem}_p{idx:03d}"
            if idx in kept:
                page_result = pdf_text.document_result(
                    layers[idx], img_bgr, upload_path, out_dir=run_dir,
                    stem=page_stem, make_pdf=make_pdf or merge,
                    make_overlay=make_overlay, make_txt=make_txt,
                    make_json=True, make_md=make_md)
            else:
                page_result = run_document_pipeline(
                    img_bgr, backend=backend, deskew=deskew, lang=lang,
                    auto_rotate=auto_rotate, deva_lines=deva_lines,
                    out_dir=run_dir, stem=page_stem,
                    make_pdf=make_pdf or merge, make_overlay=make_overlay,
                    make_txt=make_txt, make_json=True, make_md=make_md,
                    pdf_size=pdf_size, title=title,
                    # F1: read the photo and the flattened page, keep the
                    # more confident reading (opt-in, as in the CLI).
                    flatten="pick" if flatten else False)
            del img_bgr
            if merge:  # originals straight from the upload (shared fonts)
                page_pdfs.append((upload_path, idx) if idx in kept
                                 else page_result.outputs["pdf"])
            if n == 1:
                first = page_result
            elif not merge:
                if combined is None:
                    combined = SearchablePdfWriter(combined_path, title=title or stem,
                                                   size=pdf_size)
                    combined.add_page(first.display_bgr, first.ocr.tokens, 200)
                combined.add_page(page_result.display_bgr,
                                  page_result.ocr.tokens, 200)
            ocr_results.append(page_result.ocr)
            if page_result.ocr.backend != "pdf-text-layer":
                page_tables.extend(doc_tables.extract_tables(page_result.ocr.tokens, page=n))
        if check:
            check()
        if progress and total > 1:
            progress(total, total, "Writing the combined files")
        if combined is not None:
            combined.close()
            combined = None
        if merge and len(page_pdfs) > 1:
            pdf_text.merge_pdfs(combined_path, page_pdfs)
    finally:
        if combined is not None:  # stopped mid-run: drop the partial PDF
            combined.discard()

    if first is None:
        raise PipelineError("Could not read that file.")
    result = first
    n_pages = len(ocr_results)

    # Canonical page-1 artifacts -------------------------------------------
    cv2.imwrite(os.path.join(run_dir, "restored.png"), result.display_bgr)
    outputs = getattr(result, "outputs", {}) or {}
    files: Dict[str, Optional[str]] = {
        "overlay.png": _copy_or_text(run_dir, "overlay.png",
                                     outputs.get("overlay")),
        "searchable.pdf": _copy_or_text(run_dir, "searchable.pdf",
                                        outputs.get("pdf")),
        "transcript.txt": _copy_or_text(
            run_dir, "transcript.txt", outputs.get("txt"),
            fallback_text=(result.ocr.text if getattr(result, "ocr", None) else "")
            if make_txt else None),
        "transcript.md": _copy_or_text(run_dir, "transcript.md",
                                       outputs.get("md")),
        "ocr.json": _copy_or_text(run_dir, "ocr.json", outputs.get("json")),
        "restored.png": os.path.join(run_dir, "restored.png"),
    }

    # Multi-page combined outputs ------------------------------------------
    if n_pages > 1:
        with open(os.path.join(run_dir, "combined.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n\n".join(r.text for r in ocr_results) + "\n")
        if make_md:
            write_combined_transcript_md(
                os.path.join(run_dir, "combined.md"), ocr_results, title=title or stem)
        files["combined.pdf"] = combined_path
        files["combined.txt"] = os.path.join(run_dir, "combined.txt")
        if make_md:
            files["combined.md"] = os.path.join(run_dir, "combined.md")

    # Tables -> spreadsheet with the uncertain cells marked (F2) ------------
    if page_tables:
        doc_tables.write_xlsx(os.path.join(run_dir, "tables.xlsx"), page_tables)
        doc_tables.write_csv(os.path.join(run_dir, "tables.csv"), page_tables)

    # Review queue + summary from the written ocr.json (single source) -----
    summary = collect_run_summary(run_dir, run_id)

    meta_src = dict(getattr(result, "meta", {}) or {})
    meta = {
        "seconds": round(float(meta_src.get("seconds", time.time() - started)), 2),
        "backend": meta_src.get("backend", backend or "rapidocr"),
        "primary_stream": meta_src.get("primary_stream"),
        "skew_angle": meta_src.get("skew_angle", 0.0),
        "resized": bool(meta_src.get("resized", False)),
        "n_tokens": summary["n_tokens"],
        "flagged": len(summary["review"]),
        "digit_conflicts": summary["flags_summary"].get("digit_conflict", 0),
        "lang": lang or "default",
        "input_kind": kind,
        "deskew": deskew,
        "auto_rotate": auto_rotate,
        "all_pages": all_pages,
        "pages_processed": n_pages,
        "pages_from_pdf_text": len(kept),
        "pdf_size": pdf_size,
        "tables": len(page_tables),
        "from_phone": ({"pages": len(phone["pages"]), "corrected_lines": phone["corrected_lines"],
                        "confirmed_lines": phone["confirmed_lines"]} if phone else None),
        "text_layer": [{"page": i + 1, "kept": layer.usable, "reason": layer.reason}
                       for i, layer in sorted(layers.items())][:200],
        "pages_capped": bool(all_pages and cap and n_pages >= cap),
        "page_cap": cap,
    }

    return {
        "run_id": run_id,
        "meta": meta,
        "flags_summary": summary["flags_summary"],
        "review": summary["review"],
        "transcript": summary["transcript"],
        "status_line": getattr(result, "status_line", ""),
        "files": summary["files"],
        "title": (phone or {}).get("title") or None,
    }
