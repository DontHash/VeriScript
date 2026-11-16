# Technical upgrade plan: scan, PDF, OCR

Planning date: 2026-11-14. Scope: the Android app (`mobile/`), the desktop
app (`desktop/` + `webapp/`) and the shared Python pipeline (`veriscript/`).
The UI overhaul (audit Phases 0–5) is done. This plan covers what is under
the UI: capture, image processing, OCR, PDF output, the document library and
reliability.

It builds on, and does not replace, [ROADMAP.md](ROADMAP.md) (accuracy and
the correction loop) and
[mobile/docs/SCAN_CAMERA_PLAN.md](../mobile/docs/SCAN_CAMERA_PLAN.md) (the
native camera design). Same rules as the rest of the repo: every default
change ships through a written gate on a frozen set, and nothing leaves the
device.

## Status (2026-11-16)

Done and measured (details in the results tables in §3):
A1–A6 reliability, B1 library, B2 batch input, C1 resolution, D1
orientation, D2 independent digit checks, D4 phone reading order, E1 text
alignment, E2 born-digital PDFs, E3 size presets (desktop and phone), E4
PDF/A-2b archive PDFs, F2 tables to spreadsheet, B4 phone-to-desktop
bundles (first version: file transfer), C3 blur and glare warnings at
capture, plus look-alike digit flags on the phone. F1 curved-page flattening is available as an option.

Open, and why:

| Item | Blocked on |
|---|---|
| C2 scan camera, C5 device acceptance | a physical phone (stand-in measures in C5) |
| F4 real phone-photo set | consented real Nepali pages (no public set exists; DocUNet covers English photos) |
| B4 Wi-Fi pairing (second step) | the first version (file transfer) is done; pairing needs two real devices on one network |
| B3 "Open with VeriScript" | changes installer file associations; needs the desktop GUI to verify |
| F1 curved-page flattening | opt-in (`--flatten`): reads the photo and the flattened page and keeps the more confident reading; on 128 real photos CER 0.47 → 0.32 with almost none of the damage of always flattening. On by default needs a Nepali photo set (F4) and a decision on the doubled reading time; not yet in the studio or the phone |
| D3 engine default per language | a real Nepali photo corpus (F4) to decide on |
| RapidOCR speed on the phone | measuring on a phone, not the emulator |
| G release signing | the owner's keystore and code-signing certificate |

---

## 1. Where we stand

### 1.1 Scorecard

| Area | Android | Desktop | Verdict |
|---|---|---|---|
| **Capture** | Flutter `camera` plugin at `ResolutionPreset.max`; black-frame check; capability probe only (Phase 0). No live edge outline, auto-capture, glare or blur check. | Upload only (no scanner/camera input). | **Behind** every mainstream scanner. |
| **Image cleanup** | OpenCV quad detection, warp, deskew, flat-field, denoise, sharpen, 2× Lanczos. Images loaded at **≤2500 px**. | Restore stream with quality gates; mixed-page router (opt-in). | Fine for flat pages. No curved-page dewarp, finger or glare removal. |
| **OCR accuracy** | ML Kit by default; RapidOCR (PP-OCRv5 ONNX) as a preview. **No layout or reading-order analysis.** | RapidOCR + layout + reading order + Devanagari line reader + calibration. Hard-10 CER 0.255 vs raw 0.530. | Desktop is strong for Devanagari. Mobile is a separate, weaker engine. |
| **OCR speed** | Orientation runs **full OCR up to 4×** per page (0/90/180/270). Up to 80 sequential digit re-reads. | ~7.3 s/page on an RTX 2050 class machine. | Mobile pays for orientation it could get almost for free. |
| **Digit honesty** | Same-engine re-read of an enlarged crop: not independent. | 2× re-pass, validators, digit-first queue, optional bodhan verifier. | **Our edge**, but only on desktop. |
| **PDF output** | Built in memory with the Dart `pdf` package. Invisible text is line-level, `opacity: 0`, not stretched to the box. No size presets, no PDF/A. | reportlab, text render mode 3, token-level, but glyph runs are not scaled to box width. Born-digital PDFs are **rasterised and re-OCRed**. | Searchable, but selection is misaligned, files are not size-tuned, and digital PDFs get worse. |
| **Document management** | Library with folders, search, drafts, undo. One JSON file per document, absolute paths, no schema version, full scan of all JSON for search. | **None.** Runs live in a folder for 7 days, then are deleted. One file at a time, **PDFs capped at 10 pages**. | Desktop is a demo tool, not an app. |
| **Reliability** | All native work on one Activity-bound thread; no background service. Large exports build the whole PDF in RAM. | One synchronous HTTP request per document (see §1.2). | Long jobs are fragile on both. |
| **Sharing in/out** | Share sheet out; no "Share to VeriScript" intent; exports stay in app-private storage. | Browser download to Downloads; no file associations; no save dialog. | Friction at both ends of every job. |
| **Tests and evidence** | Unit + emulator integration; **no physical-device acceptance** yet. | ~338 pytest tests, frozen sets, CI. | Strong desktop evidence; phone claims unproven. |

### 1.2 Defects found in this audit (fix first)

These are bugs, not feature gaps. Each one was read in code.

1. **The server freezes while a job waits.** `webapp/vvweb/api.py:369`
   calls `_worker_sem.acquire(timeout=settings.queue_wait_s)`, a blocking
   call, inside `async def restore`. The event loop stops for up to
   `queue_wait_s`, which the desktop sets to **1800 s**
   (`desktop/src-tauri/src/lib.rs:144`). Health checks, file downloads and
   any second request hang during that time.
2. **Timeouts and cancel do not stop the work.** `asyncio.wait_for` around
   `run_in_executor` (`api.py:379`) abandons the future but the thread keeps
   running. The `finally` block then releases the semaphore and deletes
   `run_dir`, so the next job can start **while the old one is still
   running** (breaking the single-worker rule that exists because concurrent
   OCR init crashed natively), and the old thread writes into a deleted
   folder. The studio's Cancel (`studio-state.ts:157`) only aborts the HTTP
   request, which has the same effect.
3. **Desktop runs expire.** `VERISCRIPT_WEB_TTL_MINUTES=10080` deletes every
   result after 7 days. Users of a desktop app expect their documents to
   stay.
4. **Desktop PDFs stop at 10 pages.** `PAGE_CAP = 10`
   (`webapp/vvweb/pipeline.py:24`) applies in local mode too.
5. **Mobile batch OCR dies in the background.** Native work runs on
   `Executors.newSingleThreadExecutor()` in `MainActivity`, with no
   foreground service or WorkManager. Android can kill a 150-page batch when
   the user switches apps.
6. **Mobile PDF export is O(document) in memory.** `exports.dart` adds every
   page image to one `pw.Document` and calls `pdf.save()` once. At the
   documented 150-page limit with 12 MP pages this risks OOM on the 4 GB
   target phones.
7. **Mobile document paths are absolute.** `document.json` stores full
   paths. A restore from backup or a storage-path change breaks every
   document. There is also no `schemaVersion` for future migrations.

---

## 2. The competitive bar (Nov 2026)

What a user compares us to, and what each leader actually ships:

| Capability | Leaders | Us |
|---|---|---|
| Live edge outline + auto-capture + manual shutter | Adobe Scan, Google Drive, Apple, Samsung, CamScanner | Planned (SCAN_CAMERA_PLAN Phase 1+) |
| Batch capture, auto-split into documents, best-frame swap, duplicate detection | Google Drive (June 2026 update; reportedly needs 8 GB RAM) | Book video only |
| Curved page / book flattening, finger removal | vFlat, CamScanner, Samsung | Not implemented |
| Searchable PDF via OCR | All; Adobe now limits free OCR to **5 pages per scan** (Jan 2026); Genius Scan charges for it | Free, unlimited, offline |
| Export to Word/Excel/PowerPoint | Adobe (cloud), CamScanner | DOCX (plain text), no tables |
| PDF compression / size presets | Adobe, Genius Scan, CamScanner | None |
| AI Q&A / summaries over scans | Adobe AI Assistant, Drive Gemini (cloud, paid) | None (non-goal unless on-device) |
| Fully offline, no account | Genius Scan (paid OCR), Samsung | **Yes, everything** |
| Devanagari accuracy with published error rates | Nobody | **Yes** |
| Number review with alternative readings | Nobody | **Yes** (desktop; mobile partial) |

Microsoft Lens was removed from Google Play in February 2026, so its users
are looking for a replacement.

**Where we can win:** "the scanner you can trust with numbers, that never
uploads, and reads Nepali properly." Cloud scanners cannot follow us onto
privacy. Generic scanners do not do Devanagari digit honesty. What blocks us
today is **table stakes**: capture quality, book flattening, PDF quality and
a desktop that keeps documents.

---

## 3. Upgrade plan

Six workstreams, ordered by dependency and user pain. Efforts are for one
engineer; "gate" is the adopt-if rule written before the work starts.

### Phase A: Reliability foundation (weeks 1–3)

Nothing else is worth building on jobs that freeze, leak or vanish.

**Status 2026-11-14: implemented, see "Phase A results" below.** Two items
were narrowed on purpose: A1 uses one in-process worker thread with
cooperative cancel (not a separate process), and the A5 SQLite index moves
to B1, where the library model is shared with the desktop.

**A1. Server job model (desktop/web).**
- Replace synchronous `/api/restore` with jobs: `POST /api/jobs` returns at
  once; `GET /api/jobs/{id}` (or an SSE stream) reports per-page progress;
  `DELETE /api/jobs/{id}` cancels.
- One worker **process** (not thread) that owns the OCR engine. Cancelling
  or timing out terminates or signals that process, so it actually stops.
  This also isolates native OCR crashes from the server.
- Pipeline checks a cancel flag between pages and between stages.
- No blocking calls on the event loop (fixes §1.2 #1 and #2).
- *Gate:* a test that cancels a 30-page job mid-run, then starts another,
  and asserts one worker, no writes to the deleted run, and `/api/health`
  answering in <200 ms throughout.

**A2. Remove desktop page cap and expiry.** Local mode: no `PAGE_CAP`;
runs move into the library (B1) instead of a TTL folder. Keep the cap in
demo mode.

**A3. Mobile background processing.**
- Move OCR, enhancement and export into a WorkManager job with a foreground
  notification ("Reading page 12 of 80"). Resume from the last committed
  page after process death (drafts already save per page).
- Use a small thread pool for independent per-page image work; keep one
  OCR session per engine.
- *Gate:* emulator test kills the app at page 5 of 20; reopening completes
  the batch with no duplicated or lost pages.

**A4. Streaming PDF export on mobile.** Write pages incrementally (native
`PdfDocument` + a text-layer writer, or a page-by-page writer) so peak
memory is one page. *Gate:* 150-page export under 300 MB peak RSS on the
x86_64 emulator, measured.

**A5. Storage hardening (mobile).** Paths relative to the document folder;
`schemaVersion` with migrations; a SQLite index (`sqflite`, FTS5) for
titles, folders and recognised text so search does not load every JSON.
JSON stays the source of truth; the index is rebuildable.

**A6. Local diagnostics.** A rotating local log on both apps and a "Copy
diagnostics" button (versions, device, timings, last errors). No upload.
This is how field bugs become reproducible without telemetry.

### Phase B: Desktop becomes an app (weeks 3–6)

**B1. Persistent library.** Documents (not runs) stored in app data with a
SQLite index: title, folder, pages, OCR, corrections, exports. The mobile
library model is the reference; share the JSON schema where possible.

**B2. Batch input.** Drop many files or a folder; a queue with per-file
status; multi-page PDFs without a cap. Optional "watch folder" for
scanner output later.

**B3. Native OS integration.** Native save dialog, "Open with VeriScript"
via a Tauri command that hands the shell-chosen file to the server (no
read-any-path endpoint), recent documents.

**B4. Phone → desktop handoff, offline.** Export a document bundle (zip with
images + OCR JSON + corrections) from the phone and open it on desktop for
the full pipeline: layout, digit queue, verifier. First version: file
transfer through any channel. Later: local Wi-Fi pairing by QR code, LAN
only, no relay. No competitor offers privacy-preserving phone-to-desktop
with stronger desktop OCR.

### Phase C: Capture quality (weeks 3–10, in parallel with B)

Execute [SCAN_CAMERA_PLAN.md](../mobile/docs/SCAN_CAMERA_PLAN.md) Phase 1+,
with these priorities:

**C1. Resolution plumbing first (1 week).** Raise `OfflinePages.load`
(2500 px) and `RapidOcr` (2000 px) limits so a 12 MP capture reaches OCR at
≥250 DPI equivalent. *Gate:* paired OCR comparison (`compare_apps`) shows no
CER regression and the per-page time stays within +30%.

**C2. Native CameraX scan screen MVP (5–7 weeks).** 12 MP stills, live quad
outline, one status message at a time, torch, tap-to-focus, manual shutter.
Auto-capture behind a toggle, off by default until device data supports it.

**C3. Capture-time quality gate.** Blur, glare and "page cut off" checks on
the captured still, with a one-tap retake. Cheap and catches the failures
post-processing cannot recover.

**C4. Batch helpers.** Duplicate-page detection (dHash, already in the
plan) and best-frame selection, reused from the book-video path.

**C5. Physical-device acceptance.** At least three phones (low, mid, high
tier) before claiming anything about capture. This is the biggest
evidence gap in the mobile README.

*Status 2026-11-15: no physical phone is available; the gap stays open.*
Stand-in until then, and how far it reaches:

| Question | Stand-in | Covers | Does not cover |
|---|---|---|---|
| Memory | API 35 x86_64 emulator with 2.5 GB RAM, below the app's 4 GB target, sampled every 3–5 s; Android's low-memory killer is the pass/fail signal | leaks, unbounded growth, worst-case peaks (it caught the 1.7 GB RapidOCR kill) | vendor memory policies, ARM native-library sizes |
| Accuracy | paired harness on frozen images (`compare_apps`), including 12 MP camera proxies through the real import path | resolution handling, orientation, engine differences on identical bytes | real optics: blur, glare, curvature, sensor noise |
| Speed | emulator wall-clock, reported only as before/after on the same host | regressions of 2x or more | absolute phone speed (x86 host, shared CPU) |
| Camera | none; C2 waits for a phone | — | everything about live capture |

So: no capture work (C2) ships, and no phone speed or "works on phone X"
claim is made, until C5 is done. Memory and accuracy changes can still be
gated on the stand-in.

### Phase D: OCR engine and honesty on mobile (weeks 6–12)

**D1. Cheap orientation.** Replace the 4× full-OCR orientation loop
(`processing.dart:64`) with cheap signals: run text **detection only**
(no recognition) to decide portrait vs landscape from line-box shapes, then
the 0/180° line classifier already in the RapidOCR model pack
(`ch_ppocr_mobile_v2.0_cls`) to decide upright vs upside-down. Fall back to
the full 4× loop only when both are unsure. Expected: about 2–3× faster recognition per page.
*Gate:* orientation accuracy on the rotated set equal to today's; time
measured.

**D2. Independent digit verification on the phone.** The phone already has
two engines. Re-read digit lines with **the other engine** (ML Kit ↔
RapidOCR) instead of the same engine on a crop. That turns
"same-engine agreement" into real cross-model evidence, the honest version
of what the desktop bodhan verifier does. *Gate:* digit-content queue
recall@10 on the phone comparison pack ≥ the same-engine method, with
time ≤ +1 s/page.

**D3. Choose the default engine by evidence.** Run the paired comparison on
the frozen Devanagari sets at C1 resolution. If RapidOCR wins for `ne`/`hi`,
make it the Devanagari default and keep ML Kit for Latin (or the reverse).

**D4. Port reading order.** Port the column detection and reading-order
logic from `veriscript/document/layout.py` to Kotlin (it is geometric, not
a model). Two-column pages currently come out interleaved on the phone.

**D5. Word-level boxes.** Store words (ML Kit `elements`, RapidOCR tokens),
not just lines. Needed for E1 and for a token-level review queue like the
desktop's.

### Phase E: PDF output quality (weeks 6–10)

**E1. Accurate invisible text layer.** Word-level placement with horizontal
scaling (`Tz`) so selection highlights match the printed words, on both
platforms. Text render mode 3 on mobile instead of opacity 0.
*Gate:* automated test that extracts word boxes from the PDF (pypdfium2)
and checks IoU ≥ 0.7 against the OCR boxes; Devanagari copy/search round
trip stays exact.

**E2. Born-digital PDFs pass through.** If a page already has a usable text
layer, keep the original page (vector text, fonts, links) and skip OCR, or
offer "re-OCR anyway". Today such PDFs are rasterised at 200 DPI and come
back worse than they went in. Detect broken legacy-font Nepali text layers
(Preeti/Kantipur glyph soup) and OCR those pages: a common real case in
Nepali government PDFs.

**E3. Size presets.** "Small / Standard / Archive": DPI and JPEG quality
for colour and grey pages; 1-bit (CCITT G4) for clean black-and-white text
pages; target Small ≈ 100–200 KB per A4 page. Show the estimated size
before export. MRC (separate text and background layers) is a later
optional step.

**E4. PDF/A-2b for archive use.** Embedded fonts, ICC profile, XMP
metadata. Courts, land records and libraries are the stated audience; they
ask for PDF/A. Validate with veraPDF in CI.

**E5. Smaller extras that users expect:** password protection (AES-256),
document metadata (title, author, date), page-range export, merge and
split, and "Save to…" through Android's Storage Access Framework instead of
share-only.

### Phase F: Differentiators (weeks 10–20, each behind its own gate)

**F1. Book flattening (curved pages).** Evaluate an ONNX dewarping model
(UVDoc-class; check licence: Apache-2.0 or MIT only) against the current
quad warp on real book photos. *Gate:* CER improves on a curved-page set
and **zero invented tokens**, same honesty rule that killed Sauvola. If no
model passes, ship a classical text-line-based dewarp for book mode only.

**F2. Tables → CSV/XLSX with digit flags.** The hard-10 set is table-heavy
and the pipeline already wins on structure. Export detected tables with the
digit-review flags carried as cell comments. "Excel export where every
uncertain number is marked" is unique.

**F3. Finger and glare cleanup for book mode.** Detect skin-coloured
regions at page edges and blank them (never inpaint text). Glare: prefer
asking for a retake (C3) over inventing pixels.

**F4. Real phone-photo frozen set.** ROADMAP Track 3a, now urgent: every
Phase C, D and F gate needs it. 50+ consented pages across the three test
phones.

**F5. Optional on-device document Q&A (research only).** On-device VLMs
(for example PaddleOCR-VL in LiteRT format) now run on phones, but cost,
size and invented-text risk are unmeasured. Spike only; default off; never
cloud. Matches the "no VLM default" rule in ROADMAP §8.

### Phase G: Release engineering (continuous)

- Play Store internal testing track with a real upload key; Windows code
  signing (both already listed as owner-only steps).
- Crash-safe updates: desktop update check stays opt-in and offline-first.
- Performance budgets in CI: per-page OCR time on the emulator and on the
  desktop CPU path, APK size (currently 61 MB ARM64), installer size,
  cold-start time. A regression fails the build.
- Mobile CI: run `flutter test` plus one emulator integration test per PR
  (currently analyze + unit only).

---

### Phase A results (2026-11-14)

| Item | What changed | Evidence |
|---|---|---|
| A1 job model | `POST/GET/DELETE /api/jobs` (`webapp/vvweb/jobs.py`); one worker thread holds the worker slot only while a job really runs; cancel and timeouts stop between pages; `/api/restore` waits on the queue without blocking the event loop. The studio shows "Reading page n of m", a determinate bar, and Cancel sends `DELETE`. | `tests/test_webapp_jobs.py` (12 tests: health answers during a run, cancel frees the slot only after the page ends, queued cancel never runs, timeout, bounded queue). Real pipeline: `/api/health` ≤ 45 ms throughout; an 8-page job cancelled at page 2, run folder removed, next job ran after. Playwright: 50 passed. |
| A1 memory | PDF pages are rendered and read one at a time; the combined PDF is written by `SearchablePdfWriter` as pages finish. | `test_page_cap_zero_reads_every_page` (12 pages, combined PDF has 12). |
| A2 cap and expiry | `VERISCRIPT_WEB_PAGE_CAP` (0 = none) and `VERISCRIPT_WEB_TTL_MINUTES=0` (keep). Desktop sets cap 0, timeout 0, TTL 0. UI says "kept until you delete them". | `test_ttl_zero_keeps_runs`, `test_default_cap_still_applies`. |
| A3 background (Android) | `ProcessingService` (foreground service, `dataSync` / `mediaProcessing` on API 35+) with a progress notification while work runs over 2 s. | `test/background_test.dart`; `integration_test/processing_service_test.dart` on the API 35 emulator: `isForeground=true`, `types=0x2000` (mediaProcessing), notification "Page 1 of 3" with a progress bar, gone after stop. **Not yet tried on a physical phone, or with the app in the background under memory pressure.** |
| A4 streaming export (Android) | `lib/pdf_stream.dart`: JPEG pass-through, invisible line text stretched to the box, subset Type0 font with ToUnicode. The `pdf` package is removed. | `test/pdf_stream_test.dart`; pdfium extracts exact Devanagari (including conjuncts) and places it in the line boxes; `tool/verify_android.py` (every export, offline, API 35 emulator) passes. 150-page peak-memory measurement still to do. |
| A5 storage (Android) | `doc:` relative paths, `schemaVersion: 2`, re-homing of old absolute paths. | `test/storage_paths_test.dart` (moved folder, schema-1 migration). |
| A6 diagnostics | Android Settings → Diagnostics; desktop `/api/diagnostics` (local mode only) and a Copy button on errors. No titles, text or paths. | `test/diagnostics_test.dart`, `test_diagnostics_are_local_only_and_strip_paths`. |

### C1 + D1 results (2026-11-15)

Measured on the API 35 emulator with a new 12 MP camera-proxy pack plus the
smoke pack; full write-up in
[evals/comparisons/2026-11-15](../evals/comparisons/2026-11-15/README.md).

| Item | What changed | Result |
|---|---|---|
| C1 resolution | Import keeps up to 4096 px (was 2500); the RapidOCR port cuts lines from the full-resolution page. | ML Kit Nepali camera CER 0.040 → 0.027 (all 5 pages better); English unchanged. **Adopted.** |
| D1 orientation | First tried: native detector + 0/180 classifier. Slower than ML Kit's own reads on the emulator and never confident on Devanagari, so **dropped**. Adopted: read as given, stop when lines look upright, else let line angles pick the next rotation. | ML Kit 10/10 orientation; OCR + import +5% overall (gate ≤ +30%), smoke pages 2–3× faster. RapidOCR on Devanagari keeps the four-way search (its angles cannot tell up from down; not re-run after that change). |
| RapidOCR memory | ONNX Runtime arena and memory patterns off. | Baseline was killed at 1.7 GB; now 1.0 GB peak over 16 pages, but slower. Arena on reached 1.38 GB on 3 pages: not adopted. RapidOCR speed is open (best measured on a phone). |

### Phase E (first part) and loose ends (2026-11-15)

| Item | What changed | Evidence |
|---|---|---|
| E2 born-digital PDFs | `veriscript/document/pdf_text.py`: a page keeps its own text and original page only when the text layer has ≥30 characters, is not a scan carrying another tool's OCR (one image ≥75% of the page), uses no legacy Devanagari font, contains Devanagari on a Nepali/Hindi run, and has ≤2% damaged Devanagari words (`devanagari_validity`). Studio (`text_layer`, default on) and CLI (`--pdf-text auto\|off`); mixed documents are assembled from originals plus OCR'd pages. | `tests/test_pdf_text.py` (10). On the local PDFs: English born-digital 60/60 pages kept; Nepali government, textbook and unlabeled PDFs 0/137 kept (68 damaged, 29 legacy font, 12 other-tool OCR, 24 scans, 4 no Devanagari), so they are OCR'd as before. An 11-page arXiv PDF: 2.2 s instead of OCR, identical text on 11/11 pages, 161 KB vs 169 KB source. |
| E1 text layer (desktop) | Invisible text is stretched to each token box (`Tz`, clamped 10–1000%); baseline raised to the descender line. | `tests/test_text_layer_alignment.py`: IoU ≥ 0.7 between selection boxes and token boxes, exact English and Devanagari round trip. |
| E3 size presets | `--pdf-size` / studio "PDF size": archive (lossless, the old output), standard (JPEG q85, default), small (JPEG q60, ≤150 DPI). Near-grey pages are stored greyscale. The text layer is identical in all three. | Per page: textbook scan 2305 → 440 → 274 KB; government PDF render 445 → 397 → 112 KB; 12 MP camera page 7378 → 852 → 82 KB (archive → standard → small), and 2.8 s → 0.3 s to write the camera page. 8 pt Devanagari digits stay legible in small (checked by eye). `tests/test_pdf_size.py`. |
| B1 desktop library (first part) | `webapp/vvweb/library.py`: list (newest first), search over titles and recognised or corrected text, reopen in the studio, rename, delete; runs record their file name and date. Local mode only; the demo answers 404. Studio: "Library" page linked from the top bar in the desktop app, `/studio?run=<id>` reopens a document. Not yet: SQLite index, multi-file batch (B2), file associations (B3). | `tests/test_webapp_library.py` (5, incl. demo lockout); `e2e/library.spec.ts` (list, search, rename, delete, open, WCAG 2.1 AA). |
| B2 batch input | Desktop studio: drop or choose several files; they are read one after another (server job queue), each with its own live status (waiting, "Reading page n of m", done, failed with the reason, stopped/skipped). A failure does not stop the rest; Cancel stops the current file on the server and skips the others; finished files can be shown at once and are kept in the Library. The demo stays one file at a time. | `e2e/batch.spec.ts` (failure isolation, cancel, demo unchanged, WCAG 2.1 AA). |
| D4 reading order (phone) | `mobile/lib/layout.dart`: line-by-line port of `veriscript/document/layout.py` (gutter guards, bands, table grids), applied to every recognised page. | Parity: 31 cases (real two-column papers, receipts, Nepali government PDFs, letterpress, synthetic) reproduce the desktop order exactly (`test/layout_test.dart`, fixture from `scripts/build_reading_order_fixture.py`, boxes only, text masked). Emulator, two-column 12 MP proxies, same reads scored both ways: RapidOCR CER 0.70 → 0.00 (English) and 0.71 → 0.034 (Nepali); ML Kit unchanged (0.005 / 0.034: it already returns columns in order). |
| F2 tables → spreadsheet | `veriscript/document/tables.py`: the layout's grid regions become rows of cells; CSV (UTF-8 BOM) and a dependency-free XLSX with flagged cells filled amber and a Review sheet (cell, reading, alternative, reasons). Studio downloads `tables.xlsx`/`tables.csv`; CLI `<name>_tables.*` (`--no-tables`). Text is never changed. Known limit: wrapped cell text can spill into a neighbouring column. | `tests/test_tables.py` (7). Court registers from the frozen Nepali set: 5 × 13–14 tables with the right header row, 42 flagged cells listed across 4 pages; openpyxl opens the file. |
| D2 independent digit checks (phone) | Number-line crops are re-read by the other bundled engine: the RapidOCR recognizer alone when ML Kit reads (native `rapidOcrLine`, no page detection), ML Kit when RapidOCR reads. `--digits both` records both for measurement; `evals/harness/digit_checks.py` scores them. | Emulator, 16-page pack, 123 number lines, ground-truth digit groups: other engine caught 2/4 wrong lines vs 1/4, false alarms 7/119 (6%) vs 12/119 (10%), 68 vs 84 ms per line. Only 4 wrong lines: directionally better on every axis, not a precise rate. RapidOCR reading (same pack, 121 lines): caught 2/3 vs 0/3, false alarms 14/118 (12%) vs 38/118 (32%), 0.1 s vs 4.8 s per line. |
| E3 on the phone | Export sheet switch "Smaller PDF for sharing" (remembered): pages re-encoded natively to ≤1754 px long side (A4 at 150 DPI), JPEG q60; text layer unchanged. | Emulator, 150 A4 pages (1.8 MB JPEG each): searchable PDF 272 MB → 29 MB (195 KB/page), 12.8 s vs 3.6 s; peak memory 409 → 435 MB. `test/export_small_test.dart`. |
| E4 PDF/A-2b | The archive preset writes PDF/A-2b: XMP metadata mirroring the document info, an sRGB output intent, and an end-of-line before every `endstream` (applied only while saving). | veraPDF 1.30.4, PDF/A-2b profile: grey, colour and two-page Devanagari samples PASS (`scripts/check_pdfa.py`; `tests/test_pdf_size.py` runs it when veraPDF is installed). Standard and small presets are not PDF/A (JPEG pages are allowed, but they are not checked). Not yet in CI: needs veraPDF there (Docker image `verapdf/cli`). |
| F1 curved-page flattening | `veriscript/document/dewarp.py`: UVDoc (MIT) predicts a page grid on a 488×712 copy, applied to the full-resolution photo. Weights load only via `torch.load(weights_only=True)`; the repository's installer code is never imported. Opt-in: CLI `--flatten`, `run_document_pipeline(flatten=True)`; nothing changes without the local model. Not in the studio or the phone yet (needs torch or an ONNX export). | `evals/harness/eval_dewarp.py`, DocUNet's 130 real phone photos of curved or folded pages (128 with text), each scored against the pipeline's reading of its flatbed scan: CER 0.472 → 0.269, paired 95% CI of the change −0.246 to −0.161; WER 0.571 → 0.364; 95 photos better, 19 worse; invented-word rate 11.4% → 10.0%; 0.43 s per photo on CPU. The gate written before the run passed. Why it stays opt-in: the plan's stricter "zero new invented words" does not hold photo by photo (16 photos rose by >2 points, worst 65_2: 9.6% → 51%), photos that were already flat got worse (6_1, 7_2: CER 0 → 0.13/0.16), and the set is English only, so it is untested on Nepali. Two attempts to make it safe by default, both measured on the same photos (2026-11-16): (1) a "looks curved" check (how far UVDoc's grid is from one perspective transform), cut-off chosen on documents 1–32 and tested on 33–65: no effect (it skipped 2 of 66 test photos), because the pages it hurt score as strongly curved (16–33 vs 1–4 for flat ones). Removed. (2) Sizing the flattened page to its own proportions instead of the photo's frame (`flatten(keep_aspect=True)`, `eval_dewarp.py --keep-aspect`): fixes the worst case (receipt 65_2: CER 0.449 → 0.175, invented 51% → 18%) but is slightly worse overall (mean CER 0.284 vs 0.269; 21 vs 16 photos with invented words up >2 points), so the frame stays the default. (3) Read both and keep the reading the engine is more confident in (`--flatten`, now the default way to flatten; `--flatten always` reads only the flattened page). Gate written before the run: pass the gate above and at least halve always-flatten's damage. Result on the 128 photos: CER 0.472 → 0.318 (95% CI of the change −0.191 to −0.120), invented words 11.4% → 9.3%, 68 better / 9 worse; photos with invented words up >2 points 1 (vs 16), CER worse by >0.05 2 (vs 8); flattened reading kept on 86. Passed. It gives up part of the gain (0.318 vs 0.269): confidence does not always see it (23_1: 0.78 → 0.002 when flattened, but the photo's reading scored 99.0 vs 98.8). The CLI reproduces the evaluation's choices and scores. Cost: about twice the OCR time. Not default for all documents: untested on Nepali, and it doubles reading time. |
| B4 phone → desktop bundle | Phone export "For VeriScript Desktop · bundle" writes a `.veriscript` file: the selected pages' original pictures (JPEG/PNG bytes stored as they are; other formats become JPEG) and a manifest with title, notes and every line with its original reading, correction and review state. Written straight to disk one page at a time. Desktop: the studio accepts it (desktop only; the shared demo points to the desktop app), reads every page with the full pipeline, keeps the phone's title in the Library, and offers `phone_reading.json`; the phone's text is kept beside the desktop's reading, never copied into it. CLI: `--mode document --input x.veriscript` (whole document). The reader treats a bundle as untrusted: no extraction to disk, names only from the manifest (`pages/NNNN.ext`), size, ratio and pixel limits before decoding, known line fields only. Desktop upload limit raised 200 MB → 2 GB (uploads stream to disk). Not yet: Wi-Fi pairing; corrections from the phone are shown as a count and a file, not merged into the desktop review. | `tests/test_bundle.py` (15: format, hostile zips incl. path traversal and a zip bomb, demo refusal, studio run), `test/bundle_test.dart`, `e2e/bundle.spec.ts` (desktop note, demo refusal, WCAG 2.1 AA). A bundle written by the phone code opens in the desktop reader, the real server and the CLI (3 pages, real OCR, title and correction count carried). Emulator, 150 pages of 1.8 MB: 272 MB bundle in 15.9 s, peak memory unchanged at 432 MB (searchable PDF of the same pages: 29.8 s). |
| C3 capture-time quality | After each camera shot the phone measures blur (on the strongest edges, Laplacian over gradient; plus Laplacian variance) and glare (largest near-white area) on a 1024 px grey copy, natively (`captureQuality`, OfflinePages.kt). A blurry or glary shot gets "Retake this page?" with Retake / Keep photo; closing the prompt keeps it, and a failed check never costs a capture. Cut-off pages are not checked yet. | `evals/harness/eval_capture_quality.py`, DocUNet's 130 real phone photos, thresholds set on documents 1–32, reported on 33–65: out-of-focus shots caught 100%, shaken 91%, glare 100%; warnings on usable photos: blur 6.1%, glare 6.1% (target written before was ≤5%: missed by about one photo each). Those flagged photos do read worse (mean CER 0.69 blur-flagged vs 0.46 others; glare-flagged 0.53–0.74 vs median 0.49), and a warning only offers a retake, so it ships as advice (owner decision, 2026-11-16; revisit blur with real-phone photos in C5: a stricter blur setting halves false warnings for about 5 more shaken shots in 100 getting through; glare stays, since a stricter glare setting stops catching glare). A text-aware glare check (bright areas inside text blocks only) cut false warnings but caught only 18% of glare, so it was dropped. Native vs Python on the emulator: 17 photos incl. damaged copies and a 12 MP JPEG agree to 4 decimals, same warnings; 0.64 s per 12 MP photo (1.45 s for the first, while OpenCV loads). `test/capture_retake_test.dart`. Not measured on a real camera (C5). |
| A4 export memory | Measured: 150 A4 pages at 300 DPI (1.8 MB JPEG each, 30 lines per page) | Searchable PDF 272 MB in 7.6 s, image PDF in 4.1 s; the app's peak memory stayed at 413 MB through both exports (no growth). |
| RapidOCR orientation (phone) | Devanagari keeps the four-way comparison. | Re-run on the 5 Nepali camera pages: orientation 5/5, CER 0.034 (baseline 0.039), ~40 s/page, peak 903 MB, no kill. |
| Look-alike digits (phone) | `digitScriptIssue`: Bengali digits, mixed Devanagari/ASCII digits in one number, o/O/l/I inside a number. Flagged for review, text never changed. | `test/processing_test.dart`. |

## 4. Sequencing

| Weeks | Track | Depends on |
|---|---|---|
| 1–3 | **A** reliability (job model, background work, streaming export, storage) | none |
| 3–6 | **B** desktop library, batch, OS integration | A1, A2 |
| 3–10 | **C** resolution plumbing → CameraX MVP → device acceptance | C1 first; C5 needs phones |
| 6–10 | **E** text layer, digital PDF pass-through, size presets, PDF/A | A4 (mobile), D5 (word boxes) |
| 6–12 | **D** orientation, cross-engine digits, engine choice, reading order | C1 |
| 10–20 | **F** dewarp, tables, cleanup, real photo set, Q&A spike | C, D, F4 |
| ongoing | **G** signing, budgets, CI | none |

If only one person works on it, do **A → C1 → D1 → E1/E2 → B → C2**. That
order fixes the bugs, then delivers the largest quality-per-week gains
(resolution, 2–3× faster mobile OCR, correct PDFs) before the long camera
build.

## 5. Success metrics (90 days)

| Metric | Now | Target |
|---|---|---|
| Desktop: largest PDF processed in one job | 10 pages | 500 pages, with progress and cancel |
| Server responsiveness during a job | blocks up to 30 min | `/api/health` < 200 ms always |
| Mobile: per-page recognition time (emulator, same fixture) | baseline to measure | ≤ 0.5× baseline (D1) |
| Mobile: 150-page export peak memory | unmeasured (whole document in RAM) | < 300 MB |
| Mobile capture DPI reaching OCR (A4) | ~171 DPI | ≥ 250 DPI |
| Searchable PDF selection accuracy (word IoU) | unmeasured; line-level | ≥ 0.7 |
| Born-digital PDF fidelity | rasterised | original page kept |
| Phone-photo CER | proxy only (0.370 / 0.757) | measured on 50+ real pages |
| Physical devices verified | 0 | 3 |

## 6. Explicit non-goals

- No cloud OCR, no accounts, no telemetry. Diagnostics are local and copied
  by hand.
- No VLM default anywhere (cost and invented text; ROADMAP §8).
- No inpainting that could create text: cleanup may blank, never invent.
- No auto-capture on by default until device data supports the thresholds.
- No handwriting promise in this plan; it needs its own data and gate.
- iOS stays out of scope until Android capture is proven on real phones.

## Sources (accessed 2026-11-14)

- Scanner app landscape and Microsoft Lens removal:
  <https://unstar.app/blog/adobe-scan-camscanner-microsoft-lens-genius-scan-swiftscan-pdf-scanner-apps-ranked-2026>,
  <https://www.itechguides.com/7-best-scanner-apps-for-android-in-2026>,
  <https://imagetotable.ai/blog/best-mobile-ocr-apps-2026>
- Google Drive scanner update (June 2026):
  <https://heise.de/-11313237>,
  <https://www.phonearena.com/news/the-best-google-drive-feature-you-never-knew-about-just-got-a-massive-overhaul_id180762>
- Adobe Scan release notes (OCR page limit, compression, AI Assistant):
  <https://www.adobe.com/go/scan-android-release-notes>,
  <https://www.adobe.com/go/scan-ios-release-notes>
- On-device OCR and VLMs:
  <https://community.ente.io/blog/ocr>,
  <https://github.com/egdels/makeacopy>,
  <https://huggingface.co/litert-community/PaddleOCR-VL-1.6>
- Dewarping: <https://pypi.org/project/docuwarp>,
  <https://huggingface.co/DevWorld/flattener>,
  <https://arxiv.org/abs/2501.03145v3>
- Earlier in-repo research: [COMPETITORS.md](COMPETITORS.md),
  [mobile/docs/research/scanner-ux-competition.md](../mobile/docs/research/scanner-ux-competition.md)
