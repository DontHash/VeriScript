# Document Capture Science for OCR

**Scope:** evidence and engineering guidance for a Flutter/Android (minSdk 29) camera capture and real-time quality-guidance feature. The pipeline under design captures paper pages, detects boundaries, applies perspective correction, flattens grayscale shadows, runs ML Kit Latin/Devanagari OCR, and verifies digits.

**Date:** 2026-11-07  
**Audience:** VeriScript mobile engineering, QA, and product.

---

## 0. How to read this report

Every substantive claim is tagged:

- **[E] Established evidence** — standards, peer-reviewed papers, platform documentation, or direct optics/geometry.
- **[H] Engineering heuristic** — a defensible starting point that must be calibrated on real devices and paper.
- **[O] Open question** — needs device testing, a field study, or an OCR experiment before it becomes a product rule.

Where a paragraph mixes evidence and inference, both tags are shown (e.g. `[E + H]`). Most substantive sections have separate “Established evidence,” “Engineering heuristics,” and “Open questions” subsections so the three levels are visible without reading every tag.

Unless stated otherwise:

- Luminance is 8-bit sRGB, 0–255, computed from luma (BT.709: `Y = 0.2126R + 0.7152G + 0.0722B`; OpenCV's 8-bit grayscale uses BT.601 coefficients, `0.299R + 0.587G + 0.114B`). Pick one and keep it consistent.
- “Page ROI” means pixels inside the detected page quadrilateral, eroded slightly to avoid the paper edge.
- “Page height fraction” = page-quad height / frame height; “page area ratio” = page-quad area / frame area.
- “Frame-relative” means normalized by frame width, height, or diagonal, so thresholds survive preview/capture resolution changes.
- “Good enough” is defined for ML Kit Latin/Devanagari on printed paper. Tesseract-style 300 dpi guidance is reported where relevant, but ML Kit's documented minimum is lower.

**The single most important caveat:** there is no universal set of camera thresholds. OCR quality depends on text size, script, font weight, paper, lighting, lens, sensor, focusing, and the OCR engine. The numbers below are priors and starting points; the calibration protocol in §9 is what makes them defensible.

---

## 1. Executive summary: the most actionable thresholds

| # | Recommendation | Why |
|---|---|---|
| 1 | **Capture stills at 12 MP, 4:3 (≈4032×3024), not 720p.** Keep preview/analysis at 720p or 1080p. | The current capture code uses `ResolutionPreset.high`, documented by Flutter as ≈720p for image capture. At 720p a full A4 page is only ≈62 dpi; 10 pt capital letters are ≈6 px. That is below ML Kit's 16 px minimum and far below Tesseract's 30 px sweet spot. |
| 2 | **Judge framing by page height, not generic frame area.** Target page height 75–90% of the frame; for A4 in a 4:3 frame, a full page occupies at most ≈53% of frame area, and 42–48% is normal at 80–90% height. | A “60% page area” rule would force the user to crop the page. Aspect-normalized fill is the correct metric. |
| 3 | **Target Latin capital height ≈20–30 px and Devanagari glyph-cluster height ≈35–50 px** in the captured still; digits ≈25–35 px. | Matches ML Kit's 16×16 px minimum, Tesseract's ≈30 px capital sweet spot, and the extra vertical extent of Devanagari matras/conjuncts. |
| 4 | **Expose the paper, not the scene average.** Aim for page median luminance ≈180–225; keep clipped highlights (≥250) under ≈1–2% and clipped shadows (≤10) under ≈0.5–1%. Expect roughly +0.5 to +2.2 EV, with +1.5 to +2.1 EV typical when white paper fills the frame. | Reflected-light meters are calibrated near 18% average reflectance; white paper is ≈90%, so average metering renders it mid-gray or clips depending on background. |
| 5 | **Treat glare as a hard veto.** Reject if a saturated low-saturation glare blob covers more than ≈1–2% of the page; move the phone/light rather than relying on post-processing. | Specular glare saturates the sensor; text under it is unrecoverable. Veiling glare also lowers contrast globally. |
| 6 | **Use a normalized sharpness metric on the page ROI, never a raw portable Laplacian threshold.** Combine Tenengrad/variance-of-Laplacian with AF state and motion stability. | Focus measures depend on resolution, contrast, content, and noise. The folk “Laplacian variance >100” is only valid for a particular resolution/content. |
| 7 | **Require all four page corners inside the frame with ≥2–3% margin; no cut-off side; residual skew ≤2–3°; aim for camera tilt ≤20–30° (hard fail >35–45°).** | Cut-off sides lose content; extreme perspective loses effective resolution and increases blur; Tesseract and skew studies show OCR degrades with skew. |
| 8 | **Auto-capture only after 3–5 consecutive good frames (≈100–170 ms at 30 fps), with hysteresis and a 0.8–1.0 s cooldown.** | Prevents page-turn, hand, AF-hunt, and transient-glare false triggers; mirrors published/product temporal filtering. |
| 9 | **Budget ≈30 ms per analysis frame; decide within ≈0.5 s; fall back to manual shutter after 2–3 s.** | 30 fps gives 33 ms/frame; on-device document models in the literature run at 17–38 fps on mid/high-end phones. |
| 10 | **Fix resolution, focus, exposure, glare, and geometry at capture; use post-processing only for perspective, shadow flattening, and mild contrast.** | Post-processing can estimate or hide, but cannot recreate clipped, blurred, occluded, or under-sampled information. |
| 11 | **Calibrate per device/camera/resolution with a printed target and store a profile.** | Sensor, lens, AF, AE, and ISP behavior vary widely; a single threshold will either false-trigger on flagships or never trigger on low-end phones. |
| 12 | **Test 12 MP binned vs 48 MP full-res specifically for Devanagari and digits.** | 12 MP is likely sufficient for ML Kit Latin; 8–10 pt Devanagari is marginal. 48 MP may help in bright light but adds noise, motion sensitivity, and latency. |

**Suggested priority order:** (1) fix the capture resolution/aspect ratio, (2) add page-ROI exposure/sharpness/glare metrics, (3) implement the auto-capture state machine with hard vetoes, (4) calibrate per device, (5) run the 12 MP vs 48 MP and Devanagari experiments. Do not spend time tuning auto-capture thresholds on 720p captures; the resolution limit dominates.

---

## 2. Resolution and sampling

### 2.1 Established evidence

**OCR is limited by pixels per character, not by a DPI number in metadata.**

- Tesseract's documentation says it “works best on images which have a DPI of at least 300 dpi,” and recommends rescaling. It also links a test suggesting an optimal capital-letter height in pixels. [E]
- Willus's Tesseract benchmark characterizes resolution by “the height of a typical capital letter in pixels” and reports a sweet spot of about **30 px** for capital-letter height, with no continuing improvement at higher resolution in that test. [E]
- ML Kit's Text Recognition v2 documentation says each character should ideally be **at least 16×16 px**, with “generally no accuracy benefit for characters to be larger than 24×24 px.” It gives an example that a letter-sized page might require a **720×1280** image. That is a lower bound and an example, not a quality target. [E]
- Industrial OCR guidance converges on **20–30 px character height**: Basler's OCR vTool says 20–30 px is appropriate and characters below 20 px are problematic; Adaptive Recognition gives 20 px minimum for non-Latin characters and license plates. [E]
- A 2025 study by Boubehziz et al. reports reliable OCR at approximately **39 dpi for a 14×21 in document** in its specific setup, with error rising sharply below that, and negligible JPEG impact. This is a useful reminder that the causal variable is pixels per glyph and engine context, not a universal 300 dpi law; it does **not** justify 39 dpi for 8–10 pt phone captures. [E, with scope caveat]
- The U.S. GPO's 2006 OCR study used **400 dpi for color/grayscale** and **600 dpi for bitonal** scanning, and found that downsampling to 300 or 200 dpi **reduced** OCR accuracy on older documents; contrast/unsharp masking did not significantly improve it, and paper-color removal/thresholding hurt. [E]

**Paper dimensions and scan equivalents.** A4 is 210×297 mm (8.27×11.69 in); US Letter is 8.5×11 in. [E]

| Page | 200 dpi | 300 dpi | 400 dpi | 600 dpi |
|---|---:|---:|---:|---:|
| A4 (8.27×11.69 in) | 1654×2339 (3.9 MP) | 2481×3507 (8.7 MP) | 3308×4676 (15.5 MP) | 4962×7014 (34.8 MP) |
| Letter (8.5×11 in) | 1700×2200 (3.7 MP) | 2550×3300 (8.4 MP) | 3400×4400 (15.0 MP) | 5100×6600 (33.7 MP) |

**The camera geometry trap.** A 4:3 sensor frame is wider than A4 (frame aspect 1.333 vs page aspect 0.707). If the whole A4 page fits in the frame, page **height** is the limiting dimension. A full A4 page occupies at most:

- **53% of a 4:3 frame** (0.707 / 1.333),
- **40% of a 16:9 frame** (0.707 / 1.778).

At 80% page-height fill, A4 occupies only ≈42% of a 4:3 frame. Therefore a generic “page must fill 60% of the frame” rule is wrong for A4/Letter; it would force cropping. Use page-height fraction or aspect-normalized area. [E + geometry]

**Effective resolution by camera mode** (A4, 11.69 in page height, page fills 80% of frame height; capital height assumed 0.7 em):

| Camera mode | Frame px | Page height @80% | Effective dpi | 10 pt cap height | 8 pt cap height |
|---|---:|---:|---:|---:|---:|
| 720p (1280×720, 16:9) | 720 | 576 | **49 dpi** | **4.8 px** | 3.8 px |
| 1080p (1920×1080, 16:9) | 1080 | 864 | **74 dpi** | **7.2 px** | 5.7 px |
| 8 MP 4:3 (3264×2448) | 2448 | 1958 | **167 dpi** | **16.3 px** | 13.0 px |
| 12 MP 4:3 (4032×3024) | 3024 | 2419 | **207 dpi** | **20.1 px** | 16.1 px |
| 48 MP 4:3 (8000×6000) | 6000 | 4800 | **411 dpi** | **39.9 px** | 31.9 px |

At 100% page-height fill, the same modes give ≈62, 92, 209, 259, and 513 dpi respectively. The table makes the central point: **720p capture is not a document scanner**; 8 MP is at ML Kit's lower bound for 10 pt text; 12 MP is a sensible default for ML Kit Latin; 48 MP is the only mode that comfortably reaches Tesseract-style 300 dpi across a full A4 page, and even then only if the lens and focus deliver the detail.

**8 MP vs 12 MP vs 48 MP, noise, and binning.**

- A 12 MP 4:3 sensor has ≈24% more linear resolution than 8 MP 4:3; the gain in pixels per character is real but modest.
- 48 MP sensors are commonly Quad Bayer: four adjacent same-color pixels can be binned to a 12 MP output for low-light sensitivity, or remosaiced for full 48 MP resolution in bright light. Binning trades spatial resolution for SNR; 2×2 binning quadruples signal and improves SNR by ≈2× when shot-noise limited (more when read-noise limited), while halving linear resolution. [E]
- Full-resolution 48 MP does not automatically deliver 2× the detail of 12 MP: lens MTF, diffraction, demosaicing, noise, and motion all intervene. In bright, stable conditions it can help small print/digits; in ordinary handheld indoor light, the binned 12 MP output is often more robust. [E + H]
- JPEG compression at reasonable quality is not the main limit; the 2025 resolution study found JPEG impact negligible. Still, capture at quality ≥90 and avoid repeated re-encoding. [E + H]

### 2.2 Engineering heuristics

- **Capture still:** 12 MP, 4:3, no digital zoom; 48 MP full-res only as an optional “small print/digits” mode in bright light and stable conditions. If staying on the Flutter camera plugin, `ResolutionPreset.max` is the closest preset, but verify it returns a 4:3 still rather than a cropped 16:9 size; native CameraX `ImageCapture` gives more control over resolution/aspect ratio.
- **Preview/analysis:** 1280×720 or 960×720, grayscale, 10–15 fps analysis. If using CameraX, set `ImageAnalysis` resolution explicitly; its default target is 640×480, too low for page-edge detection and small-text metrics. Do not use preview resolution as the captured still: a 720p preview is 1280 px wide versus 4032 px for a 12 MP still (≈3.15× linear, ≈13× fewer pixels), and preview sharpness/denoising differ from the still. Use preview for geometry, stability, exposure, glare, and AF state; verify the still after capture.
- **Target text size:** Latin capital height 20–30 px (30–35 px for small print or Tesseract-like engines); Devanagari full glyph cluster 35–50 px; digits 25–35 px. If a page has 8 pt text and the measured cap height is <16 px, the capture is at the ML Kit floor and should be flagged. Devanagari handwritten-character datasets commonly normalize glyphs to 32×32 (UCI), so 35–50 px in the captured page gives useful headroom for matras, conjuncts, and segmentation. Keep digit crops at ≥25 px height; do not downscale the digit re-read crop below the OCR floor. For Devanagari, measure the full cluster including the shirorekha and matras, not just the base glyph.
- **Downsampling for OCR:** if the capture is above ≈400 dpi equivalent, downsample to 300–400 dpi equivalent with a good filter (Lanczos/area) before OCR. Do not downsample below ≈250–300 dpi equivalent unless the engine has been tested; GPO found downsampling hurt.
- **Do not upscale before OCR as a default.** Mild upscaling can help some engines on tiny text, but it cannot create detail; test it. Super-resolution is not a substitute for optical resolution.
- **Page-height rule:** 75–90% of frame height for auto-capture. Below 60% is a “move closer” state; above ≈95% risks cutting off corners and text.
- **Runtime resolution check:** compute `dpi_eff = (capture_height × page_height_fraction) / page_height_in`. If it is below ≈200 dpi for ML Kit Latin, or below ≈240–300 dpi for Devanagari/small print, show “move closer” or switch to 48 MP. Do this from the actual JPEG dimensions, not the preview preset.
- **Current code risk:** `mobile/lib/capture.dart` initializes `CameraController(..., ResolutionPreset.high, ...)`. Flutter documents `high` as ≈720p for image capture. Verify the actual JPEG dimensions on a device; if confirmed, this is the dominant quality limit and should be changed before tuning any downstream metric.

### 2.3 Open questions

- What is ML Kit's true minimum for **Devanagari** on our fonts and print sizes? The 16×16 px guidance is script-agnostic; matras and conjuncts may need more.
- Does 48 MP full-res improve ML Kit Devanagari/digit accuracy enough to justify the latency, storage, and motion risk?
- Is 12 MP binned better than 8 MP for our target phones after denoising and JPEG?
- What is the best OCR input resolution for ML Kit: native 12 MP, 300 dpi equivalent, or 400 dpi equivalent?
- How much does page fill vs distance affect lens softness at the corners on low-end phones?

---

## 3. Exposure and dynamic range

### 3.1 Established evidence

**Metering and white paper.** Reflected-light exposure meters are calibrated around an average scene reflectance in the ≈15–18% range; ISO 2720 specifies calibration levels and test conditions for general-purpose photoelectric exposure meters. A white paper page is ≈90% reflectance, about 5× (≈2.3 EV) brighter than 18% gray in linear terms. If the page fills the frame, an average-metering AE will tend to bring the paper down toward mid-gray (sRGB ≈118), i.e. it will look gray/underexposed for document capture. If the background is dark, average AE may instead overexpose the page. [E + optics]

**Clipping is irreversible.** Once a sensor pixel saturates, the highlight detail is gone. Google's HDR+ pipeline deliberately chooses an exposure low enough to avoid clipping, captures a burst, and merges frames to reduce noise and increase dynamic range; the paper explicitly treats blown highlights as unrecoverable by later processing. Exposure bracketing can recover highlights only if at least one bracket frame has unclipped detail. [E]

**Glare.** Veiling glare is light scattered inside the lens/body; it lowers contrast across the whole field, even where no pixel is clipped. Specular glare is direct reflection of a bright source; on coated/laminated paper it can saturate large regions. Single-image highlight removal can inpaint plausible texture, but cannot recover text that was covered by glare; multi-view capture and stitching are more reliable. [E]

**Hand/phone shadows.** A hand or phone that blocks the light source usually creates a soft shadow with a smooth gradient; that is largely recoverable by background division/flat-field correction. A hard shadow that clips blacks (or a shadow over text with no light reaching it) is not recoverable. Prefer diffuse light from multiple directions and keep the phone/hand out of the light path. [E + H]

**Flash/torch.** A phone torch/flash is a small, close source: illuminance falls as 1/d², producing a hot spot, and direct reflection from coated paper produces specular glare. Flash/torch can help in very low light but is usually the wrong default for document capture. [E + physics]

### 3.2 Metrics and defensible thresholds

Compute these on the page ROI, excluding a small border:

- **Page median luminance** `Y50`.
- **Highlight clipping fraction** `f_hi = fraction(Y ≥ 250)`.
- **Shadow clipping fraction** `f_lo = fraction(Y ≤ 10)`.
- **Local contrast** `C = p90(Y) − p10(Y)` (or p95−p5).
- **Shadow uniformity:** divide the page into a 5×5 grid; compute a background estimate per tile (e.g. 75th percentile); `U = max(tile_bg) / min(tile_bg)`.
- **Glare:** pixels with `Y ≥ 250` and low saturation (`max(R,G,B) − min(R,G,B) < 20`), connected components; `G = largest_blob_area / page_area`.
- **Histogram shape:** text and paper should form two modes; Otsu threshold should sit between them. A single narrow mode means blank/defocused/overexposed page.

| Metric | Green | Amber | Red | Basis |
|---|---:|---:|---:|---|
| Page median `Y50` | 180–225 | 150–180 or 225–240 | <150 or >240 | [H] sRGB paper target; calibrate per paper/light |
| Highlight clipping `f_hi` | <1% | 1–3% | >3% | [H] clipped text/glare is lost |
| Shadow clipping `f_lo` | <0.5% | 0.5–2% | >2% | [H] clipped shadow text is lost |
| Local contrast `C` | ≥110 | 80–110 | <80 | [H] enough separation for binarization/OCR |
| Shadow uniformity `U` | <1.25 | 1.25–1.5 | >1.5 | [H] tile background variation |
| Glare blob `G` | <0.5% | 0.5–2% | >2% | [H] specular/veiling glare veto |

**EV guidance.** With white paper filling the frame, expect roughly **+1.5 to +2.1 EV** to move an average-metered page from sRGB ≈118 to ≈210–225. Because AE implementations differ (highlight protection, center weighting, scene detection), start with **+1.0 EV**, adapt using the histogram, and allow a range of **+0.5 to +2.2 EV**. If the page occupies only 50–70% of the frame and the background is dark, less compensation may be needed; if the background is bright, more. [H, derived from 18% gray math]

### 3.3 AE strategy

1. **Meter on the page, not the whole frame.** Use a center/page ROI AE region (CameraX `FocusMeteringAction` with `FLAG_AE`, or camera2 AE regions). Query `ExposureState` for the supported compensation range/step, clamp, and wait for `CONTROL_AE_STATE_CONVERGED`/`LOCKED` before auto-capture. [E + platform]
2. **Lock AE before the still.** Once the page is stable and exposure is in range, lock AE/AWB/AF, then capture; this prevents last-moment AE drift when the user’s hand or background changes.
3. **Prefer a single correctly exposed frame.** A single frame with `f_hi < 1–2%` and `Y50` in range is more robust than aggressive HDR tone mapping, which can create halos around text.
4. **Bracket only when static and high dynamic range.** If shadow detail and highlight detail cannot both fit, capture 3 frames at −1/0/+1 EV (or 0/+1/+2 EV for white paper), align, and either pick the best or merge. Exposure bracketing has been shown to improve document readability and OCR, but it requires a static page and alignment; handheld motion between frames is the main risk. [E + H]
5. **Avoid flash/torch by default.** If light is truly insufficient, prefer a diffuse, off-axis light; if using the torch, expect a hot spot and check glare metrics. Never fire flash directly at coated paper. [H]
6. **Anti-banding.** Set camera anti-banding to 50/60 Hz or AUTO; LED/PWM dimming can produce horizontal bands at short exposures. [E + H]
7. **White balance lock.** Lock AWB when the page is stable; auto AWB can shift between preview and still. For grayscale OCR, WB is secondary, but extreme casts reduce luminance contrast. [H]

### 3.4 Open questions

- Does +EV or exposure bracketing actually improve ML Kit Devanagari OCR on our paper/lighting, or does it just change binarization?
- What is the best target median for ML Kit (it may prefer a different tone curve than Tesseract)?
- How often do phone HDR modes help vs introduce halos on text?
- What glare fraction on coated/laminated paper is still OCR-safe?
- Does torch with a diffuser beat ambient light in low-light classrooms?

---

## 4. Focus and sharpness

### 4.1 Established evidence

**Autofocus needs contrast/texture.** Contrast-detection and hybrid AF systems need scene detail to find focus; a blank, low-contrast page is a hard target. Android exposes AF state (`CONTROL_AF_STATE_FOCUSED_LOCKED`, `PASSIVE_FOCUSED`, `NOT_FOCUSED_LOCKED`, `PASSIVE_UNFOCUSED`, etc.) and lens state (`LENS_STATE_STATIONARY`/`MOVING`), so the app can wait for a real focus lock instead of guessing. CameraX exposes `FocusMeteringResult.isFocusSuccessful()` and allows AF/AE/AWB locking. [E]

**Focus measures.** Classical focus measures include variance of Laplacian (Pech-Pacheco et al.), Tenengrad/Sobel energy, modified Laplacian (Nayar & Nakagawa), Brenner gradient, and Fourier high-frequency energy. Comparative work on document images shows that combinations of focus measures can predict OCR accuracy well, and that gradient/Laplacian measures outperform simple local variance/entropy on text. [E]

**Blur is information loss.** Defocus and motion blur remove high-frequency detail. Deconvolution can partially restore mild blur, but it is ill-posed, amplifies noise, and can create ringing/halos around strokes; severe blur is not recoverable. [E]

**Depth of field is shallow at document distance.** With a typical phone lens (≈4.7 mm, f/1.8, 1.4 µm pixel, 30 cm subject), total DOF is roughly 20 mm; at 20 cm it is ≈9 mm; at 40 cm ≈36 mm. A curved page or book gutter can easily exceed the DOF, so one side of the page may be sharp and the other soft. [E + optics calculation; see Appendix A]

### 4.2 Metrics

Compute on the page ROI, grayscale, at a fixed analysis width (e.g. 960 or 1280 px), with a light Gaussian blur (σ≈1) to suppress noise:

- **Variance of Laplacian:** `Var(∇²I)`. Fast, sensitive to noise and content.
- **Tenengrad:** `Σ(Gx² + Gy²)` or `mean(√(Gx²+Gy²))`. More robust to illumination than variance of intensity.
- **Modified Laplacian:** `Σ(|∂²I/∂x²| + |∂²I/∂y²|)` with a step size; designed for shape-from-focus.
- **Normalized Tenengrad:** `T = mean(|∇I|) / (p95(I) − p5(I))` on the page ROI. This removes much of the contrast dependence and is a good default for cross-device calibration.
- **Fourier high-frequency ratio:** `E_hf / E_total` for frequencies above a fixed fraction of Nyquist. Useful as a second opinion; sensitive to noise and JPEG.

**Never ship a raw Laplacian-variance threshold without calibration.** The widely cited “variance < 100 = blurry” is a heuristic for a particular image size/content; it is not portable across 720p, 1080p, 12 MP, contrast, and paper texture. Use ISO 12233 slanted-edge MTF for camera/lens characterization, but use ROI focus measures (Tenengrad/Laplacian) for per-frame auto-capture decisions; they answer different questions.

### 4.3 Thresholds and capture strategy

| Metric / condition | Green | Amber | Red | Basis |
|---|---:|---:|---:|---|
| AF state | `FOCUSED_LOCKED` or `PASSIVE_FOCUSED` + `LENS_STATE_STATIONARY` | `PASSIVE_SCAN` / `ACTIVE_SCAN` | `NOT_FOCUSED_LOCKED` / `PASSIVE_UNFOCUSED` | [E] platform states |
| Laplacian variance, 720p page ROI | >120 | 60–120 | <60 | [H] starting point; calibrate |
| Normalized Tenengrad `T` | device-specific | device-specific | device-specific | [H] use percentile calibration |
| Frame-to-frame corner motion | <0.5% diagonal/frame | 0.5–1.5% | >1.5% | [H] stability veto |
| Shutter speed (handheld) | ≥1/125 s | 1/60–1/125 s | <1/60 s | [H] text-plane motion; OIS helps |
| ISO | ≤400 | 400–800 | >800 | [H] noise vs shutter trade |
| Page bow vs DOF | <0.5× DOF | 0.5–1× DOF | >1× DOF | [H] curvature blur |

**Capture strategy:**

1. **Tap-to-focus or AF region on the page center/text.** Do not focus on the background, hand, or table.
2. **Use continuous AF while framing, then trigger AF and wait for lock.** On CameraX: `startFocusAndMetering` with `FLAG_AF`; on camera2: `CONTROL_AF_TRIGGER_START` and wait for `CONTROL_AF_STATE_FOCUSED_LOCKED`. [E]
3. **Check lens state and focus score.** If AF reports `NOT_FOCUSED_LOCKED`, show “Move closer / find text” rather than capturing.
4. **Short shutter, moderate ISO.** Prefer 1/100–1/250 s and ISO ≤400–800; stabilize with OIS and a two-handed grip. At 30 cm, 1 mm of hand motion in 1/60 s is ≈11 px of blur; at 1/250 s it is ≈3 px. [H, order of magnitude]
5. **Focus bracketing/stacking for books/curved pages.** If the page bow exceeds DOF, capture 3–5 frames at different focus distances and pick/merge the sharpest tiles. Only when the page is static; avoid ghosting. [H]
6. **Do not trust preview sharpness alone.** Preview may be downscaled/denoised differently from the still. Use preview for stability/AF and verify the still after capture. [E + H]

### 4.4 Open questions

- Which focus metric combination best predicts ML Kit OCR on our pages: Tenengrad, Laplacian variance, modified Laplacian, or a fusion?
- How well does preview sharpness correlate with still sharpness across devices?
- Does focus stacking materially improve OCR on book gutters/curved pages, or is it too slow/ghost-prone?
- What AF behavior do low-end phones show on blank/low-contrast paper, and how quickly do they recover?
- What is the best shutter/ISO trade for indoor classroom lighting?

---

## 5. Illumination uniformity and color

### 5.1 Established evidence

**Binarization and shadow handling.** Otsu's method finds a global threshold from the histogram; Sauvola's adaptive method handles non-uniform illumination by using local mean/variance. Tesseract uses Otsu internally and offers adaptive Otsu/Sauvola in v5. OpenCV provides global, adaptive, and Otsu thresholding. These methods help with uneven light but cannot recover clipped shadow/highlight detail. [E]

**Shadow removal / flat-field correction.** Document shadow-removal methods estimate local background and text colors and correct a shadow map; flat-field correction removes vignetting and illumination non-uniformity by dividing by a reference/background. These are effective for soft shadows and illumination gradients, not for hard clipped shadows. [E]

**What processing actually helped OCR.** The GPO study found that RGB scanning was best for old/discolored documents; grayscale and color OCR accuracy were essentially equal; threshold adjustment, paper-color removal, and downsampling **reduced** accuracy; contrast adjustment and unsharp masking did **not** significantly improve it. This is a strong warning against aggressive “scan enhancement” before OCR. [E]

**Grayscale.** For black text on white paper, luma conversion is appropriate and reduces color-channel noise. Use BT.601/BT.709 luma; do not average R/G/B equally. [E]

**Devanagari.** Devanagari has a headline (shirorekha), matras above/below, and conjuncts; hard binarization can merge or break these features. The script is also harder for OCR in general: a 2025 printed-text study reports 24.47% word error rate even in a constrained character-level pipeline. Treat Devanagari as needing more pixels and gentler preprocessing than Latin. [E + H]

### 5.2 White balance and color temperature

- **AWB lock.** Auto white balance can drift between preview and still, especially with mixed light. Lock AWB when the page is stable; use `FLAG_AWB` in CameraX or `CONTROL_AWB_LOCK` in camera2. [E]
- **Target neutral paper.** For OCR, the important thing is luminance contrast, not perfect color. Aim for neutral-ish paper under 4000–6500 K light; avoid strongly tinted/mixed lighting. [H]
- **Mixed lighting.** Daylight from a window plus warm fluorescent/LED produces a color gradient across the page and can confuse AWB. Move to a more uniform light or lock AWB on the page center. [H]
- **LED flicker/PWM.** Use anti-banding (50/60 Hz/AUTO) and avoid very short exposures under dimmed LEDs; banding appears as horizontal stripes and hurts OCR. [E + H]
- **Extreme casts.** Sodium/very warm light compresses blue-channel contrast; grayscale conversion can still work, but check local contrast. Per-channel white balance or gray-world on the page background can help. [H]

### 5.3 Shadow flattening and contrast normalization

Recommended post-capture order:

1. **Keep the original color image.** Never overwrite it.
2. **Perspective rectify** at native resolution.
3. **Convert to luma** (BT.601/709).
4. **Estimate background** with a large morphological closing or Gaussian blur (kernel much larger than text stroke width; e.g. 5–10% of page width).
5. **Divide by background** and rescale to preserve paper white; clamp to avoid clipping.
6. **Mild contrast normalization** only if local contrast is low. CLAHE with clip limit ≈2–4 and 8×8 tiles is a reasonable starting point; test with and without. [H]
7. **Do not hard-binarize before ML Kit by default.** ML Kit accepts grayscale/color input; hard thresholding before the model is not required and can destroy anti-aliased strokes and Devanagari matras. Test binarization as an experiment, not a default. [H/O]
8. **Avoid aggressive unsharp masking.** It can create halos around strokes; GPO found no significant OCR gain. Mild unsharp may help visually but should be OCR-tested. [E + H]

### 5.4 Heuristics table

| Control | Recommendation |
|---|---|
| White balance | Lock AWB on page; target neutral paper; avoid mixed light |
| Color temperature | 4000–6500 K preferred; 2700 K usable if contrast is good |
| Grayscale | Luma BT.601/709; not RGB average |
| Shadow flattening | Large-kernel background division; preserve paper white |
| Contrast | Only if `p90−p10 < 80–100`; CLAHE clip 2–4 |
| Binarization | Avoid before ML Kit by default; test Sauvola/Otsu |
| Unsharp | Mild only; OCR-test; expect little gain |
| Paper color removal | Avoid; GPO found it hurt |
| JPEG quality | ≥90; avoid re-encoding |

### 5.5 Open questions

- Does white balance/color temperature materially affect ML Kit Devanagari accuracy, or only visual quality?
- Is grayscale always better than color for ML Kit on colored/cream paper?
- Does shadow flattening improve ML Kit OCR, or does ML Kit's internal preprocessing already handle it?
- What CLAHE/binarization settings, if any, help Devanagari without breaking matras?
- How much does LED banding hurt OCR on low-end phones?

---

## 6. Geometry: page detection, perspective, curvature

### 6.1 Established evidence

- Camera-based document capture research treats page detection/segmentation in preview frames as a first-class problem; the ICDAR SmartDoc 2015 challenge explicitly defines the pipeline as detect/segment during preview, assess capture quality, optionally trigger capture, and produce a high-quality output from the high-resolution capture. Its dataset includes realistic focus/motion blur, perspective, illumination change, and partial occlusion. [E]
- Perspective rectification is a homography; it resamples the image and cannot increase information. Extreme tilt makes one side farther away (lower effective dpi) and increases blur; at 45° tilt the far-side scale is ≈1/cos45° ≈1.41× worse, at 60° ≈2× worse. [E + geometry]
- Page curvature/physical distortion is a major source of OCR error. DewarpNet reports a **42% average character error rate reduction** on captured document images after unwarping, showing that curvature matters; but it is a model-based correction and can introduce artifacts/hallucinations. [E + H]
- Skew hurts OCR line segmentation; Tesseract's docs say quality “reduces significantly if a page is too skewed.” Some document systems reject skew beyond ≈5°. [E]

### 6.2 Metrics and thresholds

| Metric | Green | Amber | Red | Basis |
|---|---:|---:|---:|---|
| Page detection confidence | ≥0.80 | 0.60–0.80 | <0.60 | [H] composite score |
| Page height fraction | 0.75–0.90 | 0.60–0.75 | <0.60 (or >0.95 cut-off risk) | [H] resolution/framing |
| Page area, A4 in 4:3 | 42–53% | 32–42% | <32% | [E geometry] max ≈53% |
| Page area, A4 in 16:9 | 30–40% | 22–30% | <22% | [E geometry] max ≈40% |
| Corner margin | ≥3% of min(frame w,h) | 1–3% | <1% | [H] detection/crop safety |
| Cut-off side | none | — | any side touches frame | [E product practice] |
| Residual skew | ≤2° | 2–5° | >5° | [E skew studies; H cutoff] |
| Camera tilt from page normal | ≤20° | 20–35° | >35° | [H] perspective/resolution |
| Edge straightness deviation | ≤1% page height | 1–2% | >2% | [H] curvature/quad error |
| Rectified aspect error | ≤8% | 8–15% | >15% | [H] wrong quad/page type |
| Gutter shadow band | ≤3% page width | 3–5% | >5% | [H] book gutter |

**Page detection confidence** can be a weighted combination of:
- edge support along the quadrilateral perimeter (fraction of sampled edge points with strong gradient),
- corner strength/localization,
- convexity and no self-intersection,
- area plausibility,
- expected aspect ratio after rectification,
- temporal consistency with the previous frame.

Calibrate the weights and threshold on labeled frames; don't treat the number as a probability.

**Corner angles are a weak signal.** Perspective legitimately changes corner angles away from 90°. Use edge straightness, convexity, and homography plausibility rather than requiring near-right angles. Product patents measure distortion via deviation from 90° and opposite-side length differences, but those are relative scores, not absolute pass/fail rules. [E product practice + H]

### 6.3 Capture heuristics

- **Fill the frame with the page, but keep a margin.** Page height 75–90%, all corners ≥2–3% inside. If the page fills 100% height, the top/bottom margins are zero and corner detection/cropping becomes fragile.
- **Shoot one page at a time for books.** A two-page spread halves the effective resolution per page and puts text in the gutter; capture left/right separately unless the spread is the desired output.
- **Flatten the page.** Hand curvature/fold/gutter is the main geometric enemy. If the page bows more than the DOF (≈1–2 cm at 20–30 cm), one side will blur; flatten or use focus stacking/dewarping.
- **Avoid extreme tilt.** Keep the phone roughly parallel to the page; ≤20° is comfortable, 20–35° is usable with rectification, >35–45° loses resolution and increases blur.
- **Center the page.** Corner detection and AE/AF metering are easier when the page is centered and the background is uncluttered.
- **Detect the gutter.** If a dark band/gradient occupies >3–5% of page width at the binding, warn or split; text in the gutter may be distorted/occluded.
- **Do not rely on dewarping for folds/occlusion.** A crease that crosses text or a hand covering text is information loss; dewarping cannot recover it.

### 6.4 Open questions

- What page-detection confidence threshold gives <5% bad auto-captures on low-end phones?
- How much curvature can be tolerated before ML Kit OCR degrades: 1%, 2%, 5% of page height?
- Does offline dewarping (DewarpNet/DocUNet-style) improve our OCR enough to justify model size/latency, and does it hallucinate text?
- What is the best way to detect/handle book gutters: split, dewarp, or capture one page at a time?
- How strict should tilt be for A4 text vs receipts/IDs?

---

## 7. Real-time quality assessment and auto-capture

### 7.1 Established evidence

**The canonical pipeline.** SmartDoc 2015 describes the desired capture process as: detect/segment the document in preview; assess capture conditions and guide the user; optionally trigger capture at the right moment; produce a high-quality output from the high-resolution capture. This is exactly the architecture VeriScript needs. [E] Google's ML Kit Document Scanner API provides a bundled viewfinder/preview flow and scanning logic, but it does not expose its internal quality thresholds; treat it as a product reference, not a specification. [E product reference]

**A modern on-device implementation.** Adobe Research's 2024 handheld video document scanner uses a cascaded system: a lightweight Page Change Network (64×64 grayscale, CNN-LSTM) runs on every frame; a larger Capture Network (MobileNetV2, 320×320) runs only when needed. It labels capture attributes: hand/finger covering content, page content out of frame, out of focus/motion blur, glare, page lifted, two pages, graphical. On-device runtimes: CapN ≈5–39 fps (≈17–38 fps on the mid/high-end phones in the study) and PCN ≈42–557 fps depending on phone and CPU/GPU delegate; a 5-frame look-ahead at 30 fps adds ≈166 ms. At a capture-network filter threshold of 0.6, the expensive network ran on only 3.7% of frames with no F1 loss (F1 ≈0.94). [E]

**Product/patent practice.** Mitek's automatic-capture patent describes real-time measurement of orientation angle, motion, edge detection, focus, exposure, contrast, reflection, shadow, cut-off corners, warped image, image size, and aspect ratio; thresholds can be per-device and can differ between preview and captured image; the system can keep the best preview frame over time, use AF state, and fall back to manual capture. It gives example orientation thresholds of ≈5° maximum and ≈2° variation, and a normalized focus score where in-focus images score ≈1000 and very out-of-focus images ≈50–100. These are product heuristics, not universal science. [E product practice]

**Document-specific QA beats generic IQA.** The DIQA survey notes that OCR accuracy does not always correlate with visual quality, and generic metrics such as PSNR/MSE can rank images very differently from OCR. Document-specific features (Tenengrad, Laplacian, modified Laplacian, Brenner, edge/stroke features, skew) and OCR-labeled training are more relevant. [E]

**OCR confidence is a weak quality signal.** A sharp image can still yield lower OCR accuracy for reasons unrelated to blur (layout, fonts, language model, segmentation), and confidence calibration varies by engine. Use engine confidence only as a secondary signal; image metrics and digit cross-checks are more direct. [E + H]

### 7.2 Proposed state machine for VeriScript

```
searching → candidate → stabilizing → ready → capturing → verifying → cooldown
     ↑            ↑            │           │          │           │
     └────────────┴────────────┴───────────┴──────────┴───────────┘
```

- **searching:** no page; show “Point at a page.”
- **candidate:** page detected; compute metrics; check hard vetoes.
- **stabilizing:** geometry/fill/exposure plausible; wait for N consecutive good frames and stable corners.
- **ready:** all vetoes pass and score ≥ enter threshold; show “Hold still.”
- **capturing:** lock AF/AE/AWB; trigger still capture.
- **verifying:** analyze the still at capture resolution; if good, save; else return to candidate with a specific message.
- **cooldown:** 0.8–1.0 s before the next auto-capture.

### 7.3 Per-frame metrics

| Group | Metrics |
|---|---|
| Page | quad, area ratio, height ratio, corner margins, edge support, detection confidence |
| Sharpness | normalized Tenengrad, Laplacian variance, AF state, lens state |
| Exposure | `Y50`, `f_hi`, `f_lo`, local contrast, shadow uniformity |
| Glare | saturated low-saturation blob fraction, largest blob |
| Stability | corner displacement/frame, optical flow or homography change, gyro/accelerometer |
| Temporal | consecutive good frames, score EMA, hysteresis state |

### 7.4 Fusion and vetoes

**Hard vetoes (any one blocks auto-capture):**
- page not detected or confidence < threshold,
- any side cut off / corner margin < ≈1%,
- AF not focused or lens moving,
- highlight clipping > ≈3% or shadow clipping > ≈2% of page,
- glare blob > ≈2% of page,
- sharpness below the “red” threshold,
- motion above the “red” threshold,
- page turn/hand occlusion detected.

**Soft score (example starting point):**

```
Q = 0.30·S + 0.20·E + 0.15·G + 0.20·F + 0.15·T
```

where `S` = normalized sharpness, `E` = exposure score, `G` = glare score (1 − glare fraction), `F` = fill/geometry score, `T` = temporal stability. Trigger when `Q ≥ 0.75` for 3 consecutive frames and no veto; stop if `Q < 0.60` (hysteresis). These weights are **not** scientifically derived; tune them on labeled frames. [H]

### 7.5 Latency budget

| Stage | Target | Notes |
|---|---:|---|
| Frame capture/analysis | 30 fps → 33 ms/frame; 15 fps → 66 ms | If analysis >30 ms, run every 2nd/3rd frame |
| Page detection | 10–25 ms at 720p | Classical CV on grayscale; cascade |
| Quality metrics | 10–20 ms on page ROI | Sharpness/histogram/glare |
| Auto-capture decision | <500 ms after page becomes good | 3–5 frames |
| Still capture | 0.5–1.5 s | Device-dependent; lock 3A first |
| Still verification | 100–300 ms | Page ROI metrics; optional OCR on a crop |

The Adobe 2024 runtimes show that cascading is essential: a cheap model every frame, an expensive model only on candidates. Apply the same principle: cheap page detection every frame; sharpness/glare/geometry every 1–3 frames or when the page is stable. [E]

### 7.6 False-trigger avoidance

- **Temporal consistency:** require 3–5 consecutive good frames; use an EMA of scores; use hysteresis (enter strict, exit loose).
- **Page-turn detection:** frame differencing/edge motion; suppress auto-capture while the page or phone is moving.
- **Hand/occlusion:** skin-color or learned occlusion check; warn “Move your hand.”
- **Glare:** reject when a glare blob appears/disappears; do not average it away.
- **AF hunt:** do not trigger while `PASSIVE_SCAN`/`ACTIVE_SCAN`; wait for focused/stationary.
- **Cooldown:** 0.8–1.0 s after a capture; prevents double captures.
- **Best-frame selection:** keep the top few candidate frames/scores; if the still fails verification, return to ready rather than saving a bad page.
- **Manual override:** always show the shutter; auto-capture is an assist, not a prison.

**Suggested acceptance targets:** auto-capture precision ≥95% (of auto-captures, ≤5% fail post-capture QA), recall ≥80% of pages within 3 s of the page becoming good, false triggers <1/min. These are product targets, not published constants. [H]

### 7.7 Open questions

- What fusion weights/thresholds maximize precision without making auto-capture too slow?
- Do handcrafted metrics suffice, or is a small learned quality model needed?
- What is the real latency on a 4 GB Android 10 device at 720p/1080p?
- How do users react to auto-capture vs manual shutter? Does it reduce retakes?
- Can page detection run on the preview stream without stealing camera bandwidth from still capture?
- How should the app handle pages with photos/graphics where text metrics are sparse?
- How robust is hand/occlusion detection across skin tones, sleeves, and dark backgrounds?

---

## 8. Optical/capture vs computational correction

### 8.1 Principle

Capture is the only opportunity to acquire information. Post-processing can estimate, redistribute, or hide missing information, but it cannot recreate photons that were clipped, blurred, occluded, or never sampled. This is the information-theoretic version of “get it right in camera.” [E]

### 8.2 Correction matrix

| Problem | Best capture-time action | Post-capture option | Recoverable? |
|---|---|---|---|
| Too few pixels / small text | 12–48 MP, fill frame, optical zoom | Downsample/upscale, mild sharpen | Detail below Nyquist is lost; upscaling cannot create it |
| Defocus | AF lock, tap-to-focus, focus bracket | Deconvolution, sharpening | Mild defocus partly; severe defocus lost |
| Motion blur | Short shutter, stabilize, burst | Deconvolution, frame selection | Severe motion blur lost |
| Highlight clipping / glare | Lower EV, change angle, shade light, bracket | HDR merge if bracketed; inpainting | Single-frame clipped text/glare lost |
| Shadow clipping | Add light, raise EV, bracket | Lift shadows | Clipped shadow detail lost |
| Soft shadow / uneven light | Diffuse light, flat-field reference | Background division, shadow removal | Mostly recoverable |
| Veiling glare | Shade lens/page, avoid bright source in frame | Glare removal/deconvolution | Contrast loss partly recoverable; clipped detail not |
| Perspective | Keep phone parallel, fill frame | Homography | Resampling loss; extreme tilt loses |
| Page curvature | Flatten page, one page at a time, focus stack | Dewarping | Can improve; fold/occlusion lost; model may hallucinate |
| Fold/crease across text | Flatten/reposition | Dewarp/inpaint | Text under fold lost |
| Color cast | AWB lock, neutral light | Gray-world/white patch | Mostly recoverable; luma contrast matters |
| Noise | Low ISO, good light, binning | Denoise | Recoverable with detail loss; avoid over-smoothing |
| JPEG artifacts | Quality ≥90, avoid re-encode | None | Irreversible; avoid |

### 8.3 What cannot be recovered

- **Clipped highlights:** text under specular glare, white paper detail above 255, saturated light sources.
- **Clipped shadows:** text in a hard shadow at 0, underexposed pages.
- **Severe motion blur:** information spread beyond the stroke; deconvolution may create ringing but not truth.
- **Severe defocus:** same; deconvolution is ill-posed.
- **Resolution below Nyquist:** upscaling/super-resolution can make text look nicer but cannot recover the true glyph.
- **Occlusion:** hand/finger, fold, gutter, object on page.
- **Wrong capture geometry:** a side cut off, page out of frame, extreme tilt that loses one side.
- **Aggressive HDR/denoise artifacts:** halos, texture loss, “cartoon” text; avoid.

### 8.4 Recommended VeriScript pipeline

**Recommended defaults:**

| Setting | Default |
|---|---|
| Still capture | 12 MP, 4:3, no digital zoom |
| Preview/analysis | 1280×720 (or 960×720), 10–15 fps |
| JPEG quality | 92–95 |
| AF | page-center/text region; continuous while framing; lock on ready |
| AE | page ROI; +1.0 EV starting point, adapt to histogram; lock on ready |
| AWB | lock on ready; neutral paper |
| Torch/flash | off by default |
| Auto-capture | on, with hard vetoes + 3–5 frames + hysteresis + cooldown; manual shutter always available |

**Capture:**
1. Still: 12 MP 4:3 default; 48 MP optional in bright/stable conditions; no digital zoom.
2. Preview/analysis: 720p/1080p grayscale; 10–15 fps.
3. AF/AE/AWB: page-center region; lock on ready; EV +0.5 to +2.2 adaptive; torch off.
4. Auto-capture: hard vetoes + soft score + 3–5 frames + hysteresis + cooldown + still verification.
5. Manual shutter always available.

**Post-capture:**
1. Preserve original.
2. Perspective rectify at native resolution.
3. Grayscale (luma).
4. Shadow flatten with large-kernel background division.
5. Mild contrast only if needed; avoid hard binarization before ML Kit by default.
6. OCR; digit re-read/cross-check.
7. Keep a “needs review” flag when confidence/quality is marginal.

### 8.5 Open questions

- Which corrections actually improve ML Kit OCR on our corpus, and which only look better?
- Does dewarping help or hurt Devanagari OCR?
- Is 48 MP + downsample better than 12 MP native for small print?
- How much sharpening is safe before OCR degrades?
- Can we expose a “raw/untouched” capture for debugging and re-processing?

---

## 9. Concrete thresholds and per-device calibration

### 9.1 Threshold summary

Use these as **starting values**, then calibrate. “Green” = auto-capture/fine; “Amber” = guide/allow manual; “Red” = veto. Unless a row says “720p ROI,” thresholds refer to the captured still/rectified page; preview-analysis thresholds must be calibrated separately at the analysis resolution.

| Area | Metric | Green | Amber | Red |
|---|---|---|---|---|
| Resolution | Capture still | ≥12 MP 4:3 | 8–12 MP 4:3 | <8 MP / 720p |
| Resolution | Latin 10 pt cap height, ML Kit | ≥20 px | 16–20 px | <16 px |
| Resolution | Latin cap height, small print/Tesseract | ≥30 px | 24–30 px | <24 px |
| Resolution | Devanagari cluster height | ≥36 px | 24–36 px | <24 px |
| Resolution | Effective dpi, ML Kit Latin | ≥200 | 160–200 | <160 |
| Resolution | Effective dpi, Tesseract/small print/Devanagari | ≥300 | 240–300 | <240 |
| Framing | Page height fraction | 0.75–0.90 | 0.60–0.75 or 0.90–0.95 | <0.60 or >0.95 |
| Framing | A4 area in 4:3 | 42–53% | 32–42% | <32% |
| Framing | A4 area in 16:9 | 30–40% | 22–30% | <22% |
| Geometry | Corner margin | ≥3% | 1–3% | <1% |
| Geometry | Cut-off side | none | — | any |
| Geometry | Residual skew | ≤2° | 2–5° | >5° |
| Geometry | Camera tilt | ≤20° | 20–35° | >35° |
| Geometry | Edge straightness | ≤1% page height | 1–2% | >2% |
| Geometry | Aspect error after rectification | ≤8% | 8–15% | >15% |
| Exposure | Page median | 180–225 | 150–180 / 225–240 | <150 / >240 |
| Exposure | Highlight clipping | <1% | 1–3% | >3% |
| Exposure | Shadow clipping | <0.5% | 0.5–2% | >2% |
| Exposure | Local contrast p90−p10 | ≥110 | 80–110 | <80 |
| Exposure | Shadow uniformity max/min | <1.25 | 1.25–1.5 | >1.5 |
| Glare | Largest glare blob | <0.5% page | 0.5–2% | >2% |
| Focus | AF state | focused + stationary | scanning | not focused |
| Focus | Laplacian variance, 720p ROI | >120 | 60–120 | <60 |
| Focus | Corner motion | <0.5% diag/frame | 0.5–1.5% | >1.5% |
| Focus | Shutter | ≥1/125 s | 1/60–1/125 s | <1/60 s |
| Focus | ISO | ≤400 | 400–800 | >800 |
| Auto | Consecutive good frames | 3–5 | 2 | 1 |
| Auto | Score `Q` | ≥0.75 | 0.60–0.75 | <0.60 |
| Auto | Cooldown | 0.8–1.0 s | — | — |
| Latency | Analysis/frame | ≤30 ms | 30–50 ms | >50 ms |
| Latency | Decision | ≤500 ms | 0.5–1 s | >1 s |

**Engine caveat:** ML Kit can recognize text at 16×16 px/character, and 12 MP A4 at 80% fill gives ≈20 px caps for 10 pt Latin. That is acceptable for ML Kit Latin but below Tesseract's ≈30 px sweet spot and marginal for Devanagari. The table therefore uses a higher bar than ML Kit's absolute minimum. [E + H]

A green value in one row is necessary but not sufficient: auto-capture requires all hard gates (geometry, focus, exposure, glare, stability) plus the soft score to pass. A red value in any hard gate vetoes the frame.

### 9.2 Calibration procedure

**Target design (one A4/Letter page):**
- Latin text at 6, 8, 10, 12, 14 pt (same font family as the product content; include serif/sans).
- Devanagari text at 8, 10, 12, 14 pt (include matras/conjuncts and digits).
- A slanted edge or ISO 12233-style chart for MTF; a grid/checkerboard for geometry.
- Gray patches at ≈18%, 50%, 90% reflectance; a white and a black patch.
- A page with a soft shadow and a page with a specular glare source (for negative tests).
- Page numbers/digits in known positions for OCR scoring.

**Capture matrix:**
- 3 distances: 20, 30, 40 cm (or page fills 60%, 80%, 95% of height).
- 3 lighting conditions: daylight window, warm indoor LED, low light.
- 3 repeats per condition; 3 devices: low-end 4 GB, midrange, flagship; Android 10/13/15 if possible.
- Both 12 MP binned and 48 MP full-res where available; preview 720p/1080p.

**Measurements:**
- Actual captured JPEG dimensions; effective dpi from page height; text cap height in pixels (manual or connected-component measurement).
- Sharpness: variance of Laplacian, normalized Tenengrad, modified Laplacian on page ROI.
- Exposure: `Y50`, `f_hi`, `f_lo`, local contrast, shadow uniformity.
- Glare: blob fraction.
- Geometry: page height/area, corner margin, residual skew, tilt, edge straightness.
- OCR: character error rate (CER)/word error rate (WER) for Latin and Devanagari; digit accuracy; ML Kit confidence.

**Threshold setting:**
- For sharpness, collect the distribution of “acceptable” (OCR CER below target) and “bad” images. Set the threshold at the 5th percentile of acceptable images, or at the point that maximizes Youden's J / keeps false accepts below target. Do not use a single raw Laplacian number across devices.
- For exposure, use the median of acceptable images; set clipping limits at the 95th/99th percentile of clean pages.
- For geometry, label bad quads/occlusions and choose thresholds that keep auto-capture precision ≥95%.
- Validate on held-out pages and a different device; check auto-capture precision/recall and OCR CER.

**Store a profile** keyed by `Build.MODEL`, camera ID, capture resolution, and analysis resolution. Example schema (illustrative, not final):

```json
{
  "device": "Pixel 7",
  "cameraId": "0",
  "capture": {"width": 4032, "height": 3024, "aspect": "4:3"},
  "analysis": {"width": 1280, "height": 720},
  "sharpness": {"metric": "tenengrad_norm", "green": 0.12, "amber": 0.08},
  "exposure": {"median": [180, 225], "clipHi": 0.02, "clipLo": 0.01},
  "glare": {"maxBlob": 0.01},
  "geometry": {"pageHeight": [0.75, 0.90], "cornerMargin": 0.02},
  "latencyMs": 25
}
```

### 9.3 Test plan / acceptance criteria

- **Functional:** auto-capture triggers on good pages; never captures a cut-off side or a page with a hand over text.
- **Quality:** auto-captured pages have OCR CER no worse than ≈10–15% relative to manually captured good pages (tighten or relax from product goals).
- **Robustness:** works across 3 devices, 3 lighting conditions, Latin and Devanagari, matte and coated paper.
- **False triggers:** <1/min in a 10-minute aiming session; precision ≥95%.
- **Latency:** analysis ≤30 ms/frame on the low-end device at 720p; decision ≤500 ms; still capture/verify ≤1.5 s.
- **User experience:** one clear guidance message at a time; manual shutter always works; no crashes on camera lifecycle changes.

### 9.4 Open questions

- What OCR CER target is achievable for 8–10 pt Devanagari on low-end phones?
- Does per-device calibration generalize across OS updates/ISP changes?
- Can we ship a small calibration target in-app, or must QA use a printed chart?
- How often should profiles be recalibrated?
- Can on-device telemetry (metrics + OCR confidence) refine thresholds without privacy risk?

---

## 10. Sources

All URLs accessed **2026-11-07** unless otherwise noted. Standards are cited by number; where a public preview/sample exists, the URL is given.

### Standards and optics

| ID | Source | URL |
|---|---|---|
| S1 | ISO 216 — A4 210×297 mm (1975 preview; dimensions unchanged in current standard) | https://cdn.standards.iteh.ai/samples/4087/9050e9a6768b43e2bcdedca70c895c61/ISO-216-1975.pdf |
| S2 | ANSI/ASME Y14.1 — US Letter 8.5×11 in (standard; no stable public URL) | — |
| S3 | ISO 2720:1974 — exposure meter calibration | https://cdn.standards.iteh.ai/samples/7690/31617d4fbe1843c5b8c3eaea5b3c2164/ISO-2720-1974.pdf |
| S4 | ISO 12233:2017 — resolution/MTF measurement | https://cdn.standards.iteh.ai/samples/71696/2b2be0b6ec904495b9243e7376ab7310/ISO-12233-2017.pdf |
| S5 | ITU-R BT.709 — luma coefficients | https://www.itu.int/rec/R-REC-BT.709/en |
| S6 | CIE standard illuminants | https://cie.co.at/datatable/cie-standard-illuminants |

### OCR and document capture research

| ID | Source | URL |
|---|---|---|
| R1 | Tesseract — Improving the quality of the output (300 dpi; Otsu/Sauvola; skew) | https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html |
| R2 | Willus — Tesseract accuracy vs capital-letter height (≈30 px sweet spot) | https://www.willus.com/blog.shtml?tesseract_accuracy |
| R3 | ML Kit Text Recognition v2 — Android (16×16 px; 24×24 no benefit; 720×1280 example) | https://developers.google.com/ml-kit/vision/text-recognition/v2/android |
| R4 | ML Kit Document Scanner — Android (product flow) | https://developers.google.com/ml-kit/vision/doc-scanner/android |
| R5 | IBM — OCR accuracy considerations (300 dpi guidance) | https://www.ibm.com/docs/en/rpa/23.0.x?topic=automation-considerations-about-ocr-accuracy |
| R6 | Basler — OCR vTool (20–30 px character height) | https://docs.baslerweb.com/ocr-vtool |
| R7 | Adaptive Recognition — input image guide (20 px minimum non-Latin) | https://adaptiverecognition.com/app/uploads/DOC/Software/Carmen/brief_guide_for_input_images.pdf |
| R8 | Google Cloud Vision — supported files/dimensions | https://docs.cloud.google.com/vision/docs/supported-files |
| R9 | UCI — Devanagari Handwritten Character Dataset (32×32) | https://archive.ics.uci.edu/ml/datasets/Devanagari+Handwritten+Character+Dataset |
| R10 | Boubehziz, Koudoro-Parfait, Lejeune — Assessing the Impact of Image Resolution on OCR Transcription Accuracy (2025) | https://hal.science/hal-05620753v1 ; https://doi.org/10.12794/langarc2543322 |
| R11 | GPO — Optimizing OCR Accuracy on Older Documents (2006) | https://www.govinfo.gov/media/WhitePaper-OptimizingOCRAccuracy.pdf |
| R12 | Hasinoff et al. — Burst photography for HDR and low-light imaging (HDR+) | https://doi.org/10.1145/2980179.2980254 ; https://people.csail.mit.edu/hasinoff/pubs/HasinoffEtAl16-hdrplus.pdf |
| R13 | Liu et al. — Exposure Bracketing Techniques for Camera Document Image Enhancement (2019) | https://doi.org/10.3390/app9214529 |
| R14 | Talvala et al. — Veiling Glare in High Dynamic Range Imaging | https://graphics.stanford.edu/papers/glare_removal/glare_removal.pdf |
| R15 | Removing Shadows from Images of Documents (ACCV 2016) | http://civc.ucsb.edu/graphics/Papers/ACCV2016_DocShadow/PaperData/DocumentShadowRemoval-Paper.pdf |
| R16 | Highlight removal for camera captured documents based on image stitching | https://www.semanticscholar.org/paper/bebf5e270b15401e148602ed40b458f862273d9f |
| R17 | Text-Aware Single Image Specular Highlight Removal | https://arxiv.org/abs/2108.06881 |
| R18 | Pech-Pacheco et al. — Diatom autofocusing: variance of Laplacian / modified Laplacian | https://doi.org/10.1109/ICPR.2000.903548 ; https://ccia.ugr.es/vip/files/conferences/Autofocusing2000.pdf |
| R19 | Nayar & Nakagawa — Shape from Focus (modified Laplacian) | https://doi.org/10.1109/34.308479 |
| R20 | Rusiñol et al. — Combining Focus Measure Operators to Predict OCR Accuracy in Mobile-Captured Document Images | https://doi.org/10.1109/DAS.2014.11 |
| R21 | OpenCV — Autofocus using OpenCV: comparative study of focus measures | https://opencv.org/autofocus-using-opencv-a-comparative-study-of-focus-measures-for-sharpness-assessment/ |
| R22 | PyImageSearch — Blur detection with OpenCV (Laplacian variance heuristic) | https://pyimagesearch.com/2015/09/07/blur-detection-with-opencv/ |
| R23 | Baker & Kanade — Limits on super-resolution and how to break them | https://doi.org/10.1109/TPAMI.2002.1033210 |
| R24 | Levin et al. — Understanding and evaluating blind deconvolution algorithms | https://doi.org/10.1109/CVPR.2009.5206815 |
| R25 | Sauvola & Pietikäinen — Adaptive document image binarization | https://doi.org/10.1016/S0031-3203(99)00055-2 |
| R26 | Otsu — A Threshold Selection Method from Gray-Level Histograms | https://doi.org/10.1109/TSMC.1979.4310076 |
| R27 | OpenCV — Histogram equalization/CLAHE | https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html |
| R28 | Alaei et al. — Document Image Quality Assessment: A Survey (2023) | https://doi.org/10.1145/3606692 |
| R29 | Krithika et al. — OCR-based document image quality assessment (2026) | https://doi.org/10.3389/frsip.2026.1779355 |
| R30 | Peng et al. — Automated image quality assessment for camera-captured OCR (2011) | https://doi.org/10.1109/ICIP.2011.6116204 |
| R31 | Kumar et al. — A Dataset for Quality Assessment of Camera Captured Document Images (2013) | https://doi.org/10.1007/978-3-319-05167-3_9 |
| R32 | SmartDoc 2015 — ICDAR competition on smartphone document capture and OCR | https://doi.org/10.1109/ICDAR.2015.7333943 ; https://sites.google.com/site/icdar15smartdoc/home |
| R33 | SmartDoc 2015 dataset (120 clips, ≈24k frames, annotated quads) | https://zenodo.org/record/1230218 ; https://sites.google.com/site/icdar15smartdoc/challenge-1/dataset |
| R34 | SmartDoc-QA — quality assessment dataset | https://doi.org/10.1109/ICDAR.2015.7333960 |
| R35 | Devanagari OCR — Offline Recognition of Devanagari Script: A Survey | https://doi.org/10.1109/TSMCC.2010.2095841 |
| R36 | Devanagari OCR — printed text character-level pipeline (2025) | https://doi.org/10.11591/ijece.v15i6.pp5914-5923 |
| R37 | Document skew estimation and correction | https://doi.org/10.1080/08839514.2011.607009 |
| R38 | Skew rejection above ≈5° (document analysis practice) | https://www.iajit.org/downloadfile/2168 |
| R39 | DewarpNet — single-image document unwarping (42% CER reduction) | https://sagniklp.github.io/dewarpnet-webpage/ |
| R40 | DocUNet — document unwarping project | https://www3.cs.stonybrook.edu/~cvl/projects/DocUnwarp/index.html |
| R41 | Wigington et al. — Handheld Video Document Scanning: A Robust On-Device Model (Adobe, 2024) | https://arxiv.org/abs/2411.00576 |
| R42 | Mitek — Systems and methods for automatic image capture on a mobile device (US11539848B2) | https://patents.google.com/patent/US11539848B2/en |
| R43 | Beyond OCRs for Document Blur Estimation | https://ieeexplore.ieee.org/document/8270113/ |
| R44 | Document Image Quality Assessment via Explicit Blur and Text Size Estimation | https://doi.org/10.1007/978-3-030-86337-1_19 |

### Camera/platform and image processing

| ID | Source | URL |
|---|---|---|
| P1 | Flutter camera — `ResolutionPreset` (`high` ≈720p, `max` highest) | https://pub.dev/documentation/camera/latest/camera/ResolutionPreset.html |
| P2 | Android CameraX — configuration (preview/analysis/capture resolutions, exposure compensation) | https://developer.android.com/media/camera/camerax/configuration |
| P3 | Android CameraX — `FocusMeteringAction` (AF/AE/AWB regions, lock, success) | https://developer.android.com/reference/androidx/camera/core/FocusMeteringAction |
| P4 | Android camera2 — `CameraCharacteristics` (sensor, lens, AF, exposure compensation) | https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics |
| P5 | Android camera2 — `CaptureRequest` (AF/AE/AWB/flash/antibanding/stabilization) | https://developer.android.com/reference/android/hardware/camera2/CaptureRequest |
| P6 | Android camera2 — `CaptureResult` (AF/AE/AWB/lens states) | https://developer.android.com/reference/android/hardware/camera2/CaptureResult |
| P7 | Sony — Quad Bayer Coding (binning/remosaic) | https://www.sony-semicon.com/en/technology/mobile/quad-bayer-coding.html |
| P8 | Teledyne — Pixel binning and SNR | https://www.teledynevisionsolutions.com/learn/learning-center/imaging-fundamentals/binning/ |
| P9 | OpenCV — Image thresholding (global/adaptive/Otsu) | https://docs.opencv.org/4.x/d7/d4d/tutorial_py_thresholding.html |
| P10 | OpenCV — Laplacian operator | https://docs.opencv.org/4.x/d5/db5/tutorial_laplace_operator.html |
| P11 | OpenCV — Structural analysis and shape descriptors (`approxPolyDP`) | https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html |

---

## Appendix A — Useful calculations

### A.1 Effective dpi and text height

For a page of physical height `H_in` (A4 11.69 in, Letter 11 in) occupying `f` fraction of the captured frame height `H_px`:

```
dpi_eff = (H_px × f) / H_in
```

For a font of size `P` points, a rough capital-height fraction is 0.7 em:

```
cap_px = 0.7 × (P / 72) × dpi_eff
```

Example: 12 MP 4:3, page 80% of height:
`dpi_eff = 3024 × 0.8 / 11.69 ≈ 207 dpi`; 10 pt cap ≈ `0.7 × 10/72 × 207 ≈ 20 px`.

### A.2 Page area ratio

For page aspect `a_page = width/height` and frame aspect `a_frame = width/height`, a page that fits the frame height occupies:

```
area_ratio = a_page / a_frame
```

A4 in 4:3: `0.707 / 1.333 ≈ 0.53`; A4 in 16:9: `0.707 / 1.778 ≈ 0.40`; Letter in 4:3: `0.773 / 1.333 ≈ 0.58`. At 80% height fill, multiply by 0.8 (A4 4:3 ≈0.42).

### A.3 Exposure compensation from 18% gray

If AE maps average scene reflectance to 18% linear, and the page is 90% linear white, the page is 5× brighter (≈2.32 EV). To render it at sRGB 210 instead of 118, the linear ratio is ≈3.5× (≈1.8 EV); at 225, ≈4.1× (≈2.0 EV). Hence the +1.5 to +2.1 EV starting range when the page fills the frame; AE highlight protection may reduce this.

### A.4 Depth of field at document distance

Thin-lens approximation for close-up:

```
m = f / (d − f)
DOF ≈ 2 N c (1 + m) / m²
```

With `f=4.7 mm`, `N=1.8`, `c=0.0014 mm`:
- d=20 cm: m≈0.024, DOF≈9 mm
- d=30 cm: m≈0.016, DOF≈20 mm
- d=40 cm: m≈0.012, DOF≈36 mm

A page bow larger than the DOF will blur part of the page; focus stacking or flattening is needed.

### A.5 Motion blur order of magnitude

At 30 cm with the same lens, `m≈0.016`. A 1 mm subject-plane hand motion produces ≈16 µm sensor motion; at 1.4 µm pixel pitch that is ≈11 px. At 1/250 s, a comparable hand speed gives ≈2.7 px. OIS reduces this, but text-plane motion (page/phone relative) remains.

### A.6 Resolution loss from tilt

For camera tilt `θ` from the page normal, the far side is ≈`1/cosθ` farther than the near side. At 30°: ≈1.15×; at 45°: ≈1.41×; at 60°: ≈2×. This is a geometric scale loss on top of focus/blur; keep tilt ≤20–30° for document capture.

---

## Appendix B — Suggested analyzer outline

This is a sketch, not production code:

```text
every analysis frame (720p grayscale, 10–15 fps):
  quad, conf = detect_page(frame)
  if conf < 0.6: state = searching; continue

  page = warp_preview(frame, quad)
  S = normalized_tenengrad(page)
  Y = histogram(page)
  E = exposure_score(Y)          # median, clipping, contrast
  G = glare_fraction(page)
  F = geometry_score(quad, frame) # height, area, margins, aspect
  M = motion_score(prev_quad, quad)
  A = af_ae_awb_state()

  if hard_veto(conf, quad, Y, G, S, M, A): state = candidate; continue

  score = 0.30*S + 0.20*E + 0.15*(1-G) + 0.20*F + 0.15*M
  update hysteresis/consecutive counters
  if score >= enter and consecutive >= 3:
      lock AF/AE/AWB
      still = capture_still()
      if verify(still): save; cooldown
      else: guide(retry)
```

**Guidance priority:** cut-off side → resolution/fill → focus → glare → exposure → stability. Show one message at a time; do not flash metrics.

---

## Appendix C — Glossary

- **Cap height:** height of a capital Latin letter; a proxy for pixels per character.
- **CER/WER:** character/word error rate.
- **DOF:** depth of field.
- **EV:** exposure value; +1 EV doubles exposure.
- **Glare (specular):** direct reflection of a light source; often clipped.
- **Veiling glare:** scattered light that lowers contrast globally.
- **MTF:** modulation transfer function; lens/sensor sharpness vs spatial frequency.
- **Page ROI:** pixels inside the detected page quadrilateral.
- **Quad:** four-corner page boundary.
- **Tenengrad:** gradient-energy focus measure.
- **Variance of Laplacian:** focus measure based on second-derivative variance.
- **3A:** auto-focus, auto-exposure, auto-white-balance.

---

## Appendix D — What would change this report

This report should be revised after:

1. Measuring actual capture resolution on target devices (especially the `ResolutionPreset.high`/720p issue).
2. Running the calibration target through ML Kit Latin and Devanagari at 8/10/12 pt.
3. Comparing 12 MP binned vs 48 MP full-res on the same pages.
4. Measuring auto-capture precision/recall in a 10-minute field session.
5. Testing glare/shadow thresholds on coated/laminated paper and book gutters.
6. Measuring analysis latency on a 4 GB Android 10 device.
7. Validating whether shadow flattening/CLAHE/binarization help or hurt ML Kit Devanagari.

Until then, treat the numbers as **priors**, not promises.
