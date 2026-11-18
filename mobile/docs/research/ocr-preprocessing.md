# Capture-time camera tuning and document preprocessing for offline Latin/Devanagari OCR

**Status:** research note for the VeriScript Android app  
**Date:** 2026-11-07  
**Scope:** still-photo and book-video capture; Google ML Kit (default) and RapidOCR/PaddleOCR ONNX (experimental); current native pipeline in `mobile/lib/processing.dart`, `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt`, and `RapidOcr.kt`.  
**Purpose:** decide what the camera should optimize, what post-processing should fix, and what cannot be recovered.

**Evidence labels used throughout**

- **[E] Evidence** — published documentation, peer-reviewed/preprint research, or a frozen measurement in this repository. The source is listed in §12.
- **[L] Local probe** — a small controlled experiment run for this note on 2026-11-07. Directional only: synthetic pages, one engine (RapidOCR), no confidence intervals, not a frozen product measurement. The method and raw numbers are in §11; they are reproducible with the repository’s `ocr_page` helper and the noted `data/doc_eval` sets.
- **[I] Inference** — a reasoned conclusion from [E]/[L], not directly measured here.
- **[U] Uncertainty** — needs a device/field test; do not ship as fact.

**Related internal notes.** `mobile/docs/research/document-capture-science.md` covers capture-science thresholds (resolution, exposure, focus, glare, auto-capture, per-device calibration) in more depth; `native-camera-architecture.md` evaluates CameraX/Camera2 architecture options. This note focuses on the OCR/preprocessing boundary and should be read alongside them.

---

## 0. Executive summary

1. **The current camera is likely the largest bottleneck, not the preprocessing.** `capture.dart` requests `ResolutionPreset.high`, which the Flutter camera plugin documents as roughly 720p. A full A4 page at 720p is about 60–90 DPI. A 10 pt Latin x-height is then about 4–6 px; ML Kit asks for at least 16×16 px per character, and Tesseract reports that x-heights below 10 px are unreliable and below 8 px are effectively removed. **[E]** for the thresholds; **[I]** for the DPI arithmetic. This is a much larger effect than any CLAHE/unsharp choice. The book-video path is worse: it uses the same ~720p preset and requests 1600 px frames (`OfflinePages.kt:339`), so the extra pixels are upscaling, not detail.
2. **The second-largest issue is likely resolution discarded before OCR.** `normalize` caps every imported image at max side 2500 (`OfflinePages.kt:41–69`, default `maxSide=2500`), and the RapidOCR path then resizes to max side 2000 (`RapidOcr.kt:214`). A4 at 2500 px (page filling the long side) is ~214 DPI; at 2000 px it is ~171 DPI. Both are below the 300 DPI that Tesseract recommends, and for small (8–9 pt) or Devanagari text they leave little margin above ML Kit's 16 px character guidance. The current 2× enlargement only fires when the *shorter* side is below 1000 px (`OfflinePages.kt:95`), so a low-DPI full A4 page is not enlarged.
3. **Post-processing should be conservative.** In a controlled degradation probe, Otsu binarization was catastrophic under shadow (CER 0.391 vs 0.035 raw) and under combined shadow+blur+noise+JPEG (0.405 vs 0.049). Sauvola was better than Otsu but still degraded blur/combined conditions. CLAHE hurt under shadow and noise. Mild unsharp masking helped blur (0.0397 → 0.0272). This matches the repository's earlier failure of Sauvola preprocessing on letterpress (1,754 invented tokens; raw retained) in `docs/EVALUATION.md`. **[L], [E]**
4. **Camera should optimize:** exposure without clipping, focus lock, resolution and framing so body text reaches roughly x-height ≥16 px (Latin) or line/akshara height ~40–50 px (Devanagari) in the OCR input, stability, and glare avoidance. **Post-processing should handle:** perspective/deskew, illumination flattening, mild contrast/color correction, conservative denoise/sharpening, and resampling. **Unrecoverable:** clipped highlights, motion blur, defocus, too-low resolution, and specular glare that saturates the strokes.
5. **Do not binarize by default** for ML Kit or RapidOCR. Both engines do internal normalization and expect grayscale/color. Binarization can disconnect Devanagari matras and headlines, break Latin serifs, and create isolated speckle that the detector reads as characters.
6. **Measure with paired pages and paired statistics.** The repository already has the right skeleton (`eval_document.py`, `eval_lines.py`, `compare_ocr.py`). Add a capture/degradation sweep that varies one factor at a time, keeps the original, and reports CER/WER/grapheme CER/digit-exact/ECE with paired bootstrap intervals. Thirty paired pages can resolve roughly 1–3.5 pp CER differences depending on variance; 200+ pages may be needed for ~1 pp, while 500+ line crops give tighter recognition-only intervals. **[I]**

---

## 1. Which image properties actually matter for OCR

OCR is two different problems on one page:

- **Detection** (finding lines/words) needs edges and local contrast at page scale. It is hurt by blur, low contrast, shadow boundaries, glare, and extreme skew.
- **Recognition** (mapping a line crop to characters) needs stroke shape at the recognizer's input height. It is hurt by too few pixels per stroke, noise, clipping, over-sharpening, and binarization that changes stroke topology.

The properties below are ordered by expected impact in this app.

| Property | Why it matters | Camera lever | Practical metric |
|---|---|---|---|
| **Text height in pixels** | The recognizer resizes each line to a fixed height (PP-OCR: 48 px). If the source line is below that, it is interpolated; below ~20–30 px, stroke and matra detail is already gone. ML Kit recommends ≥16×16 px/character and says there is little gain above 24×24. Tesseract targets ~20 px x-height at 10 pt/300 DPI; <10 px is poor; <8 px is removed. | Capture resolution, framing, optical zoom, distance | Median detected line-box height; estimated x-height/akshara height; DPI |
| **Stroke-to-background contrast** | Recognition depends on the dark/light difference at the stroke, not global contrast. Low contrast can be amplified, but not if the stroke is clipped or buried in noise. | Exposure, diffuse light, white balance, flat-field | Michelson/Weber contrast of text vs local background; 5th/95th percentile background range |
| **Sharpness / MTF** | Blur mixes adjacent strokes; Devanagari matras and conjuncts are especially vulnerable. Motion blur is directional; defocus is isotropic. | Shutter speed, OIS, focus lock, aperture/distance | Laplacian/Tenengrad variance on text regions; edge-width; no-reference document quality (CG-DIQA) |
| **Noise / SNR** | Noise creates false edges and speckle; denoising can erase thin strokes. Small pixels and high ISO make this worse. | Exposure (more light), lower ISO, pixel binning, avoid digital zoom | High-pass noise sigma; SNR in flat paper regions |
| **Illumination uniformity** | Shadows and gradients change the local threshold; a global threshold fails, and the recognizer's normalization may not fully compensate. | Diffuse multi-source light, avoid torch, angle to page, flat-field post | Background luminance coefficient of variation; max local background gradient; shadow mask area |
| **Highlight/shadow clipping** | A saturated white pixel has no stroke information. A crushed black pixel has no stroke separation. Neither is recoverable. | Exposure compensation, histogram check, HDR/bracketing, glare control | Fraction of pixels ≥250 and ≤5; per-channel clipping; specular mask area |
| **Geometry** | Skew reduces line segmentation; perspective changes stroke width; curvature needs dewarping. Small deskew is cheap; severe warp is not. | Square the camera, fill frame, avoid extreme angles | Page-quad angle; Hough skew; line straightness residual |
| **Compression artifacts** | Low-quality JPEG creates ringing around strokes, especially at low resolution; repeated re-encoding compounds it. | JPEG quality, avoid resaving, RAW/PNG intermediate | Blockiness/ringing metric; JPEG quality; generation count |
| **Color / white balance** | Mostly secondary for black text, but a strong cast changes grayscale contrast; colored text/matras can lose contrast in grayscale. | AWB lock or neutral reference; keep color original | Per-channel clipping; gray-world error; color cast ΔE on paper |
| **Glare/specular** | A specular highlight saturates the paper and the stroke underneath; inpainting cannot recover the glyph. | Diffuse light, no flash/torch on glossy paper, angle/polarizer | Saturated low-saturation region fraction; local max/median ratio |

**Camera settings → image properties**

| Camera setting | Primary image property | What to watch |
|---|---|---|
| Resolution mode, zoom, distance, framing | Text height / pixels per glyph | Page height 75–90% of frame; no digital zoom |
| Shutter time, OIS/EIS, ZSL, bracing | Motion blur | ≥1/60 s; 1/100–1/250 s preferred for text |
| AF mode/point, focus distance, aperture | Defocus / MTF | Lock AF after convergence; avoid macro at page edges |
| ISO, exposure time, aperture, light level | Noise / SNR | More light or lower ISO; avoid underexposure |
| Exposure compensation, metering point | Clipping / contrast | Paper ~70–85%; highlight clipping <1–2% |
| Aperture, lens, pixel size | Diffraction / sharpness | Stop down if available; do not force 48 MP if soft |
| Flash/torch, light geometry, diffusion | Glare / illumination uniformity | No point source on glossy paper; diffuse multi-source light |
| White balance / AWB lock | Color cast / grayscale contrast | Lock or use a white reference; avoid mixed lighting |
| HDR/tone mapping | Local contrast / halos | Neutral exposure fusion; avoid strong local tone mapping |
| JPEG quality, ISP denoise/sharpen | Compression / halo / stroke loss | JPEG 95; natural/pro mode; avoid repeated re-encoding |

**What matters most in practice:** text height and sharpness are the two properties that most directly predict recognition failure; clipping/glare are the two that most directly make a page unrecoverable. Contrast and illumination are usually recoverable if the strokes are not clipped, but aggressive correction can make them worse.

**Evidence for the thresholds**

- ML Kit: “Ideally, each character should be at least 16×16 pixels. There is generally no accuracy benefit for characters to be larger than 24×24 pixels.” **[E]**
- Tesseract: 300 DPI recommended; 10 pt × 300 DPI x-height is typically ~20 px; below 10 px “very little chance”; below 8 px “most of the text will be noise removed”; LSTM has a maximum useful x-height around 30 px. **[E]**
- Willus’s Tesseract benchmark characterizes resolution by **capital-letter height** and finds a sweet spot around **30 px**, with no continuing improvement above it; the related internal capture-science note reviews industrial guidance that converges on roughly 20–30 px character height. This supports “enough pixels per glyph,” not “maximum megapixels.” **[E]**
- PaddleOCR/RapidOCR recognition: the line crop is resized to height 48 px (PP-OCRv5/v6 mobile rec, `rec_img_shape: [3, 48, 320]`; the Android port uses height 48 and a width based on the line aspect ratio). **[E]**
- RapidOCR detector: the Android port uses ``ratio = max(1, 736/min(rows, cols))`` and caps the OCR input at max side 2000 px; the desktop defaults are `limit_side_len: 736`, `limit_type: min`, and global `max_side_len: 2000`. **[E]**

**Implication:** the camera and resize chain should be designed around **line height in the OCR input**, not around megapixels. A 12 MP capture that leaves the page small in the frame can be worse than a 5 MP capture that fills the frame.

---

## 2. Capture vs post-processing: who should fix what

The division of labor should be:

- **Camera: acquire information.** Maximize optical resolution on the page, focus, expose without clipping, and avoid glare/blur. The camera cannot add information later.
- **Post: remove nuisance, not invent structure.** Correct geometry, illumination, color cast, and mild sharpness/noise; resample to the recognizer's input. Do not “restore” strokes that were never captured.

| Defect | Recoverable? | Camera action | Post action |
|---|---|---|---|
| **Clipped highlights** (paper or specular) | **No** — saturated pixels have no stroke signal | Lower exposure/EV, avoid torch/flash, diffuse light, bracket | None that recovers; mask and ask recapture |
| **Clipped shadows / crushed black text** | Partially, if not fully clipped | Raise exposure/light; avoid underexposure | Lift shadows, but noise increases; do not overdo |
| **Motion blur** | **No** reliably | Faster shutter (≥1/60 s, preferably 1/100–1/250 s), brace/stand, OIS, ZSL | Deconvolution is research-grade and can hallucinate; do not rely on it |
| **Defocus blur** | **No** reliably | Tap-to-focus, lock AF, respect minimum focus distance, avoid macro at page edges | Mild unsharp can improve perceived sharpness but cannot restore lost strokes |
| **Too-low resolution** | **No** beyond interpolation | Higher resolution, optical zoom, fill frame, crop later | 2× upscale can help only when line height is below the recognizer input; it cannot recreate detail |
| **Specular glare on glossy paper** | **No** where saturated | No flash/torch; diffuse light; tilt page/camera; polarizer | Highlight removal/inpainting is risky for text; prefer recapture |
| **Uneven illumination / shadow** | **Yes**, if not clipped | Diffuse multi-source light; avoid hand/phone shadow | Flat-field/background division, Retinex, illumination-correction model; limit gain |
| **Color cast** | **Yes**, if channels not clipped | AWB lock or neutral white reference; avoid mixed lighting | Gray-world/white-patch or calibrated WB; correct before grayscale |
| **Slight skew (≤8°)** | **Yes** | Square the page in the frame | Hough/deskew (current pipeline handles ±8°); keep border white |
| **Perspective** | **Yes** | Shoot perpendicular to page; avoid extreme angles | Page-quad warp (current `restore`); check quad confidence |
| **Curvature / book gutter** | Partially | Hold pages flat; shoot from above; use a stand | Dewarping (DocUNet/DocTr-class) is research; current pipeline does not dewarp |
| **Noise** | Partially | More light, lower ISO, pixel binning, no digital zoom | Bilateral/NLM; test on thin strokes; denoise before sharpening |
| **JPEG artifacts** | Partially | JPEG quality 95, avoid re-encoding, RAW if available | Use PNG/ TIFF intermediates; do not repeatedly resave |
| **Finger/occlusion** | **No** | Show framing guide; warn | None; recapture |

**Rule of thumb:** if the information is missing at the sensor (saturation, blur, too few pixels), post-processing can only make the image look better, not make OCR better. If the information is present but distorted (shadow, cast, skew), post-processing can recover most of it.

**Evidence**

- SmartDoc-QA (ICDAR 2015) explicitly models smartphone capture distortions — lighting, blur, perspective — and uses OCR accuracy as the quality ground truth; it exists because these distortions materially hinder OCR. **[E]**
- “Automated image quality assessment for camera-captured OCR” (ICIP 2011) predicts OCR error from acquisition degradations and argues for immediate capture feedback. **[E]**
- DocTr (ACM MM 2021) combines geometric unwarping and illumination correction and reports 20.02% CER, a 15% absolute improvement over prior art (the number includes unwarping, not illumination alone). **[E]**
- Intrinsic decomposition of document images in the wild (BMVC 2020) reports a 26% CER improvement when used as an OCR preprocessing step. **[E]**
- Exposure bracketing for camera document images (Applied Sciences 2019) improves OCR under uneven lighting by capturing multiple exposures and merging useful information. **[E]**
- Specular highlight removal work (ICSP 2016) states that highlights on glossy surfaces have negative effects on OCR and proposes multi-view capture/stitching. **[E]**

---

## 3. Color vs grayscale, white balance, flash/torch, HDR

### 3.1 Capture in color; convert late

**Recommendation:** keep the camera output in color (sRGB JPEG or RAW), preserve the color original, and let the OCR engine see color or a well-formed grayscale image. Do not capture in a “document grayscale” mode that discards color before the ISP.

Why:

- Black text on white paper is mostly a luminance problem, so grayscale is sufficient for the common case. But colored headings, stamps, signatures, highlighted text, and colored matras lose contrast when converted with standard luma weights. ML Kit and RapidOCR accept color; there is no need to throw it away before OCR. **[I]**
- The current `enhanced()` converts to grayscale before flat-field, denoise, sharpening, and resize (`OfflinePages.kt:78–99`). That is acceptable for black text but is a lossy default for mixed-color documents. Keep the color original; optionally produce both a color OCR stream and a grayscale/flat-field stream and choose by confidence. **[I/U]**
- If the engine is ML Kit, test color vs grayscale on the same pages. If RapidOCR, likewise. The model was trained on color crops; grayscale replicated to three channels is usually fine, but colored text is a real difference. **[U]**

### 3.2 White balance

- Auto white balance (AWB) can drift between pages and under mixed lighting (window + tungsten), producing a color cast that changes grayscale contrast. Lock AWB where the API allows it, or shoot a white sheet and correct in post. **[I]**
- The Flutter `camera` plugin exposes exposure/focus points and modes but not an explicit AWB lock; Camera2 `CONTROL_AWB_LOCK` does. If batch consistency matters, use Camera2/CameraX interop or a neutral reference and post-correct. **[E/U]**
- A gray-world/white-patch correction is usually enough for paper documents; do not overcorrect colored content. Apply correction before grayscale conversion, and check per-channel clipping first. **[I]**

### 3.3 Flash and torch

- **Default: off.** A phone flash/torch is a small, close point source. On coated/glossy textbook paper it creates a specular hot spot that can saturate a whole word. The saturated region has no stroke information; no post-process recovers it. **[E] for glare harming OCR; [I] for the point-source mechanism.**
- Torch can help matte paper in low light, but only with diffusion (e.g., a diffuser or bouncing off a white surface) and flat-field correction. Warn the user, and detect saturation. **[I]**
- `CameraController.setFlashMode(FlashMode.off)` exists; `FlashMode.torch` keeps the light on during capture. CameraX’s torch behaves the same. **[E]**

### 3.4 HDR and tone mapping

- **Exposure bracketing / exposure fusion can help** uneven illumination because it captures highlight and shadow detail that a single exposure loses. The Applied Sciences 2019 paper supports this for document OCR; burst HDR+ (Hasinoff et al. 2016) is the phone-camera precedent for aligned multi-frame capture. **[E]**
- **Veiling glare matters even without a saturated hot spot.** A bright source in or near the frame lowers contrast across the page (Talvala et al. 2006); shade the lens/page rather than relying on tone mapping. **[E]**
- **Aggressive local tone mapping can hurt.** Local operators compress global contrast and produce halos around high-contrast edges (text on paper is exactly such an edge). Halos change the stroke profile and can confuse recognition. This is a well-known tone-mapping artifact (Reinhard et al. 2002); direct OCR measurements of halos are scarce. **[E] for halos; [I] for OCR impact.**
- **Recommendation:** if HDR is used, prefer **exposure fusion with a neutral/linear merge**, aligned frames, and motion rejection. Avoid “AI HDR,” strong local contrast, and beauty filters. If the device’s auto-HDR cannot be disabled, test it against HDR-off on the same pages and pick per device. **[I/U]**
- HDR merging of hand-held frames can ghost if the page or camera moves; ghosting is worse than the shadow it was meant to fix. Require a stable burst or a stand. **[I]**

### 3.5 ISP “enhancement” (denoise, sharpen, beauty)

Phone JPEGs are already processed: noise reduction, edge sharpening, local tone mapping, and sometimes text-specific enhancement. Over-sharpened JPEGs have halos; over-denoised JPEGs have plastic strokes and lost matras. The app cannot fully control this through the `camera` plugin. Options: use RAW/DNG where available (Camera2), use a “natural”/“pro” mode, or test the device’s default against a known target. **[I/U]**

---

## 4. Resolution, text height, interpolation, and 2× upscaling

### 4.1 Capture resolution: target DPI, not megapixels

A practical target is **250–300 DPI at the page**, with **200 DPI as a preferred floor** for 10 pt body text; 150 DPI may still work for large text or ML Kit, but validate it on the target engine. The table below uses x-height ≈ 0.5 × point size (a rough Latin approximation; actual x-height varies by font). For Devanagari, use line/akshara height instead; the same DPI logic applies.

| Capture situation (A4, 11.69 in tall) | Page height in px | Effective DPI | 10 pt x-height (px) | Expected OCR |
|---|---:|---:|---:|---|
| 720p, page fills frame | ~700 | 60 | ~4 | Fails for body text |
| 1080p, page fills frame | ~1050 | 90 | ~6 | Fails |
| 12 MP 4:3 landscape (3000 px tall), page fills 70% height | ~2100 | 180 | ~12 | Marginal |
| 12 MP 4:3 landscape, page fills 88% height | ~2640 | 226 | ~16 | Near ML Kit floor; marginal for Tesseract |
| 12 MP 4:3 portrait (4000 px tall), page fills 88% height | ~3500 | 300 | ~21 | Good |
| 48 MP (8000×6000), portrait, tight crop | ~5000+ | 400+ | ~28 | Good but diminishing; noise/diffraction risk |

**Important:** the table is for A4/letter. A 6×9 in book page at 300 DPI is only 1800×2700 = 4.9 MP, so a 12 MP camera has ample headroom if the page fills the frame. The app’s primary book use case is easier than A4 government forms. **[I]**

**Pixel binning and diffraction.** Smaller sensor pixels collect less light; at the same exposure, a 48 MP mode can be noisier than a 12 MP binned mode. Smartphone lenses are also diffraction-limited at small f-numbers, so “more megapixels” does not always mean more resolvable text. The sensor’s default binned output is often the better OCR input; test `max`/`ultraHigh` against the default 12 MP mode on the actual device. **[E] for smaller pixels/less light; [I] for the device-specific choice.**

**Current app facts**

- `capture.dart` uses `ResolutionPreset.high` (~720p). This is the dominant limitation. **[E]**
- Video mode captures at the same ~720p preset and requests 1600 px frames (`OfflinePages.kt:339`); this is upscaling, not native detail, so book video is even lower resolution than stills. **[E]**
- `normalize` caps at 2500 px; RapidOCR caps at 2000 px. **[E]**

### 4.2 Resize targets: what the engines actually see

| Stage | Current behavior | Effective A4 DPI | Comment |
|---|---|---:|---|
| Camera still | `ResolutionPreset.high` (~720p) | ~60–90 | Too low for body text |
| `normalize` | max side 2500 | ~214 | Loses resolution from a 12 MP capture |
| `restore` | loads max side 2500 | ~214 | Warp/deskew at 2500 |
| `enhance` | loads max side 2500; output up to 5000/12.5 MP; 2× only if shorter side <1000 | ~214 for full A4 | Full A4 does not trigger 2× |
| RapidOCR input | max side 2000 | ~171 | Detector/recognizer see 2000 |
| PP-OCR rec crop | height 48 px | — | Line crop is resized to 48 px |
| ML Kit | internal, not documented | unknown | Treat as opaque; test |

**Recommendation:** crop to the page (or text region) **before** downscaling, then resize to the engine’s working size. A fixed 2500 px cap is reasonable for a 6×9 book page but not for A4. Use either page-size metadata or a text-height estimate to choose the cap. For RapidOCR, if the page is A4 and the text is small, consider a 3000–3500 px working image (subject to memory/time), or crop to columns/text blocks and OCR those at higher resolution. **[I]**

**Order matters.** The current `enhance` sharpens at 2500 px, then RapidOCR downsizes to 2000; some of that sharpening is aliased away. Resize to the engine’s working size first, then apply the final mild sharpening. **[I]**

### 4.3 Text height targets

- **Latin:** ML Kit: ≥16×16 px/character, no benefit >24×24. Tesseract: ~20 px x-height at 10 pt/300 DPI; <10 px poor; <8 px removed; LSTM max ~30 px x-height. A practical camera target is **x-height ≥16 px and character box ≥24 px**, which corresponds to roughly 250–300 DPI for 10 pt text. **[E]**
- **Devanagari:** the recognizer sees a 48 px line crop; target **line/akshara height ≥40–48 px** in the OCR input so the crop is not upsampled from too few pixels. In the local 300 DPI synthetic page, the median line box was ~72 px; at 180 DPI it was ~44 px; at 135 DPI ~36 px; at 99 DPI ~30 px; at 75 DPI ~21.5 px. CER stayed near 0.036 down to ~36 px line height, rose at ~30 px, and rose sharply at ~21.5 px. **[L]**
- The safest rule: **aim for 300 DPI at capture**, then downsample to the engine’s cap with `INTER_AREA`. If the page cannot fill the frame at 300 DPI, crop to the text block and capture that at 300 DPI rather than capturing the whole page at 150 DPI. **[I]**
- The related internal note `document-capture-science.md` states the same target in different units: **capital-letter height ~20–30 px** and **Devanagari glyph-cluster height ~35–50 px**. Capital height is larger than x-height, so the two sets of numbers are consistent. **[I]**

### 4.4 Interpolation: Lanczos vs bicubic vs area

- **Downscale:** use `INTER_AREA` (area averaging). It is the standard choice for shrinking photographs and avoids aliasing. The current `enhanced()` uses `INTER_AREA` only for the 1/4 background estimate; the main enhancement resize uses `INTER_LANCZOS4`. **[E] for area; [I] for this pipeline.**
- **Upscale:** bicubic or Lanczos are both reasonable. Lanczos has a sharper kernel and can ring; bicubic is softer. In the local probe, at a fixed final size after 0.45× downscale, CER was: Lanczos 0.0406, bicubic 0.0363, linear 0.0445, nearest 0.0363, area 0.0329, no-upscale 0.0355. The differences are small and within noise for 9 pages; **there is no consistent Lanczos advantage**. **[L]**
- **Do not sharpen before downscaling.** Sharpening then downsampling creates aliasing and ringing. If sharpening is needed, do it after resampling to the working size, and keep it mild. **[I]**
- **Nearest-neighbor** is inappropriate for photographs; it preserves hard pixel edges but loses grayscale antialiasing that recognizers use. The local probe’s nearest result was not catastrophic, but do not use it as a default. **[L/I]**

### 4.5 Does 2× upscaling help?

**Sometimes, conditionally.** The local upscale probe:

| Source scale (long side) | Native OCR CER | 2× Lanczos CER | 2× bicubic CER | App enhance + 2× CER |
|---|---:|---:|---:|---:|
| 0.45 (~1184 px) | 0.0355 | 0.0406 | 0.0363 | 0.0385 |
| 0.33 (~868 px) | 0.0657 | **0.0549** | **0.0545** | 0.0852 |
| 0.25 (~658 px) | 0.1111 | 0.1211 | **0.0813** | 0.1457 |

- At 0.33× (line height ~30 px), 2× upscaling helped (0.066 → 0.055). At 0.25× (line height ~21 px), bicubic 2× helped but Lanczos and the app’s enhance+2× did not. At 0.45× (line height ~36 px), 2× slightly hurt. **[L]**
- Interpretation: upscaling can help when the line crop is below the recognizer’s 48 px input, but the gain is not guaranteed and the interpolation/processing choice matters. The app’s enhance recipe (flat-field + bilateral + unsharp before 2×) hurt at 0.33/0.25, likely because it amplifies low-resolution artifacts before interpolation. **[L/I]**
- **Recommendation:** keep a bounded 2× only for small pages or crops, trigger it by **estimated line height < ~32–36 px**, not by “shorter side <1000 px,” and compare bicubic vs Lanczos on the device. Do not upscale a page that already meets the line-height target; it costs time/memory and can hurt. **[L/I]**
- CNN super-resolution is a different claim. Papers report gains on low-resolution/binary document images, but generic 2× interpolation cannot recreate strokes that were not sampled. Treat learned SR as an experiment, not a default. **[E] for SR papers; [U] for this app.**

### 4.6 Does higher capture resolution always help?

**No.** Beyond the recognizer’s input height and the detector’s effective resolution, extra pixels:

- are downsampled (or ignored) by the engine;
- increase ISP noise reduction/sharpening and JPEG artifacts;
- increase memory and processing time on 4 GB phones;
- can make handshake/defocus more visible at 100% crop.

The optimum is **enough pixels per character**, not the largest sensor mode. For a 6×9 book page, 8–12 MP is usually enough; for A4 with 8–9 pt text, tight framing at 12 MP is the minimum, and a higher-resolution mode may help only if the lens can resolve it. **[I]**

---

## 5. Latin vs Devanagari: exposure, contrast, and the risks of over-processing

### 5.1 What is different about Devanagari

Devanagari is an abugida: the orthographic syllable is a consonant–vowel core, with dependent vowel signs (matras) placed above, below, left, or right of the consonant, and consonant clusters (conjuncts) rendered as half-forms or ligatures. The headline (*shirorekha*) is a strong horizontal stroke; many letters share it. Matras and the distinction between similar letters can be only a few pixels wide at low resolution. **[E]** (Unicode Standard, chapter 12)

Consequences for OCR:

- **Thin strokes above/below the headline** (matras, anusvara, nukta) are the first detail lost to blur, low contrast, or binarization.
- **Conjuncts and half-forms** change glyph topology; a recognizer may split or merge them. The 2026 Devanagari stress-test benchmark (preprint) reports structural errors in conjuncts, matras, and nukta as a distinct error class, separate from surface errors (numerals, punctuation). **[E]**
- **Visually similar pairs** (for example भ/म and ब/व) differ by internal strokes/loops; at low resolution or after over-sharpening, these distinctions can merge. The specific confusion rates are engine- and font-dependent; measure them locally rather than assuming. **[I/U]**
- **Devanagari digits** (०–९) are separate code points; engines may output Latin or Bengali digits. The repository's Android comparison already found ML Kit substituting Bengali zero U+09E6 for Devanagari zero U+0966. This is a script/engine issue, not an image-quality issue, but it affects digit accuracy measurement. **[E]** (repo `evals/comparisons/2026-10-17/README.md`)

### 5.2 Exposure and contrast

- **Target a bright paper background, but leave headroom.** A background at ~70–85% of full scale (roughly 180–217 in 8-bit) keeps text dark, preserves paper texture for flat-field, and leaves room for specular highlights. A background at 95–100% is more likely to clip and has little flat-field signal; a background at 50% is noisy and low-contrast. **[I]**
- **Do not crush blacks.** Clipping the darkest text pixels destroys stroke separation and makes denoising/sharpening worse. Keep the text peak around 5–20% (13–51 in 8-bit) if possible. **[I]**
- **Slightly brighter is usually better than darker for OCR**, as long as clipping is controlled, because it raises SNR and separates text from paper. But overexposure blooms thin matras and can merge strokes. **[I]**
- **Devanagari needs a little more contrast/resolution than Latin** because of the thin marks; do not use the same aggressive denoise/sharpening on both scripts without testing. **[I]**

### 5.3 Over-sharpening, denoising, and binarization

| Operation | Potential benefit | Risk | Recommendation |
|---|---|---|---|
| **Mild unsharp mask** | Restores edge acuity after slight blur; local probe helped blur (0.0397 → 0.0272) | Halos/ringing; thickens strokes; can merge matras | Use only when blur is detected; amount ~0.2–0.4, radius ~1–1.5 px; compare CER |
| **Strong unsharp** | Looks crisp | Halos, clipped edges, false strokes; worse for Devanagari | Avoid |
| **Bilateral/NLM denoise** | Removes sensor/JPEG noise | Smooths thin strokes/matras; plastic texture; can erase nukta | Mild; test on line crops; denoise before sharpening, not after |
| **CLAHE** | Local contrast in shadows/low contrast | Amplifies noise; halos; can hurt shadow/noise (local probe: shadow 0.035 → 0.044; noise 0.034 → 0.051) | Optional for low-contrast only; clip 1.5–2.0, tile 8×8; gate by CER |
| **Otsu global threshold** | Simple, fast | Catastrophic under shadow/gradients (local probe: shadow 0.035 → 0.391; combined 0.049 → 0.405) | Do not use for camera documents |
| **Sauvola/adaptive threshold** | Handles uneven background better than Otsu | Can disconnect strokes, create speckle; local probe blur 0.040 → 0.074, combined 0.049 → 0.084; repo W2.1 Sauvola invented 1,754 tokens | Do not use as default; if needed, keep grayscale stream and compare |
| **Morphological opening/closing** | Removes speckle, repairs breaks | Changes stroke width; can merge characters | Only for cleanup after binarization, not for grayscale OCR |

**Why binarization is risky for modern engines:** ML Kit and PP-OCR recognizers are trained on grayscale/color images with antialiasing and natural variation. A binary image removes the antialiasing that helps the model separate a thin stroke from background, and it makes the result sensitive to the threshold. The repository’s own W2.1 experiment is the strongest local evidence: Sauvola preprocessing on letterpress “invents 1,754 tokens” and was rejected; raw stayed. **[E] for the repo measurement; [I] for the training-data rationale.**

The U.S. Government Printing Office’s 2006 OCR study is an independent warning: threshold adjustment, paper-color removal, and downsampling to 300/200 DPI **reduced** accuracy on older documents, while contrast adjustment and unsharp masking did not significantly improve it. That study is scanner-era and not Devanagari, but it reinforces the same rule: do not add a default “scan enhancement” stage without an OCR gate. **[E]**

**If a binary image is required** (archival, debug, or a legacy engine), use Sauvola with a conservative window (25–51) and `k` around 0.2–0.34, and keep the grayscale image. Never overwrite the only image with a binary version. **[E/I]**

### 5.4 What “optimal exposure” means for Devanagari vs Latin

- **Latin:** prioritize x-height pixels and serif/terminal separation. A slightly softer image with no halos is better than a crunchy, over-sharpened one.
- **Devanagari:** prioritize matra/headline separation and avoid bloom. A slightly lower exposure with diffuse light can be better than a bright image with clipped thin strokes. Check the histogram on the text region, not the whole frame.
- **Both:** avoid mixed lighting that creates a color gradient across the page; avoid torch hotspots; avoid HDR halos. The best “contrast” is often better light, not more processing.

---

## 6. Measuring OCR quality changes offline

### 6.1 Design the comparison as a paired experiment

The same page must be measured under each condition, with the same engine, language, and settings. Pairing removes page-to-page variance (content, font, layout) and lets a small number of pages detect a real effect.

Recommended design for capture/preprocessing tuning:

1. **Base set:** 30–60 clean pages with reliable ground truth, stratified by script (Latin, Devanagari), layout (prose, table, form), and page size (book, A4).
2. **Conditions:** one factor at a time — resolution (300/250/200/150/100 DPI equivalent), exposure (−1/0/+1 EV), focus (sharp/soft), blur (none/σ1/σ2), shadow (none/mild/strong), glare (none/specular patch), noise/JPEG, HDR on/off, torch on/off.
3. **Preprocessing arms:** raw, current app enhance, flat-field, CLAHE, unsharp, flat+unsharp, Sauvola/Otsu (as negative controls), 2× Lanczos/bicubic.
4. **Repeats:** 3–5 captures per cell for hand-held conditions, to average AF/AE/handshake variability. For synthetic degradations, one deterministic render per seed is enough.
5. **Order:** randomize condition order; do not run all clean pages first and all degraded pages later, to avoid engine warm-up/caching confounds.
6. **Freeze:** hash the images and ground truth; use `eval_freeze.py`; never tune on the holdout.

### 6.2 Metrics

| Metric | What it captures | Notes |
|---|---|---|
| **CER** (character error rate) | Edit distance / GT length | Standard; sensitive to reading-order and segmentation errors at page level |
| **WER** | Word-level errors | Useful for prose; less meaningful for tables/forms |
| **bagCER** | Order-insensitive CER | Separates recognition from reading order; the repo uses it |
| **Grapheme/akshara CER** | Devanagari-appropriate unit | Code-point CER can over-penalize equivalent sequences; report both |
| **Digit CER / digit-exact** | Money/date/ID accuracy | Report exact digit-sequence match and per-digit errors; digits are rare, so CIs are wide |
| **Coverage / false alarm** | Detected tokens vs GT; hallucinated tokens | Important for “invented text” failures |
| **ECE / Brier** | Confidence calibration | ML Kit/RapidOCR confidence is not a calibrated probability |
| **Review recall@k** | Whether errors reach the review queue | The product’s trust metric; the repo uses `eval_flags.py` |
| **Latency / memory** | On-device feasibility | Report per stage; emulator numbers are not phone numbers |

### 6.3 Confidence calibration

- **Do not treat ML Kit `line.confidence` or RapidOCR CTC confidence as a probability.** Scene-text recognizers are consistently overconfident; calibration methods can reduce calibration error by up to ~7× (Slossberg et al. 2020). The repository’s own token flags on real Devanagari report ECE 0.82 (`docs/EVALUATION.md`), i.e., the flag scores are close to uninformative for review ranking; ML Kit/RapidOCR line confidence should be calibrated separately. **[E]**
- **Calibrate per engine, per script, per device** on a held-out set. Use a reliability diagram (10–15 bins), ECE, and Brier score. Temperature scaling or isotonic regression on line-level correctness is enough for a review threshold; do not use the raw 0.8 cutoff as a probability.
- **Digits need a separate calibration** because digit errors are rare and often high-confidence. Report digit exact-match and conflict-flag recall/precision, not just mean confidence.
- **Minimum sample:** at least 300–500 lines per script for a stable 10-bin reliability diagram; 1,000+ is better. For ECE on rare digit errors, report counts and confidence intervals, not a single number.

### 6.4 Sample size and confounders

**Sample size.** For a paired design, the standard error of the mean difference is `σ_d / √n`; a two-sided 95% interval with 80% power needs approximately `n = 7.84 × (σ_d/δ)²` paired pages for a difference `δ`. A rough planning table:

| Paired SD of CER difference `σ_d` | n for 1 pp | n for 2 pp | n for 5 pp |
|---:|---:|---:|---:|
| 0.02 | ~32 | ~8 | ~2 |
| 0.05 | ~196 | ~49 | ~8 |
| 0.10 | ~784 | ~196 | ~32 |

These are indicative; use the observed paired differences from a pilot. In practice 30 paired pages resolve roughly a 1–3.5 pp difference depending on the paired SD; 200+ pages are needed for ~1 pp at the higher variance. For page-level CER on 41 pages, the repository’s bootstrap CIs are often ±4–6 pp, so only large effects are detectable. For line-level recognition, 500 lines gives much tighter intervals because each line is a unit. **[I]**

**Confounders to control or report:**

- Page content: prose vs tables vs forms; table reading order can dominate page CER.
- Font/script: letterpress vs modern print; Devanagari font coverage; Latin serif vs sans.
- Ground truth quality: model-generated anchors, corrupt PDF text layers, Unicode normalization.
- Engine version and model hash; ONNX runtime/EP; ML Kit bundled vs unbundled.
- Device/ISP: different phones process JPEG differently; emulator vs phone.
- Compression: JPEG quality, repeated re-encoding, PNG vs JPEG.
- Orientation: 0/90/180/270; the app reads four orientations and picks by score, which can hide recognition errors.
- Reading order: page CER includes ordering; line CER does not.
- Correlated conditions: shadow/rotation cases derived from the same source are not independent documents.
- Multiple comparisons: pre-register the primary metric and gate; do not cherry-pick the best arm.

### 6.5 Use the existing harness, and extend it

- `evals/harness/eval_document.py` already supports `clean`, `raw`, `sauvola`, `lanczos2`, `restore`, `restore_*`, and `pipeline`, with CER, bagCER, digit CER/exact, ECE, coverage, false alarm, box coverage, and bootstrap CIs. Use `--frozen` and `--bootstrap 2000`. **[E]**
- `evals/harness/eval_lines.py` isolates recognition from detection/layout; use it for preprocessing effects on line crops. **[E]**
- `mobile/tool/compare_ocr.py` runs the paired Android integration test in an isolated package with no network; it verifies input hashes and pulls outputs. Use it for device-level ML Kit vs RapidOCR comparisons. **[E]**
- **Add** a `capture_sweep` harness (or extend `eval_document.py`) that:
  - takes a clean page and a list of degradation/preprocessing functions;
  - writes each variant with a deterministic name and hash;
  - runs each backend with the same language/confidence settings;
  - reports per-page and aggregate CER/WER/grapheme CER/digit-exact/ECE with paired bootstrap CIs;
  - saves a contact sheet and a CSV of the worst pages for human review.
- The repository’s `docs/EVALUATION.md` already documents the adopt-if gates (e.g., “CER −≥5% relative”); keep that discipline. **[E]**

---

## 7. Capture-quality metrics that predict OCR failure

### 7.1 Image metrics worth computing at capture time

These are cheap (preview resolution) and can be shown live:

| Metric | How to compute | Failure signal | Caveat |
|---|---|---|---|
| **Text height** | Detect text lines/connected components on a downscaled preview; median box height; convert to estimated DPI using page quad size | Line height < ~30–36 px; x-height < ~12–16 px | Detection itself fails on blur/low contrast |
| **Clipping** | Fraction of pixels ≥250 and ≤5; per-channel | >1–2% highlight clipping; >1% shadow clipping | White margins can inflate highlight fraction; mask to page/text region |
| **Sharpness** | Variance of Laplacian/Tenengrad on text regions; or CG-DIQA character gradient | Below a device/lighting-specific threshold | Texture/paper grain inflates it; compare to a reference |
| **Illumination uniformity** | Background estimate (median blur) percentiles; coefficient of variation; max local gradient | CV > ~15–20%; strong gradient across page | Shadows from the phone/hand are common |
| **Glare** | Saturated, low-saturation regions inside the page; local max/median ratio | Specular area > ~0.5–1% of page | White paper can look saturated; use local contrast |
| **Noise** | High-pass residual sigma in flat paper regions | Sigma above device/ISO-specific threshold | JPEG denoise can hide noise |
| **Skew** | Hough line angle on text edges | >8° (current deskew limit) | Curved text gives mixed angles |
| **Page quad** | Contour/edge quad; area, convexity, aspect | Quad not found, area <25% or >98%, aspect outside 0.35–2.5 | Current `pageView` already checks these; reuse |
| **Focus distance** | Camera metadata (if available) | Below minimum focus distance; page edges blurred | Not exposed by all devices |

For a formal, scanner-oriented framework, FADGI’s 2023 technical guidelines define modulation transfer function (MTF/SFR), opto-electronic conversion function (OECF), illumination uniformity, noise, and color accuracy, measured with a test target. Those metrics are excellent for calibrating a fixed capture rig or validating a device, but they are heavier than the live preview metrics above and are not a substitute for OCR ground truth. **[E]** (FADGI 2023)

### 7.2 Do image metrics alone predict OCR failure?

Not reliably. The literature says image quality assessment can predict OCR error (ICIP 2011; CG-DIQA 2018), and focus-measure operators can predict OCR accuracy on mobile-captured documents (Rusiñol et al. 2014); DIQA surveys catalog many learned and hand-crafted approaches (Alaei et al. 2023). But the best methods are learned and document-specific, not a single Laplacian threshold. A blurry-looking page with large, high-contrast text may OCR fine; a sharp-looking page with 8 pt text may fail. **[E]**

**Recommended hybrid:**

1. **Hard gates on image metrics** for failures that are certainly fatal: text height below the engine floor, clipping above a threshold in the text region, specular glare covering strokes, page quad missing, severe defocus/motion blur. Warn and ask for recapture.
2. **Cheap OCR pre-check** for marginal cases: run the detector/recognizer on a downscaled page (e.g., 1000–1200 px long side) or a center crop. Use:
   - number of detected lines vs expected text density;
   - mean/median line confidence (calibrated, not raw);
   - character count and valid-script ratio;
   - presence of digits if the page is expected to have them;
   - empty-output rate.
   A 1–2 MP pre-check costs a fraction of full OCR and directly measures the thing you care about. **[I]**
3. **Full OCR** only if the pre-check passes or the user chooses “recognize anyway.” Always keep the original and allow review.

**Why not just use image metrics?** They are explainable and cheap, but they do not see font, language, layout, or the recognizer’s quirks. The pre-check sees the actual engine’s behavior on the actual page. The combination is more robust than either alone. **[I/U]**

### 7.3 Logging for field analysis

Log per capture (without text content): device model, camera ID, capture resolution, ISO/exposure time/focus distance (if available), zoom, flash/torch, HDR mode, WB gains, page quad area, estimated DPI/text height, clipping %, sharpness, glare %, and the OCR engine/model version. This lets you correlate field failures with capture conditions and choose device-specific defaults. **[I]**

---

## 8. Practical preprocessing improvements worth testing

Ordered by expected value and risk. Each item should be tested with the paired harness in §6; do not ship a visual improvement without a CER gate. **The interaction matters:** better capture reduces the need for aggressive preprocessing; at low resolution, upscaling may help but flat-field/sharpening can amplify artifacts; at high resolution, sharpening/denoising is more likely to hurt than help. Tune preprocessing at the capture resolution and device you will ship, not on downscaled proxies.

### 8.1 Crop to the page/text region before resizing (highest value, low risk)

- **Why:** the current 2500/2000 px caps are applied to the whole frame, including margins, table borders, and background. Cropping first puts the available pixels on text.
- **How:** use the existing page-quad/`paper()` mask; crop with a small margin; then resize to the engine cap. For two-page spreads, split before resizing.
- **Expected effect:** largest for pages that do not fill the frame; can recover 20–40% effective DPI. **[I]**
- **Caution:** bad crops can cut text; keep the full original and a crop-confidence flag.

### 8.2 Raise/adapt the working resolution (high value, medium risk)

- **Why:** 2500 px is ~214 DPI for A4; RapidOCR's 2000 px is ~171 DPI. Both are below the 300 DPI target, and for small or Devanagari text they leave little margin above ML Kit's 16 px character guidance.
- **How:** after cropping, keep max side ~3000–3500 for A4-like pages; use `INTER_AREA`; for RapidOCR ensure the line crop height is ≥48 px. Raising `normalize` alone is not enough for RapidOCR: `RapidOcr.kt:214` downsizes the OCR input to max side 2000 again, so raise that cap or OCR higher-resolution crops/text blocks. On 4 GB phones, measure peak memory and time; a 3500 px page is roughly 9–12 MP depending on aspect, which is manageable if you release intermediates.
- **Expected effect:** CER improvement where text height is the limiting factor; no effect on already-large text. **[L/I]**
- **Caution:** memory/time; larger images can be slower and may trigger different detector behavior.

### 8.3 Illumination flattening / flat-field (high value, medium risk)

- **Why:** shadows are the most common recoverable defect. Published illumination-correction methods report large CER gains (26% in intrinsic decomposition; DocTr includes illumination correction), and dedicated document shadow-removal methods exist (ACCV 2016). The current median+Gaussian background estimate is a reasonable classical approach.
- **How to improve:**
  - Work in **linear light** (sRGB → linear) before division, then convert back; gamma-space division is not physically correct and can distort contrast. **[I]**
  - Use a larger background kernel / lower-resolution estimate, and **regularize the gain**: limit `src/bg` to a range (e.g., 0.5–2.0) to avoid blowing up noise in dark regions.
  - Preserve local contrast; do not subtract the background entirely (that flattens text).
  - Estimate the background from paper pixels only (mask text/edges) where possible.
- **Evidence:** published illumination correction helps; the local probe’s simple flat-field was roughly neutral on a synthetic shadow (0.0350 → 0.0366, slightly worse) and slightly helpful on noise+JPEG (0.0335 → 0.0319), but not a large win. The difference is likely the synthetic shadow and the engine’s internal normalization. **[E/L]**
- **Caution:** flat-field can amplify noise and create halos around dark text; test on real shadows, not only synthetic gradients.

### 8.4 Mild unsharp mask (medium value, medium risk)

- **Why:** the local probe found unsharp helped blur (0.0397 → 0.0272) and shadow (0.0350 → 0.0272), with little effect on clean pages (0.0327 → 0.0296). The GPO 2006 study, by contrast, found unsharp masking did not significantly improve overall OCR accuracy; treat it as a **conditional blur remedy**, not a default. **[L/E]**
- **Parameters to test:** amount 0.2–0.4, radius 1.0–1.5 px, threshold to avoid amplifying flat paper; optionally edge-aware/unsharp on the luminance channel only.
- **Caution:** over-sharpening creates halos and can merge Devanagari matras; do not apply when the image is already sharp. Gate on a blur metric. **[L/I]**

### 8.5 CLAHE (medium value, medium risk)

- **Why:** can improve local contrast in shadows/low-contrast captures.
- **Parameters to test:** clip limit 1.5–2.0, tile 8×8 (the app already uses 2.0/8×8 for digit crops); compare against raw and flat-field.
- **Evidence:** mixed. The local probe found CLAHE hurt under shadow (0.035 → 0.044) and noise (0.034 → 0.051), and helped slightly on clean (0.0327 → 0.0319). A 2026 preprint using CLAHE as a baseline reports that learned preprocessing beats it; a historic-image parameter study optimizes CLAHE+USM for PSNR, not OCR. **[L/E]**
- **Caution:** CLAHE amplifies noise and can create halos; do not use as a default on clean pages. Gate on low contrast and test CER.

### 8.6 Denoise (medium value, medium risk)

- **Why:** sensor/JPEG noise creates false edges.
- **Options:** bilateral (current: diameter 5, sigmaColor 40, sigmaSpace 5), non-local means, or a light median. Test on line crops with thin matras.
- **Caution:** denoising before sharpening can erase the very strokes you want; denoise after flat-field but before unsharp; keep it mild. **[L/I]**

### 8.7 Binarization (low value/high risk; not default)

- **Why not:** the local probe and the repository’s W2.1 experiment both show failures. Otsu is catastrophic under shadow/gradients; Sauvola can disconnect strokes and invent tokens. Modern recognizers do not need binary input.
- **If required:** Sauvola window 25–51, k 0.2–0.34; keep the grayscale image; use binary only for layout/debug; compare CER. **[E/L]**
- **Never** replace the original or the only working image with a binary version.

### 8.8 Resampling and 2× upscaling (conditional)

- Use `INTER_AREA` for downscale; bicubic/Lanczos for upscale; trigger 2× only when line height <~32–36 px; compare bicubic vs Lanczos; do not sharpen before downscale. See §4. **[L/I]**

### 8.9 Geometry (already good; don’t overdo)

- The current pipeline does page-quad warp + Hough deskew ±8°, which is appropriate for hand-held pages. Deskew should keep a white border and avoid cropping text.
- For curved pages/gutters, a learned dewarping model (DocTr/DocUNet-class) is the next step, but it is heavier and can hallucinate; only add if real book photos show a CER gain. **[E/U]**

### 8.10 Color and grayscale streams

- Keep the color original. For OCR, test color vs grayscale vs flat-field grayscale. Colored text/stamps may favor color; black text may favor grayscale. Choose by confidence/CER, not by assumption. **[I/U]**

### 8.11 JPEG and intermediate formats

- Set the camera JPEG quality to 95 (`CameraController.setJpegImageQuality`); native derivative saves already use 95. Avoid repeated re-encoding; use PNG/TIFF for intermediates if storage allows. Low-quality JPEG ringing is especially harmful at low resolution. **[E for current code; I for impact]**

### 8.12 Linear-light processing

- Flat-field division, exposure fusion, and resizing are ideally done in linear light. The current pipeline works on gamma-encoded 8-bit values. Converting to linear float, processing, and converting back may improve shadow correction and resize quality, at a memory/time cost. Test on real shadows; do not assume. **[I/U]**

---

## 9. Preserving originals and non-destructive tuning

The app already does the most important thing: `importImage` copies the original to `original_$id` before any transformation (`documents.dart:239–246`). Keep that invariant.

Recommendations:

1. **Never overwrite the original.** Keep `original_*` immutable; write `source_*` (normalized), `page_*` (restored), `enhanced_*` (OCR working image) as separate files.
2. **Record the transform chain.** For each derivative, store a sidecar JSON with: source hash, operation name, parameters (e.g., CLAHE clip/tile, unsharp amount/radius, resize target/interpolation, flat-field kernel), app version, engine/model hash, device model, and timestamp. This lets you reproduce or revert a tuning change.
3. **Keep OCR evidence.** Store raw text, boxes, line confidence, engine version, orientation decisions, and digit re-read alternatives. The current `ScanPage` already keeps `original`/`reviewed` text and a recovery version; extend the metadata rather than replacing it.
4. **Show original vs processed in review.** A side-by-side or toggle lets the reviewer verify that preprocessing did not invent or erase text. This is especially important for Devanagari matras and digits.
5. **Make preprocessing parameters configurable and versioned.** A `preprocess_version` field lets you compare “v1 default” vs “v2 candidate” on the same document and roll back.
6. **Re-run from the original.** If the user changes a preprocessing setting or the engine is updated, re-run from `original_*`, not from a previously enhanced JPEG, to avoid compounding artifacts.
7. **Freeze evaluation data.** Use content hashes and manifests; do not tune on the holdout. The repository already has `eval_freeze.py` and frozen manifests. **[E]**
8. **Privacy.** Keep processing offline; do not log text or images to remote services; strip PII from field-test captures. The app’s no-INTERNET permission is a strength; preserve it. **[E]**
9. **Storage.** Originals can be large (12 MP JPEG ~3–6 MB). Keep them for verification; compress working copies; provide a “remove originals” option only with explicit user consent. The current P1 notes already discuss storage growth; this is a product trade-off, not a technical blocker. **[E]**

---

## 10. Recommended capture contract and preprocessing policy

### 10.1 Camera contract (what the camera must deliver)

| Setting | Recommendation | Why |
|---|---|---|
| **Resolution** | `ResolutionPreset.max`/`ultraHigh` (or CameraX 4:3 ~12 MP); verify actual output size; prefer the sensor’s binned mode if 48 MP is noisy | 720p is the current bottleneck; 12 MP is enough for 6×9 at 300 DPI and marginal for A4 |
| **Aspect / framing** | 4:3; page height 75–90% of the frame (A4 in a 4:3 frame occupies well under half the frame area even at that fill); show a page-quad guide; no digital zoom | Pixels on the page, not on the desk; page-area rules are misleading for A4 |
| **Focus** | Tap-to-focus on text; wait for AF convergence; `FocusMode.locked` before capture; respect minimum focus distance | Defocus is unrecoverable |
| **Exposure** | `ExposureMode.auto`, then lock; use `setExposureOffset` to keep paper at ~70–85% and avoid clipping; check histogram | Clipped highlights are unrecoverable; underexposure is noisy |
| **White balance** | Lock AWB where possible, or use a white reference and correct in post; avoid mixed lighting | Cast changes grayscale contrast |
| **Flash/torch** | Off by default; torch only for matte paper with diffusion and a glare warning | Specular glare saturates strokes |
| **HDR** | Off, or neutral exposure fusion/bracketing with alignment and motion rejection; no strong local tone mapping | Halos/ghosting can hurt OCR |
| **Stability** | Shutter ≥1/60 s (1/100–1/250 s preferred); OIS/stand; brace; ZSL if it does not reuse a stale AF/AE frame | Motion blur is unrecoverable |
| **JPEG** | Quality 95; avoid re-encoding; RAW/DNG optional for archival | Fewer ringing artifacts |
| **Video** | 4K if supported; extract frames at native resolution (not 1600 px); hold each page still ≥1 s | Current video path captures ~720p and requests 1600 px frames (upscaling) |

The current `camera` plugin exposes resolution presets, focus/exposure points and locks, exposure offset, torch, zoom, and JPEG quality, but not AWB lock or RAW stills. CameraX/Camera2 give finer control (target resolution, AE/AWB lock, RAW); migrating is worth evaluating if the plugin cannot deliver the resolution/focus contract on the target phones. **[E/I]**

### 10.2 Capture-time checks (what to show the user)

- **Page quad**: found / not found; warn if not found.
- **Text height**: estimated line height and DPI; warn if below ~40 px line height or ~180–200 DPI.
- **Clipping**: highlight/shadow percentage; warn if >1–2% in the text region.
- **Sharpness**: blur score; warn if below threshold; show “hold still.”
- **Glare**: specular mask; warn if a hot spot covers text.
- **Skew**: warn if >8°.
- **Distance/framing**: “move closer / fill the frame” if the page is small.
- **HDR/torch**: show active modes; warn about glare.

### 10.3 Preprocessing policy (what post should do)

1. **Preserve original**; work on a copy.
2. **Crop to page**; perspective warp; deskew (current ±8°).
3. **Optional linear-light conversion** for flat-field/resize; test.
4. **Flat-field / illumination normalization** with gain limiting; preserve local contrast.
5. **Optional CLAHE** only for low-contrast captures; clip 1.5–2.0, tile 8×8.
6. **Optional mild unsharp** only when blur is detected; amount 0.2–0.4, radius 1–1.5 px.
7. **Mild denoise** if noise is high; avoid erasing matras.
8. **No binarization by default**; keep grayscale/color.
9. **Resize** with `INTER_AREA` down; bicubic/Lanczos up only if line height <~32–36 px; cap 2×.
10. **OCR**; keep raw text/boxes/confidence; flag uncertain lines/digits for review.
11. **Log** the chain and parameters; allow re-run from the original.

### 10.4 Engine-specific notes

- **ML Kit:** 16×16 px/character minimum; no benefit >24×24; confidence is not calibrated; Latin is real-time, Devanagari slower. Use color/grayscale, not binary. Test internal resolution behavior on device. **[E]**
- **RapidOCR/PaddleOCR:** det limit 736 min side / global max 2000; rec 48 px height; the Android port caps OCR input at 2000 and uses width up to 16384. Ensure the line crop is ≥48 px after resize; do not compress long lines. **[E]**
- **Digit crops:** the current `digitCrop` uses up to 2× Lanczos + CLAHE 2.0/8×8; this is a targeted review aid, not a page default. Keep it, but measure digit CER and avoid applying it to the whole page. Same-engine agreement is supporting evidence, not independent verification. **[E]**

---

## 11. Local probes (directional evidence)

These probes were run on 2026-11-07 with the repository’s RapidOCR backend (`veriscript.document.ocr.ocr_page`, `lang='ne'`) on synthetic Nepali pages from `data/doc_eval`. They are **not** frozen product measurements: 5–9 pages, one engine, one run per condition, no confidence intervals. They are useful for direction and for choosing what to test properly.

### 11.1 Resolution sweep

**Setup:** 9 clean synthetic Nepali pages (3 at 300 DPI, 6 at 200 DPI; 2,313 GT characters). Each page was downscaled with `INTER_AREA` to the target long side, then OCR’d. Median line height is the median of `(y2 − y1)` over detected token boxes on the 300 DPI subset. CER/WER/digit CER are averaged over all 9 pages; because the set mixes 200 and 300 DPI sources, the DPI column is the approximate DPI for the 300 DPI subset (6×9 in page), not a single DPI for every page in the average.

| Long side (px, 300 DPI subset) | Approx. DPI (6×9 page) | Median line height (px) | CER | WER | Digit CER |
|---:|---:|---:|---:|---:|---:|
| 2631 | 300 | 72.5 | 0.0359 | 0.1640 | 0.0968 |
| 2105 | 240 | 58 | 0.0398 | 0.1799 | 0.1344 |
| 1579 | 180 | 44 | 0.0419 | 0.1931 | 0.1183 |
| 1184 | 135 | 36 | 0.0355 | 0.1772 | 0.1022 |
| 868 | 99 | 30 | 0.0657 | 0.2831 | 0.1935 |
| 658 | 75 | 21.5 | 0.1111 | 0.4048 | 0.2419 |

**Reading:** CER is flat from 300 to ~135 DPI, then degrades at ~99 DPI and sharply at ~75 DPI. This is consistent with the recognizer’s 48 px line input: at 135 DPI the line is ~36 px and still usable; at 99 DPI ~30 px; at 75 DPI ~21.5 px, where matras/strokes are lost. The practical floor for this engine/page is ~120–150 DPI; 200–300 DPI is safer. The 200 DPI pages enter the average at proportionally smaller pixel sizes, so the average CER at a given long side may differ slightly from a same-DPI-only run.

### 11.2 Interpolation at fixed final size

**Setup:** each page downscaled to 0.45× (long side ~1184 px), then upscaled back to the original size with each kernel; CER on the final image.

| Kernel | CER | WER | Digit CER |
|---|---:|---:|---:|
| Lanczos4 | 0.0406 | 0.2090 | 0.0932 |
| Bicubic | 0.0363 | 0.1746 | 0.0699 |
| Linear | 0.0445 | 0.2090 | 0.1380 |
| Nearest | 0.0363 | 0.1825 | 0.1201 |
| Area | 0.0329 | 0.1693 | 0.1129 |
| No upscale (native 0.45×) | 0.0355 | 0.1772 | 0.1022 |

**Reading:** differences are small and inconsistent; there is no clear Lanczos win. Bicubic/area are safer defaults; do not use nearest for photographs.

### 11.3 2× upscaling vs app enhance+2×

| Source scale | Native | 2× Lanczos | 2× bicubic | App enhance+2× |
|---|---:|---:|---:|---:|
| 0.45× (~1184 px) | 0.0355 | 0.0406 | 0.0363 | 0.0385 |
| 0.33× (~868 px) | 0.0657 | 0.0549 | 0.0545 | 0.0852 |
| 0.25× (~658 px) | 0.1111 | 0.1211 | 0.0813 | 0.1457 |

**Reading:** 2× can help when the line is ~30 px or below, but it is not a consistent win; the app’s enhance recipe before 2× hurt at the lowest resolutions. Trigger upscaling by line height, not by page size, and validate the interpolation/preprocessing combination.

### 11.4 Degradation × preprocessing matrix

**Setup:** 5 clean synthetic pages (1,285 GT characters); controlled degradations applied in code; each cell is mean CER over the 5 pages. “flat” is the current median+Gaussian background division; “flat+unsharp” mirrors the app’s enhance order; Sauvola window 25/k 0.2; Otsu global.

| Degradation | raw | flat | CLAHE | unsharp | flat+unsharp | Sauvola | Otsu |
|---|---:|---:|---:|---:|---:|---:|---:|
| clean | 0.0327 | 0.0342 | 0.0319 | **0.0296** | 0.0350 | 0.0342 | 0.0311 |
| shadow | 0.0350 | 0.0366 | 0.0444 | **0.0272** | 0.0327 | 0.0358 | **0.3914** |
| low contrast | 0.0374 | 0.0374 | 0.0381 | 0.0412 | 0.0397 | 0.0366 | **0.0296** |
| blur | 0.0397 | 0.0389 | 0.0374 | **0.0272** | 0.0335 | 0.0739 | 0.0848 |
| noise+JPEG | 0.0335 | **0.0319** | 0.0514 | 0.0366 | 0.0405 | 0.0397 | 0.0335 |
| combined | **0.0490** | 0.0529 | 0.0934 | 0.0591 | 0.0545 | 0.0840 | **0.4047** |

**Reading:** aggressive binarization is the biggest risk; CLAHE can hurt under shadow/noise; mild unsharp helps blur; flat-field is neutral-to-slightly-positive on noise but not a universal win. The synthetic shadow is a smooth gradient and may not match a real hand/phone shadow; RapidOCR also does internal normalization, so do not generalize these numbers to ML Kit or real captures without re-running.

### 11.5 What the probes do **not** establish

- No ML Kit results (the probes use RapidOCR only).
- No real phone captures, no real Devanagari book photos, no handshake/AF/AE variability.
- No confidence intervals; 5–9 pages is small.
- Synthetic degradations are simpler than real shadows/glare/curvature.
- The frozen `nepali_photo_proxy` set was too degraded for method ranking in a quick run (raw CER near 0.98 on the first 10 pages); use it for end-to-end behavior, not for fine-grained preprocessing comparisons.

### 11.6 Evidence status summary

| Established (documented or frozen) | Inferred (reasoned, not directly measured here) | Unknown / needs device testing |
|---|---|---|
| ML Kit 16×16 px/character, no gain >24×24 | 300 DPI capture target and 200 DPI preferred floor for this app | ML Kit’s internal input resolution and preprocessing |
| Tesseract 300 DPI, ~20 px x-height at 10 pt, <10 px poor, <8 px removed, LSTM max ~30 px | 12 MP binned output is often better than 48 MP for text | Device ISP/AWB/HDR/torch behavior on real phones |
| PP-OCR rec input 48 px; RapidOCR det 736 min side / global 2000 cap | HDR local tone-mapping halos hurt OCR (tone-mapping literature, not direct OCR) | Best interpolation, unsharp, CLAHE, and denoise parameters for this engine |
| Current app: 720p capture, 2500/2000 px caps, 1600 px video frames | Flat-field in linear light with gain limiting is better than gamma-space division | Whether 2× upscaling helps on real captures; color vs grayscale |
| Smartphone lighting/blur/perspective hurt OCR; illumination correction helps; specular glare hurts OCR; exposure bracketing helps | A cheap OCR pre-check catches failures that image metrics miss | Real Devanagari camera corpus and low-end phone performance |
| Binarization risk: local Otsu/Sauvola results and repo W2.1 Sauvola failure | Text-height-triggered 2× upscaling is safer than page-size-triggered | Optimal capture-quality thresholds for this product |
| OCR confidence is overconfident; repo token-flag ECE 0.82 | 30 paired pages resolve ~1–3.5 pp CER depending on variance | Whether a learned document-quality model is worth the size |
| Devanagari structural errors (conjuncts, matras, nukta) and collapse under degradation | Grapheme/akshara CER is the right Devanagari unit | Font-specific confusion rates (भ/म, ब/व, digits) |

---

## 12. Sources

All URLs accessed 2026-11-07 unless otherwise noted.

### Primary documentation and code

1. Tesseract documentation, “Improving the quality of the output.” https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
2. Tesseract FAQ (archived), “Is there a Minimum / Maximum Text Size?” https://tesseract-ocr.github.io/tessdoc/tess3/FAQ-Old.html
3. Google ML Kit, “Text recognition v2 — Android,” input image guidelines. https://developers.google.com/ml-kit/vision/text-recognition/v2/android
4. Google ML Kit, “Text recognition v2” overview (scripts, confidence, structure). https://developers.google.com/ml-kit/vision/text-recognition/v2
5. PaddleOCR PP-OCRv5 mobile recognition config (`RecResizeImg`, 48×320). https://github.com/PaddlePaddle/PaddleOCR/blob/main/configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml
6. PaddleOCR PP-OCRv5 mobile detection config (DB postprocess, input shape). https://github.com/PaddlePaddle/PaddleOCR/blob/main/configs/det/PP-OCRv5/PP-OCRv5_mobile_det.yml
7. RapidOCR default config (`max_side_len: 2000`, det `limit_side_len: 736`, `limit_type: min`, rec `[3, 48, 320]`). https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml
8. Flutter `camera` package, `ResolutionPreset` (high ≈720p, veryHigh ≈1080p, ultraHigh ≈2160p, max). https://pub.dev/documentation/camera/latest/camera/ResolutionPreset.html
9. Flutter `camera` package, `CameraController` (focus/exposure modes and points, exposure offset, JPEG quality, zoom, torch). https://pub.dev/documentation/camera/latest/camera/CameraController-class.html
10. Android CameraX configuration guide (4:3 default, target resolution, CameraControl focus/metering, exposure compensation, torch, zoom). https://developer.android.com/media/camera/camerax/configuration
11. Unicode Standard 16.0, Chapter 12, “South and Central Asia-I,” Devanagari matras, virama, conjuncts, half-forms, ZWJ/ZWNJ. https://www.unicode.org/versions/Unicode16.0.0/core-spec/chapter-12/
12. FADGI, “Technical Guidelines for Digitizing Cultural Heritage Materials,” 3rd edition (2023). https://www.digitizationguidelines.gov/guidelines/digitize-technical.html

### Research on capture quality, OCR, and preprocessing

13. Burie et al., “ICDAR2015 competition on smartphone document capture and OCR (SmartDoc),” ICDAR 2015. https://doi.org/10.1109/ICDAR.2015.7333943
14. Nayef et al., “SmartDoc-QA: A dataset for quality assessment of smartphone captured document images — single and multiple distortions,” ICDAR 2015. https://doi.org/10.1109/ICDAR.2015.7333960
15. “Automated image quality assessment for camera-captured OCR,” ICIP 2011. https://doi.org/10.1109/ICIP.2011.6116204
16. Li, Zhu, Qiu, “CG-DIQA: No-reference Document Image Quality Assessment Based on Character Gradient,” ICPR 2018. https://arxiv.org/abs/1807.04047
17. Feng et al., “DocTr: Document Image Transformer for Geometric Unwarping and Illumination Correction,” ACM MM 2021. https://arxiv.org/abs/2110.12942 ; https://doi.org/10.1145/3474085.3475388
18. “Intrinsic Decomposition of Document Images In-the-Wild,” BMVC 2020 (26% CER improvement as OCR preprocessing). https://doi.org/10.5244/C.34.188
19. “Exposure Bracketing Techniques for Camera Document Image Enhancement,” Applied Sciences 9(21):4529, 2019. https://doi.org/10.3390/app9214529
20. “Highlight removal for camera captured documents based on image stitching,” ICSP 2016. https://doi.org/10.1109/ICSP.2016.7877950
21. Singh, “Can OCR-VLMs Read Devanagari? A Stress-Test Benchmark and Post-Correction Study,” arXiv:2606.29213, 2026. https://arxiv.org/abs/2606.29213
22. Slossberg et al., “On Calibration of Scene-Text Recognition Models,” arXiv:2012.12643, 2020. https://arxiv.org/abs/2012.12643
23. Yang et al., “Towards Spatially-Varying Gain and Binning,” arXiv:2507.04190, 2025 (smaller pixels collect less light; binning/noise trade-off). https://arxiv.org/abs/2507.04190
24. “Perceptual Image Enhancement for Smartphone Real-Time Applications,” WACV 2023 (smartphone noise, diffraction blur, HDR overexposure). https://doi.org/10.1109/WACV56688.2023.00189
25. “Enhancing OCR Accuracy with Super Resolution,” ICPR 2018. https://doi.org/10.1109/ICPR.2018.8545609
26. Fu et al., “Cascaded Detail-Preserving Networks for Super-Resolution of Document Images,” arXiv:1911.10714, 2019. https://arxiv.org/abs/1911.10714
27. Sauvola & Pietikäinen, “Adaptive document image binarization,” Pattern Recognition 33(2):225–236, 2000. https://doi.org/10.1016/S0031-3203(99)00055-2
28. Otsu, “A Threshold Selection Method from Gray-Level Histograms,” IEEE Trans. SMC 9(1):62–66, 1979. https://doi.org/10.1109/TSMC.1979.4310076
29. Zuiderveld, “Contrast Limited Adaptive Histogram Equalization,” Graphics Gems IV, 1994, pp. 474–485. https://doi.org/10.1016/B978-0-12-336156-1.50061-6
30. Reinhard et al., “Photographic Tone Reproduction for Digital Images,” ACM TOG 21(3):267–276, 2002 (local tone-mapping halos). https://doi.org/10.1145/566654.566575
31. “Improving the Recognition Accuracy of Tesseract-OCR Engine on Nepali Text Images via Preprocessing,” 2020 (Nepali preprocessing pipeline; accuracy gains on high/medium/low quality). https://doi.org/10.5281/zenodo.4361895
32. “OCR Accuracy Improvement on Document Images Through a Novel Pre-Processing Approach,” SIPIJ 6(4), 2015 (local brightness/contrast, grayscale conversion, unsharp masking, binarization). https://doi.org/10.5121/sipij.2015.6401
33. “Improving the Accuracy of Tesseract 4.0 OCR Engine Using Convolution-Based Preprocessing,” Symmetry 12(5):715, 2020 (learned kernels; F1 0.134→0.616). https://doi.org/10.3390/sym12050715
34. “Whispering to a Blackbox: Bootstrapping Frozen OCR with Visual Prompts,” arXiv:2603.05276, 2026 (learned preprocessing beats CLAHE baseline; 8% absolute CER reduction). https://arxiv.org/abs/2603.05276
35. “Assessing the Impact of Image Resolution on OCR Transcription Accuracy,” LangArc 2025. https://doi.org/10.12794/langarc2543322
36. “PreP-OCR: A Complete Pipeline for Document Image Restoration and Enhanced OCR Accuracy,” ACL 2025 (restoration + post-correction; 63.9–70.3% CER reduction on historical documents). https://aclanthology.org/2025.acl-long.749/

### Additional sources used for specific claims

37. Willus, “Tesseract accuracy vs capital-letter height” (≈30 px sweet spot), 2023. https://www.willus.com/blog.shtml?tesseract_accuracy
38. U.S. Government Printing Office, “Optimizing OCR Accuracy on Older Documents: A Study of Scan Mode, File Enhancement, and Software Products,” 2006 (thresholding/paper-color removal/downsampling reduced accuracy; contrast/unsharp did not significantly improve). https://www.govinfo.gov/media/WhitePaper-OptimizingOCRAccuracy.pdf
39. Rusiñol, Chazalon, Ogier, “Combining Focus Measure Operators to Predict OCR Accuracy in Mobile-Captured Document Images,” DAS 2014. https://doi.org/10.1109/DAS.2014.11
40. Alaei et al., “Document Image Quality Assessment: A Survey,” ACM Computing Surveys, 2023. https://doi.org/10.1145/3606692
41. Talvala et al., “Veiling Glare in High Dynamic Range Imaging,” 2006. https://graphics.stanford.edu/papers/glare_removal/glare_removal.pdf
42. Hasinoff et al., “Burst Photography for High Dynamic Range and Low-Light Imaging on Mobile Cameras,” SIGGRAPH Asia 2016. https://doi.org/10.1145/2980179.2980254
43. “Removing Shadows from Images of Documents,” ACCV 2016. http://civc.ucsb.edu/graphics/Papers/ACCV2016_DocShadow/PaperData/DocumentShadowRemoval-Paper.pdf
44. “Text-Aware Single Image Specular Highlight Removal,” arXiv:2108.06881, 2021. https://arxiv.org/abs/2108.06881

### Repository evidence

45. `mobile/lib/capture.dart` — `ResolutionPreset.high`; capture flow.
46. `mobile/lib/documents.dart` — original preservation; normalize → restore → enhance pipeline.
47. `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt` — 2500 px load cap; flat-field/denoise/unsharp/enlarge; deskew; video 1600 px.
48. `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/RapidOcr.kt` — 2000 px OCR cap; det 736 min side; rec 48 px height; width cap.
49. `mobile/tool/compare_ocr.py` — isolated Android paired comparison; hash verification.
50. `evals/harness/eval_document.py` — page CER/bagCER/digit/ECE/coverage/bootstrap methods.
51. `evals/harness/eval_lines.py` — recognition-only line-crop evaluation.
52. `docs/EVALUATION.md` — frozen sets, adopt-if gates, W2.1 Sauvola failure, photo-proxy CER, ECE 0.82.
53. `evals/README.md` — manifests and harness map.
54. `evals/comparisons/2026-10-17/README.md` — six-page Android/desktop comparison; ML Kit Bengali zero; no consistent winner.
55. `evals/bakeoff_results.md` — model bake-off; bagCER/order findings; page CER.

---

## 13. Bottom line

**The camera should optimize information capture:** resolution and framing (300 DPI at the page; ≥40–50 px line height in the OCR input), focus lock, exposure without clipping, stability, and glare-free diffuse light. It should not try to “enhance” the document; leave color/grayscale and let OCR see the raw signal.

**Post-processing should remove nuisance:** crop, perspective/deskew, illumination flattening with gain limiting, optional mild CLAHE/unsharp/denoise, and `INTER_AREA` resizing to the engine’s working size. It should not binarize by default, not over-sharpen, not over-denoise, and not upscale blindly.

**The current 720p capture and the 2500/2000 px caps are the first things to fix.** They are likely worth more CER than any preprocessing parameter. Measure the change with the paired harness before shipping; the repository’s frozen sets and bootstrap CIs are the right foundation.
