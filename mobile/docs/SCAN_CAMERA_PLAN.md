# In-app scan camera with automatic tuning (Android first)

**Status:** proposed implementation plan. Phase 0 is implemented; see [`SCAN_CAMERA_PHASE0.md`](SCAN_CAMERA_PHASE0.md).
**Date:** 2026-11-07 (Phase 0 verification 2026-11-09)
**Scope:** Android app in `mobile/` (Flutter, minSdk 29, offline release build).
**Related research (all in `mobile/docs/research/`):**

- [`camera-plugin-capabilities.md`](research/camera-plugin-capabilities.md) - exact limits of `camera: 0.12.1` / `camera_android_camerax` 0.7.5+1.
- [`document-capture-science.md`](research/document-capture-science.md) - resolution, exposure, focus, glare, geometry, auto-capture thresholds.
- [`native-camera-architecture.md`](research/native-camera-architecture.md) - CameraX vs Camera2, stream combinations, component design, effort.
- [`ocr-preprocessing.md`](research/ocr-preprocessing.md) - what capture must fix vs what post-processing can fix, resolution plumbing, OCR measurement.
- [`scanner-ux-competition.md`](research/scanner-ux-competition.md) - Google/Microsoft/Adobe/Apple/Samsung patterns, guidance priority, UX pitfalls.

Many numbers below are starting points from the research, not universal constants. They must be calibrated per device and against OCR results.

---

## 0. Decision in one page

1. **The app already has an in-app camera, but it is a thin wrapper.** `mobile/lib/capture.dart` uses `CameraController` with `ResolutionPreset.high` (about 720p) for both photos and video. It has no live quality analysis and no tuning loop. The photos are imported raw, then aligned/enhanced after the user taps Done.
2. **Build a purpose-built native CameraX scan camera** (Option B in the architecture research): separate `Preview`, `ImageAnalysis`, and `ImageCapture` use cases, Flutter texture preview, Kotlin analyzer on a background thread, 12 MP 4:3 stills, and a small MethodChannel/EventChannel API.
3. **Keep the Flutter `camera` plugin only for the existing book-video route and as a fallback.** The two camera owners must never be open at the same time.
4. **Auto-tune the things that actually affect OCR:** resolution, framing, focus, exposure/EV, glare, stability, and light (torch). Contrast is handled after capture; there is no portable Camera2 "contrast" control, and local tone mapping/HDR can hurt OCR.
5. **Manual shutter is always available. Auto-capture is optional and confidence-gated; default it off at launch** until field data proves the thresholds. This follows the strongest patterns in the scanner UX research: manual-first, one message at a time, no surprising shutter.
6. **Fix the downstream resolution plumbing.** A 12 MP capture is wasted if `normalize`, `restore`, `enhance`, and RapidOCR keep downsizing to 2500/2000 px. This plan includes a resolution audit and an OCR A/B gate before changing defaults.
7. **Guidance copy comes later, but the engine emits structured reason codes now** (`MOVE_CLOSER`, `HOLD_STILL`, `GLARE`, `PAGE_CURVED`, etc.). The temporary UI can show plain English; localization and coaching copy can be added without changing the vision/control layer.
8. **Effort:** roughly 8-11 engineer-weeks for one engineer for the full scope. A useful MVP (native 12 MP capture + live overlay + basic auto EV/AF/torch + manual shutter) is about 5-7 weeks. Auto-capture, manual controls, calibration, and hardening add the rest.

---

## 1. What the app does today

Relevant current behavior:

- `mobile/lib/review.dart` starts `CaptureScreen` for the `camera` action, passes an `onPhoto` callback, and after the capture screen closes, runs `restore` (boundary/perspective/deskew) and `enhance` (grayscale shadow flattening, denoise, sharpening) on each new page if the user settings are enabled.
- `mobile/lib/capture.dart`:
  - selects the first back camera;
  - creates one `CameraController` with `ResolutionPreset.high`;
  - uses the same controller for photo and video modes;
  - saves a photo via `takePicture()`, then calls `onPhoto(path)`.
- `mobile/lib/documents.dart`:
  - `DocumentStore.importImage` copies the captured file to an app-private `original_*.jpg`;
  - runs native `normalize` to a `source_*.jpg`;
  - optionally runs `restore` and `enhance`;
  - saves the draft after each page.
- `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt`:
  - loads images with a default `maxSide` of 2500 px (5000 px only for a few methods);
  - does OpenCV page detection, perspective warp, deskew, flat-field background division, bilateral denoise, mild unsharp, and optional 2x enlargement;
  - caps warped output at 12.5 MP.
- `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/RapidOcr.kt`:
  - downsizes OCR input to max side 2000 px.
- The release manifest has `CAMERA` but no `INTERNET` permission. The app is fully offline.

**Consequence:** even if the camera captured 12 MP, the current pipeline would downsample the page to 2500 px before/around processing and RapidOCR would downsample again to 2000 px. For A4 that is roughly 214 DPI and 171 DPI, below the 250-300 DPI target for small print and Devanagari. Fixing the camera without fixing this would produce better-looking originals but little OCR gain.

---

## 2. Research findings that drive the design

| Finding | Evidence / source | Design consequence |
|---|---|---|
| **Resolution is the dominant limit.** A 720p still gives an A4 page roughly 60-90 DPI; 10 pt Latin capitals are only a few pixels. 12 MP 4:3 is the sensible target; 8 MP is the floor. | `document-capture-science.md` sections 1-2; `ocr-preprocessing.md` section 1; ML Kit 16x16 px guidance; Tesseract ~20-30 px x-height | Capture 12 MP 4:3; keep preview/analysis at 720p-1080p; never tune quality thresholds on 720p captures. |
| **Frame the page by height, not generic area.** A4 in a 4:3 frame occupies only about 42-53% of frame area at 80-90% page height in landscape; a "page must fill 60% of the frame" rule would force cropping. | `document-capture-science.md` section 1 and 9.1 | Use page-height fraction 0.75-0.90 (Latin) / 0.80-0.90 (Devanagari), plus corner margins and aspect checks. Do not use a naive area percentage. |
| **Expose the paper, not the scene average.** Target page paper level around 180-225/255, highlight clipping under 1-2%, shadow clipping under 0.5-1%. White paper can need +0.5 to +2.2 EV. | `document-capture-science.md` section 3; `ocr-preprocessing.md` section 1 | Meter on the page ROI; use p75/p90 of luma for paper level; EV loop with deadband and bounds. |
| **Glare is a hard veto.** Specular highlights saturate the sensor and destroy the strokes underneath; post-processing cannot recover them. | `document-capture-science.md` sections 3 and 9.1; `ocr-preprocessing.md` section 2 | Detect saturated, low-gradient blobs; reject auto-capture above about 1-2% of page; guide tilt/move/light off. |
| **Sharpness and motion are better than a raw Laplacian threshold.** Focus measures depend on resolution, content, noise, and device. | `document-capture-science.md` section 4 | Use a normalized sharpness score on the page ROI, plus quad stability/AF result; calibrate per device. |
| **Geometry: all four corners inside with 2-3% margin; residual skew <= 2-3 degrees; camera tilt ideally <= 20-30 degrees.** | `document-capture-science.md` section 6; `scanner-ux-competition.md` section 4.1 | Detect quad confidence, corner margins, aspect, opposite-side ratios, edge straightness, and quad stability. Emit framing reasons. |
| **Auto-capture needs temporal filtering and hysteresis.** Require several consecutive good frames, enter/exit thresholds, cooldown, and duplicate suppression. | `document-capture-science.md` section 7; `scanner-ux-competition.md` sections 5 and 9 | State machine with 6-8 good frames, 1.5-2 s cooldown, dHash duplicate suppression; manual shutter always bypasses. |
| **Capture vs post-processing division.** Capture must fix resolution, focus, exposure, glare, and geometry. Post can fix perspective, soft shadows, color cast, mild noise/contrast. | `ocr-preprocessing.md` section 2; `document-capture-science.md` section 8 | Do not promise post-hoc recovery of clipping/blur; add a capture quality gate. |
| **The stock Flutter camera plugin cannot run low-res analysis and high-res stills together.** One `ResolutionPreset` controls preview, stream, capture, and video. It also lacks manual ISO/shutter/WB, crop/rotation metadata, continuous point AF/AE, and reliable high-res capture. | `camera-plugin-capabilities.md` sections 1-10 and Appendix A | Custom native CameraX layer is required for the target behavior. The plugin is only an interim improvement and video path. |
| **Leading scanners are manual-first and show one prioritized message.** Auto-capture is an enhancement, not a replacement for the shutter. | `scanner-ux-competition.md` sections 4-5 and 9 | Manual shutter permanent; one guidance message at a time; minimum display time and repeat cooldown; auto-capture default off. |
| **Devices vary widely; absolute thresholds do not transfer.** | `document-capture-science.md` section 9; `scanner-ux-competition.md` section 4.1 | Normalize metrics; store a device/camera/resolution profile; conservative defaults; device matrix before enabling auto-capture. |
| **No portable camera-side contrast control.** Camera2 has no reliable "contrast" key across devices; tone curves/HDR are vendor-specific and can create halos. | `ocr-preprocessing.md` sections 1-2 and 8 | Auto-tune exposure/light/focus; handle contrast with flat-field and conditional mild unsharp after capture, measured by OCR. Do not add a fake contrast slider in v1. |

---

## 3. Options considered

| Option | What it gives | What it cannot do | Verdict |
|---|---|---|---|
| **A. Retrofit the Flutter `camera` plugin** | Fast: switch photo mode to `ResolutionPreset.max`, add EV/AE lock, AF point, torch, zoom, capture validation. Maybe 1-2 weeks. | One resolution preset for preview/stream/capture; no low-res analysis + 12 MP still; no manual ISO/shutter/WB; no crop/rotation metadata; stream copies on main thread; high-res black-JPEG bug. | **Interim only.** Use the resolution fix as a quick win; do not build the tuning loop on it. |
| **B. Native CameraX + Flutter texture + Kotlin analyzer** | Separate resolutions; background analysis; 12 MP capture; Camera2Interop for optional manual controls; precise crop/rotation; full control loop. | More code and device testing; CameraX stream-combination limits on some devices; texture/rotation mapping must be verified. | **Chosen.** Bounded addition to an app that already has Kotlin/OpenCV/ML Kit/ONNX. |
| **C. Full Camera2 pipeline without CameraX** | Maximum control, potentially full sensor/RAW. | Session/lifecycle/3A/rotation/device-quirk risk; more code; no product feature that CameraX cannot provide for v1. | Rejected for now. Revisit only if CameraX cannot deliver 12 MP or required manual controls. |
| **D. Google ML Kit Document Scanner API** | Polished scanner UI, edge detection, auto-capture, offline-ish models. | Black box; owns preview/UI; no custom frame analysis or tuning; Play Services-dependent resources; release has no Internet permission; hard to integrate with existing review/OCR flow. | Rejected as the core. Optional import experiment only. |
| **E. Hybrid: plugin preview + native analyzer** | Seems incremental. | The plugin calls `unbindAll()` and owns the camera; a second CameraX/Camera2 client cannot share it reliably. | Rejected. One camera owner at a time. |

**Decision:** Option B. Keep `CaptureScreen` for `recordMode: true` (video) and as a fallback. Add `ScanScreen` for document photos. The native scan plugin owns the camera only while the scan route is open.

---

## 4. Target behavior

### 4.1 User flow

1. User taps **Scan pages** in the library.
2. If camera permission is missing, show a short rationale: camera is used only while scanning; pages stay on the phone; no account/upload. If denied, offer image/PDF import.
3. The scan screen shows a full-frame 4:3 preview (letterboxed, not cropped) with a page outline, a status line, a large shutter, page count, torch toggle, auto-capture toggle (if enabled), and a manual-adjust button.
4. The camera continuously detects the page and tunes exposure/focus/light. A one-line status tells the user what to do. The engine may emit reason codes for later copy/localization.
5. Manual shutter always works. Auto-capture, when enabled, fires only from a stable READY state and shows a progress ring/haptic/thumbnail.
6. Each captured page is validated (dimensions, valid JPEG, mean luma, rough sharpness) and imported through the existing `onPhoto` path. Original is preserved.
7. Done returns to the existing review/align/enhance/OCR flow. Count and draft persistence remain as today.
8. Camera unavailable, permission denied, thermal limit, or bind failure falls back to a clear message and import/old capture path.

### 4.2 In scope

- Android only; portrait-first v1.
- 12 MP 4:3 still capture (8 MP floor, capability-dependent).
- Live page detection, quality metrics, overlay, guidance state machine.
- Auto EV, auto focus/metering, torch policy, framing guidance, capture validation.
- Optional auto-capture (feature-gated, default off at launch).
- Manual overrides: EV slider, torch, tap-to-focus, zoom; advanced ISO/shutter/WB later, capability-gated.
- Local diagnostics; no network.
- Integration with existing import/review/OCR/export flow.

### 4.3 Out of scope (for this plan)

- iOS.
- Curved-page dewarping, guaranteed hand removal, automatic book-spread splitting.
- OCR inside the camera preview.
- 48 MP/RAW default, HDR/Night extension as a core feature.
- Cloud processing, accounts, analytics upload.
- Full manual cinema controls or a general-purpose camera app.

---

## 5. Architecture

### 5.1 Component diagram

```
Flutter ScanScreen
  Texture(textureId)                  <- preview pixels
  ScanOverlay (CustomPainter)         <- quad, corner ticks, status, progress
  ScanViewModel (pure Dart reducer)   <- frame/capture/session events
  ScanCameraController                <- MethodChannel + EventChannel
                 |
                 | methods / events
                 v
Kotlin ScanCameraPlugin (FlutterPlugin, ActivityAware)
  ScanCameraSession        owns ProcessCameraProvider and use cases
  ScanPreviewSurfaceProvider  Flutter TextureRegistry.SurfaceProducer -> CameraX Preview
  ScanAnalyzer             ImageAnalysis.Analyzer on a dedicated thread
    YuvFrameAdapter        Y plane + cropRect + rotation -> 480x360/960x720 luma
    PageDetector           quad + confidence
    QualityAnalyzer        sharpness/exposure/glare/shadow/stability/fill
    AutoCapturePolicy      pure state machine
  ScanControlLoop          EV/focus/torch/zoom decisions at ~4 Hz
  ManualControlController  Camera2Interop, capability-gated
  ScanCaptureController    ImageCapture 12 MP JPEG, validation/retry
  ThermalMonitor           PowerManager thermal status/headroom
  ScanEventSender          main-thread event throttling (<=10 Hz)
```

### 5.2 Why a native CameraX layer

- **Separate resolutions:** `Preview` (about 1280x960), `ImageAnalysis` (960x720, YUV), `ImageCapture` (12 MP 4:3) can be bound together without forcing the still down to preview resolution.
- **Background analysis:** `ImageAnalysis.Analyzer` runs on a dedicated executor; `STRATEGY_KEEP_ONLY_LATEST` drops stale frames; no per-frame Pigeon copies or main-thread work.
- **Control:** `CameraControl.startFocusAndMetering` gives AF/AE/AWB metering at the page centroid; `Camera2Interop` can provide AE/AF lock and optional manual ISO/shutter/WB on capable devices.
- **Metadata:** `ImageProxy.cropRect` and `ImageInfo.rotationDegrees` let the overlay and tap-to-focus share one coordinate system.
- **Capture quality:** `CAPTURE_MODE_MAXIMIZE_QUALITY`, JPEG 95, explicit resolution selector, file validation, and retry.

The app already ships Kotlin, OpenCV, ML Kit, and ONNX Runtime, so this is a bounded addition rather than a new platform.

### 5.3 Native component responsibilities

| Component | Responsibility |
|---|---|
| `ScanCameraPlugin.kt` | Flutter plugin, `ActivityAware`, permission request/result, MethodChannel, EventChannel, lifecycle. |
| `ScanCameraSession.kt` | `ProcessCameraProvider`, back-camera selector, `UseCaseGroup`, bind/unbind, actual resolutions, fallback ladder. |
| `ScanPreviewSurfaceProvider.kt` | `TextureRegistry.SurfaceProducer` + CameraX `Preview.SurfaceProvider`; surface create/destroy/recreate; transformation info. |
| `ScanCameraEngine.kt` | Facade used by the plugin; keeps CameraX types out of channel code. |
| `ScanAnalyzer.kt` | `ImageAnalysis.Analyzer`; throttling; calls adapter/detector/quality/policy; closes `ImageProxy` in `finally`. |
| `YuvFrame.kt` / `YuvFrameAdapter.kt` | Immutable luma frame plus stride/crop/rotation; reuse buffers; no Android types in the core. |
| `PageQuad.kt` / `PageDetector.kt` | Ordered normalized quad, area, IoU, edge confidence; pure-Kotlin detector interface (OpenCV-backed implementation allowed behind it). |
| `QualityAnalyzer.kt` / `FrameQuality.kt` | Sharpness, paper/ink levels, clipping, glare, shadow uniformity, stability, fill, estimated DPI, reason codes. |
| `AutoCapturePolicy.kt` / `CaptureGate.kt` | Hysteresis state machine, hard vetoes, soft score, duplicate suppression, cooldown. |
| `ScanControlLoop.kt` / `ScanControlState.kt` | 4 Hz EV/focus/torch/zoom decisions; rate limits; scene-change reset. |
| `ScanCaptureController.kt` | `ImageCapture` builder, 12 MP 4:3 selector, JPEG 95, capture-in-flight guard, validation, retry. |
| `ScanCapabilityProbe.kt` / `CameraCapabilities.kt` | Hardware level, manual-sensor support, AE compensation range/step, ISO/exposure ranges, AWB modes, max JPEG size, flash unit, extensions. |
| `ManualControlController.kt` | Capability-gated `Camera2Interop` for AE/AF lock and optional ISO/shutter/WB; reset on exit. |
| `ThermalMonitor.kt` / `ScanDiagnostics.kt` / `ScanFallbackPolicy.kt` | Thermal adaptation, local diagnostics, bind/capture fallback decisions. |
| `ScanCoordinateMapper.kt` | Pure mapping between analysis buffer, display rotation, aspect-fit widget, and metering points. |

### 5.4 Flutter component responsibilities

| Component | Responsibility |
|---|---|
| `lib/scan/scan_camera_controller.dart` | Channel calls, typed errors, open/close/capture/control, event subscription, lifecycle. |
| `lib/scan/scan_models.dart` | `ScanSessionInfo`, `ScanFrame`, `ScanQuality`, `ScanGate`, `ScanCapture`, `ScanError`; JSON validation; enums with safe fallbacks. |
| `lib/scan/scan_geometry.dart` | Pure normalized-coordinate rotation, aspect-fit, letterbox, mirror, tap mapping. |
| `lib/scan/scan_overlay.dart` | `CustomPainter`: page quad, corner ticks, status chip, progress ring, debug overlays. |
| `lib/scan/scan_view_model.dart` | Pure reducer over session/frame/capture/error events; page count, last capture, gate message, thermal banner. |
| `lib/scan/scan_screen.dart` | `Texture` preview, overlay, shutter, torch, auto-capture, zoom, pro sheet; same `onPhoto` contract as `CaptureScreen`. |
| `lib/scan/scan_feedback.dart` | Reason-code to temporary copy/icon mapping; localization hook. |
| `lib/scan/scan_pro_controls.dart` | EV slider, torch, tap-to-focus, zoom; advanced manual controls only when reported supported. |
| `lib/scan/scan_camera_api.dart` | Interface + method-channel implementation + fake API for tests. |

### 5.5 Channel protocol

Method channel: `veriscript/scan_camera`

| Method | Arguments | Result | Notes |
|---|---|---|---|
| `open` | `{analysisWidth, analysisHeight, captureWidth, captureHeight, preferPortrait}` | session info | Idempotent; asks permission if needed; returns actual resolutions/fallback mode. |
| `close` | none | null | Releases camera, analyzer, surface, executors; safe if already closed. |
| `capture` | `{auto: bool}` | `{captureId}` | Starts one capture; completion via `capture` event. `BUSY` if in flight. |
| `setAutoCapture` | `{enabled}` | null | Native gate; manual shutter always works. |
| `setTorch` | `{enabled}` | null | User override; thermal/glare policy may refuse. |
| `setZoom` | `{ratio}` | null | Clamped; no auto zoom in v1. |
| `setExposureCompensation` | `{ev}` | `{appliedEv}` | Clamped/rounded to device step; disables auto EV while manual. |
| `resetExposureCompensation` | none | null | Re-enables auto EV. |
| `focusAt` | `{x, y}` | null | Normalized widget coordinates; native maps to metering point. |
| `setMeteringPoint` | `{x, y, flags}` | null | Advanced AF/AE/AWB point. |
| `setManualExposure` | `{iso, exposureTimeNs}` | null | Only if `MANUAL_SENSOR`; else `UNSUPPORTED`. |
| `clearManualExposure` | none | null | Restore auto AE. |
| `setManualWhiteBalance` | `{mode, gains}` | null | Only if supported/validated; else `UNSUPPORTED`. |
| `clearManualWhiteBalance` | none | null | Restore auto AWB. |
| `getCapabilities` | none | capabilities map | For UI/feature gating. |
| `getDiagnostics` | none | diagnostics map | Local only; no network. |

Event channel: `veriscript/scan_camera/events`

| Event | Payload | Rate |
|---|---|---|
| `session` | state, mode (`FULL`/`ANALYSIS_REDUCED`/`MANUAL_ONLY`), preview/analysis/capture sizes, rotation, capabilities, fallback reason | on open/fallback/close |
| `frame` | seq, timestamp, analysis size/rotation, quad (4 normalized points), quality scores, gate ready/reasons, camera state (EV/zoom/torch/AF/AE/thermal) | <=10 Hz |
| `capture` | captureId, state (`started`/`saved`/`failed`), auto flag, path, width/height, rotation, captured quad, error | per capture |
| `error` | code, message, fatal flag | on error |

Error codes: `CAMERA_PERMISSION`, `CAMERA_UNAVAILABLE`, `CAMERA_BUSY`, `BIND_FAILED`, `STREAM_COMBINATION_UNSUPPORTED`, `CAPTURE_FAILED`, `NOT_OPEN`, `UNSUPPORTED`, `THERMAL_LIMIT`, `INTERNAL`.

Do not send pixel arrays or full JPEGs over the channel. Send small maps only.

### 5.6 Threading and performance budget

| Thread | Work | Rules |
|---|---|---|
| Android main / Flutter main | Plugin lifecycle, channel replies, CameraX bind, `CameraControl` calls, event sink | Never block; coalesce control calls; drop frames when no listener. |
| `scan-analysis` | Analyzer, downsample, detector, quality, policy | Close `ImageProxy` in `finally`; reuse buffers; no Bitmap/Mat allocation per frame; no IPC. |
| `scan-control` | 4 Hz EV/focus/torch/zoom loop | Read immutable snapshot; rate-limit; cancel superseded futures. |
| `scan-capture` | `takePicture`, validation, retry | One capture in flight; file I/O off main. |
| `scan-io` (optional) | Cache cleanup, diagnostics | Never block preview. |

Targets for a mid-range device:

- Analysis input 960x720 YUV; detection downsample 480x360; quality ROI at 960x720 where affordable.
- Analyze at 10-15 fps; emit UI frames at <=10 Hz; control loop 4 Hz.
- p95 analyzer time <= 40 ms; if >50 ms for 2 s, drop to 640x480/8 fps or `ANALYSIS_REDUCED`.
- Capture latency target 0.5-1.5 s for 12 MP JPEG; show shutter feedback; analysis may drop frames during capture.
- Thermal: at `LIGHT` reduce analysis fps; at `MODERATE` reduce resolution and disable auto torch; at `SEVERE` stop auto-capture; at `CRITICAL` pause preview.

### 5.7 Coordinate system

One canonical rule:

1. Analysis coordinates are normalized to the `ImageProxy` crop rect, top-left origin, unrotated.
2. Rotate by `ImageInfo.rotationDegrees` for display.
3. Aspect-fit the rotated buffer inside the preview/overlay rect (`BoxFit.contain`), preserving letterbox.
4. Map tap coordinates back through the inverse transform for `focusAt`.
5. Front-camera mirroring is not used (back camera only), but keep a flag in the model.

The preview must show the full sensor frame, not a center-cropped "cover" view; otherwise a page corner can be visible in analysis but invisible on screen. Use letterboxed 4:3 preview.

Add a debug mode that draws the raw analysis quad and the transformed widget quad, and logs actual preview/analysis/capture sizes, rotation, and crop rect. This is the fastest way to catch rotation bugs on device.

### 5.8 Lifecycle, permission, and camera ownership

- `ScanCameraPlugin` implements `ActivityAware`; `open` requires an attached activity.
- Request `CAMERA` at `open` if missing; keep a pending open; on denial return `CAMERA_PERMISSION` and let Dart show import fallback.
- `ProcessCameraProvider.bindToLifecycle(activity, selector, useCaseGroup)`.
- On detach/destroy: `unbindAll()`, clear analyzer, release surface/executors, null event sink.
- On pause: CameraX closes the camera via lifecycle; keep binding. On resume: reapply EV/zoom/torch/auto-capture and rebind if needed.
- Set `FLAG_KEEP_SCREEN_ON` while the scan route is active; clear on exit. No wake lock.
- v1 locks the scan screen to portrait to reduce rotation risk; the mapping code remains rotation-agnostic for a later landscape/tablet phase.
- **Single owner rule:** the `camera` plugin must not be initialized while the native scan session is open. The review route closes scan before video; add a route-level guard and a test for scan -> video.

### 5.9 Capture pipeline

- `ImageCapture.Builder`:
  - `CAPTURE_MODE_MAXIMIZE_QUALITY`;
  - JPEG 95;
  - 4:3 resolution selectors targeting about 4000x3000 (12 MP), preferring 8-16 MP; choose from the device's supported sizes and use a closest-lower-then-higher fallback rather than an unbounded "highest" rule, so a 48 MP mode is not selected by accident;
  - `setTargetRotation` to the current display rotation;
  - output to app cache (`cacheDir/scan/...jpg`), no external storage permission.
- After bind, read actual `ResolutionInfo` for capture and analysis; emit in `session`. Verify by pixel area, not assumed orientation.
- On capture success:
  - validate file exists and is non-trivial;
  - decode a small sample to check dimensions, valid JPEG, mean luma (not black), and rough sharpness;
  - if invalid, retry once with a lower resolution/latency mode;
  - emit `capture.saved` with path and metadata.
- Dart calls the existing `onPhoto(path)`. `DocumentStore.importImage` copies the original; delete the cache temp after successful import, keep it on failure for retry/diagnostics.
- Do not decode 12 MP in the preview pipeline; `OfflinePages` already handles EXIF and size caps.
- Do not request RAW or 48 MP in v1.
- The preview quad is guidance, not the final crop. The existing `restore` remains authoritative.

### 5.10 Fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| Full three-use-case bind fails | Exception/configure failure | Retry analysis at 640x480; then `Preview + ImageCapture` only (`MANUAL_ONLY`). |
| Capture < 8 MP | Resolution info | Try 12 MP selector; then highest available <=16 MP; warn. Never silently ship 720p. |
| Analyzer fails repeatedly | 3 consecutive errors | Clear analyzer, `MANUAL_ONLY`, emit non-fatal error. |
| Capture fails/black JPEG | Validation | Retry once; then `CAPTURE_FAILED` with retake message. |
| Thermal severe | Thermal listener | Reduce analysis, disable auto-capture/torch; critical -> pause preview. |
| Manual controls unsupported | Capability probe | Hide pro UI; auto only. |
| Camera busy/permission | Open error | Close other owner/retry; offer import. |
| Storage low | StatFs / import failure | Warn before capture; offer cleanup/export. |

---

## 6. Auto-tuning and quality engine

### 6.1 State machine

```
SEARCHING        no page / low confidence
  -> FRAMING     quad exists, but fill/margin/center/aspect/straightness fail
  -> STABILIZING geometry good, but motion/focus/exposure still settling
  -> QUALITY_BLOCKED  hard issue: glare, clipping, low sharpness, shadow
  -> READY       all hard gates pass; good-frame counter running
  -> CAPTURING   manual shutter or auto-capture fired
  -> COOLDOWN    ignore same page for 1.5-2 s; duplicate hash
  -> SEARCHING
```

Rules:

- Only one user-facing message at a time.
- Manual shutter is enabled in every state. If the page is missing, it still takes a photo; show a warning, do not block.
- Auto-capture can only fire from READY, never from FRAMING/QUALITY_BLOCKED.
- Manual EV or torch input disables the corresponding auto controller until the user taps Reset.
- On page change (quad IoU < 0.6) reset auto EV to 0 and re-meter; this prevents carrying an exposure value from a dark background onto white paper.

### 6.2 Metrics and starting thresholds

All luma values are 8-bit (0-255) or normalized 0-1. "Page ROI" means the detected quad, shrunk slightly inward to avoid its border. Preview thresholds are calibrated separately from still-image thresholds. A green value is necessary but not sufficient: auto-capture requires all hard gates plus the soft score.

| Metric | Where computed | Definition | Green (ready) | Amber (guide/manual) | Red / veto | Action |
|---|---|---|---|---|---|---|
| Page confidence | 480x360 luma | Fraction of quad perimeter with strong gradient support + convexity | >= 0.80 | 0.60-0.80 | < 0.60 | No outline / keep searching |
| Page height fill | 480x360 luma | Quad height / frame height after display rotation | 0.75-0.90 (Latin); 0.80-0.90 (Devanagari) | 0.60-0.75 or 0.90-0.95 | < 0.60 or > 0.95 | Move closer/farther |
| Corner margin | 480x360 luma | Min distance of quad corners to frame edge / min(frame w,h) | >= 0.03 | 0.01-0.03 | < 0.01 or any cut-off side | Fit all four corners |
| Centering | 480x360 luma | Distance of quad center from frame center / min(frame w,h) | <= 0.08 | 0.08-0.15 | > 0.15 | Move left/right/up/down |
| Aspect plausibility | quad | Long side / short side | 1.10-1.80 | 0.90-1.10 or 1.80-2.00 | outside | Tilt / reframe |
| Opposite-side ratio | quad | max(top,bottom)/min(top,bottom), same for left/right | <= 1.15 | 1.15-1.30 | > 1.30 | Tilt / flatten |
| Corner angles | quad | Interior angles | 70-110 deg | 60-70 or 110-120 | outside | Tilt / flatten |
| Edge straightness | quad + contour | Max deviation of each side from a straight line / page height | <= 0.01 | 0.01-0.02 | > 0.02 | Flatten the page |
| Residual skew | quad/deskew estimate | Angle of dominant page edges | <= 2 deg | 2-5 deg | > 5 deg | Rotate/tilt |
| Paper level | page ROI, 960x720 | 75th percentile luma (p75) | 0.72-0.88 | 0.60-0.72 or 0.88-0.93 | < 0.55 or > 0.95 | EV up/down; light |
| Ink level | page ROI | 10th percentile luma (p10) | 0.02-0.25 | 0.01-0.02 or 0.25-0.35 | < 0.005 or > 0.40 | EV/light; avoid crushing |
| Highlight clipping | page ROI | Fraction of pixels Y >= 250 | < 0.01 | 0.01-0.03 | > 0.03 | Lower EV; glare check |
| Shadow clipping | page ROI | Fraction of pixels Y <= 5 | < 0.005 | 0.005-0.02 | > 0.02 | Raise EV/light |
| Glare | page ROI | Largest low-gradient saturated blob / page area | < 0.005 | 0.005-0.02 | > 0.02 | Tilt/move; torch off |
| Shadow uniformity | page ROI 4x4 cells | max(cell p75) / min(cell p75) | < 1.25 | 1.25-1.50 | > 1.50 | Avoid shadow |
| Sharpness | page ROI 960x720 | Normalized Laplacian/Tenengrad score (calibrated) | >= 0.60 | 0.45-0.60 | < 0.45 | Hold still / tap focus |
| Stability | 2-3 frames/200 ms | min(quad IoU, 1 - normalized frame difference) | >= 0.90 | 0.85-0.90 | < 0.85 | Hold still |
| Estimated DPI | quad + capture size | Assume A4 height 11.69 in; page pixels / 11.69 | >= 260 | 200-260 | < 200 | Move closer; warn |
| Thermal | PowerManager | Thermal status/headroom | 0-1 | 2 | >= 3 | Reduce analysis/torch/auto |

Notes:

- The paper/ink percentiles are more robust than a plain mean when a page contains dense text or photos.
- The 180-225 target in the capture-science report corresponds to roughly 0.70-0.88 normalized. Preview YUV tone mapping may differ from the final JPEG; calibrate preview thresholds against captured stills on each device.
- "Estimated DPI" assumes A4/Letter. Label it approximate in diagnostics; do not show a false precise DPI to the user.

### 6.3 Exposure controller

Inputs: page ROI p75, p10, highlight/shadow clipping, change in p75, EV range/step from capabilities.

Policy:

```
target p75 = 0.80 (deadband 0.72-0.88)
if p75 < 0.70 and highlight clipping < 0.01:  ev += 1 step
if p75 > 0.90 or highlight clipping > 0.02:  ev -= 1 step
if p10 < 0.005 and shadow clipping > 0.02:    raise light / suggest torch (do not only lower EV)
```

Guards:

- Rate limit: at most one EV step per 300 ms, at most two steps per second.
- Clamp to device min/max; round to the reported EV step; if step <= 0, disable EV auto tuning and show manual light guidance.
- Do not change EV while an AF metering action is in flight; wait about 250 ms.
- Reset EV to 0 on page change or after 1 s with no page.
- If at max EV and still too dark, emit `TOO_DARK`/`NEED_MORE_LIGHT`; do not keep pumping.
- If highlight clipping persists, lower EV first; then check glare. Clipped highlights are unrecoverable.
- At capture: lock AE (and AF) via Camera2Interop if supported, wait 80-150 ms for the lock to apply, capture, then unlock after the capture. If lock fails/unsupported, rely on the stability gate and capture anyway.

Why not rely on auto exposure alone: a reflective meter is calibrated near 18% gray, so white paper can render mid-gray or clip depending on the background. The EV loop targets the paper percentile, not the scene average.

### 6.4 Focus controller

- On page detection, call `FocusMeteringAction` at the quad centroid with AF (and AE/AWB on the first trigger). Use `disableAutoCancel()` while a page candidate is present.
- Check the `FocusMeteringResult.isFocusSuccessful` signal. Do not treat a missing result as success.
- Re-trigger only when:
  - the page changed (IoU < 0.6);
  - sharpness stayed below the amber threshold for about 2 s;
  - the user tapped to focus.
- Re-trigger focus with AF only, so it does not reset the EV/AE state.
- Before capture, lock AF if supported; if not, require the sharpness score and low motion to pass.
- On devices where AF hunts on low-contrast paper, show "Tap to focus" and let the user tap a text region; also allow a manual focus-distance control only if `LENS_FOCUS_DISTANCE` is supported (phase 4).
- Do not use digital zoom to compensate for focus; guide the user to move to the minimum focus distance.

### 6.5 Light and torch policy

Default: torch off. Document capture usually wants diffuse ambient light, not a point source.

- If p75 < 0.30 for about 1 s and no glare, emit `TOO_DARK` and offer a one-tap "Light" toggle. If the user enabled auto-torch, turn the torch on.
- Turn auto-torch off when p75 > 0.55 for 2 s, when glare exceeds 2%, when the page is glossy (glare history), when thermal status is moderate or worse, or after capture.
- Never auto-fire the flash. Flash is a short, high-intensity point source that creates specular hotspots and can fire before AE settles. A continuous torch is meterable and can stay on during preview; it still needs glare monitoring.
- If torch causes clipping/glare, turn it off and guide "Glare - tilt slightly" / "Move away from the light".
- User override always wins, but the app may show a warning for glare/thermal.

### 6.6 Framing and geometry guidance

Priority: page presence -> all corners/cut-off -> size (too small/large) -> centering -> tilt/curvature -> stability -> quality. This order prevents telling a user to hold still when half the page is out of frame.

Reason codes (temporary copy in parentheses):

- `NO_PAGE` ("Point at a page")
- `FIT_CORNERS` ("Fit all four corners")
- `PAGE_CUT_OFF` ("Page may be cut off")
- `MOVE_CLOSER` ("Move closer")
- `MOVE_FARTHER` ("Move farther")
- `MOVE_LEFT` / `MOVE_RIGHT` / `MOVE_UP` / `MOVE_DOWN` ("Center the page")
- `TILT_PAGE` ("Hold the camera above the page")
- `PAGE_CURVED` ("Flatten the page")
- `HOLD_STILL` ("Hold steady")
- `LOW_SHARPNESS` ("Blurry - hold still or tap to focus")
- `TOO_DARK` ("More light")
- `TOO_BRIGHT` ("Too bright - reduce light")
- `GLARE` ("Glare - tilt slightly")
- `SHADOW` ("Avoid shadow")
- `READY` ("Ready")
- `CAPTURING` ("Capturing...")
- `CAPTURED` ("Page N captured")
- `THERMAL` ("Phone is warm - slowing down")
- `CAMERA_ERROR` ("Camera unavailable - import images")

One message at a time; minimum display 1.5-2 s; repeat cooldown 4-6 s; tie the message to a visual anchor (outline, corner ticks, dashed cut-off edge). Do not block the viewfinder with modals.

### 6.7 Shadow and glare details

- **Glare:** find near-saturated pixels (Y >= 250) with low local gradient and low chroma variation; form connected components; compare the largest blob to page area. White paper is also bright but usually has paper texture/text edges; a specular blob is flat and saturated. A hard veto at >2% is conservative; calibrate on glossy and matte paper.
- **Shadow:** compute a 4x4 or 8x8 grid of paper-level (p75) values over the page; max/min > 1.5 is a strong shadow. Shadows are recoverable if not clipped, so this is usually amber, not a hard veto; combine with shadow clipping.
- **Paper texture:** a blank page can look flat; use gradient density and text edges to avoid mistaking a blank page for glare. A completely blank page should still be capturable manually.
- **Curvature:** compare each quad side to a straight line and measure the maximum bow. More than about 2% of page height suggests a curved book page; emit `PAGE_CURVED`. This is guidance, not dewarping.

### 6.8 Auto-capture policy

Recommended for v1: **off by default**. Ship manual shutter + READY indicator first; enable auto-capture after field validation. This follows the manual-first pattern and avoids false triggers eroding trust.

When enabled:

```
hard gates: page confidence, corner margin, fill range, aspect, glare, clipping,
            sharpness, stability, not thermal-limited
soft score: Q = 0.30*sharpness + 0.25*confidence + 0.20*exposure
              + 0.15*stability + 0.10*(1 - glare/0.02)
enter: all hard gates + Q >= 0.75 for 6-8 consecutive frames (~400-600 ms)
exit:  Q < 0.60 or any hard veto
cooldown: 1.5-2.0 s; require page change (IoU < 0.55 or corner shift > 8%)
duplicate: 64-bit dHash of the page ROI; Hamming distance <= 6 -> skip
manual shutter: always bypasses the gate and duplicate suppression
```

Use hysteresis (separate enter/exit values) to prevent flicker. Do not capture while the previous page is importing; Dart can call `setAutoCapture(false)` during `onPhoto` and re-enable in `finally`.

Best-frame selection and exposure bracketing are deferred. A 12 MP still plus capture validation is enough for v1; ZSL/burst can be evaluated later if capture latency or blur is a problem.

### 6.9 Capture validation

After every capture (manual or auto):

1. File exists and size is plausible.
2. Decode bounds; actual pixel area >= 8 MP (target 12 MP).
3. Decode a small sample (inSampleSize) and check mean luma is not near 0/255; reject black/blank frames.
4. Optional rough sharpness on a downscaled center crop; reject obvious defocus if the gate was bypassed.
5. If invalid, retry once with `CAPTURE_MODE_MINIMIZE_LATENCY` or a lower resolution; then emit `CAPTURE_FAILED` with a retake message.

This is mandatory because high-resolution capture has known intermittent black-JPEG reports, and because a page can move between gate and shutter.

### 6.10 Manual overrides

v1 manual controls:

- EV slider (auto/manual toggle; range from capabilities; step-aware).
- Torch off/auto/on (auto is opt-in; user override wins but warnings remain).
- Tap-to-focus (one-shot at the tapped point; show a focus ring).
- Zoom (pinch, 1x-2x, digital; warn that digital zoom reduces detail; default 1x).
- Reset all auto controls.

Phase 4, capability-gated:

- ISO and shutter speed (`MANUAL_SENSOR`); show only on supported devices; reset to auto on exit; watchdog on preview stall/capture failure.
- White balance mode/gains (`MANUAL_POST_PROCESSING`); only if validated; otherwise auto WB + post color cast handling.
- Manual focus distance if supported.

Contrast is not a camera control in v1. The UI can offer an "Image look" after capture (existing enhance setting) but not a fake camera contrast slider.

### 6.11 Calibration and thresholds

- Normalize scores (0-1) rather than shipping raw Laplacian thresholds. Calibrate against device/resolution.
- Store a profile keyed by `Build.MODEL | Build.DEVICE | cameraId | analysisResolution | captureResolution`; initial defaults are conservative.
- Device matrix: at least one low-end/LIMITED or LEGACY device, one mid-range, one flagship; different OEMs (Pixel/Samsung/Xiaomi if available).
- Calibration target: printed page with Latin and Devanagari at 6-14 pt, gray patches, slanted edge, glossy/matte areas, shadow/glare negatives. Use it to set sharpness/exposure/glare percentiles, not to train a model.
- Do not enable auto-capture globally until precision/recall are measured on the matrix.
- Log metric distributions locally so thresholds can be tuned without guessing.

### 6.12 What we deliberately will not do

- No default flash; no aggressive HDR/local tone mapping; no camera-side contrast curve.
- No 48 MP default; no RAW; no digital zoom as a substitute for moving closer.
- No binarization at capture; no destructive overwrite of the original.
- No OCR inside the preview (too slow, and it would duplicate the review pipeline).
- No auto-capture based only on a page outline; geometry, stability, focus, exposure, and glare must all pass.
- No claim that post-processing can recover clipped highlights, motion blur, defocus, or glare.

---

## 7. UX and guidance

### 7.1 Layout

```
+--------------------------------------------------+
| Close   [Auto-capture toggle]   [Torch] [Adjust] |
|                                                  |
|              full-frame 4:3 preview              |
|         (letterboxed, page outline overlay)      |
|                                                  |
|                 status chip                      |
|                 progress ring                    |
|                                                  |
|   [thumbnail]   [   large shutter   ]   [Done n] |
+--------------------------------------------------+
```

- Top: close/back, auto-capture toggle (if enabled), torch, adjust/manual.
- Center: preview + page outline + corner ticks + status chip + progress ring.
- Bottom: last-capture thumbnail, large shutter, Done (n).
- Manual shutter is always visible and stable; auto-capture is an enhancement.
- The preview shows the full sensor frame so all four corners can be seen; do not use a center-cropped cover view.

### 7.2 Guidance rules

- One message at a time, in the priority order from section 6.6.
- Minimum display time 1.5-2 s; repeat cooldown 4-6 s; persistent chip for ongoing conditions.
- Use color + shape + text; do not rely on outline color alone (color-blind users, bright sunlight).
- Haptics on capture and state changes; respect silent mode for shutter sound; keep controls large; support TalkBack labels and short announcements.
- Volume-key shutter and accessibility actions are desirable; add if cheap.
- Localize short action-first strings later; the engine already emits stable reason codes.
- Do not blame the user: "Move closer", not "Document too small"; "More light", not "Low luminance".

### 7.3 Auto-capture indication

Two stages:

1. **Acquiring:** solid outline + small progress ring + "Hold steady".
2. **Capturing:** ring completes, shutter animation/flash, medium haptic, thumbnail slides in, "Page N captured".

Do not capture silently. Do not re-arm immediately; wait 1.5-2 s and require a page change. Provide a pause/toggle.

### 7.4 Permission, privacy, fallback

- Rationale before the system prompt: camera is used only while scanning; pages stay on this phone; no account/upload; release build has no Internet permission.
- If permission is denied: explain and offer image/PDF import; do not loop the prompt.
- If the camera is unavailable/busy: show a clear message and the import fallback.
- If thermal limit is reached: explain slowing down; reduce analysis/torch; pause auto-capture.
- Diagnostics are local only. Do not add analytics or network calls.

---

## 8. Integration with the existing app

### 8.1 Route and fallback

In `mobile/lib/review.dart`, the `capture()` method currently pushes `CaptureScreen`. Change it to choose:

```dart
final useScanCamera = widget.settings.getBool('scanCameraV2') ?? false;
await Navigator.of(context).push(
  MaterialPageRoute<void>(
    builder: (_) => useScanCamera
        ? ScanScreen(
            count: doc.pages.length,
            onPhoto: (path) async { /* same as today */ },
          )
        : CaptureScreen(
            count: doc.pages.length,
            onPhoto: (path) async { /* same as today */ },
          ),
  ),
);
```

- Keep `CaptureScreen(recordMode: true)` for video.
- Keep the old `CaptureScreen` as a fallback if native scan open fails or the feature flag is off.
- The `onPhoto` contract is unchanged: import raw (`align: false, enhance: false`), then after Done run the existing align/enhance pass with progress.
- Add a route-level single-owner guard: close scan before starting video; do not allow both controllers open.

### 8.2 Feature flag and rollout

- SharedPreferences key `scanCameraV2`, default `false` until Phase 5 acceptance.
- Debug builds can enable it manually; add a hidden diagnostics screen (long-press version/settings) showing capabilities, actual resolutions, frame timings, thermal status, and capture counts.
- Rollout: internal -> beta with telemetry-free field notes -> default on supported devices. Keep the flag override and import fallback.
- If native bind fails, automatically fall back to the old capture for that session; do not block the user.

### 8.3 Resolution plumbing (must ship with the camera)

A 12 MP capture is pointless if the pipeline immediately downsizes it. Audit and change these:

1. **`OfflinePages.load`:** add an explicit `maxSide` argument to `normalize`, `restore`, and `enhance` (or a `fullResolution` flag). For camera captures, preserve up to 3500-4000 px through `normalize -> restore -> enhance`; for gallery/PDF imports, keep the current 2500 px default unless the user opts into higher quality.
2. **`DocumentStore.importImage`:** pass the capture quality flag into the native calls; do not silently cap camera captures at 2500.
3. **`warp` limit:** 12 MP 4:3 is 12.19 MP, inside the existing 12.5 MP warp limit. A page crop smaller than that is fine. Do not raise to 48 MP without a memory plan.
4. **`OfflinePages.enhance`:** currently loads at 2500; raise the cap for camera captures, or process the already-cropped page. `bilateralFilter` and sharpening on ~10 MP need timing/memory measurement on 4 GB devices.
5. **RapidOCR input cap:** `RapidOcr.kt` downsizes to max side 2000. For the experimental RapidOCR backend, test a higher cap (3000-3500) or per-line crops; do not change the default without an OCR A/B gate.
6. **Crop before resize:** the OCR research recommends cropping to the page/text region before applying the engine's working-size cap. The existing `restore` already crops, but `normalize` runs before it and can discard resolution. Reorder or pass a higher cap so the crop happens while pixels are available.

Budget target: keep the preserved page around 3000-3500 px on the long side (about 250-300 DPI for A4), not full 4000 if it blows memory/time. 12 MP sensor capture, 3500 px working page, 12.5 MP warp cap.

### 8.4 Storage budget and derivative cleanup

At 12 MP, a JPEG 95 page can be 3-8 MB. The current flow can keep multiple derivatives per page:

- `original_*.jpg` (captured original)
- `source_*.jpg` (normalized)
- `aligned_*.jpg` (restored)
- `enhanced_*.jpg` (final)
- optional previous version / digit crops

For 150 pages this can exceed the app's 2 GB free-space target. Required work:

- Keep the original and the final working page. Do not keep redundant intermediates after a successful step; delete `source`/`aligned` when no longer needed, or overwrite in place where safe.
- Do not delete a path still referenced by `ScanPage.source`, `ScanPage.path`, or `previousVersion` without updating the reference. Re-running `restore`/`enhance` must always be possible from the preserved original; if an intermediate is removed, make the pipeline fall back to the original.
- Keep `previousVersion` only for text/image rollback; document the storage cost.
- Add a free-space check before capture (e.g., `StatFs`); warn and offer cleanup/export when low.
- Measure actual bytes/page on device; consider JPEG 90-92 if OCR shows no difference. Keep original at capture quality.
- Delete scan cache temps after successful import; keep failed ones only for retry/diagnostics with a cleanup policy.

### 8.5 Page metadata

Add an optional `capture` map to `ScanPage` (backward-compatible; default null):

```json
{
  "engine": "camerax",
  "captureWidth": 4000,
  "captureHeight": 3000,
  "rotationDegrees": 90,
  "quad": [[0.12,0.08],[0.88,0.10],[0.86,0.92],[0.10,0.90]],
  "quality": {"sharpness":0.72,"paper":0.81,"glare":0.004,"stability":0.93},
  "gate": "manual",
  "ev": 0.33,
  "torch": false,
  "estimatedDpi": 280,
  "warnings": []
}
```

Use it for review diagnostics ("why was this page flagged?"), calibration, and future re-processing. Keep it small; do not store frames or thumbnails in JSON. Update `ScanPage.toJson/fromJson`, document tests, and tolerate missing fields for old drafts.

### 8.6 Post-processing defaults

- Do not change `align`/`enhance` defaults at the same time as the camera. Use a factorial OCR experiment:
  1. old capture + old pipeline;
  2. new capture + old pipeline;
  3. old capture + new pipeline;
  4. new capture + new pipeline.
  This isolates the camera effect from processing changes.
- If the new capture is sharp and well-exposed, aggressive sharpening/denoising may hurt. Gate unsharp on a blur metric; keep it mild.
- Keep the color original; grayscale/enhance remains a user setting. Do not silently force B&W.
- Preserve the existing "check fine text against the original" review behavior.

### 8.7 Video path

- Leave `CaptureScreen(recordMode: true)` and the video pipeline alone in this plan.
- The native scan plugin is not used for video. Close it before recording.
- The current `ResolutionPreset.high` is appropriate for the 10-minute video route; do not switch video to `max`.

### 8.8 Interim quick win

Before the native layer lands, make the photo path use the highest sensible still resolution:

```dart
// in CaptureScreen.initialize()
ResolutionPreset preset = widget.recordMode
    ? ResolutionPreset.high   // keep video files manageable
    : ResolutionPreset.max;   // photos only
```

Then validate the JPEG dimensions, aspect ratio, and mean luma on device (the high-res black-JPEG issue exists; `max` may also choose a 16:9 size on some devices, which can cut page edges). If `max` selects 16:9 or an excessive 48 MP mode, fall back to `veryHigh` or a capability-selected 4:3 size instead. This is a small, testable improvement that recovers some OCR detail immediately; it is not a substitute for the scan camera.

---

## 9. Phased implementation plan

Effort scale: S <= 1 week, M = 1-2 weeks, L = 2-4 weeks for one experienced Android/Flutter engineer. Native and Dart work can overlap after Phase 1.

### Phase 0 - Baseline, quick win, and capability spike (S, 2-4 days)

**Status:** implemented and emulator-verified; physical-device 12 MP validation and OCR baseline remain pending. See [`SCAN_CAMERA_PHASE0.md`](SCAN_CAMERA_PHASE0.md).

Goal: prove the risky device assumptions before building UI.

Tasks:

- Measure the current 720p capture baseline on a small OCR fixture (Latin + Devanagari + digits). Record actual JPEG dimensions, effective DPI, and CER/WER with the existing engines.
- Apply the interim photo preset fix (`ResolutionPreset.max` only for photo mode) behind a debug flag; validate JPEG dimensions, mean luma, and black-frame rate on at least one real device.
- Implement `ScanCapabilityProbe`: Camera2 hardware level, `MANUAL_SENSOR`, AE compensation range/step, max JPEG sizes, AWB modes, flash unit, extensions.
- Build a throwaway instrumentation/debug bind: `Preview(1280x960) + ImageAnalysis(960x720, YUV, KEEP_ONLY_LATEST) + ImageCapture(~4000x3000, JPEG 95)`.
- Test on at least 3 devices if available: low-end/LEGACY or LIMITED, mid-range, flagship. Record bind success, actual resolutions, analysis p50/p95, capture latency, and 10-minute thermal behavior.

Exit criteria:

- At least one low/mid device binds all three use cases, captures >= 8 MP, and analyzes at >= 10 fps for 10 minutes without thermal shutdown.
- If the stream combination fails, decide the fallback (640x480 analysis, then `MANUAL_ONLY`) before Phase 1.
- Baseline data exists to compare the new camera against, not just anecdotal "looks better".

### Phase 1 - Native session, texture preview, 12 MP capture (M, 1.5-2 weeks)

Deliverables:

- `ScanCameraPlugin.kt`, `ScanCameraSession.kt`, `ScanPreviewSurfaceProvider.kt`, `ScanCaptureController.kt`, `ScanEventSender.kt`, `ScanEvent.kt`.
- CameraX dependencies aligned at 1.6.2 with the existing `camera_android_camerax` transitive version.
- Dart `scan_camera_controller.dart`, `scan_models.dart`, `scan_screen.dart` with `Texture` preview, manual shutter, Done/count, fallback UI.
- `open`/`close`/`capture`/`getCapabilities`; `session` and `capture` events.
- Permission request/result, lifecycle, surface recreation, keep-screen-on, portrait lock.
- `review.dart` route behind `scanCameraV2`; old `CaptureScreen` remains for video/fallback.
- If `SurfaceProducer` texture transformation proves unreliable on a device, keep a fallback preview via `AndroidView(PreviewView)` while retaining the Flutter overlay; document the deviation and verify the coordinate mapping.

Exit criteria:

- 12 MP (or verified 8-16 MP) 4:3 JPEG saved from the Flutter shutter.
- Actual capture dimensions validated, not assumed; black/blank JPEG retry works.
- Preview rotates correctly in portrait; background/resume recovers; no camera-plugin conflict.
- Scan -> video -> scan sequence works without a busy camera.

### Phase 2 - Analyzer, quality metrics, overlay (L, 2-3 weeks)

Deliverables:

- `YuvFrame.kt`, `YuvFrameAdapter.kt`, `PageQuad.kt`, `PageDetector.kt`, `QualityAnalyzer.kt`, `FrameQuality.kt`, `ScanCoordinateMapper.kt`.
- `PageDetector` as an interface. Start with a pure-Kotlin detector; add an OpenCV-backed implementation behind the same interface if low-contrast pages need it.
- `ScanAnalyzer.kt` wiring; `frame` events at <=10 Hz.
- Dart `scan_geometry.dart`, `scan_overlay.dart`, `scan_view_model.dart`; debug overlay.
- Unit tests for YUV strides/crop/rotation, synthetic quads, quality metrics, coordinate mapping.

Exit criteria:

- Live quad at 10-15 fps; overlay aligns on portrait and (if enabled) 0/90/180/270 with letterboxing.
- p95 analysis <=40 ms on the mid device; no ANRs; preview stays smooth.
- Synthetic tests cover dark/bright/clipped/glare/blur/shadow/no-page cases.

### Phase 3 - Auto-tuning, guidance, capture gate (M, 1.5-2 weeks)

Deliverables:

- `AutoCapturePolicy.kt`, `CaptureGate.kt`, `ScanControlLoop.kt`, `ScanControlState.kt`, `ThermalMonitor.kt`, `ScanFallbackPolicy.kt`.
- EV loop, focus/metering triggers, torch policy, scene-change reset, capture lock (capability-gated).
- Reason-code state machine and temporary UI messages.
- Capture validation/retry.
- Auto-capture option, default off; enable in debug for tuning.
- Dart gate UI, progress ring, haptic/thumbnail feedback.

Exit criteria:

- Auto EV converges within about 1 s in normal light without visible oscillation; no repeated hunting.
- Focus triggers only on page change/failure/tap; no per-frame AF spam.
- 20-page manual run: no preview freezes, no corrupt captures, no duplicate imports.
- If auto-capture is enabled for testing: 0 captures with absent/covered page in 100 attempts; <5% false triggers; 0 duplicates in a 20-page run.
- 10-minute thermal run degrades gracefully.

### Phase 4 - Manual controls, calibration, diagnostics (M, 1 week)

Deliverables:

- EV slider, torch auto/on/off, tap-to-focus, pinch zoom, reset.
- `ManualControlController`: ISO/shutter/WB only when capability-probed and validated; hide unsupported UI; reset auto on exit; watchdog.
- `ScanDiagnostics.kt` + hidden diagnostics screen: device/camera ID, actual resolutions, frame timing percentiles, capture latency, thermal status, threshold profile, counts.
- Per-device profile storage; initial defaults; optional calibration routine using a printed target.
- Accessibility pass: TalkBack labels/announcements, large controls, haptics, volume-key shutter if feasible.

Exit criteria:

- Manual EV/torch/tap-focus/zoom work on the mid device; auto/manual transitions are predictable.
- Unsupported manual controls return `UNSUPPORTED` and are hidden.
- Leaving manual mode restores auto and does not stall the preview.
- Diagnostics can be collected locally without network.

### Phase 5 - Resolution plumbing, OCR A/B, hardening, rollout (M, 1.5-2 weeks)

Deliverables:

- `OfflinePages` maxSide/full-resolution plumbing for camera captures; crop-before-resize where feasible.
- Storage/derivative cleanup and free-space guard; actual bytes/page measurement.
- Optional RapidOCR cap experiment (3000-3500) behind a flag.
- Factorial OCR A/B: old/no-new capture/pipeline combinations; Latin, Devanagari, digits; paired CIs.
- Device matrix: 3+ devices, low/mid/flagship; 50-page sessions; rotation/background stress; 150-page storage run.
- Release APK verification: no Internet permission, no new permissions, ProGuard/R8, both routes, offline.
- Feature-flag rollout and fallback rehearsal.

Exit criteria:

- OCR shows no regression and a statistically credible improvement on resolution-sensitive pages; if not, do not flip the default.
- 50-page session: no crash/ANR, acceptable thermal/battery, p95 analysis within budget.
- 150-page storage run fits the documented free-space target with cleanup.
- Release APK has no network permission and both camera paths work offline.

### Milestones

| Milestone | Scope | Approx. effort |
|---|---|---|
| M0 | Baseline + spike + interim photo resolution fix | 2-4 days |
| M1 | Native preview + 12 MP capture behind flag | +1.5-2 weeks |
| M2 | Live overlay + quality metrics | +2-3 weeks |
| M3 | Auto EV/focus/torch + guidance + capture gate (manual shutter) | +1.5-2 weeks |
| M4 | Auto-capture tuned/validated (optional default) | +0.5-1 week |
| M5 | Manual controls + calibration/diagnostics | +1 week |
| M6 | Resolution plumbing + OCR A/B + hardening/rollout | +1.5-2 weeks |
| **Total** | Full scope | **~8-11 engineer-weeks** |

M3 is the useful MVP: about 5-7 weeks for one engineer, depending on device access and how much of the Dart UI can be built in parallel.

### Critical path and parallelization

1. **Phase 0 first.** Do not build the UI until the stream combination and actual capture size are proven on real devices. A failed spike changes the architecture, not just a threshold.
2. **Native session/capture next.** The 12 MP still is the core product value; preview texture and capture validation must be solid before tuning.
3. **Analyzer next.** Page detection, quality metrics, and coordinate mapping are prerequisites for any guidance or auto-tuning. Build them against synthetic frames and a debug overlay.
4. **Control loop and gate after the analyzer.** Never let the control loop read raw frames or block the analyzer thread; it reads the latest immutable snapshot.
5. **Pipeline resolution and OCR A/B in parallel with late camera hardening.** The OCR harness can run on captured fixtures before the UI is finished; this is the only credible way to know whether the camera helps.

Parallel work that is safe:

- Dart models, view-model reducer, geometry, and overlay can be built against fake `frame`/`capture` events while the native analyzer is developed.
- The OCR baseline and factorial A/B harness can be prepared in Phase 0 and run as soon as captures exist.
- Device capability probing, diagnostics, and the permission/lifecycle tests can be developed alongside the session.

Do not build auto-capture first. It depends on stable page detection, quality metrics, focus/exposure settling, and a reliable capture path; building it early produces impressive demos and unreliable field behavior.

---

## 10. Test and validation plan

### 10.1 Unit tests (pure JVM Kotlin)

- `YuvFrameAdapterTest`: planar/semi-planar YUV, rowStride/pixelStride, cropRect, odd dimensions, rotation metadata, downsampling.
- `PageDetectorTest`: synthetic page on plain background, low contrast, shadow, partial page, no page, rotated page, curved edge.
- `QualityAnalyzerTest`: dark, normal, clipped, glare, shadow, blur, blank page, dense text; expected green/amber/red classifications.
- `AutoCapturePolicyTest`: transitions, hysteresis, cooldown, duplicate suppression, manual bypass, thermal veto, scene change.
- `ScanCoordinateMapperTest`: rotation 0/90/180/270, aspect-fit letterbox, mirror, tap-to-focus mapping.
- `ScanCapabilityProbeTest`: fake Camera2 characteristics, unsupported manual modes, zero EV step.
- `CaptureValidationTest`: black JPEG, tiny file, wrong dimensions, valid JPEG.

### 10.2 Android instrumentation

- Bind/unbind and fallback ladder with CameraX test fakes where possible.
- Permission grant/deny/resume.
- Surface destroy/recreate; background/resume; rotation/portrait lock.
- Capture to cache; file validation; retry.
- Scan -> video route guard.
- Thermal listener behavior with fake status if feasible.

### 10.3 Dart tests

- Model parsing/validation with missing/extra fields and enum fallbacks.
- View-model reducer: frame -> gate -> capture -> cooldown -> error/thermal.
- Geometry tests for rotation/letterbox/tap mapping.
- Widget tests for shutter, Done, auto-capture toggle, fallback message.
- Fake channel API for scan screen tests.

### 10.4 Device matrix

At minimum:

- Low-end / 4 GB RAM / Camera2 LEGACY or LIMITED.
- Mid-range (main target).
- Flagship / FULL or LEVEL_3.
- Different OEMs if available (Pixel, Samsung, Xiaomi/Redmi).
- Emulator virtual camera for smoke tests only; never use it to set quality thresholds.

Record: device model, camera ID, actual preview/analysis/capture sizes, frame p50/p95, capture latency, thermal status, black-frame rate, and any fallback.

### 10.5 Field test protocol

Per device, capture at least 20 pages across:

- normal indoor light; low light; mixed light; direct overhead light;
- matte paper, glossy paper/coated pages, newsprint;
- flat page, slightly curved book page, strong perspective, shadow from hand/phone;
- Latin 8-12 pt, Devanagari, digits/tables;
- page touching frame edge; page absent; page turn; hand/occlusion.

Measure:

- auto-capture precision/recall, false triggers, missed pages, duplicates;
- time from page presentation to READY/capture (target 0.6-1.2 s in good conditions);
- retake rate by reason (blur/glare/shadow/crop/curvature);
- manual override rate;
- crash/ANR/battery/thermal;
- storage bytes per page.

### 10.6 OCR A/B experiment

Use paired pages and one factor at a time:

1. old capture + old pipeline;
2. new capture + old pipeline;
3. old capture + new pipeline;
4. new capture + new pipeline.

Metrics:

- character error rate (CER), word error rate (WER), grapheme CER for Devanagari;
- digit exact match and digit conflict rate;
- confidence calibration/ECE if available;
- runtime and memory.

Sample size: 30 paired pages resolves roughly 1-3.5 percentage points depending on variance; 200+ may be needed for ~1 pp at high variance. Report paired bootstrap confidence intervals. Keep Latin and Devanagari separate. Do not tune on 720p captures. Use the existing harness (`evals/`, `mobile/tool/compare_ocr.py`) and the ML Kit/RapidOCR engines consistently.

### 10.7 Acceptance gates

| Gate | Target |
|---|---|
| Actual still capture | >= 8 MP; target 12 MP 4:3; verified, not assumed |
| Analysis performance | p95 <= 40 ms mid-range; preview smooth; no ANR |
| Overlay | Correct in portrait; rotation tests pass if enabled |
| Auto EV | Converges within ~1 s; no sustained oscillation; clamped to device range |
| Auto focus | Triggered on page change/failure/tap, not every frame; result checked |
| Torch | Default off; auto only if enabled; glare/thermal off-ramps |
| Guidance | One message at a time; priority order; min display/repeat cooldown |
| Auto-capture (if enabled) | 0 absent/covered-page captures in 100; <5% false triggers; 0 duplicates/20 pages |
| Capture validation | Black/blank/corrupt JPEG caught and retried |
| OCR | No regression; statistically credible improvement on resolution-sensitive pages |
| Thermal | 10-minute session degrades gracefully; no shutdown |
| Storage | 150-page run fits documented free-space target with cleanup |
| Privacy | Release APK has no INTERNET permission; diagnostics local only |
| Fallback | Permission/bind/capture/thermal failures all have a usable path |

---

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Three-use-case stream combination fails on some devices | Medium | High | Phase 0 spike; fallback to 640x480 analysis, then `MANUAL_ONLY`; verify on device matrix. |
| Actual capture < 8 MP or 48 MP surprise | Medium | High | Capability probe; explicit 4:3 12 MP selector; verify `ResolutionInfo`; fallback ladder; warn. |
| Preview/analysis/capture coordinate or rotation mismatch | High | Medium | One normalized coordinate system; cropRect/rotation metadata; pure mapper tests; debug overlay. |
| Camera2Interop AE/AF lock or manual controls destabilize 3A | Medium | High | Auto mode default; capability gate; lock only at capture; watchdog; clear options on exit; manual controls behind advanced UI. |
| Thermal/battery drain during long sessions | Medium | Medium | Y-plane-only analysis; KEEP_ONLY_LATEST; adaptive fps/resolution; thermal listener; torch off by default. |
| Camera ownership conflict with plugin/video | Medium | High | Single owner rule; close scan before video; route guard; tests for scan -> video -> scan. |
| Device variance makes thresholds unreliable | High | Medium | Normalized scores; per-device profiles; conservative defaults; auto-capture off until field data. |
| 12 MP pipeline/storage blowup | High | Medium | Working page ~3000-3500 px; derivative cleanup; free-space guard; JPEG quality measurement; 150-page test. |
| OCR regression from capture/processing changes | Medium | High | Factorial A/B; no default change without evidence; keep originals; preserve rollback. |
| Auto-capture false triggers erode trust | Medium | High | Manual-first; 6-8 good frames; hysteresis; cooldown; duplicate hash; default off. |
| Permission/lifecycle edge cases | Medium | Medium | ActivityAware; pending open; resume reapply; permission tests; import fallback. |
| Scope creep (copy, auto-capture, pro controls, dewarp) | High | Medium | Phase gates; reason codes now/copy later; auto-capture optional; manual controls phase 4; dewarp out of scope. |

---

## 12. Open decisions

| Decision | Recommendation | Why |
|---|---|---|
| Auto-capture default | **Off at launch; enable after field validation** | Thresholds are device-dependent; false triggers are worse than manual shutter. |
| Orientation | **Portrait lock in v1**; rotation support later | Reduces overlay/rotation risk; document scanning is usually portrait. |
| Capture target | **12 MP 4:3 target, 8 MP floor, avoid 48 MP default** | 12 MP is enough for ~200-300 DPI at 75-90% page height; 48 MP adds noise/storage/processing and exceeds warp limits. |
| Working page size | **3000-3500 px long side** | Balances OCR detail, memory, and storage; validate with OCR A/B. |
| Page detector | **Pure-Kotlin interface, OpenCV implementation behind it if needed** | Testability and low-end performance; OpenCV already bundled for hard pages. |
| Manual controls | **EV/torch/tap-focus/zoom in v1; ISO/shutter/WB phase 4** | Matches user need without destabilizing auto 3A. |
| Capture metadata | **Optional `capture` map on `ScanPage`** | Useful for diagnostics/review; backward-compatible. |
| Feature flag rollout | **Internal -> beta -> default on supported devices** | Keeps old capture as a safety net; no network telemetry. |
| ML Kit Document Scanner | **No core dependency; optional import experiment only** | Black box, Play Services, no custom analysis; release has no Internet. |
| HDR/Night extensions | **Out of v1; evaluate only with OCR gate** | Local tone mapping/halos can hurt OCR; extension stream support varies. |

---

## 13. Proposed file map

### New native files

`mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/scan/`

- `ScanCameraPlugin.kt`
- `ScanCameraSession.kt`
- `ScanPreviewSurfaceProvider.kt`
- `ScanCameraEngine.kt`
- `ScanAnalyzer.kt`
- `YuvFrame.kt`
- `YuvFrameAdapter.kt`
- `PageQuad.kt`
- `PageDetector.kt`
- `QualityAnalyzer.kt`
- `FrameQuality.kt`
- `AutoCapturePolicy.kt`
- `CaptureGate.kt`
- `ScanControlLoop.kt`
- `ScanControlState.kt`
- `ScanCaptureController.kt`
- `ScanCapabilityProbe.kt`
- `CameraCapabilities.kt`
- `ManualControlController.kt`
- `ThermalMonitor.kt`
- `ScanDiagnostics.kt`
- `ScanFallbackPolicy.kt`
- `ScanCoordinateMapper.kt`
- `ScanEventSender.kt`
- `ScanEvent.kt`

The exact file split can be consolidated during implementation, but keep the pure analyzer/policy core free of Android/CameraX types for JVM tests.

### Modified native files

- `MainActivity.kt`: register `ScanCameraPlugin`; keep the existing `veriscript/offline` channel.
- `OfflinePages.kt`: explicit `maxSide`/full-resolution plumbing for camera pages; free-space/cleanup support if needed.
- `RapidOcr.kt`: optional higher input cap behind a flag, only after OCR A/B.
- `android/app/build.gradle.kts`: CameraX 1.6.2 dependencies, test dependencies; keep ONNX/OpenCV/ML Kit.
- `android/app/proguard-rules.pro`: CameraX keeps if release build needs them.
- `AndroidManifest.xml`: no new permissions expected; CAMERA already present.

### New Dart files

`mobile/lib/scan/`

- `scan_camera_api.dart`
- `scan_camera_controller.dart`
- `scan_models.dart`
- `scan_geometry.dart`
- `scan_overlay.dart`
- `scan_view_model.dart`
- `scan_screen.dart`
- `scan_feedback.dart`
- `scan_pro_controls.dart`

### Modified Dart files

- `lib/review.dart`: route to `ScanScreen` behind `scanCameraV2`; keep `CaptureScreen` for video/fallback.
- `lib/capture.dart`: interim photo preset fix; keep video path; add validation/fallback if desired.
- `lib/documents.dart`: optional `capture` metadata; pass resolution options to native import.
- `lib/main.dart`: feature flag/settings/diagnostics entry if needed.
- `pubspec.yaml`: no new Flutter dependency required; keep `camera` for video.

### Tests

- `mobile/android/app/src/test/kotlin/.../scan/` for JVM tests.
- `mobile/android/app/src/androidTest/kotlin/.../scan/` for bind/lifecycle/capture tests.
- `mobile/test/scan_models_test.dart`, `scan_geometry_test.dart`, `scan_view_model_test.dart`, `scan_screen_test.dart`.
- `mobile/integration_test/scan_camera_test.dart` for device smoke.
- Extend existing `mobile/test/processing_test.dart`, `document_test.dart`, `review_test.dart` for metadata/feature flag.

### Docs

- This plan.
- `docs/VERIFICATION.md`: actual device results, not assumptions.
- `README.md`: user-facing capture behavior and limits after rollout.
- Update `docs/P1.md`/P2/P3 only if the workflow changes.

---

## 14. Acceptance checklist

- [ ] Baseline 720p vs 12 MP data recorded.
- [ ] Native scan session binds Preview + ImageAnalysis + ImageCapture on the target devices.
- [ ] Actual still >= 8 MP (target 12 MP 4:3); dimensions validated from file.
- [ ] Preview full-frame, letterboxed; overlay aligned; debug overlay verified.
- [ ] Analysis p95 <= 40 ms mid-range; no ANR; thermal adaptation works.
- [ ] Page detection confidence/quad stable; framing guidance priority correct.
- [ ] Auto EV converges and stays within deadband; no oscillation; device range respected.
- [ ] AF metering at page centroid; re-trigger policy; capture lock/fallback.
- [ ] Torch default off; auto/on/off; glare/thermal off-ramps.
- [ ] Guidance shows one message at a time with min display/repeat cooldown.
- [ ] Manual shutter always available; auto-capture (if enabled) passes false-trigger/duplicate gates.
- [ ] Capture validation catches black/blank/corrupt JPEG and retries.
- [ ] Scan -> video -> scan works; camera ownership guard tested.
- [ ] Permission denied/unavailable/busy/thermal all fall back to import or old capture.
- [ ] Downstream resolution plumbing preserves 3000-3500 px pages; storage cleanup/free-space guard tested.
- [ ] Factorial OCR A/B shows no regression and a credible improvement; defaults changed only then.
- [ ] 50-page and 150-page runs pass performance/thermal/storage targets.
- [ ] Release APK has no INTERNET permission and no new permissions; offline verified.
- [ ] Feature flag/rollback documented.

---

## 15. Bottom line

The app does not need a different camera app; it needs a **document-specific camera pipeline** inside the existing app. The current camera is a thin 720p wrapper, and the current image pipeline caps resolution before OCR. The highest-leverage changes are:

1. capture 12 MP 4:3 with a real preview/analysis/capture split;
2. frame the page by height with all corners visible;
3. expose the paper correctly and treat glare/clipping as hard vetoes;
4. focus/stabilize before capture and validate every still;
5. preserve resolution through the OpenCV/OCR chain and prove the gain with paired OCR tests.

The auto-tuning loop should be conservative and observable, not magical: small EV steps, page-ROI metering, AF at the page centroid, torch only when it helps, one guidance message at a time, and a manual shutter that always works. Build the analyzer and reason codes first; add coaching copy, auto-capture, and advanced manual controls behind measured gates. This keeps the offline, privacy-preserving, review-first character of VeriScript intact while giving the OCR pipeline materially better input.

---

## 16. Research references

Local detailed reports (primary source for this plan):

- `mobile/docs/research/camera-plugin-capabilities.md`
- `mobile/docs/research/document-capture-science.md`
- `mobile/docs/research/native-camera-architecture.md`
- `mobile/docs/research/ocr-preprocessing.md`
- `mobile/docs/research/scanner-ux-competition.md`

Key external references cited in those reports:

- Android CameraX: use cases, `ImageAnalysis`, `ImageCapture`, `FocusMeteringAction`, `Camera2Interop`, resolution selectors, stream combinations.
- Android Camera2: `CONTROL_AE_LOCK`, `CONTROL_AE_COMPENSATION_RANGE`, `SENSOR_EXPOSURE_TIME`, `SENSOR_SENSITIVITY`, `CONTROL_AWB_MODE`, `LENS_FOCUS_DISTANCE`.
- Flutter camera plugin 0.12.1 / camera_android_camerax 0.7.5+1 source and issue tracker (single resolution preset, stream copies, high-res black JPEG, preview rotation).
- Google ML Kit text recognition guidance (16x16 px per character; little gain above 24x24).
- Tesseract/Willus resolution guidance (roughly 20-30 px capital/x-height; 300 DPI recommended).
- PaddleOCR/RapidOCR input sizing (line height 48 px; detector/working-size caps).
- Document capture/OCR research: SmartDoc-QA (ICDAR 2015), camera-captured OCR quality assessment (ICIP 2011), DocTr (ACM MM 2021), intrinsic decomposition (BMVC 2020), exposure bracketing for document images (Applied Sciences 2019), specular highlight removal (ICSP 2016).
- Scanner UX: Google ML Kit Document Scanner API, Google Drive scan, Microsoft Lens/OneDrive, Adobe Scan, CamScanner, Apple Notes/VisionKit, Samsung document scan, OpenNoteScanner.

Where the research reports label something as a heuristic or open question, treat the thresholds in this plan the same way: starting values for device calibration, not universal guarantees.

