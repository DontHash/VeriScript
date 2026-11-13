# Scanner UX, Auto-Tuning, and Real-Time Coaching

**Competitive research for a Flutter Android document-scanning camera**

Research date: **2026-11-07**  
Scope: Google ML Kit Document Scanner API (`GmsDocumentScanning`), Google Drive scan, Microsoft Lens (and its OneDrive successor), Adobe Scan, CamScanner, Apple Notes / VisionKit / Continuity Camera, Samsung Camera Document Scan / Samsung Notes, and open-source scanners.

> **Method.** This is desktop research, not a hands-on lab test. It prioritizes official docs and help pages, then vendor engineering/research material, reputable reviews, app listings, and source code. Camera-pipeline internals, confidence thresholds, and auto-capture timing are mostly unpublished; where that is true it is stated explicitly rather than guessed. App-store review evidence is used for failure modes, not to prove feature behavior.

## 1. Executive summary

1. **The market has standardized the flow, not the coaching.** Detect → outline → hold steady → capture → review/reorder → export is universal. Live guidance is usually one to three short states; glare, shadow, blur, and page completeness are mostly handled after capture. That is the clearest opening for a differentiated scanner.
2. **Auto-capture is expected, but also the most common source of anger.** Adobe's default auto-capture is the cautionary example: users report the blue crop rectangle locking onto a text block or part of a page. The winning design is confidence-gated, two-stage auto-capture with a permanent manual shutter, a pause/toggle, and a visible reason when capture is waiting.
3. **Geometry is the strongest predictor of a good capture.** Every mature scanner gates on four corners, full page in frame, and reasonable size. Samsung publishes unusually concrete guidance: text ≥**20%** of the document area, page ≈**80%** of the screen, all four corners visible. That is a calibration starting point, not a universal law.
4. **The live guidance vocabulary is tiny.** Adobe documents three states: *Looking for document*, *Capturing… hold steady*, *No document found. Capture manually*. Apple and Samsung use an outline plus a hold-steady/scan-button state. Microsoft Lens is the accessibility outlier with TalkBack directional voice guidance.
5. **Google ML Kit is not a drop-in replacement for a differentiated camera.** It gives a polished, on-device, permissionless scanner UI, but exposes only page limit, gallery import, scanner mode, and output format. No preview frames, camera controls, custom overlays, or custom guidance; it depends on Play Services plus a first-use download. Use it only as an optional "Quick scan" fallback.
6. **The best opportunity is "calm confidence."** One instruction at a time, only when it changes what the user should do; outline + progress ring + haptic for auto-capture; blocking UI only for permissions and manual fallback; manual shutter and import always available; preserve the original and make enhancement explicit.

## 2. Comparison table

Legend: **AC** = auto-capture; **AF/AE/AWB** = autofocus/exposure/white balance; **ML** = machine learning.

| Product | Camera pipeline | AC / multi-shot | Auto tuning | Live guidance | Review / import / offline | Limits |
|---|---|---|---|---|---|---|
| **ML Kit Document Scanner** | System camera; still; auto edge/perspective/rotation; no frame access | AC; page limit; gallery; JPEG/PDF | Auto; no camera controls; 3 scanner modes | Built-in UI; no custom overlays | Built-in crop/rotate/reorder/filters/cleanup; on-device after Play Services; no camera permission | Fixed UI; Android/Play Services; API 21+/1.7 GB; first-use download |
| **Google Drive scan** | Blue outline; manual/auto; 2026 smart batch | Manual/auto; hover batch; auto-split; best frame; duplicate detection | Auto crop/filters/cleanup; no manual EV/AF/WB | Blue line, toggle, pause; no coaching documented | Crop/rotate/filter/clean/add/retake/delete; PDF/JPG; uploads to Drive; 8 GB gate | Sparse feedback; high-end-only new path |
| **Microsoft Lens** (retired) | Orange frame; manual; auto crop/perspective; five modes | Manual; AC reports conflict; QR auto | Mode processing; auto flash; whiteboard cleanup | Orange frame + TalkBack voice | Add/filter/crop/rotate/delete/annotate/reorder; PDF/Word/PPT/OneNote/OneDrive; offline capture, cloud saves | Retired; successor cloud-only; manual-first |
| **Adobe Scan** | AC default; blue dots; still; auto crop/perspective/straighten | AC default; manual; book split; high-speed | Auto crop/clean/straighten; flash; filters; brightness/contrast; no manual EV/AF/WB | *Looking for document* → *Capturing… hold steady* → *No document found. Capture manually* | Crop/straighten/rotate/filter/cleanup/reorder/delete/add; Adobe cloud default; gallery originals | AC locks onto partial page; cloud/account friction |
| **CamScanner** | AC toggle; edge overlay; auto crop; book/ID/batch | AC toggle; book/ID/batch; turn-page AC (iOS) | Auto crop/enhance/filters/shadow/moiré/finger; HD | Edge outline; no rich messages; FAQ tips | Batch review/reorder/retake/OCR/PDF/JPG/Word; local + cloud; some AI online; ads | Ads/monetization; auto-crop cuts margins; opaque enhancement |
| **Apple Notes / VisionKit / Continuity** | System camera; auto mode; manual shutter/volume; edge/perspective/deskew | Auto + manual; multi-page; no page-limit API | Auto enhancement; flash/filter iOS 26; no dev camera control | Blue outline + "hold steady"; preview | Adjust corners/Keep/add/filters/rotate/retake/delete; no gallery import; on-device/iCloud optional | Closed UI; no AC disable; ~24 scans |
| **Samsung Camera Scan / Notes** | Scan button on detection; yellow outline; auto crop/straighten; Notes multi-page | Tap Scan; multi-scan; Notes many | De-warp/tilt/finger/fold/moiré; filters; resolution; no manual EV/WB | Yellow outline; Scan button | Crop/rotate/reorder/add/delete; PDF/images; OCR in Notes; local/no ads | Device fragmentation; cleanup limits; Notes lock-in |
| **OpenNoteScanner** | Manual; OpenCV; green outline; full-res still | Manual; QR auto mode only; no multi-page auto | Canny 75/200, 500 px, approx 2%, adaptive 225/15; torch; AF | Corner markers/green outline; no text | Local gallery; no reorder; PDF/share; local only | Brittle low contrast; no coaching; legacy |

### 2.1 Controls and tuning surface

**Controls.** No reviewed product exposes manual exposure compensation or white balance in its scanner UI. Flash/torch is the main user control (Lens, Adobe, CamScanner, OpenNoteScanner); Apple exposes flash/filter only on iOS 26; ML Kit, Drive, and VisionKit expose no developer camera controls. Tap-to-focus is camera-app behavior, not a documented scanner control. Samsung recommends zoom for small documents; the rest do not document zoom. The practical override surface is therefore: manual shutter, auto-capture toggle, flash/torch, filter, crop, and resolution — not EV/WB sliders.

**Still vs preview.** Every shipping product uses a captured still for the final page image; preview frames are used for edge detection and auto-capture, not as the exported scan. Most vendors do not publish still resolution. Samsung is the exception with default/high/low output settings. OpenNoteScanner explicitly uses the largest still size matching the preview aspect ratio. ML Kit and VisionKit return still-derived images but do not expose raw preview frames or camera parameters. [1][2][19][24][25]

**Low-light handling.** Vendors handle low light mainly with flash/torch plus post-processing, not a dedicated night mode. Lens defaults to auto flash; Adobe, CamScanner, and OpenNoteScanner expose flash/torch controls; Apple exposes flash in iOS 26. None of the reviewed system scanners documents a low-light exposure-fusion mode. This is an opportunity, but only if direct flash can be avoided when it creates a center hotspot or glare.

## 3. Product findings

### 3.1 Google ML Kit Document Scanner API

**What it is.** A system-provided Android scan flow. The host launches Google's UI; the user captures, edits, and returns JPEG/PDF. Models, logic, and UI come via Google Play Services (~300 KB app-size impact). [1][2]

**Camera pipeline.** The SDK owns the camera; the app gets no preview stream, raw frames, camera parameters, or metadata. Documented: automatic capture with document detection, edge detection for crop, auto rotation, optional ML cleaning (stains, fingers, shadows). [1][2]

**Automatic tuning.** Automatic, with no exposed exposure/focus/metering/WB/HDR/zoom/torch controls. Modes: `SCANNER_MODE_BASE` (crop/rotate/reorder), `BASE_WITH_FILTER` (adds filters), `FULL` (default; adds ML cleaning and future Play Services features). [3] The reference lists `CAPTURE_MODE_AUTO`/`MANUAL`, but the documented Builder has no capture-mode setter; only gallery import (default on), page limit, result formats (JPEG default, PDF optional), and scanner mode are configurable. [3][4]

**Guidance and UX.** Google's UI, with no API for custom overlays, labels, help text, colors, or error messages. Built-in preview supports crop, rotate, reorder, filters, shadow/stain removal, and finger removal. [1][2]

**Offline / permissions.** On-device, no host-app camera permission (Play Services owns the camera); users choose what to share back. First use may wait for Play Services to download resources. The 16.0.0 AAR declares no `CAMERA`/`INTERNET` permission (our inspection), but Play Services can download over its own connection. [1][2][36]

**Fit for our app.** Not as the primary camera: no custom real-time analysis, coaching, overlays, camera tuning, or threshold control. Reasonable only as an optional "Quick scan" fallback on Play Services devices with cached resources; never the only path for our offline app.

### 3.2 Google Drive scan

**Camera pipeline.** A camera viewfinder with a blue outline showing the crop. Users take the photo manually or enable automatic capture; Drive auto-crops, offers filters, and cleans stains/fingers. Saves PDF or JPG. [6]

The 2026 redesign adds a Material 3 Expressive viewfinder, **Smart Batch Scanning** (hover over pages; continuous capture; auto-split), pause, a system file picker, **Auto-Best Frame** (replace blurry scans with the best frame), and **Duplicate Detection**. Google says it is on-device, offline-capable, and private; it is in Drive and Files by Google and requires **8 GB RAM** on the new high-end path. [7][8]

**Tuning and guidance.** Auto crop, auto color/filters, shadow/stain cleanup, auto-best frame; no documented manual exposure/focus/WB/HDR/zoom. Guidance is sparse: blue crop line, manual/auto toggle, pause; no documented move/hold/glare/shadow/page-not-detected coaching. [6][7]

**UX flow.** Capture → crop → adjust/filter/clean → add/retake/delete → Done → name → save PDF/JPG to Drive. Multi-page review and file-picker import are supported. [6]

**Offline / privacy.** New path processed on-device and works offline; files upload to Drive; Google says content is not used for advertising. [6][7][8]

**Lesson.** Batch and auto-best-frame are strong, but the 8 GB gate and sparse coaching expose the limits of a black box. A mid-range app can win by doing less automatically but explaining more.

### 3.3 Microsoft Lens (retired) and OneDrive

**Status.** Microsoft retired Lens from Android and iOS starting **January 9, 2026**; support ended **February 9, 2026**; new scans could be created until **March 9, 2026**; the app was removed from stores on February 9. The recommended replacement is OneDrive's built-in "Scan photo" feature, which does **not** save scans locally. [10]

**Camera pipeline.** Lens opens in a mode (Whiteboard, Document, Actions, Business Card, Photo). The user aligns content inside an **orange frame** and taps the round shutter. Flash defaults to **auto** and can be changed; gallery import is supported. Captures are auto-cropped/perspective-corrected and enhanced by mode; Whiteboard mode reduces background brightness and improves ink visibility. [9]

Microsoft's Android help documents only the manual shutter; auto-capture reports conflict by version. Treat Lens as **manual-first with version-dependent auto-capture**, not as a reliable auto-capture reference.

**Tuning and guidance.** Mode-specific processing, auto crop, auto flash, filters, cleanup; no documented exposure/focus/WB/HDR/zoom. The orange frame is the main visual guide. The standout is accessibility: with TalkBack, Lens gives **real-time directional voice guidance** ("move right", "move up"), the only such documented feature in this set. [9]

**UX flow.** Capture → review/adjust borders → filter/crop/rotate/delete/annotate → reorder → save PDF, Word, PowerPoint, OneNote, OneDrive, or gallery. Up to **100 images** per scan on devices with >3 GB RAM. OCR: 30 languages printed; handwriting English-only. [9]

**OneDrive successor.** Flash on/off/auto/torch; four modes; white circle shutter; multi-page max **10**; crop/rotate/filter; automatic PDF; cloud auto-save, no local-only option. [11]

**Lesson.** TalkBack guidance is the strongest accessibility pattern here. Manual-only capture tires users on long documents, and Lens's retirement shows platform-vendor risk; the successor is cloud-oriented, the opposite of our offline promise.

### 3.4 Adobe Scan

**Camera pipeline.** Auto-capture is the default. In auto mode, live edge detection shows **blue dots at the document corners**; when the app is confident enough, it shows **"Capturing… hold steady"** and captures. Manual mode is available; the user centers the document and taps the capture button. Book mode captures a two-page spread and splits it into pages; high-speed scan lets users scan multiple pages without pressing "Keep Scanning" each time. [12]

**Automatic tuning.** Auto crop, auto image cleaning, AI-powered Straighten for curved pages (including when one edge is outside the frame), flash auto/on/off, and filters. Users can adjust brightness/contrast, cleanup artifacts, rotate, resize, crop, and reorder. There is no documented manual exposure compensation, focus point, metering, white balance, HDR, or zoom control. [12][13]

**Real-time guidance.** Adobe documents exactly three states: [12]

1. **Looking for document** — searching for the document and trying to detect boundaries.
2. **Capturing… hold steady** — edge detection can see the entire document and the app is confident enough to capture.
3. **No document found. Capture manually** — the app cannot detect the edges; the user can tap the shutter.

There is no documented glare, shadow, "move closer/farther", or "flatten page" coaching. The blue dots are the main visual feedback. Auto-capture is the default; manual fallback is explicit. [12][13]

**UX flow.** Capture → optionally adjust borders → keep scanning or retake → review thumbnails → edit (crop, straighten, rotate, filter, brightness/contrast, cleanup, resize, reorder, delete, add) → Save PDF to Adobe cloud. [12][13]

**What users complain about.** The most concrete complaint is the **blue rectangle locking onto part of the page**. Adobe community users report that auto-capture "is never covering an entire page but just the text" and that the outline persists even when auto-capture is off. [14] Visible App Store reviews also complain about forced cloud upload and crashes with large PDFs. [34]

**Lesson.** Adobe proves the value of a clear three-state model and confidence-gated capture. It also shows the danger of **coupling auto-capture to auto-crop**: users cannot get the crop without false triggers. Auto-detect/crop should always be available; auto-capture should be a separate, conservative option. Adobe Research's capture-gating model is summarized in §4. [30]

### 3.5 CamScanner

**Camera pipeline.** CamScanner has auto-capture and auto-crop toggles on the capture screen. It supports single, batch, book, ID card, PPT, whiteboard, and test-paper modes. In Book mode, the user aligns two pages and matches a guide line to the binding; the app splits the spread into pages. Auto-capture and auto-crop can be turned off from the three-dot menu. [15]

**Automatic tuning.** Auto crop/enhance, filters, shadow removal, moiré/bleed/finger cleanup, orientation, HD resolution, and tap-to-focus advice. FAQ tips (fill the viewfinder, tap to focus, good light, avoid shadows/glare, hold steady, adjust distance) are post-failure advice, not necessarily live messages. [15]

**Turn Page to Auto Capture.** Announced in 2025 for books/multi-page documents. The user captures page one manually, then turns pages. A deep-learning algorithm analyzes hand movements, lighting changes, shadows, and book colors; it detects a page turn, waits for the page to **settle, be unobstructed, and be clear**, then captures. It triggers only after a page-turn action to avoid duplicates. At announcement it was **iOS-only**. [16]

**Guidance and UX.** Edge outline + auto-capture are the main feedback; no rich message set documented. FAQ: "Photos are blurry" → HD, good light, avoid shadows/glare, hold steady, tap to focus; if the image is not sharp, the app cannot fix it. Flow: capture → crop/enhance → filter → review/reorder/retake → OCR → export PDF/JPG/Word. OCR supports 40+ languages; some AI features require internet; ads/watermark/premium on free tier. [15]

**Lesson.** Book/ID/batch modes and page-turn detection are valuable, but monetization and opaque defaults destroy trust: visible 2026 Play reviews include complaints about full-screen ads, and the FAQ itself is mostly blur/enhancement troubleshooting. The differentiators should be offline privacy, no ads/watermark, and explicit enhancement, not more modes. [15][33]

### 3.6 Apple Notes / VisionKit / Continuity Camera

**Camera pipeline.** Apple's document scanner is a system camera pass-through. In Notes or Files, the user taps Scan Documents; the scanner detects edges and perspective. In iOS 26, the user can select flash or an image filter at capture. If the device is in **Auto** mode, the document is scanned automatically; the user can always tap the shutter or press a volume button to capture manually, then drag the corners and tap **Keep Scan**. Additional scans can be added before Done. [17][18]

**Automatic tuning.** VisionKit auto-enhances: deskew, flatten, contrast. It has edge detection, auto-capture, torch, perspective correction, and user guidance. Filters: Color, Grayscale, Black & White, Photo. No developer control over exposure, focus, WB, HDR, or zoom; the flash/filter UI is system-provided and not exposed via API. [17][19]

**Guidance and UX.** Blue outline around the detected page; "keep your iPhone steady"; preview thumbnail. Subtle, non-blocking, consistent; no documented glare/shadow coaching. Flow: scan → auto/manual → adjust corners → Keep Scan → add more → review/edit → Done. VisionKit provides **no gallery import** and returns `UIImage` only; the app builds PDF/export. Continuity Camera reuses the same scanner from a Mac and returns a PDF. [17][18][19][20]

**API limits.** `VNDocumentCameraViewController` is iOS 13+; the UI is closed. Developers cannot hide buttons, change colors, add a flash control, limit scans, or receive custom guidance callbacks. Scanbot reports a built-in ceiling of about **24 scans per session** and iOS 26 UI bugs. [19][29] Apple exposes no API to disable auto-capture; users can switch to manual, but apps cannot force manual-only. Standard UIKit controls inherit system localization and VoiceOver; the volume-button shutter is a strong motor-accessibility pattern.

**Lesson.** Apple is the benchmark for **zero-config default + manual escape hatch**: auto mode on, shutter always available, a clear hold-steady moment, then review.

### 3.7 Samsung Camera Document Scan / Samsung Notes

**Camera pipeline.** On recent Galaxy devices, the Camera app shows a **Scan** button in Photo mode when a document is detected. The user taps Scan, waits for processing, previews the result, and saves. A dedicated multi-scan mode supports continuous capture. Samsung Notes has a separate scan flow: create a note → plus → Scan; it highlights edges in **yellow**, auto-straightens, flattens, and adds contrast; supports multiple pages; lets users reorder pages; and bakes OCR into the device. It does not require an account or show ads. [21][23]

**Automatic tuning.** Samsung's Galaxy S26 documentation is unusually specific: enhanced de-warp corrects folds (up to two folds, 130–180°) and flattens book pages; camera tilt up to 20° is supported; smart distraction removal handles fingers, folded corners, and moiré (needs ≥0.7 cm gap; fails on fully obscured content, tiny distractions, or unusual colors such as tattoos/nail art); four filters (Clean, Natural, Grayscale, B&W); default/high/low resolution. Recognition works best when text is ≥20% of the document area, all four corners are visible, and the page fills ≈80% of the screen. Small documents should use zoom rather than extreme close-up. [22]

**Guidance and UX.** Yellow outline is the main overlay; the Scan button is a strong implicit framing instruction. No documented glare/shadow/move message set. Flow: Camera single scan → preview → save; or multi-scan → review → reorder/add/delete → PDF/images; or Samsung Notes for OCR/annotation/export. Gallery also exposes a scan button when text is detected. [21][23]

**Lesson.** Samsung shows how far **geometry-gated capture + strong post-processing** can go. Copy the "Scan button appears only when a document is detected" pattern and use its thresholds as a starting point; do not copy the device fragmentation or opaque AI cleanup limits (shadow/reflection removal in Notes may require a Gallery round-trip).

### 3.8 Open-source scanners

**OpenNoteScanner.** Android, OpenCV 3.1, GPLv3, requires OpenCV Manager. The user places four corner markers inside the page and taps the camera icon; the app detects, draws a green outline, and takes the photo. "Automatic Mode" only works with a special printed page containing a QR code; normal auto detection requires manual mode. Low-contrast backgrounds fail; the FAQ recommends a dark background, flash, and keeping markers inside the page. Pipeline: 500 px analysis, grayscale, 5×5 blur, Canny 75/200, contours, `approxPolyDP` 0.02×perimeter, four-point hot-area check, perspective warp, adaptive threshold 225/15 for B&W; continuous AF with center metering, torch, still matched to preview. **No blur/stability/glare checks, auto-capture confidence, multi-page review, or guidance.** [24][25][26]

**OpenScan.** A privacy-focused Flutter scanner: local PDF/JPG export, cropping, filters, compression, no ads/account; Play rating 3.6/5 from ~589 reviews. No documented live edge detection or auto-capture; useful as a minimal local-only Flutter reference, not advanced coaching. [27]

**Documind.** No canonical open-source mobile camera scanner named "Documind" could be verified. GitHub `DocumindHQ/documind` is a **document data-extraction platform for PDFs**, not a camera scanner; App Store "DocuMind" apps are unrelated and closed-source. Excluded from the camera comparison rather than guessed at. [28]

**Lesson.** The classic OpenCV pipeline is cheap and offline but brittle. It needs a quality gate and a UX layer to be usable by non-experts.

## 4. Published thresholds and algorithm details

Most commercial vendors do not publish confidence thresholds. The concrete public data points are Samsung's usability guidance, Adobe Research's capture model, OpenNoteScanner's source, and a third-party Vision rectangle example.

| Source | Published detail |
|---|---|
| **ML Kit** | API 21+; **1.7 GB** minimum total RAM; ~300 KB app-size impact; automatic capture, edge detection, auto rotation; no published confidence/quality thresholds. [2] |
| **Google Drive 2026** | **8 GB RAM** minimum for the new high-performance scanner; smart batch, auto-best frame, duplicate detection; no published thresholds. [7][8] |
| **Samsung S26** | Text ≥**20%** of document area; document ≈**80%** of screen; all four corners visible; folds ≤**2**, fold angle **130–180°**; camera tilt ≤**20°**; distraction removal needs ≥**0.7 cm** gap. [22] |
| **Adobe Research** | Page-change network 64×64 grayscale CNN-LSTM; capture network MobileNetV2 320×320; capture threshold **0.6** runs the expensive model on **3.7%** of frames; F1 **0.94** (one-capture) / **0.96** (multi-capture) at 0.6; peak 0.97 at threshold 0. [30] |
| **Adobe Scan** | Three-state message machine; "Capturing… hold steady" when confident that a complete document is in range; no numeric threshold published. [12] |
| **CamScanner** | Deep-learning page-turn detector; waits for page stable, unobstructed, and clear; triggers only after a page-turn action; no numeric thresholds published. [16] |
| **Apple / VisionKit** | Auto-capture, edge detection, perspective, auto enhancement; no thresholds/confidence API published; Scanbot reports a ~24-scan session ceiling. A third-party `VNDetectRectanglesRequest` example uses confidence **0.6**, min size **0.3**, aspect **0.3–1.0** — app-level, not Apple's internal scanner. [19][29][31] |
| **OpenNoteScanner** | 500 px analysis; 5×5 blur; Canny **75/200**; approxPolyDP **0.02×perimeter**; adaptive threshold **225/15**; QR duplicate suppression **15 s**. [25] |

### 4.1 Recommended starting thresholds

These are **engineering starting points**, not vendor-published values. Calibrate on real devices; absolute blur/glare numbers vary by sensor, lens, and lighting.

| Signal | Starting rule | Action |
|---|---|---|
| Page area | **55–85%** of frame; hard accept **40–92%** | <45% → "Move closer"; >90% → "Move farther"; outside 20–95% → don't auto-capture |
| Corners | All four inside frame with ≥**2%** margin; convex; no self-intersection | Missing/touching edge → "Fit all four corners" |
| Aspect ratio | **0.55–1.6** for documents; **1.2–1.8** for ID cards | Reject extreme slivers; don't auto-capture ID as document |
| Temporal stability | Same quad IoU ≥**0.85** for **5–8** frames (~400–600 ms at 10–15 fps); corner angles 60–120° | "Hold steady"; only then count toward capture |
| Sharpness | Laplacian variance on a ~1 MP grayscale text ROI; calibrate so the bottom decile fails. Start around **100** (OpenCV units) and tune per device; also check Tenengrad | "Blurry — hold still" or "Tap to focus"; don't auto-capture |
| Exposure | Mean luma **90–180** (8-bit); clipped highlights **<2–5%** of page; shadow gradient **<35–45%** luminance drop | "More light" if <70; "Reduce glare" if clipped; adjust exposure compensation if available |
| Glare | Bright pixels (>250) within page **<1–2%** | "Glare — tilt slightly"; don't fire flash if it increases clipping |
| Auto-capture | 8–10 consecutive good frames + **300–500 ms** hold; **1.5–2 s** cooldown; gyro <0.05 rad/s or <1–2 px displacement | Capture once; show thumbnail; don't re-trigger on the same page |
| Duplicate | dHash Hamming ≤**5/64** or SSIM >**0.95** on the warped page | Skip duplicate; offer "Keep anyway" |
| Best frame | Buffer 5–10 frames; score sharpness **40%**, edge **30%**, exposure **20%**, low glare **10%** | Choose best frame at trigger, not necessarily the trigger frame |
| Page completeness | Text/content bounding box ≥**2%** from crop edge; no content touching frame edge | "Page may be cut off"; "Retake" / "Use anyway" |

Important: do **not** copy one absolute blur threshold across devices. Use a normalized score and a short per-device calibration (e.g., a test pattern at first run, or learn from accepted/retaken pages). The same applies to glare and shadow.

## 5. Real-time guidance: what products do and how to prioritize

### 5.1 Observed guidance models

| Product | Primary cue | Text | Audio/haptic | Auto-capture indication | Blocking? |
|---|---|---|---|---|---|
| Adobe Scan | Blue corner dots + outline | "Looking for document" → "Capturing… hold steady" → "No document found. Capture manually" | None documented | "Capturing… hold steady" + preview | Subtle; manual fallback message |
| Apple Notes / VisionKit | Blue outline | "Hold steady" while scanning | System haptics/sounds; VoiceOver labels | Preview thumbnail | Subtle |
| Samsung Camera | Yellow outline; Scan button | None documented | System shutter/haptics | Scan button | Subtle |
| Google Drive | Blue crop line | None documented | None documented | Auto toggle + pause; thumbnails | Subtle |
| Microsoft Lens | Orange frame | None visually; TalkBack directional voice | TalkBack voice guidance | Manual shutter; auto-flash | Subtle |
| CamScanner | Edge outline | No documented message set; FAQ tips after failure | Shutter sound | Auto-capture toggle; thumbnail | Subtle |
| ML Kit scanner | System outline/UI | System UI only | System | System auto-capture | Subtle |
| OpenNoteScanner | Green outline + corner markers | None | Shutter sound | Green outline then photo | Subtle |

### 5.2 A defensible priority order

When multiple conditions are true, show **one** instruction, in this order:

1. **Page presence** — "Point at a page." (No outline or an invalid quad.)
2. **Framing** — "Fit all four corners" / "Move closer" / "Move farther." (Quad exists but incomplete, too small, or clipped.)
3. **Stability** — "Hold steady." (Geometry good, but motion/focus/exposure not settled.)
4. **Quality** — "Blurry — hold still" / "More light" / "Glare — tilt slightly" / "Avoid shadow." (Only when measurable and actionable.)
5. **Capture** — "Capturing…" + progress ring/haptic.
6. **Confirmation** — "Page 3 captured" + thumbnail; cooldown.
7. **Fallback** — "No page found — tap to capture." (After ~2–3 s without a valid quad.)

Why this order: framing errors are the most common and most fixable; telling someone to hold steady when the page is half out of frame is useless. Stability is the next prerequisite for a sharp still; auto-capture before focus/exposure settle is the main cause of blur. Lighting/glare messages are only useful if the user can act. Capture confirmation should be multimodal because the user may not be looking at the status text.

### 5.3 Message design rules

- **One message at a time.** Never stack "move closer" + "hold steady" + "too dark."
- **Minimum display time 1.5–2 s.** Don't flicker between states.
- **Repeat cooldown 4–6 s.** If the condition persists, keep a persistent chip but don't re-announce every frame.
- **Tie the message to a visual anchor.** Outline the page and highlight the problem area (e.g., dashed edge where content is clipped).
- **Do not block the viewfinder.** Use a bottom chip/banner or a small status line; reserve modals for permission rationale and manual fallback.
- **Use color + shape + text.** A blue outline alone fails color-blind users and bright sunlight; add corner ticks, dash pattern, and an icon.
- **Make the manual shutter always available** and visually stable; auto-capture is an enhancement, not a replacement.
- **Respect silent mode and regional shutter rules.** Haptics are usually safe; camera shutter sound may be mandatory in some regions.
- **Localize short, action-first strings.** "Move closer" is easier to translate than "The document appears to be too small in the frame."

### 5.4 Auto-capture indication

The best pattern is a **two-stage confirmation**:

1. **Acquiring:** solid outline + small progress ring + "Hold steady."
2. **Capturing:** ring completes, shutter animation/flash, medium haptic, thumbnail slides in, "Page 3 captured."

Do not rely on the outline changing color alone. Do not capture silently with no countdown; users need to know why the shutter fired. Do not re-arm immediately; wait 1.5–2 s and require the page to change or the user to tap "Next page."

## 6. UX flow, permissions, privacy, and offline behavior

### 6.1 Table stakes

- **Multi-page capture without leaving the camera.** Count visible at all times ("Done (7)").
- **Thumbnail rail / page strip.** Last page preview, tap to review; drag to reorder.
- **Retake / delete / add page.** Per page, not just the last one.
- **Review after Done.** Crop, rotate, filter, reorder, delete, retake; "Save" and "Export" clear.
- **Import fallback.** Gallery, file picker, or PDF import. Never trap the user if the camera fails or permission is denied.
- **Draft persistence.** Save after each page; recover after app kill.
- **Permission rationale.** Explain camera use before the system prompt; offer import if denied.
- **Offline clarity.** Say what stays on device and what uploads (if anything).
- **Page limit / memory guard.** Prevent runaway captures; show a clear limit and graceful stop.
- **Accessible controls.** Large shutter, volume-key shutter, TalkBack labels, haptics.

### 6.2 Differentiators worth investing in

- **Specific, calm coaching** (glare/shadow/blur/completeness) — most competitors do not do it live.
- **Auto-capture with a transparent confidence state** — show why it is waiting; let the user pause/toggle.
- **Best-frame selection** — buffer a few frames and pick the sharpest, rather than trusting the trigger frame.
- **Duplicate detection** — especially for book/workbook scanning.
- **Page completeness warning** — "Page may be cut off" before the user leaves the camera.
- **Color preservation by default** — neutral/Original filter, optional B&W; never silently force enhancement.
- **Book/spread mode** — binding line, left/right split, page-turn auto-capture (later).
- **Offline privacy** — no account, no ads, no watermark, no upload; a direct contrast to CamScanner/Adobe/Drive.

### 6.3 Permissions, data flow, and offline claims

| Product | Permission model | Where data goes | What the user is told |
|---|---|---|---|
| **ML Kit scanner** | Host app needs no camera permission; Play Services owns the camera | On-device; user chooses which scanned files to share back | On-device processing; low APK impact |
| **Google Drive** | Camera permission in Drive; Google account | On-device processing, then upload to Drive | Drive privacy page; content not used for advertising |
| **Microsoft Lens** | Camera + storage; optional Microsoft account | Local or OneDrive/OneNote/Word/PowerPoint | Cloud save prompts; retirement notice points to OneDrive |
| **OneDrive** | Camera + Microsoft account | Cloud auto-save; no local-only scans | Files automatically saved as PDFs to OneDrive |
| **Adobe Scan** | Camera, storage, optional account | Adobe Document Cloud by default | Account/cloud prompts; save originals to gallery option; cellular-data toggle |
| **CamScanner** | Camera + storage | Local and/or CamScanner cloud | Cloud sync/OCR prompts; ads/watermark; premium |
| **Apple Notes / VisionKit** | Camera usage description in Info.plist | On-device; iCloud only if the note is stored there | Standard iOS permission prompt; no account required for local use |
| **Samsung Camera / Notes** | Camera + storage | Local Gallery/Samsung Notes; cloud only if user syncs | Native app permissions; no ads; Samsung account optional |

The strongest trust position for our app is the combination of **offline, private, no account, no ads, no watermark, no upload, and a release manifest without INTERNET permission**. The permission rationale should say that plainly before the system prompt, and the import fallback should remain available if camera permission is denied.

## 7. Accessibility and internationalization

### 7.1 What good looks like

- **Visual:** high-contrast outline (not color-only), 3–4 px stroke, corner ticks, dashed vs solid state, large status text; adapt to theme/sunlight; scrim behind critical text.
- **Audio/haptic:** optional short spoken cues via TalkBack/`SemanticsService.announce`, throttled to state changes; light impact on page acquisition, medium at capture, success on save. Respect silent mode.
- **Motor/cognitive:** large shutter, volume-key shutter, one-handed reach, no precision dragging; one instruction at a time; plain language ("straighten", not "perspective correction"); persistent manual escape.
- **Screen reader:** label preview, torch, AC toggle, shutter, thumbnail rail, page count; announce state changes, not the whole UI; avoid focus traps.
- **Permission:** explain why before the system prompt; offer "Import instead"; if denied, keep the app usable and show Settings.
- **Internationalization:** short action-first strings; ICU plurals; RTL mirroring; Devanagari line height/font fallback; locale-aware numbers/dates; test German/Turkish length; keep OCR language separate.
- **Regional:** shutter sound may be mandatory; flash may be restricted; privacy expectations vary.

The only product in this set with documented real-time directional audio guidance is Microsoft Lens, which uses TalkBack to say "move right" / "move up." Apple's system scanner inherits VoiceOver and offers a volume-button shutter; ML Kit's fixed UI cannot be customized for app-specific accessibility. This is a clear differentiation area.

### 7.2 Guidance copy catalog (English starter set)

Keep each string short and localizable. Avoid concatenation; use full messages.

| State | Primary copy | Secondary/visual |
|---|---|---|
| Searching | "Point at a page" | Dashed frame |
| Too small | "Move closer" | Shrink/grow arrows |
| Too large/clipped | "Move farther" or "Fit all four corners" | Corner ticks turn solid |
| Off-center | "Center the page" | Edge highlight |
| Unstable | "Hold steady" | Progress ring begins |
| Blurry | "Blurry — hold still" | Focus reticle / warning chip |
| Low light | "More light" | Torch suggestion |
| Glare | "Glare — tilt slightly" | Highlight clipped area |
| Shadow | "Avoid shadow" | Shadow-side chevron |
| Curved page | "Flatten the page" | Curvature hint |
| Capturing | "Capturing…" | Ring completes, haptic |
| Captured | "Page 3 captured" | Thumbnail, count |
| No detection | "No page found — tap to capture" | Shutter emphasized |
| Cut-off risk | "Page may be cut off" | "Retake" / "Use anyway" |
| Auto off | "Auto-capture off" | Manual shutter only |

**Screen-reader priority:** announce only when the actionable state changes (searching → framing → hold steady → capturing → captured), never every 500 ms; use earcons/haptics for continuous feedback; provide a "Describe scene" action that reads page detection, lighting warning, and auto-capture state on demand.

## 8. Common failure modes and complaints

| Failure | Why it happens | Evidence | Mitigation |
|---|---|---|---|
| **Auto-capture false triggers** | Edge detector sees hands, floors, mugs, table rectangles; no temporal/quality gate; fires as soon as a quad appears | Adobe community: blue rectangle captures only part of page; Adobe default AC; Drive adds pause | Two-stage AC; 8–10 good frames; geometry + quality gate; cooldown; duplicate hash; permanent manual shutter; pause/toggle |
| **Missed pages / duplicates** | Page turns/occlusion; AC stops; no page-change model; user moves too fast | CamScanner Turn Page waits for stable/unobstructed page; Drive duplicate detection + smart batch; Adobe Research page-change model | Thumbnail count; "Add page" always; page-change detection later; review step; duplicate detection |
| **Blurry scans** | Motion/focus not settled; AC fires before AF/AE; small text; low light | CamScanner FAQ: hold steady, tap focus, good light; blur cannot be fixed post-hoc | Lock focus/exposure before capture; Laplacian/Tenengrad gate; 400–600 ms hold; best-frame buffer; "Tap to focus" |
| **Glare / shadows** | Direct light, glossy paper, flash reflection, phone/lamp shadow | CamScanner FAQ: avoid shadows/glare; Samsung/Adobe cleanup | Detect clipped highlights and shadow gradient; "Tilt slightly" / "Avoid shadow"; torch only when it helps; preserve original |
| **Crop cuts content** | Auto-crop too tight; low contrast; margins/handwriting ignored | Adobe community partial-page complaint; CamScanner auto-crop toggle | 2–5% margin; text bbox check; crop overlay; manual crop; "Page may be cut off" |
| **Low light / harsh flash** | No night mode; flash blows out center; AF hunts | Lens auto flash; CamScanner: use flash/good light; Adobe flash auto | Auto torch with luma + clipping check; exposure compensation; "More light"; bracket/fusion later |
| **Opaque enhancement / cloud friction** | Auto-classification, default filter, cloud save, sign-in | CamScanner filters; Adobe cloud default; OneDrive cloud-only | Preserve original; neutral default; explicit filter; local save; no account |
| **Device/OS/accessibility gaps** | Play Services/RAM gates; One UI differences; API limits; visual-only guidance | ML Kit 1.7 GB; Drive 8 GB; Samsung availability; VisionKit ~24 scans; only Lens documents TalkBack guidance | Capability check; graceful fallback; import; manual mode; haptics/TalkBack; large text; color-blind-safe outline |

**What users complain about, in rough order of impact:**

1. **Ads/monetization** — CamScanner's visible 2026 Play reviews are dominated by full-screen ads interrupting a scan. [33]
2. **Auto-capture false triggers** — Adobe's default AC and the blue rectangle locking onto part of the page. [14]
3. **Blur/low resolution** — CamScanner's FAQ is largely a blur-prevention guide; Drive's Auto-Best Frame responds to blurry captures. [7][15]
4. **Crop/cloud/fragmentation** — Adobe partial-page captures; CamScanner auto-crop toggle; Adobe cloud default; OneDrive no local-only; 1.7–8 GB RAM gates; Samsung feature availability varies. [2][7][8][10][13][14][15][23]

## 9. Prioritized patterns worth adopting

### P0 — Build before shipping the new camera

1. **Manual-first, auto-capture optional and confidence-gated.** Permanent shutter, AC toggle, pause; 8–10 good frames, stable geometry, settled focus/exposure, low motion, no glare, page 55–85% of frame; 1.5–2 s cooldown; duplicate hash.
2. **One prioritized guidance state machine.** searching → framing → stabilizing → quality-blocked → capturing → captured → cooldown; one message at a time; 1.5–2 s minimum; 4–6 s repeat cooldown; outline + corner ticks + progress ring + haptic; manual fallback after 2–3 s without a quad.
3. **Geometry/completeness gating.** Four corners inside ≥2% margin; convex; aspect 0.55–1.6; area 40–92%; angles 60–120°; text/content bbox ≥2% from crop edge; warn "Page may be cut off."
4. **Post-capture quality gate with specific reasons.** Blur, glare, shadow, exposure, crop margin, curvature; "Retake because it's blurry" beats "poor quality"; allow "Use anyway."
5. **Multi-page rail with retake/reorder/delete/import.** Count in the app bar; drag to reorder; tap to review; "Add page" always; import from gallery/PDF; save drafts after each page.
6. **Offline/privacy permission UX.** Rationale before the prompt ("Pages stay on this phone. No account, no upload."); if denied, offer import; release build keeps no Internet permission; no ads/watermarks.

### P1 — High value, moderate effort

7. **Auto AF/AE/metering with override.** Continuous AF, ROI metering on the page, small exposure compensation, torch auto/off/on; lock focus/exposure immediately before capture.
8. **Subtle, actionable glare/shadow/light coaching.** Only when measured; combine with torch/exposure/post-processing; don't fire flash if it increases clipping.
9. **Best-frame selection and duplicate detection.** Buffer 5–10 frames; pick sharpest/exposure-best; dHash/SSIM duplicate skip with "Keep anyway."
10. **Color preservation and explicit filters.** Default Original/neutral; Grayscale/B&W/Enhance opt-in; "Apply to all pages" only on request; keep original separate.
11. **Accessibility/i18n baseline.** Haptics, TalkBack labels/announcements, large text, color-blind-safe outline, volume-key shutter, RTL/Devanagari.

### P2 — Differentiators / later

12. **Book/spread mode.** Manual first page, then page-turn detection; wait for stable/unobstructed/clear; no overpromised dewarping; "Retake" when confidence is low.
13. **Smart batch/hover scanning.** Only on capable devices; pause; auto-split; duplicate detection.
14. **ML Kit "Quick scan" fallback.** Optional, Play Services-dependent, cached-resources-only; disclose first-use download; never block the normal camera.

### Do not copy

- **Adobe's aggressive default AC** and coupling of auto-crop to auto-capture.
- **CamScanner's ads, watermarks, and opaque enhancement defaults.**
- **Apple VisionKit's opaque AC** with no API to disable or limit pages.
- **Google Drive's 8 GB RAM gate** and sparse auto feedback.
- **Samsung's device fragmentation** and AI cleanup limits presented as universal.
- **Lens's manual-first long-document flow** and platform-retirement risk.
- **OpenNoteScanner's OpenCV-only pipeline** without quality gates or coaching.

## 10. Implementation blueprint for a Flutter Android camera

### 10.1 Camera pipeline

Use a **custom CameraX-based pipeline**, not the ML Kit black box:

- **Preview** at 30 fps for the viewfinder.
- **ImageAnalysis** at 720p/1080p, 10–15 fps, YUV_420_888, for edge detection and quality metrics.
- **ImageCapture** at the highest still resolution the device supports.
- **Torch/flash** control independent of capture.

The Flutter `camera` plugin is fine for a prototype and exposes focus, exposure, zoom, and flash controls on Android. For production, a small native CameraX platform channel is safer because it lets preview, analysis, and still capture use different resolutions; many Flutter camera setups otherwise couple them. [37]

### 10.2 Camera tuning

- Start with continuous AF and center/ROI metering. On page detection, move the focus/exposure point to the page centroid. Lock both immediately before capture; unlock after.
- Use exposure compensation sparingly; check the supported min/max range and handle devices that report a zero step.
- Torch: `FlashMode.auto` for stills; `FlashMode.torch` only for low-light preview when the user enables it or the app decides it helps. Avoid firing the flash when the page is glossy and clipping is already high.
- Keep zoom at 1× by default; suggest moving closer or using zoom only when the page is small and the lens cannot focus at close range (Samsung's guidance makes the same point). [22]
- Leave HDR/WB to the camera HAL unless device testing shows a consistent win; do not add a manual WB slider in v1.

### 10.3 Analyzer

- Downscale to 480–720 px long side; grayscale; Gaussian blur; Canny/contour + `approxPolyDP` or Hough lines; track the quad with EMA/Kalman; compute IoU across frames.
- Compute quality metrics on the **warped page ROI**, not the whole frame:
  - Laplacian variance / Tenengrad for sharpness.
  - Mean luma and clipped-highlight ratio for exposure/glare.
  - Horizontal/vertical illumination gradient for shadow.
  - Text/content bounding box for completeness.
  - Frame-to-frame motion or gyro magnitude for stability.
- Feed a small state machine; do not let the UI read raw metrics directly.
- Drop frames while the previous analysis is running; never block the preview thread.

### 10.4 Capture state machine

```
searching
  └─ valid quad → framing
framing
  ├─ too small → "Move closer" → framing
  ├─ too large/clipped → "Move farther" / "Fit all four corners" → framing
  ├─ off-center → "Center the page" → framing
  └─ geometry good → stabilizing
stabilizing
  ├─ motion/focus/exposure not settled → "Hold steady" → stabilizing
  ├─ quality fail → "Blurry" / "More light" / "Glare" → quality_blocked
  └─ 8–10 good frames + 300–500 ms → capturing
capturing
  └─ takePicture / best frame → processing
processing
  ├─ quality fail → "Retake because …" → review/retake
  └─ success → captured → cooldown (1.5–2 s) → searching
```

Rules:

- Auto-capture only from `stabilizing`; never from `framing` or `quality_blocked`.
- Manual shutter works in every state.
- `cooldown` suppresses the same page; require the quad to change or the user to tap "Next page."
- Show a progress ring during `stabilizing`; complete it at capture.
- If no valid quad for 2–3 s, show "No page found — tap to capture" and keep the shutter prominent.

### 10.5 Post-capture

- `takePicture` at full resolution; run the OpenCV page detection/perspective warp.
- Run a full-res quality gate; record scores and reasons in the page metadata.
- Save the original and the processed copy separately; never overwrite the original.
- Update the thumbnail rail and count; show a short "Page 3 captured" confirmation.
- If quality fails, keep the page but mark it "Needs review" and show the reason; offer "Retake" and "Use anyway."
- Async: never block the camera UI on enhancement/OCR. Show progress and allow "Done" later.

### 10.6 UI and copy

Top: close/back, flash, AC toggle, torch, more. Center: preview + outline + status chip + progress ring. Bottom: thumbnail rail (last 3–5 + count), large shutter, "Done (n)". Review: full-page preview, crop, rotate, filter, retake, delete, reorder, "Use anyway." Empty/error: "Camera unavailable — import images instead." Copy is short, calm, action-first: "Move closer", "Hold steady", "More light", "Glare — tilt slightly", "Page may be cut off" — not "Document too small", "Motion detected", "Low luminance", or "Content bounding box violation."

### 10.7 Metrics to evaluate

Track auto-capture precision/recall, time-to-capture (target 0.6–1.2 s), retake rate by reason, OCR accuracy on Devanagari/small print, page completeness, manual override rate, crash/ANR rate on 2–4 GB devices, and TalkBack task completion/repeated announcements.

## 11. Sources

All sources were accessed on **2026-11-07** unless a publication date is given. Product behavior may change with app/OS updates; Microsoft Lens is retired, and Google Drive's new scanner is still rolling out by device/RAM tier.

### Official docs and help

- **[1]** Google ML Kit, "Document scanner" overview. https://developers.google.com/ml-kit/vision/doc-scanner
- **[2]** Google ML Kit, "Document scanner with ML Kit on Android." https://developers.google.com/ml-kit/vision/doc-scanner/android
- **[3]** Google ML Kit reference, `GmsDocumentScannerOptions`. https://developers.google.com/android/reference/com/google/mlkit/vision/documentscanner/GmsDocumentScannerOptions
- **[4]** Google ML Kit reference, `GmsDocumentScannerOptions.Builder`. https://developers.google.com/android/reference/com/google/mlkit/vision/documentscanner/GmsDocumentScannerOptions.Builder
- **[5]** Google ML Kit, "Release notes." https://developers.google.com/ml-kit/release-notes
- **[6]** Google Drive Help, "Scan documents with Google Drive" (Android). https://support.google.com/drive/answer/3145835?hl=en&co=GENIE.Platform%3DAndroid
- **[9]** Microsoft Support, "Microsoft Lens for Android." https://support.microsoft.com/en-us/lens/microsoft-lens-for-android
- **[10]** Microsoft Support, "Retirement of Microsoft Lens." https://support.microsoft.com/en-us/lens/retirement-of-microsoft-lens
- **[11]** Microsoft Support, "Scan a whiteboard, document, business card, or photo in OneDrive for Android." https://support.microsoft.com/en-us/onedrive/scan-a-whiteboard-document-business-card-or-photo-in-onedrive-for-android
- **[12]** Adobe Scan for Android documentation, "Scan." https://www.adobe.com/devnet-docs/adobescan/android/en/scan.html
- **[13]** Adobe Scan for Android documentation, "Configure Adobe Scan." https://www.adobe.com/devnet-docs/adobescan/android/en/settings.html
- **[15]** CamScanner FAQ. https://www.camscanner.com/faq
- **[17]** Apple Support, "How to scan documents on your iPhone or iPad" (published 2026-02-13). https://support.apple.com/en-us/108963
- **[18]** Apple iPhone User Guide, "Scan text and documents in Notes using the iPhone camera." https://support.apple.com/guide/iphone/scan-text-and-documents-iph653f28965/ios
- **[19]** Apple Developer Documentation, `VNDocumentCameraViewController`. https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller
- **[20]** Apple Support, "Continuity Camera: Use your iPhone or iPad to scan documents or take a picture on your Mac." https://support.apple.com/en-us/102332
- **[21]** Samsung Support, "Scan and edit documents on your Galaxy phone or tablet." https://www.samsung.com/us/support/answer/ANS10003696/
- **[22]** Samsung Members / CamCyclopedia, "Document Scan" (Galaxy S26, 2026). https://r2.community.samsung.com/t5/CamCyclopedia/Document-Scan/ba-p/21857429

### Vendor engineering, research, and design material

- **[7]** 9to5Google, "Google Drive rolling out powerful document scanner redesign" (2026-05-29). https://9to5google.com/2026/05/29/google-drive-document-scanner-wide/
- **[8]** Android Authority, "Google Drive's big document scanner overhaul is finally here" (2026-05-29). https://www.androidauthority.com/google-drive-scanner-ui-upgrade-3672777/
- **[16]** CamScanner Blog, "CamScanner Introduces 'Turn Page to Auto Capture'…" (2025-11-10). https://blog.camscanner.com/2025/11/10/camscanner-introduces-turn-page-to-auto-capturefeature-for-effortless-document-digitization/
- **[30]** Adobe Research, "Handheld Video Document Scanning: A Robust On-Device Model for Multi-Page Document Scanning," arXiv:2411.00576. https://arxiv.org/html/2411.00576v1
- **[31]** "A Document Scanner in an Afternoon: VisionKit's Camera, Core Image Clean-Up and AirPrint" (2026-10-22). https://bestlatestapps.com/blog/a-document-scanner-in-an-afternoon/
- **[37]** Flutter `camera` package. https://pub.dev/packages/camera

### Reviews, comparisons, and community evidence

- **[14]** Adobe Support Community, "Turn off auto scan." https://community.adobe.com/questions-517/turn-off-auto-scan-12920
- **[23]** Android Police, "Why didn't anyone tell me Samsung Notes could completely replace my paid scanner app?" (2026-03-13). https://www.androidpolice.com/samsung-notes-scanner-feature/
- **[24]** OpenNoteScanner README. https://github.com/allgood/OpenNoteScanner
- **[25]** OpenNoteScanner `ImageProcessor.java`. https://github.com/allgood/OpenNoteScanner/blob/master/app/src/main/java/com/todobom/opennotescanner/ImageProcessor.java
- **[26]** OpenNoteScanner FAQ. https://github.com/allgood/OpenNoteScanner/blob/master/FAQ.md
- **[27]** OpenScan GitHub. https://github.com/ethereal-developers/OpenScan
- **[28]** DocumindHQ/documind (document extraction, not a camera scanner). https://github.com/DocumindHQ/documind
- **[29]** Scanbot SDK, "Comparing iOS document scanners: WeScan vs. VisionKit." https://scanbot.io/blog/ios-document-scanners-wescan-vs-visionkit
- **[32]** Google Play, Adobe Scan listing and reviews. https://play.google.com/store/apps/details?id=com.adobe.scan.android
- **[33]** Google Play, CamScanner listing and reviews. https://play.google.com/store/apps/details?id=com.intsig.camscanner
- **[34]** Apple App Store, Adobe Scan listing and reviews. https://apps.apple.com/us/app/adobe-scan-pdf-doc-scanner/id1199564834
- **[35]** Apple App Store, CamScanner listing and reviews. https://apps.apple.com/us/app/camscanner-pdf-scanner-app/id388627783
- **[36]** Google Maven, `play-services-mlkit-document-scanner:16.0.0` AAR manifest inspection (no `CAMERA`/`INTERNET` permission declared). https://dl.google.com/dl/android/maven2/com/google/android/gms/play-services-mlkit-document-scanner/16.0.0/play-services-mlkit-document-scanner-16.0.0.aar

### Access notes and limitations

- Adobe's official pages returned HTTP 403 to direct fetches; their text was read through the `r.jina.ai` proxy and matched the visible docs.
- Stack Overflow's VisionKit thread was blocked by Cloudflare; only the public title/snippet was used. CamScanner's help search API returned no usable results, so its official FAQ/blog were used. Samsung's official Notes scanner help page was not found; Samsung's camera support and Android Police were used for Notes, while the S26 CamCyclopedia article supplied the thresholds.
- Google Drive's 2026 scanner is rolling out by device/RAM tier; the 8 GB requirement applies to the new path. App-store review sampling was not systematic. No canonical open-source camera scanner named "Documind" was verified; it is excluded rather than guessed at.

## 12. Bottom line

The winning UX makes automation **legible, interruptible, and recoverable**: show the outline and one actionable instruction; capture only when the page is complete, stable, sharp, and reasonably exposed; keep the manual shutter, pause, and import fallback; review/reorder before export; preserve the original; stay offline, ad-free, and honest about permissions. That combination is rare and is exactly what a Flutter Android app with bundled OpenCV and an offline-first promise can deliver.
