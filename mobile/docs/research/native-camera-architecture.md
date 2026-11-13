# Native scan-camera architecture for VeriScript

**Status:** research + recommendation  
**Date:** 2026-11-07  
**Scope:** Flutter Android app, `minSdk 29`, offline release (no `INTERNET` permission), document scanning for OCR  
**Decision:** use **Option B** — a native CameraX session in Kotlin, a Flutter `Texture` preview through `TextureRegistry`, a pure-Kotlin analysis/quality/auto-capture core, and a thin Dart presentation layer. Keep the existing `camera` plugin only for the separate video-recording flow. Do not use the plugin and the native scan session at the same time.

---

## 0. Executive summary

The current document capture path uses `CameraController(..., ResolutionPreset.high)` and `CameraPreview` (`mobile/lib/capture.dart`). In the Android CameraX implementation of the Flutter camera plugin, `ResolutionPreset.high` maps to a 1280×720 target and, more importantly, the same resolution selector is applied to `Preview`, `ImageAnalysis`, and `ImageCapture` ([R23], [R24]). That means the current path is not a viable base for:

- 8–12 MP OCR stills,
- small-resolution real-time analysis,
- native per-frame quality/3A state,
- manual ISO/shutter/white balance,
- reliable auto-capture.

The Android camera stack has a hard stream-combination constraint: the guaranteed combination is **preview-sized YUV analysis + preview + maximum-size JPEG**, not **full-resolution YUV analysis + full-resolution JPEG + preview** ([R14]). Any architecture that ties analysis resolution to capture resolution will either fail to bind or run at an unacceptable frame rate. This single fact rules out Option A as a production architecture.

**Recommendation in one sentence:** own the camera in Kotlin with CameraX, expose only a Flutter texture and small event payloads to Dart, analyze downsampled luma natively at 10–15 fps, capture 12 MP JPEG separately, and use `Camera2Interop` only behind capability-gated “pro” controls.

---

## 1. Current state and constraints

### 1.1 Existing capture screen

The app pins `camera: ^0.12.1`; on Android that resolves to the endorsed `camera_android_camerax` implementation (0.7.x at the time of writing) ([R25]). `mobile/lib/capture.dart`:

- opens the back camera with `CameraController(selected, ResolutionPreset.high, enableAudio: false)`,
- displays `CameraPreview`,
- takes stills with `camera.takePicture()` and passes the path to `onPhoto`,
- handles video recording in the same screen (`recordMode`),
- disposes the controller on `inactive` and re-initializes on `resumed`.

The screen is used by `mobile/lib/review.dart`:

- document capture: `CaptureScreen(count: ..., onPhoto: ...)` with `align: false, enhance: false`,
- after the user taps Done, `review.dart` runs the existing native `restore`/`enhance` passes.

This is useful: **the existing `OfflinePages.restore` and `enhance` pipeline already performs the final page-boundary warp and deskew for stills.** The new preview path only needs a rough live quad and quality signal; it does not need to duplicate the mature final crop logic.

### 1.2 Existing native operations

`mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt`:

- `pageView()`: resizes to 960 px, Canny, contours, quadrilateral approximation, fallback paper mask, warp,
- `deskew()`: Hough lines, median angle,
- `enhance()`: shadow flattening, bilateral filter, unsharp mask, optional 2× enlargement,
- `load()`: EXIF orientation handling, 30 MP input cap, 5000 px max side for `restore`/`crop`.

The new native analyzer can reuse the same OpenCV package and conventions, but its real-time core should be pure Kotlin for testability and to avoid JNI/Mat allocation on every preview frame.

### 1.3 Release/offline constraints

`mobile/android/app/src/release/AndroidManifest.xml` removes `INTERNET` and `ACCESS_NETWORK_STATE` from the merged manifest. This is not a soft preference: any dependency that needs a first-use model/UI download cannot be part of the core scan flow.

### 1.4 Requirements

| Requirement | Implication |
|---|---|
| Real-time page boundary + quality on preview | Native analysis, small frames, no Dart pixel copies |
| Auto-tune EV/focus/metering/torch/zoom; possibly WB/ISO/shutter | CameraX `CameraControl` by default; `Camera2Interop` for manual, capability-gated |
| ≥8 MP still, ideally 12 MP | `ImageCapture` separate from analysis resolution |
| Auto-capture + manual shutter | Native state machine with capture-in-flight guard |
| Low latency, reasonable battery/thermal | `KEEP_ONLY_LATEST`, luma-only downsampling, thermal adaptation, no full-res analysis |
| Testability/maintainability | Pure Kotlin analyzer + pure Dart geometry/model; CameraX fakes for session tests |
| No cloud | All processing on-device; no Play Services-dependent first-use download |

---

## 2. Options evaluated

### Option A — keep the Flutter `camera` plugin, analyze YUV in Dart

**How it would work:** keep `CameraController`, call `startImageStream`, convert YUV `CameraImage` planes to grayscale in Dart, run page/quality analysis in Dart, use `setExposureOffset`, `setFocusPoint`, `setExposurePoint`, `setFlashMode`, `setZoomLevel`.

**What the plugin actually does on Android:**

- `camera_android_camerax` creates `Preview`, `ImageCapture`, and `ImageAnalysis` with the **same** `_presetResolutionSelector` ([R23]).
- `initializeCamera` binds all three use cases in one `bindToLifecycle` call ([R23]).
- `ResolutionPreset.high` is 1280×720; `max` uses `ResolutionStrategy.highestAvailableStrategy` for all use cases ([R23]).
- `startImageStream` is documented as running best with `ResolutionPreset.low`; `ResolutionPreset.high` can cause “significant frame rate drops” ([R24]).
- streamed frames are copied into `CameraImageData` planes and delivered through a Dart stream; the analyzer closes `ImageProxy` only after the copy ([R23]).
- exposure mode maps only to `CONTROL_AE_LOCK`; there is no public ISO or shutter control ([R23]).
- focus/exposure points map to `FocusMeteringAction`; EV maps to `ExposureState` compensation; torch/zoom are exposed ([R23], [R24]).

**Assessment:**

| Criterion | Result |
|---|---|
| 3A/manual control | EV, focus/exposure point, focus lock, torch, zoom. No ISO/shutter/WB. No per-frame AF/AE/AWB result stream. |
| Max still resolution | `high` targets 1280×720; `veryHigh` 1920×1080; `ultraHigh` 3840×2160; `max` is highest available but also applies to analysis. Cannot cleanly get 12 MP still + small analysis. |
| Preview analysis performance | Dart receives full YUV planes over a platform channel; grayscale conversion in Dart; at 720p+ this is expensive and at 12 MP is impractical. |
| Auto-capture | Possible in Dart, but gate decisions are delayed by channel copies and lack camera 3A state. |
| Integration complexity | Low initially. |
| Extensions (HDR/Night) | Not exposed by the plugin. |
| Lifecycle/rotation | Plugin handles it. |
| Conflict with existing plugin | None (it is the plugin). |
| Thermal/battery | Poor if analysis and capture share a high-resolution selector. |
| Testability | Dart unit tests possible; camera behavior is opaque behind the plugin. |
| Risk | **High** for the actual product requirements. |

**Verdict:** good for a quick prototype, **not acceptable** for the production document scanner. It cannot decouple analysis from capture resolution, and the current `high` preset is below the 8 MP requirement.

---

### Option B — custom CameraX in Kotlin, Flutter texture preview, MethodChannel/EventChannel

**How it would work:**

- Native `Preview` + `ImageAnalysis` + `ImageCapture` bound with `ProcessCameraProvider`.
- Preview rendered through `TextureRegistry.SurfaceProducer` and `Preview.setSurfaceProvider`; Flutter draws a `Texture` plus a Dart overlay.
- `ImageAnalysis` delivers `YUV_420_888`; the analyzer reads only the Y plane, downsamples to 320–480 px, and runs pure-Kotlin page/quality analysis.
- `ImageCapture` captures a separate 4:3 12 MP JPEG.
- `CameraControl` handles EV, focus/metering, torch, zoom.
- `Camera2Interop` handles ISO/shutter/WB only when the device reports the required capabilities.
- Small JSON-like maps go to Flutter over `EventChannel`; control commands come back over `MethodChannel`.

**Assessment:**

| Criterion | Result |
|---|---|
| 3A/manual control | CameraX controls cover EV, AF/AE/AWB metering, torch, zoom; `Camera2Interop` adds ISO/shutter/WB on capable devices. |
| Max still resolution | `ImageCapture` independently targets 12 MP 4:3; actual size verified with `getResolutionInfo()`. |
| Preview analysis performance | Native Y-plane access, no platform-channel pixel copies; 10–15 fps at 960×720 feasible on mid-range devices. |
| Auto-capture | Native state machine sees every analysis frame, quality scores, and capture state. |
| Integration complexity | Medium–high: new Kotlin session, texture, lifecycle, channel, tests. |
| Extensions | Available via `camera-extensions` but **only Preview+ImageCapture are guaranteed**; analysis may be unsupported. Keep off in scan mode. |
| Lifecycle/rotation | CameraX lifecycle binding; custom texture needs explicit rotation/crop handling. |
| Conflict with existing plugin | Must not run simultaneously; `ProcessCameraProvider` and the camera device are shared. |
| Thermal/battery | Good if analysis is downsampled and capture is not bursty; thermal listener can lower fps. |
| Testability | Best: pure Kotlin analyzer/state machine + CameraX fakes; thin Dart layer. |
| Risk | **Medium**, concentrated in stream-combination fallbacks, coordinate mapping, and manual interop. |

**Verdict:** **recommended.**

---

### Option C — native Camera2 full pipeline (no CameraX)

**How it would work:** `CameraManager.openCamera`, `CameraDevice.createCaptureSession(SessionConfiguration)`, `ImageReader` for YUV and JPEG, `CaptureRequest.Builder`, repeating requests, manual 3A, `SurfaceView`/`TextureView`.

**Assessment:**

| Criterion | Result |
|---|---|
| 3A/manual control | Maximum: `TEMPLATE_MANUAL`, `CONTROL_AE_MODE_OFF`, `SENSOR_SENSITIVITY`, `SENSOR_EXPOSURE_TIME`, `CONTROL_AF_MODE_OFF`/`LENS_FOCUS_DISTANCE`, `CONTROL_AWB_MODE_OFF`, `COLOR_CORRECTION_GAINS`. |
| Max still resolution | Maximum JPEG/YUV, subject to stream combinations. |
| Preview analysis performance | Native, potentially best, but entirely app-managed. |
| Auto-capture | Native, but all state/3A handling is app code. |
| Integration complexity | **High**: session configuration, surface lifecycle, rotation, AF/AE precapture, device quirks, JPEG/analysis concurrency, thermal, lifecycle. |
| Extensions | Camera2 extension sessions are possible but add another device-specific path. |
| Lifecycle/rotation | Manual; error-prone. |
| Conflict with existing plugin | Same camera-device exclusivity problem. |
| Thermal/battery | Can be tuned, but requires more work. |
| Testability | Hardest: less abstraction, more device/HAL behavior. |
| Risk | **High** relative to benefit. |

CameraX is explicitly built on Camera2 and exposes the underlying `CaptureRequest` through `Camera2Interop` ([R1], [R10], [R11]). A full Camera2 pipeline only becomes justified if the Phase 0 spike proves CameraX cannot deliver 12 MP still + analysis + required manual controls on a device in the support matrix. That is not expected.

**Verdict:** **not recommended** for this product.

---

### Option D — hybrid plugin preview/manual fallback + separate native analyzer/capture, or ML Kit Document Scanner

There are two variants:

**D1: plugin for preview/manual fallback + native analyzer/capture.**  
The Flutter camera plugin already holds a `ProcessCameraProvider` and calls `unbindAll()` during create/dispose ([R23]). A native analyzer cannot open a second camera session at the same time. A “separate native analyzer path” would have to fully take over the camera, which is Option B with extra complexity. The plugin can only be a **sequential fallback** (switch routes, tear down one, open the other), not a simultaneous hybrid.

**D2: Google ML Kit Document Scanner API.**  
It provides a complete scanner UI and returns JPEG/PDF URIs, but:

- “The models, scanning logic and UI flow are dynamically downloaded by Google Play services” ([R26]).
- first use may wait for models/UI to download ([R26]),
- it requires Google Play services and a minimum device RAM of 1.7 GB ([R26]),
- the viewfinder/preview screen is provided by the SDK; there is no API for custom per-frame analysis, auto-capture policy, or manual 3A control ([R26]),
- the release build has **no `INTERNET` permission**, so a first-use dynamic download cannot be relied on.

**Assessment:**

| Criterion | D1 plugin + native | D2 ML Kit Document Scanner |
|---|---|---|
| 3A/manual control | plugin controls only; native path is Option B | none |
| Max still resolution | plugin preset limits | SDK-defined, not controllable |
| Preview analysis | none while plugin owns camera | none exposed |
| Auto-capture | no | SDK-provided, not customizable |
| Integration complexity | medium but redundant | low UI integration, high product constraint |
| Extensions | no | no |
| Lifecycle/rotation | two camera owners | separate activity |
| Conflict | unavoidable | separate flow |
| Thermal/battery | no control | SDK |
| Testability | poor | black box |
| Risk | **high** | **high for offline product** |

**Verdict:** reject as the core architecture. Option B already includes a clean fallback path (manual shutter, no analysis). ML Kit Document Scanner can only be considered as an optional “import via system scanner” feature if the product later allows Play Services and network on first use — not for this release.

---

### 2.1 Comparison matrix

Ratings: **++** strong, **+** acceptable, **0** limited, **−** poor.

| Criterion | A: plugin + Dart | B: CameraX native | C: Camera2 native | D: hybrid / ML Kit |
|---|---|---|---|---|
| 3A/manual control | 0 (EV/AF/AE point/torch/zoom only) | ++ (CameraX + interop) | ++ (full) | − / − |
| Max still resolution | − (preset conflicts) | ++ (12 MP target) | ++ | 0 |
| Preview analysis performance | − (Dart copies) | ++ (native luma) | ++ | − (none) |
| Auto-capture | 0 | ++ | ++ | 0 (SDK) |
| Integration complexity | ++ (low) | 0 (medium–high) | − (high) | + / ++ |
| Extensions HDR/Night | − (not exposed) | + (available, analysis caveat) | 0 | − |
| Lifecycle/rotation | ++ | + | − | + / ++ |
| Conflict with existing plugin | ++ | 0 (exclusive) | 0 (exclusive) | − |
| Thermal/battery | − at high res | + | + (with work) | 0 |
| Testability | 0 | ++ | − | − |
| Overall risk | High | **Medium** | High | High |

---

## 3. Evidence deep dive

### 3.1 Stream combinations: the decisive constraint

Android’s Camera2 documentation lists guaranteed stream combinations by hardware level ([R14]). For **LEGACY** devices, the guaranteed “still capture plus in-app processing” row is:

| Target 1 | Target 2 | Target 3 | Use case |
|---|---|---|---|
| `PRIV` `PREVIEW` | `YUV` `PREVIEW` | `JPEG` `MAXIMUM` | Still capture plus in-app processing |

For **LIMITED** devices, an additional guaranteed row is:

| Target 1 | Target 2 | Target 3 | Use case |
|---|---|---|---|
| `YUV` `PREVIEW` | `YUV` `PREVIEW` | `JPEG` `MAXIMUM` | Two-input in-app processing with still capture |

For **FULL** devices, there are rows with `YUV MAXIMUM` plus preview, and rows with `JPEG MAXIMUM` plus preview, but **no guaranteed row with full-resolution YUV + full-resolution JPEG + preview**. The docs also warn that if an app exceeds the table limits, session creation may succeed but miss frame-rate guarantees, or fail entirely with `onConfigureFailed` ([R14]).

CameraX states that it allows one instance each of `Preview`, `VideoCapture`, `ImageAnalysis`, and `ImageCapture`, but “depending on camera capability, some cameras may support the combination at lower resolution modes, but can not support the same combination at some higher resolutions” ([R1]). If an incompatible combination is bound, a runtime error is thrown on `createCaptureSession()` ([R1]).

**Conclusion:** the production configuration must be:

- `Preview` at preview resolution (4:3 or 16:9 depending on device, ideally 1280×960),
- `ImageAnalysis` at **preview resolution or smaller** (default 960×720, low-end 640×480),
- `ImageCapture` at a **high-resolution JPEG target** (4000×3000, 4:3 for 12 MP; verify actual area, ≥ 8 MP). This stays within the guaranteed `JPEG MAXIMUM` stream size.

This configuration is guaranteed on LEGACY/LIMITED/FULL. **Direct answer to “is full-resolution `ImageCapture` + `ImageAnalysis` + `Preview` supported?”:** yes on typical devices **only if `ImageAnalysis` is at preview size**; full-resolution `ImageAnalysis` is not a guaranteed combination. It is also unnecessary: page detection and quality scoring work at 320–480 px.

We deliberately do **not** bind `VideoCapture` in scan mode. Adding it can force CameraX to duplicate the `PRIV` stream for preview/video on LIMITED or lower devices (“stream sharing”), increasing latency and battery use ([R1]).

**CameraX resolution behavior:** `ImageCapture` defaults to the highest available resolution (or the highest device-preferred resolution matching its aspect ratio); `ImageAnalysis` defaults to 640×480; `Preview` defaults to the highest preview/device-preferred size, while its maximum is the best screen match or 1080p, whichever is smaller ([R2]). Use `ResolutionSelector`/`ResolutionStrategy` to set explicit bounds, and always verify actual output with `ImageCapture.getResolutionInfo()` and `ImageAnalysis.getResolutionInfo()` after binding ([R5], [R3]).

**Important plugin finding:** `camera_android_camerax` uses the **same** `_presetResolutionSelector` for `Preview`, `ImageCapture`, and `ImageAnalysis` ([R23]). `ResolutionPreset.max` uses `ResolutionStrategy.highestAvailableStrategy` for all three ([R23]). Therefore:

- If you choose `max`, the analysis stream is also max-resolution YUV — likely unsupported or extremely slow.
- If you choose `high`, stills target 1280×720 — below the 8 MP floor.
- There is no preset that gives “12 MP still + small analysis” simultaneously.

This is the decisive reason to leave the plugin for the document scan path.

**Extensions caveat:** with CameraX Extensions enabled, “only the `ImageCapture` and `Preview` combination is guaranteed to work”; adding `ImageAnalysis` may fail depending on OEM implementation ([R1]). `ExtensionsManager.isImageAnalysisSupported(selector, mode)` must be checked before binding, and it returns false when the extension cannot coexist with analysis ([R13]). That makes extensions unsuitable for the default live-analysis mode.

### 3.2 3A and manual controls

**CameraX auto controls (default):**

- EV: `CameraControl.setExposureCompensationIndex()`; range/step from `CameraInfo.getExposureState()` (`getExposureCompensationRange()`, `getExposureCompensationStep()`, `isExposureCompensationSupported()`) ([R2], [R8]). A **positive** index brightens the image; a negative index darkens it ([R2], [R8]).
- Focus/metering: `CameraControl.startFocusAndMetering(FocusMeteringAction)` with `MeteringPoint`s and `FLAG_AF`, `FLAG_AE`, `FLAG_AWB`; default action locks AF after a successful scan and auto-cancels after 5 s ([R7]).
- Torch: `CameraControl.enableTorch(boolean)`; torch state via `CameraInfo.getTorchState()`; flash mode only applies when torch is off ([R2]).
- Zoom: `setZoomRatio()` / `setLinearZoom()`; range from `ZoomState` ([R2]).
- AE/AWB locking: `FocusMeteringAction` locking modes in newer CameraX; on 1.6.2, `Camera2Interop`/`Camera2CameraControl` can set `CONTROL_AE_LOCK`/`CONTROL_AWB_LOCK` if needed ([R7], [R11]).

**Manual controls (pro mode):**

`Camera2Interop` lets you set `CaptureRequest` keys through a `Camera2Interop.Extender` or `Camera2CameraControl` ([R10], [R11]). Relevant keys:

| Control | Key | Capability gate |
|---|---|---|
| Disable auto exposure | `CONTROL_AE_MODE = OFF` | `CONTROL_AE_AVAILABLE_MODES` contains `OFF`; FULL always, LIMITED only with `MANUAL_SENSOR`, LEGACY never ([R15]) |
| ISO | `SENSOR_SENSITIVITY` | `SENSOR_INFO_SENSITIVITY_RANGE` present; `MANUAL_SENSOR` ([R15]) |
| Shutter | `SENSOR_EXPOSURE_TIME` (ns) | `SENSOR_INFO_EXPOSURE_TIME_RANGE` present; `MANUAL_SENSOR` ([R15]) |
| Manual WB | `CONTROL_AWB_MODE = OFF`, `COLOR_CORRECTION_MODE = TRANSFORM_MATRIX`, `COLOR_CORRECTION_GAINS` | `CONTROL_AWB_AVAILABLE_MODES` contains `OFF`; `MANUAL_POST_PROCESSING` (all FULL devices, some LIMITED) ([R15]) |
| Manual focus | `CONTROL_AF_MODE = OFF`, `LENS_FOCUS_DISTANCE` | `MANUAL_SENSOR`; optional, not needed for most document scanning |

The docs are explicit about the risk: values set through `Camera2Interop` override CameraX’s values and “may interfere with some CameraX CameraControl APIs as well as 3A behavior” ([R10]); `Camera2CameraControl` options apply to every repeating and single capture request issued by CameraX ([R11]). Also, when `CONTROL_AE_MODE = OFF`, AWB/AF behavior is device-dependent; the recommended approach is to set AWB/AF to OFF or lock them first ([R16], `CONTROL_AE_MODE_OFF`).

**Design consequence:** manual ISO/shutter/WB is a **capability-gated pro mode**, not the default. Auto mode uses CameraX controls; manual mode is only shown when `MANUAL_SENSOR`/`MANUAL_POST_PROCESSING` and the relevant ranges are present. On exit from manual mode, clear the interop options and reset to auto; run a watchdog that resets if preview stalls or capture fails.

**Version note:** pin CameraX **1.6.2** (current stable) for this work. `Camera2Interop.Extender` and `Camera2CameraControl` are usable there; they are deprecated in `1.7.0-rc02` in favor of `CameraControl.applyCamera2Interop { ... }` / `Camera2Interop` configurators ([R10], [R11], [R19]). Migrate the manual-control adapter when 1.7 reaches stable, not before.

### 3.3 Preview delivery: Flutter `TextureRegistry` vs AndroidView

Flutter’s platform-view guidance:

- **Texture layer:** good Flutter performance, full widget transforms; can be janky during quick scrolling and breaks accessibility/text magnification for `SurfaceView`s ([R20]).
- **Hybrid composition:** full native fidelity and `SurfaceView` support, but merges raster/platform threads and degrades Flutter FPS ([R20]).
- **HCPP:** experimental, Android API 34+, Vulkan + Impeller; not a baseline for `minSdk 29` ([R20]).

`TextureRegistry.SurfaceProducer` provides a Flutter-managed `Surface` (`getSurface()`, `setSize()`, `setCallback()`, `release()`), and its `handlesCropAndRotation()` returns whether the rendering path handles crop/rotation automatically. On API 29+ with the `ImageReader` backend it may return false, so the plugin must rotate/crop itself ([R21]). For a custom CameraX `SurfaceProvider`, `SurfaceRequest.getTransformationInfo()` supplies the source rotation/crop; use it rather than guessing ([R2]).

The existing camera plugin already uses this texture pattern: it calls `Preview.setSurfaceProvider(systemServicesManager)` and returns a texture ID, then displays `Texture(textureId: cameraId)` with a `RotatedPreviewDelegate` ([R23]). That is a proven path in this codebase’s dependency set.

**Recommendation:** use `TextureRegistry.SurfaceProducer` + `Preview.setSurfaceProvider` as the primary preview path. Draw the page quad, quality badges, and shutter controls in Flutter. This avoids a full-screen Android view compositing path and keeps the overlay in one rendering system.

**Fallback only:** `AndroidView`/`PlatformViewLink` hosting a `PreviewView`. If used:

- `PreviewView` is the recommended surface provider for CameraX ([R1]),
- `previewView.getViewPort()` gives the crop rect shared by use cases ([R2]),
- `previewView.getMeteringPointFactory()` gives correct metering points for taps ([R2]),
- use `PreviewView.ImplementationMode.COMPATIBLE` (TextureView) under a texture-layer platform view, or hybrid composition if `SurfaceView` is required. Accept the FPS/accessibility tradeoff; do not make it the default.

### 3.4 CameraX Extensions (HDR/Night)

`ExtensionsManager` supports `BOKEH`, `HDR`, `NIGHT`, `FACE_RETOUCH`, and `AUTO` modes on supported devices ([R13]). Availability is OEM-specific: query `isExtensionAvailable(cameraSelector, mode)` and `isImageAnalysisSupported(cameraSelector, mode)` ([R13]).

Key constraints:

- With extensions enabled, only `Preview` + `ImageCapture` are guaranteed; `ImageAnalysis` may not bind ([R1], [R13]).
- Extensions may use multi-frame capture and add latency; they are not a good fit for a live auto-capture loop.
- Manual `Camera2Interop` settings can conflict with the extension pipeline; do not combine them without device testing.

**Recommendation:** keep extensions off in scan mode. If the product wants a “Night still” mode later, treat it as a separate still-only mode that pauses analysis and requires manual shutter; do not make auto-capture depend on it.

### 3.5 ML Kit Document Scanner

The ML Kit Document Scanner API is attractive for a quick scanner UI, but it is the wrong core for this app:

- models, scanning logic, and UI flow are **dynamically downloaded by Google Play services** ([R26]),
- first use may wait for the download ([R26]),
- the SDK provides its own viewfinder and preview screens; customization is limited to gallery import, page limit, scanner mode, and output formats ([R26]),
- it exposes no preview-frame callback, no quality metrics, no auto-capture policy, and no manual 3A control ([R26]),
- it requires Google Play services and a 1.7 GB minimum RAM device ([R26]),
- the release manifest removes `INTERNET`, so a first-use dynamic download cannot be assumed.

**Recommendation:** reject for the core. Optionally add an “Import with Google Document Scanner” path only if the product later permits Play Services and network on first use; this would be a separate activity flow, not the in-app camera.

### 3.6 CameraX vs full Camera2

CameraX is built on Camera2 and exposes the underlying `Camera2CameraInfo` and `CaptureRequest` controls ([R1], [R10], [R12]). A full Camera2 pipeline would duplicate what CameraX already provides:

- camera open/close and lifecycle,
- stream combination selection and surface management,
- preview/analysis/JPEG concurrency,
- rotation and viewport/crop,
- device workarounds.

It would add the need to implement AF/AE precapture, 3A locks, JPEG orientation, and session recovery. The only reason to choose C is a measured CameraX limitation on a target device. Phase 0 should test that explicitly; otherwise C is unjustified risk.

---

## 4. Recommended architecture (Option B)

### 4.1 Component diagram

```
┌──────────────────────────────── Flutter (Dart) ────────────────────────────────┐
│ ScanScreen                                                                     │
│  ├─ Texture(textureId)            ← preview pixels                            │
│  ├─ ScanOverlay (CustomPainter)   ← quad, quality badges, shutter             │
│  ├─ ScanViewModel (pure Dart)     ← reducer over ScanFrame/ScanCapture events  │
│  └─ ScanCameraController          ← MethodChannel + EventChannel               │
└───────────────────────────────▲───────────────────────────────┬────────────────┘
                                │ events (small maps, 10 Hz)   │ methods
┌───────────────────────────────┴───────────────────────────────▼────────────────┐
│ ScanCameraPlugin (Kotlin, FlutterPlugin/ActivityAware)                         │
│  ├─ ScanCameraSession        owns ProcessCameraProvider + use cases            │
│  ├─ ScanPreviewSurfaceProvider  TextureRegistry.SurfaceProducer → Preview       │
│  ├─ ScanAnalyzer             ImageAnalysis.Analyzer on dedicated thread        │
│  │   ├─ YuvFrameAdapter      Y plane + cropRect + rotation → 480×360 luma      │
│  │   ├─ PageDetector         pure Kotlin quad detection                        │
│  │   ├─ QualityAnalyzer      sharpness/exposure/glare/stability/fill           │
│  │   └─ AutoCapturePolicy    pure state machine                                │
│  ├─ ScanControlLoop          EV/focus/torch/zoom at 4 Hz                       │
│  ├─ ManualControlController  Camera2Interop, capability-gated                   │
│  ├─ ScanCaptureController    ImageCapture 12 MP JPEG                           │
│  ├─ ThermalMonitor           PowerManager thermal status/headroom               │
│  └─ ScanEventSender          main-thread event throttling                       │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Native file layout

Package: `com.veriscript.veriscript_mobile.scan`

| File | Responsibility |
|---|---|
| `ScanCameraPlugin.kt` | `FlutterPlugin`, `ActivityAware`, `MethodCallHandler`, `EventChannel.StreamHandler`; owns channel names and lifecycle. |
| `ScanCameraSession.kt` | `ProcessCameraProvider`, camera selector, `UseCaseGroup`, bind/unbind, actual resolution/capability reporting, fallback ladder. |
| `ScanPreviewSurfaceProvider.kt` | `TextureRegistry.SurfaceProducer` + CameraX `Preview.SurfaceProvider`; surface size/callback/release. |
| `ScanCameraEngine.kt` | Facade used by the plugin: open/close, capture, controls, diagnostics. Keeps CameraX types out of Flutter-facing code. |
| `ScanAnalyzer.kt` | `ImageAnalysis.Analyzer`; throttles, adapts `ImageProxy` to `YuvFrame`, calls detector/quality/policy, closes `ImageProxy` in `finally`. |
| `YuvFrame.kt` | Immutable downsampled luma + metadata (`sourceWidth`, `sourceHeight`, `cropRect`, `rotationDegrees`, `timestampNs`). No Android types in the core. |
| `YuvFrameAdapter.kt` | Stride-aware Y-plane downsampler: `rowStride`, `pixelStride`, `cropRect`; planar/semi-planar-safe. |
| `PageQuad.kt` | Four normalized points, ordering, area, IoU, edge support; pure Kotlin. |
| `PageDetector.kt` | Interface + default pure-Kotlin boundary detector on downsampled luma; returns `PageQuad?` + confidence. An OpenCV-backed implementation can be swapped in later behind the same interface if accuracy on low-contrast pages requires it. |
| `QualityAnalyzer.kt` | Sharpness (Laplacian variance on page ROI), exposure histogram, glare, stability (frame-to-frame motion), fill ratio. |
| `FrameQuality.kt` | Normalized scores + `reasons`; pure data. |
| `AutoCapturePolicy.kt` | Hysteresis/state machine: SEARCHING → CANDIDATE → READY → CAPTURING → COOLDOWN; duplicate-page suppression. |
| `CaptureGate.kt` | Decision + human-readable reason codes. |
| `ScanControlLoop.kt` | Scheduled 4 Hz control loop; EV/focus/torch/zoom commands; guards against oscillation. |
| `ScanControlState.kt` | Latest snapshot shared between analyzer/control/UI. |
| `ScanCapabilityProbe.kt` | Reads `Camera2CameraInfo` characteristics: hardware level, AE modes, ISO/exposure ranges, AWB modes, max JPEG size, extension availability. |
| `CameraCapabilities.kt` | Pure data returned to Dart; decides which pro controls are visible. |
| `ManualControlController.kt` | `Camera2CameraControl`/`CaptureRequestOptions` for `CONTROL_AE_MODE`, `SENSOR_SENSITIVITY`, `SENSOR_EXPOSURE_TIME`, `CONTROL_AWB_MODE`, `COLOR_CORRECTION_GAINS`; clears on exit. |
| `ScanCaptureController.kt` | `ImageCapture` builder, 12 MP/8 MP resolution selector, JPEG 95, `takePicture`, retry/fallback, capture-in-flight guard. |
| `ScanEventSender.kt` | Main-thread `EventSink`; drops frames when no listener; throttles to 10 Hz. |
| `ScanEvent.kt` | Serialization of `frame`, `capture`, `session`, `error` payloads; pure except for map building. |
| `ThermalMonitor.kt` | `PowerManager.addThermalStatusListener` (API 29); `getCurrentThermalStatus`; `getThermalHeadroom(10)` on API 30+; emits policy hints. |
| `ScanDiagnostics.kt` | Actual resolutions, stream combo, frame-time percentiles, capture latency, thermal status, capability summary. |
| `ScanFallbackPolicy.kt` | Bind/analysis/capture fallback ladder; returns a `ScanMode` (`FULL`, `ANALYSIS_REDUCED`, `MANUAL_ONLY`). |
| `ScanCoordinateMapper.kt` | Pure Kotlin mapping between analysis buffer, preview view, and metering points; used for tap-to-focus and tests. |

Tests (same package or `src/test`):

- `PageDetectorTest.kt`
- `QualityAnalyzerTest.kt`
- `AutoCapturePolicyTest.kt`
- `YuvFrameAdapterTest.kt`
- `ScanCoordinateMapperTest.kt`
- `ScanCapabilityProbeTest.kt`
- `ScanSessionTest.kt` (`androidTest`, CameraX fakes)
- `ScanAnalyzerTest.kt` (`androidTest` or JVM if adapter is pure)
- `ScanTestFrames.kt` (synthetic luma/quad/glare/dark frames)

### 4.3 Flutter file layout

| File | Responsibility |
|---|---|
| `mobile/lib/scan/scan_camera_controller.dart` | `MethodChannel('veriscript/scan_camera')` + `EventChannel('veriscript/scan_camera/events')`; open/close/capture/control; typed errors; lifecycle. |
| `mobile/lib/scan/scan_models.dart` | `ScanSessionInfo`, `ScanFrame`, `ScanQuality`, `ScanGate`, `ScanCapture`, `ScanError`; JSON parsing/validation; pure. |
| `mobile/lib/scan/scan_geometry.dart` | `ScanOverlayGeometry`: normalized buffer ↔ rotated display ↔ widget rect; rotation/mirror/aspect-fit; pure. |
| `mobile/lib/scan/scan_overlay.dart` | `CustomPainter` for quad, corner handles, “too dark/glare/hold still” badges; debug mode. |
| `mobile/lib/scan/scan_view_model.dart` | Pure reducer for frame/capture/session events; page count, last capture, gate message, thermal banner. |
| `mobile/lib/scan/scan_screen.dart` | `Texture` preview, overlay, shutter, auto toggle, torch, zoom, pro sheet; integrates `onPhoto`. |
| `mobile/lib/scan/scan_feedback.dart` | Human-readable gate reasons and icons. |
| `mobile/lib/scan/scan_pro_controls.dart` | ISO/shutter/WB controls, only if `CameraCapabilities` says supported. |
| `mobile/lib/scan/scan_camera_api.dart` | Interface + `MethodChannelScanCameraApi` + `FakeScanCameraApi` for tests. |
| `mobile/test/scan_geometry_test.dart` | Rotation 0/90/180/270, crop rect, aspect-fit, mirror. |
| `mobile/test/scan_models_test.dart` | Payload parsing, invalid/missing fields, enum fallbacks. |
| `mobile/test/scan_view_model_test.dart` | Reducer tests, duplicate capture, error/thermal states. |
| `mobile/integration_test/scan_camera_test.dart` | End-to-end on device: open, capture, auto-capture, rotate, background/resume. |

Integration point: in `review.dart`, change the document capture route from `CaptureScreen` to `ScanScreen`, keeping the same `onPhoto` contract. Keep `CaptureScreen(recordMode: true)` for video. Do not touch the video route until CameraX `VideoCapture` is deliberately adopted.

### 4.4 Channel protocol

Use the existing style (`MethodChannel` + `EventChannel`, `StandardMethodCodec`). Pigeon is optional; it would add generated code and is not necessary for this small protocol.

#### Method channel: `veriscript/scan_camera`

| Method | Arguments | Result | Notes |
|---|---|---|---|
| `open` | `{cameraId?: "0", analysisWidth?: 960, analysisHeight?: 720, captureWidth?: 4000, captureHeight?: 3000, prefer12MP?: true}` | `ScanSessionInfo` map | Idempotent; must be on main thread; returns actual resolutions and fallback mode. |
| `close` | none | `null` | Releases camera, analyzer, surface, executors; safe if already closed. |
| `capture` | `{auto?: false}` | `{captureId: string}` | Starts one capture; completion via `capture` event. Returns `BUSY` if a capture is already in flight. |
| `setAutoCapture` | `{enabled: bool}` | `null` | Enables/disables the native gate; manual shutter always works. |
| `setTorch` | `{enabled: bool}` | `null` | User override; thermal guard may refuse. |
| `setZoom` | `{ratio: double}` | `null` | Clamped to `ZoomState`; no auto-zoom unless enabled. |
| `setExposureCompensation` | `{ev: double}` | `{appliedEv: double}` | Clamped/rounded to `ExposureState` step. |
| `focusAt` | `{x: double, y: double}` | `null` | Normalized widget coordinates; native maps to `MeteringPoint`. |
| `setMeteringPoint` | `{x, y, flags?: "AF|AE|AWB"}` | `null` | Optional advanced API. |
| `setManualExposure` | `{iso: int, exposureTimeNs: int}` | `null` | Only if capabilities allow; returns `UNSUPPORTED` otherwise. |
| `clearManualExposure` | none | `null` | Restores `CONTROL_AE_MODE=ON`. |
| `setManualWhiteBalance` | `{mode?: string, gains?: [r,g,b,g2]}` | `null` | Only if `MANUAL_POST_PROCESSING`; explicit gains or preset mode. |
| `clearManualWhiteBalance` | none | `null` | Restores auto WB. |
| `reset3A` | none | `null` | Clears interop options, restarts AF/AE/AWB. |
| `getCapabilities` | none | `CameraCapabilities` map | Hardware level, manual ranges, max capture size, extensions. |
| `getDiagnostics` | none | `ScanDiagnostics` map | For device matrix/support; no network. |

Error codes: `CAMERA_PERMISSION`, `CAMERA_UNAVAILABLE`, `CAMERA_BUSY`, `BIND_FAILED`, `STREAM_COMBINATION_UNSUPPORTED`, `CAPTURE_FAILED`, `BUSY`, `NOT_OPEN`, `UNSUPPORTED`, `THERMAL_LIMIT`, `INTERNAL`.

#### Event channel: `veriscript/scan_camera/events`

| Event `type` | Payload | Rate |
|---|---|---|
| `session` | `{state: "opened"|"closed"|"error", mode: "FULL"|"ANALYSIS_REDUCED"|"MANUAL_ONLY", preview: {width,height}, analysis: {width,height}, capture: {width,height}, rotationDegrees, capabilities, fallbackReason?}` | On open/fallback/close |
| `frame` | `{seq, tsMs, analysis: {width,height,rotationDegrees}, quad: [[x,y]×4], quality: {sharpness,exposure,glare,stability,fill,confidence}, gate: {ready,reasons}, camera: {evIndex, zoom, torch, af, ae, thermal}}` | 10 Hz max |
| `capture` | `{captureId, state: "started"|"saved"|"failed", auto, path?, width?, height?, rotationDegrees?, quad?, error?}` | Per capture |
| `error` | `{code, message, fatal}` | On error |

`frame.quad` is normalized to the **analysis buffer’s unrotated coordinate system**, after applying `ImageProxy.cropRect`; `rotationDegrees` tells Dart how to rotate it for display. Do not send pixel arrays or full JPEGs over the channel.

Example `frame`:

```json
{
  "type": "frame",
  "seq": 1234,
  "tsMs": 1731012345678,
  "analysis": {"width": 960, "height": 720, "rotationDegrees": 90},
  "quad": [[0.12, 0.08], [0.88, 0.10], [0.86, 0.92], [0.10, 0.90]],
  "quality": {"sharpness": 0.72, "exposure": 0.81, "glare": 0.01, "stability": 0.93, "fill": 0.78, "confidence": 0.88},
  "gate": {"ready": true, "reasons": []},
  "camera": {"evIndex": 0, "zoom": 1.0, "torch": false, "af": "FOCUSED", "ae": "CONVERGED", "thermal": 0}
}
```

### 4.5 Threading model

| Thread/executor | Work | Rules |
|---|---|---|
| Flutter main / Android main | Plugin lifecycle, channel handlers, `ProcessCameraProvider.bindToLifecycle`, `CameraControl` calls, `EventSink`, channel results | Never block; post camera-control futures; coalesce EV/zoom requests. |
| CameraX internal camera executor | Camera open/configure/repeating requests | Leave default; do not replace globally (the plugin also uses CameraX). |
| `scan-analysis` (`HandlerThread` or single-thread executor) | `ImageAnalysis.Analyzer.analyze`, Y-plane downsampling, detector, quality, gate | Close `ImageProxy` in `finally`; no blocking IPC; no Bitmap/Mat allocation per frame. |
| `scan-control` (single-thread scheduled executor) | 4 Hz control loop: EV/focus/torch/zoom decisions; thermal policy | Reads latest immutable `ScanControlState`; posts actual CameraX calls to main; cancel superseded futures. |
| `scan-capture` (single-thread executor) | `ImageCapture.takePicture` callbacks, metadata, retry/fallback | One capture in flight; file IO off main; emit event on completion. |
| `scan-io` (optional) | Cache cleanup, diagnostics file | Never block analysis/main. |

**Key invariant:** the analyzer downsamples the Y plane into a reusable 320–480 px buffer and closes the `ImageProxy` before returning. It never holds an `ImageProxy` across threads. The control loop only sees the small immutable snapshot.

Pseudo-code:

```kotlin
override fun analyze(image: ImageProxy) {
    val nowMs = image.imageInfo.timestamp / 1_000_000
    if (nowMs - lastAcceptedMs < minIntervalMs) {
        image.close()
        return
    }
    try {
        val frame = frameAdapter.downsample(image, targetWidth = 480, targetHeight = 360)
        val result = engine.analyze(frame) // pure Kotlin, no Android types
        latestState.set(result)
        if (nowMs - lastEmitMs >= 100) {
            eventSender.sendFrame(result)
            lastEmitMs = nowMs
        }
    } catch (t: Throwable) {
        eventSender.sendError("ANALYSIS_FAILED", t.message, fatal = false)
    } finally {
        image.close()
    }
}
```

### 4.6 Frame throttling and performance budget

- `ImageAnalysis.Builder().setBackpressureStrategy(STRATEGY_KEEP_ONLY_LATEST)` — only the latest frame is delivered; old frames are dropped; failing to close stalls future images ([R3], [R4]).
- `setOutputImageFormat(OUTPUT_IMAGE_FORMAT_YUV_420_888)` and read only `planes[0]` (Y). Avoid `RGBA_8888`, which makes CameraX convert internally ([R4]).
- Target analysis: 960×720 default; 640×480 if frame time > 40 ms or thermal status ≥ LIGHT; 1280×960 only on devices that prove it.
- Downsample to 480×360 (or 320×240 on low-end) before detection; use `rowStride`/`pixelStride` and `cropRect` correctly ([R17]).
- Analyze at 10–15 fps (`minIntervalMs` 66–100 ms); emit UI events at 10 Hz; control loop at 4 Hz.
- No `Bitmap`, no `Mat`, no full-frame copy in the hot path. Reuse `ByteArray`/`FloatArray` buffers.
- Measured budget target on a mid-range device: downsample + detector + quality ≤ 15 ms/frame; total ≤ 25 ms; p95 ≤ 40 ms. If p95 > 50 ms for 2 s, drop analysis resolution/fps.
- Capture is separate: 12 MP JPEG encode can take 200–800 ms; show a shutter animation; analysis may drop frames during capture, which is fine.
- `ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY` prioritizes quality over latency and defaults to JPEG 100; we set JPEG 95 explicitly to keep files manageable ([R5]). If capture latency is unacceptable on low-end devices, fall back to `CAPTURE_MODE_MINIMIZE_LATENCY` (JPEG 95) ([R5]).

### 4.7 Coordinate mapping

Define one canonical coordinate system:

1. **Analysis buffer coordinates:** `(0,0)` top-left, unrotated, size = `ImageProxy.width × ImageProxy.height`. If `image.cropRect` is non-empty, normalize relative to the crop rect:
   `nx = (x - crop.left) / crop.width`, `ny = (y - crop.top) / crop.height`.
2. **Display-normalized coordinates:** rotate by `rotationDegrees` (`ImageInfo.rotationDegrees`):
   - 0°: `(x, y)`
   - 90° clockwise: `(1 - y, x)`
   - 180°: `(1 - x, 1 - y)`
   - 270° clockwise: `(y, 1 - x)`
3. **Widget coordinates:** aspect-fit the rotated buffer rect inside the `Texture`/overlay rect:
   `fit = BoxFit.contain` of `(rotatedWidth/rotatedHeight)` in the widget; map `(nx, ny)` into `fit`.
4. **Mirror:** for front camera only, flip `nx = 1 - nx` after rotation. Document scanning uses the back camera, but keep the flag in the model.

Dart pure function:

```dart
Offset rotateNormalized(Offset p, int degrees) => switch (degrees % 360) {
  90 => Offset(1 - p.dy, p.dx),
  180 => Offset(1 - p.dx, 1 - p.dy),
  270 => Offset(p.dy, 1 - p.dx),
  _ => p,
};

Rect aspectFit(Size content, Size widget) {
  final scale = math.min(widget.width / content.width, widget.height / content.height);
  final w = content.width * scale, h = content.height * scale;
  return Rect.fromLTWH((widget.width - w) / 2, (widget.height - h) / 2, w, h);
}
```

**Tap-to-focus:** Flutter sends normalized widget coordinates. Native options:

- `PreviewView` fallback: `previewView.getMeteringPointFactory().createPoint(xPx, yPx)` — PreviewView handles scale/crop ([R2]).
- Texture/SurfaceView path: `DisplayOrientedMeteringPointFactory(display, cameraInfo, viewWidth, viewHeight)` and adjust for letterbox; the docs explicitly recommend this for SurfaceView/TextureView ([R2]).
- Analyzer-driven metering: `SurfaceOrientedMeteringPointFactory(analysisWidth, analysisHeight, imageAnalysis)` for points specified in `ImageProxy` coordinates ([R2]).

**Debug mode:** draw both the raw analysis quad and the rotated/aspect-fit widget quad; log `rotationDegrees`, `cropRect`, actual preview/analysis/capture sizes, and `SurfaceProducer.handlesCropAndRotation()`. This is the fastest way to catch rotation/crop bugs on device.

### 4.8 Auto-capture policy

Use a pure Kotlin state machine, not Dart, because the gate must see every frame and the camera’s capture state. Dart only renders `gate.ready/reasons` and the last capture.

**Metrics (normalized 0..1, except fill/glare):**

| Metric | Computation | Suggested enter threshold |
|---|---|---|
| `sharpness` | Variance of Laplacian on page ROI, normalized by local contrast, on 480×360 luma | ≥ 0.55 |
| `exposure` | Mean luma in page ROI (target 70–190), penalty for clipped dark/bright pixels | ≥ 0.60 |
| `glare` | Fraction of saturated pixels (`Y > 250`) with low local gradient | ≤ 0.01 |
| `stability` | Frame-to-frame translation/quad displacement over 200 ms; or phase-correlation peak | ≥ 0.85 |
| `fill` | Quad area / analysis frame area | 0.40–0.95 |
| `confidence` | Fraction of quad perimeter supported by strong gradients; convexity; aspect/side ratios | ≥ 0.65 |

**Hysteresis:** thresholds have separate enter/exit values (e.g., sharpness enter 0.55, exit 0.45; glare enter 0.01, exit 0.03) to prevent flicker.

**State machine:**

```
SEARCHING --(quad confidence > 0.5, fill > 0.30)--> CANDIDATE
CANDIDATE --(all metrics pass for 6 frames / 400 ms)--> READY
CANDIDATE --(bad frame)--> SEARCHING
READY --(still good, no capture in flight)--> CAPTURING
CAPTURING --(capture saved)--> COOLDOWN
CAPTURING --(capture failed)--> SEARCHING (retry once at lower quality)
COOLDOWN --(page changed: IoU < 0.55 or corner shift > 8%)--> SEARCHING
COOLDOWN --(1.5 s elapsed)--> SEARCHING
```

**Duplicate suppression:** after a capture, compute a 64-bit dHash of the page ROI. If the next candidate’s hash is within Hamming distance ≤ 6, do not auto-capture again until the page changes or 2 s pass. Manual shutter always bypasses duplicate suppression.

**Capture guard:** `AtomicBoolean capturing`; `takePicture` is sequential in CameraX, but explicit guarding prevents queued duplicate requests and gives the UI a stable `BUSY` response ([R5]).

**UI reasons:** return stable codes (`MOVE_CLOSER`, `MOVE_AWAY`, `HOLD_STILL`, `TOO_DARK`, `TOO_BRIGHT`, `GLARE`, `LOW_SHARPNESS`, `NO_PAGE`, `PAGE_CUT_OFF`, `CAPTURING`, `THERMAL`) plus a default localized string in Dart.

### 4.9 Control loop

| Loop | Rate | Action | Guard |
|---|---|---|---|
| EV | 4 Hz | If exposure score < 0.45 (too dark), increase index (brighter) by 1 step; if > 0.80 (too bright), decrease index by 1 step | Deadband 0.1 EV; max 2 steps/s; clamp to `ExposureState` range; reset on page change |
| Focus/metering | On page change, focus failure, or every 2 s while searching | `FocusMeteringAction` at quad center with `FLAG_AF|FLAG_AE|FLAG_AWB`; `disableAutoCancel` while page candidate; re-arm on page change | Never call every frame; default auto-cancel is 5 s ([R7]); check `isFocusSuccessful` |
| Torch | Hysteresis | Auto only if user enables “auto torch”; on when exposure < 0.35 for 1 s; off when > 0.60 for 2 s or after capture | Thermal status < MODERATE; user override wins; torch can create glare, so default off |
| Zoom | On fill low/high | Step 1.1× if fill < 0.35 and zoom < 2×; step down if fill > 0.90 | Only if user enables auto-zoom; deadband; prefer “move closer” message |
| Manual ISO/shutter/WB | On user change | `Camera2Interop` options; lock AF/AWB first; set `CONTROL_AE_MODE=OFF` | Capability gate; reset to auto on exit; watchdog resets on preview stall/capture failure |
| Thermal | 1 Hz | ≥ LIGHT: analysis 8 fps; ≥ MODERATE: 640×480/4 fps, disable auto torch; ≥ SEVERE: stop auto-capture; ≥ CRITICAL: pause preview | `PowerManager` status/headroom ([R18]) |

**Anti-oscillation:** all control commands are rate-limited and only issued when the error exceeds a deadband. EV changes are small (1 step). Never combine a focus trigger with an EV change in the same 250 ms window; wait for the focus result or let it cancel.

### 4.10 Lifecycle and rotation

- `ScanCameraPlugin` implements `ActivityAware`; `open` requires an attached `Activity`.
- `FlutterActivity` implements `androidx.lifecycle.LifecycleOwner` ([R22]); use it directly for `ProcessCameraProvider.bindToLifecycle(activity, selector, useCaseGroup)`.
- On `onDetachedFromActivity` / `onDestroy`: `unbindAll()`, `imageAnalysis.clearAnalyzer()`, release the `SurfaceProducer`, shut down executors, null the event sink.
- On `onPause`: CameraX closes the camera via the lifecycle; keep the binding, release nothing permanently. On `onResume`: **reapply** EV/zoom/torch/auto-capture settings, because CameraX control state reverts when the camera is closed ([R2]); rebind only if the session was explicitly unbound during a fallback or route change.
- Rotation: use `OrientationEventListener` and `UseCase.snapToSurfaceRotation(orientation)` ([R3]); call `setTargetRotation` on `Preview`, `ImageAnalysis`, and `ImageCapture`. Emit a `session`/`frame` field so Dart can recompute the overlay.
- `SurfaceProducer`: create with `SurfaceLifecycle.manual`; `setSize(previewWidth, previewHeight)`; `setCallback` for surface destroyed/recreated; in `ScanPreviewSurfaceProvider.onSurfaceRequested`, call `request.provideSurface(surfaceProducer.getSurface(), mainExecutor) { result -> ... }` and release the result; never cache the `Surface` ([R21]).
- In `ScanPreviewSurfaceProvider`, read `SurfaceRequest.getTransformationInfo()` and pass the rotation/crop to Dart (or apply it to the surface) so the texture and overlay use the same transform ([R2]).
- Check `surfaceProducer.handlesCropAndRotation()`; on API 29+ ImageReader backend it may be false, so apply the rotation/crop transform in Dart or native ([R21]).
- Keep the screen on with `WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON` while the scan route is active; clear on exit. No wake lock.

### 4.11 Capture pipeline and reuse of `OfflinePages`

- `ImageCapture.Builder`:
  - `setCaptureMode(CAPTURE_MODE_MAXIMIZE_QUALITY)`,
  - `setJpegQuality(95)`,
  - `setResolutionSelector` with 4:3 aspect and `ResolutionStrategy(Size(4000, 3000), FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER)`,
  - `setTargetRotation(currentRotation)`.
- After bind, read `imageCapture.getResolutionInfo()` and `imageAnalysis.getResolutionInfo()`; emit actual sizes in `session`. `getResolutionInfo()` is expressed in sensor coordinates; the delivered JPEG may be rotated, so validate by pixel area (width × height), not by assuming portrait/landscape orientation. If capture area < 8 MP, try `HIGHEST_AVAILABLE_STRATEGY`; if still < 8 MP, warn in `session` but allow capture.
- `takePicture(OutputFileOptions.Builder(file).build(), captureExecutor, callback)`; save to app cache (`context.cacheDir/scan/…jpg`). No external storage permission needed on API 29+.
- On success: emit `capture.saved` with path, dimensions, rotation, and the quad used at trigger time. Dart calls the existing `onPhoto(path)`; `review.dart` later runs `OfflinePages.restore`/`enhance` as it does today. While `onPhoto` is importing, Dart may temporarily call `setAutoCapture(false)` and re-enable it in `finally`; the native 1.5 s cooldown and duplicate-page hash already prevent rapid re-triggers.
- Do not decode the 12 MP JPEG in Dart or in the preview pipeline. `OfflinePages.load` already handles EXIF and caps input at 30 MP ([local source]).
- Do not request RAW. A 12 MP JPEG is sufficient for OCR and much faster; RAW+JPEG increases stream pressure, file size, and processing time for no OCR benefit.
- If final OpenCV `restore` corrects the crop differently from the preview quad, that is acceptable: the preview quad is guidance, not the final crop. This keeps the mature still pipeline authoritative and reduces risk.
- Scope note: this design detects **one page quad**. If open-book spread capture is required, extend `PageDetector` to return up to two quads, trigger auto-capture on the spread, and let the existing split/crop logic produce two pages. Do not silently crop one page out of a spread.

### 4.12 Fallbacks and failure modes

| Failure | Detection | Fallback |
|---|---|---|
| Full three-use-case bind fails | `IllegalArgumentException` / `onConfigureFailed` / `bindToLifecycle` throws | Retry with analysis 640×480; then retry Preview+ImageCapture only (`MANUAL_ONLY`) |
| ImageCapture < 8 MP | `getResolutionInfo()` after bind | Try 12 MP bounded selector; then `HIGHEST_AVAILABLE_STRATEGY`; warn |
| Analysis analyzer throws repeatedly | 3 consecutive failures | `clearAnalyzer()`, switch to `MANUAL_ONLY`, emit `ANALYSIS_FAILED` |
| Capture fails | `ImageCaptureException` | Retry once with `CAPTURE_MODE_MINIMIZE_LATENCY` or 8 MP; then emit `CAPTURE_FAILED` |
| Thermal ≥ SEVERE | `PowerManager` listener | Reduce analysis fps/resolution, disable auto-capture/torch; if CRITICAL, pause preview |
| Manual controls unsupported | Capability probe | Hide pro UI; auto mode only |
| Extensions unavailable/analysis unsupported | `ExtensionsManager` | Keep extensions off; no user-visible failure |
| Camera in use by plugin | `CAMERA_BUSY` / open error | Close plugin camera first; route guard; show message |
| Permission denied | `CAMERA_PERMISSION` | Offer “Import images” and retry |

---

## 5. Phased implementation plan

Effort scale: **S** ≤ 1 week, **M** 1–2 weeks, **L** 2–4 weeks (one experienced Android/Flutter engineer; can parallelize native/Dart after Phase 1).

### Phase 0 — Capability and stream-combination spike (S, 2–3 days)

**Goal:** prove the configuration on real devices before building UI.

Deliverables:

- `ScanCapabilityProbe.kt`: hardware level, `CONTROL_AE_AVAILABLE_MODES`, `MANUAL_SENSOR`, `MANUAL_POST_PROCESSING`, ISO/exposure ranges, AWB modes, max JPEG sizes, extension availability.
- A throwaway `ScanSessionSpike` (instrumentation test or debug screen) that binds `Preview(1280×960) + ImageAnalysis(960×720, YUV, KEEP_ONLY_LATEST) + ImageCapture(4000×3000, JPEG 95)`.
- Measurements on at least 3 devices (low/mid/high): bind success, actual resolutions, analysis frame time p50/p95, capture latency, 10-minute thermal behavior.

**Exit criteria:** at least one low/mid device binds the three-use-case combination, captures ≥ 8 MP, and analyzes at ≥ 10 fps for 10 minutes without thermal shutdown. If not, adjust analysis resolution/fallback before Phase 1.

### Phase 1 — Native CameraX session, texture preview, still capture (M, 1.5–2 weeks)

Deliverables:

- `ScanCameraPlugin.kt`, `ScanCameraSession.kt`, `ScanPreviewSurfaceProvider.kt`, `ScanCaptureController.kt`, `ScanEventSender.kt`, `ScanEvent.kt`.
- Add CameraX dependencies at **1.6.2** and align them with the `camera` plugin’s transitive CameraX version; run both the video route and scan route in the same build to catch binary/runtime mismatches.
- Dart `scan_camera_controller.dart`, `scan_models.dart`, `scan_screen.dart` with `Texture` preview and manual shutter.
- `open`/`close`/`capture`/`getCapabilities`; `session` and `capture` events.
- Lifecycle/rotation/surface callback handling; `FLAG_KEEP_SCREEN_ON`.
- `review.dart` route to `ScanScreen` for documents; `CaptureScreen` remains for video.

**Exit criteria:** 12 MP JPEG saved from the Flutter shutter; preview rotates correctly on portrait/landscape; background/resume recovers; no camera-plugin conflict.

### Phase 2 — Pure-Kotlin analyzer, quality metrics, overlay (L, 2–3 weeks)

Deliverables:

- `YuvFrame.kt`, `YuvFrameAdapter.kt`, `PageQuad.kt`, `PageDetector.kt`, `QualityAnalyzer.kt`, `FrameQuality.kt`, `ScanCoordinateMapper.kt`.
- Keep `PageDetector` an interface. If the pure-Kotlin detector misses low-contrast pages, add an `OpenCvPageDetector` behind the same interface; the pure detector remains the test oracle for synthetic cases and the fast path on low-end devices.
- `ScanAnalyzer.kt` wiring; `frame` events at 10 Hz.
- Dart `scan_geometry.dart`, `scan_overlay.dart`, `scan_view_model.dart`; debug overlay.
- Unit tests for YUV strides/crop/rotation, synthetic page quads, quality metrics.

**Exit criteria:** live quad at 10–15 fps; overlay aligns with preview on 0/90/180/270 and letterboxed preview; p95 analysis ≤ 40 ms on the mid device; no ANRs.

### Phase 3 — Control loop and auto-capture (M, 1.5–2 weeks)

Deliverables:

- `AutoCapturePolicy.kt`, `CaptureGate.kt`, `ScanControlLoop.kt`, `ScanControlState.kt`, `ThermalMonitor.kt`, `ScanFallbackPolicy.kt`.
- Dart gate UI: “Hold still”, “Move closer”, “Glare”, “Too dark”, auto-capture toggle, shutter feedback.
- Duplicate-page suppression; capture-in-flight guard; thermal adaptation.

**Exit criteria:** 20-page auto-capture run with no duplicates and < 5% false triggers; manual shutter always works; 10-minute thermal test degrades gracefully; no preview freeze during capture.

### Phase 4 — Capability-gated manual controls (M, 1 week)

Deliverables:

- `ScanCapabilityProbe.kt` full implementation; `CameraCapabilities.kt`, `ManualControlController.kt`.
- `setManualExposure`, `clearManualExposure`, `setManualWhiteBalance`, `clearManualWhiteBalance`, `reset3A`.
- Dart `scan_pro_controls.dart`; hide unsupported controls.

**Exit criteria:** ISO/shutter/WB work on a FULL/LEVEL_3 device; unsupported devices return `UNSUPPORTED` and hide the UI; leaving manual mode restores auto and preview does not stall; watchdog test passes.

### Phase 5 — Hardening, tests, device matrix (M, 1.5–2 weeks)

Deliverables:

- `ScanDiagnostics.kt`; diagnostics UI/log file (no network).
- `ScanSessionTest.kt` with CameraX `camera-testing`/`FakeCamera`; instrumentation tests for bind/fallback.
- Dart unit/widget tests; integration test on device.
- Device matrix: at least one LEGACY/LIMITED, one FULL/LEVEL_3, one low-RAM device; thermal/battery run.

**Exit criteria:** fallback paths exercised; no leaks on 100 captures; rotation/background stress passes; p95 timings and thermal behavior documented.

### Phase 6 — Optional extensions / ML Kit import (S, 3–5 days; not core)

Only if product explicitly wants it:

- `ScanExtensionController.kt` for `ExtensionMode.NIGHT`/`HDR` when `isExtensionAvailable` and `isImageAnalysisSupported`; pause auto-capture, manual shutter only.
- Optional “Import with Google Document Scanner” activity, with a clear Play Services/network requirement. Do not make it the main flow.

**Exit criteria:** extension mode never breaks the default scan path; disabling it returns to Option B without a restart.

**Total:** roughly **8–11 engineer-weeks** for one engineer; Phase 2 (analyzer/overlay) and Phase 3 (control/auto) can overlap with Phase 1 Dart work if two engineers are available.

---

## 6. Testability

### 6.1 Pure Kotlin core (JVM unit tests)

Everything below has no Android dependency and can be tested with JUnit:

- `YuvFrameAdapter`: planar/semi-planar, `rowStride > width`, `pixelStride = 2`, non-zero `cropRect`, odd widths/heights.
- `PageDetector`: synthetic luma (white page on dark background, perspective quad, low contrast, cut-off page, no page); rotation 0/90/180/270; expected quad IoU.
- `QualityAnalyzer`: uniform gray, text-like checkerboard, dark/bright, glare blob, motion blur; score monotonicity.
- `AutoCapturePolicy`: enter/exit hysteresis, consecutive-frame requirement, duplicate suppression, capture failure/retry, page-change reset.
- `ScanCoordinateMapper`: round-trip analysis ↔ display ↔ widget; crop rect; mirror; letterbox.
- `ScanFallbackPolicy`: bind failure → reduced analysis → manual only; capture size < 8 MP → alternate selector.
- `CameraCapabilities`: manual exposure/WB visibility rules.

Use a `ScanTestFrames` fixture generator rather than image files for speed and determinism.

### 6.2 Android instrumentation

- `androidx.camera:camera-testing` provides `FakeCamera`, which implements `CameraInternal` and can simulate use-case attach/session configuration ([R27]). Use it to test `ScanCameraSession` bind/fallback logic without hardware.
- Real-device tests for the things fakes cannot prove: actual stream combination, 12 MP JPEG, thermal behavior, rotation/crop, torch, manual interop.
- `CameraInfo.isSessionConfigSupported(...)` (stable in CameraX 1.6) can be used in diagnostics before binding ([R19]); do not rely on it as the only check because OEM implementations vary.

### 6.3 Dart tests

- `scan_models_test.dart`: parse valid/invalid/missing fields; enum fallbacks; numeric clamping.
- `scan_geometry_test.dart`: rotation 0/90/180/270, aspect-fit, crop rect, mirror; property-based round-trip.
- `scan_view_model_test.dart`: reducer over frame/capture/session/error events; duplicate capture; thermal banner; page count.
- `scan_camera_controller_test.dart`: fake `MethodChannel`/`EventChannel` via `TestDefaultBinaryMessenger`; verify method arguments and error mapping.
- Widget/golden tests for overlay at portrait/landscape/letterboxed sizes.

### 6.4 Field diagnostics

`getDiagnostics` should return:

- camera ID, hardware level, sensor orientation,
- actual preview/analysis/capture resolutions,
- stream combination/fallback mode,
- analysis frame time p50/p95, dropped frames,
- capture latency, JPEG size,
- thermal status/headroom,
- manual capability flags and extension availability.

This makes device-specific bug reports actionable without network access.

---

## 7. Top 5 technical risks and mitigations

### 1. Stream combination or 12 MP capture is unsupported on some devices

**Risk:** three-use-case bind fails, or `ImageCapture` selects < 8 MP, or the device silently drops frame rate.

**Mitigation:**

- Use the guaranteed combination: preview + preview-sized YUV analysis + max JPEG, never full-res analysis ([R14]).
- Verify actual resolutions with `ImageCapture.getResolutionInfo()`/`ImageAnalysis.getResolutionInfo()` ([R5], [R3]).
- Phase 0 device spike; `isSessionConfigSupported` diagnostics; explicit fallback ladder (960×720 → 640×480 → manual-only; 12 MP → 8 MP → highest available).
- Emit `session.mode`/`fallbackReason` to Dart; never fail silently.

### 2. Preview/analysis/capture coordinate and rotation mismatch

**Risk:** overlay quad is rotated, mirrored, cropped, or offset; tap-to-focus lands in the wrong place; auto-capture triggers on the wrong region.

**Mitigation:**

- One canonical normalized analysis-buffer coordinate system; use `ImageProxy.cropRect` + `ImageInfo.rotationDegrees` ([R3], [R17]).
- Pure `ScanCoordinateMapper`/`scan_geometry.dart` with golden tests for 0/90/180/270, letterbox, crop, mirror.
- Debug overlay drawing both raw and transformed quads; on-device validation on portrait/landscape.
- Use `PreviewView.getViewPort()`/`getMeteringPointFactory()` in the AndroidView fallback ([R2]); use `SurfaceOrientedMeteringPointFactory` for analysis-driven metering ([R2]).

### 3. 3A/manual interop causes oscillation, stalls, or unsupported settings

**Risk:** `Camera2Interop` overrides CameraX controls and breaks AE/AF/AWB; manual ISO/shutter/WB is unavailable on LIMITED/LEGACY; capture hangs.

**Mitigation:**

- Auto mode is the default; `Camera2Interop` only in an explicit pro mode, behind capability checks (`MANUAL_SENSOR`, `MANUAL_POST_PROCESSING`, `CONTROL_AE_AVAILABLE_MODES` contains `OFF`, ranges present) ([R15]).
- When entering manual, lock AF/AWB first, then set `CONTROL_AE_MODE=OFF` ([R16]); clear all options and reset to auto on exit.
- Rate-limit EV/focus/zoom; deadbands; cancel superseded futures.
- Watchdog: if preview frame time > 100 ms or capture fails twice, clear interop options and reset to auto; emit `UNSUPPORTED`/`MANUAL_RESET`.

### 4. Thermal throttling and battery drain during long scanning sessions

**Risk:** 12 MP captures + analysis + torch heat the device; frame rate collapses; user sees lag or shutdown.

**Mitigation:**

- Luma-only 480×360 analysis at 10–15 fps; no full-res analysis; no RGBA/Bitmap/Mat in the hot path.
- `STRATEGY_KEEP_ONLY_LATEST`; drop frames proactively; emit at 10 Hz, not every frame ([R3]).
- `PowerManager.addThermalStatusListener`/`getCurrentThermalStatus` (API 29) and `getThermalHeadroom(10)` (API 30+) ([R18]).
- Thermal policy: ≥ LIGHT reduce to 8 fps; ≥ MODERATE 640×480/4 fps + no auto torch; ≥ SEVERE stop auto-capture; ≥ CRITICAL pause preview.
- No extensions (multi-frame) in live mode; torch off by default and duty-cycled; capture cooldown 1.5 s.

### 5. Lifecycle, surface, and camera-ownership conflicts

**Risk:** the existing `camera` plugin and the native scanner fight over `ProcessCameraProvider`; background/resume loses the surface; rotation leaks or shows a stale texture; activity recreation crashes.

**Mitigation:**

- Single owner policy: close/dispose the plugin camera before pushing `ScanScreen`; close the native session before opening the video route. The plugin calls `unbindAll()` on create/dispose ([R23]); do not rely on both.
- Use `ActivityAware` + `FlutterActivity` as `LifecycleOwner` ([R22]); `bindToLifecycle` and `unbindAll` in the right callbacks.
- `SurfaceProducer.setCallback` to handle surface destroyed/recreated; never cache `Surface` ([R21]).
- On resume, reapply controls; rebind only if the session was explicitly unbound (CameraX control state resets when the camera closes) ([R2]).
- Integration tests for background/resume, rotation, route switch, and 100 captures; strict `close()` idempotency.

---

## 8. Decision and decisive tradeoffs

**Chosen architecture:** **Option B plus Flutter texture preview.** It is the only option that simultaneously satisfies:

1. **12 MP still + small real-time analysis** without violating Camera2 stream-combination guarantees.
2. **Native per-frame quality/3A state** for auto-capture and control loops.
3. **Capability-gated manual ISO/shutter/WB** where the hardware supports it.
4. **Offline/no-network** operation with no Play Services first-use download.
5. **Testable pure Kotlin core** and a thin Flutter presentation layer.

**Tradeoffs accepted:**

- **Leave the camera plugin for document scanning.** The plugin’s convenience is not compatible with decoupled analysis/capture resolutions. Keep it for the existing video-recording route, but never run both camera owners simultaneously.
- **Do not analyze at full resolution.** Full-res YUV + full-res JPEG + preview is not a guaranteed stream combination; full-res analysis would waste CPU and violate frame-rate guarantees. Use 960×720 (or 640×480) analysis and let `ImageCapture` handle 12 MP.
- **Do not use CameraX Extensions in scan mode.** HDR/Night are OEM-dependent and can exclude `ImageAnalysis`; they are not worth breaking auto-capture.
- **Reject ML Kit Document Scanner as core.** It owns the UI and downloads its models/UI flow on first use; it cannot satisfy the custom live analysis, manual controls, or no-Internet release constraint.
- **Reject full Camera2.** CameraX already provides Camera2 interop for the manual controls we need; a full pipeline adds session/lifecycle/3A/device-quirk risk without a product feature.
- **Accept native maintenance.** The new scan path is a small, well-tested Kotlin subsystem; this is the price of reliable document scanning.

**Success looks like:** on a mid-range API 29+ device, preview stays fluid at 10–15 analysis fps, the quad tracks the page, auto-capture fires after a short “hold still”, a 12 MP JPEG lands in the existing review flow, and a 20-page session finishes without thermal collapse or duplicate pages. On a device that cannot bind the full combination, the app falls back to manual shutter and still captures 8–12 MP.

---

## 9. References

All Android docs accessed 2026-11-07. CameraX version context: stable **1.6.2**, release candidate **1.7.0-rc02** ([R19]).

| ID | Source | Used for |
|---|---|---|
| R1 | [CameraX architecture](https://developer.android.com/media/camera/camerax/architecture) | Use-case model, simultaneous use cases, stream-sharing, extensions guarantee, CameraX built on Camera2 |
| R2 | [CameraX configuration](https://developer.android.com/media/camera/camerax/configuration) | Resolution tables, rotation, `ViewPort`, `PreviewView.getViewPort()`, `CameraControl`, `FocusMeteringAction`, `ExposureState`, `Camera2Interop` |
| R3 | [ImageAnalysis reference](https://developer.android.com/reference/androidx/camera/core/ImageAnalysis) | YUV/RGBA formats, `STRATEGY_KEEP_ONLY_LATEST`, analyzer lifecycle, resolution info |
| R4 | [Analyze images with CameraX](https://developer.android.com/training/camerax/analyze) | Non-blocking/blocking modes, 32 ms/frame guidance, `ImageProxy.close()` |
| R5 | [ImageCapture reference](https://developer.android.com/reference/androidx/camera/core/ImageCapture) | `CAPTURE_MODE_MAXIMIZE_QUALITY`, JPEG quality defaults, `getResolutionInfo()`, takePicture |
| R6 | [Take photos with CameraX](https://developer.android.com/media/camera/camerax/take-photo) | File output, callbacks, executors |
| R7 | [FocusMeteringAction reference](https://developer.android.com/reference/androidx/camera/core/FocusMeteringAction) | AF/AE/AWB flags, default auto-cancel 5 s, locking behavior |
| R8 | [ExposureState reference](https://developer.android.com/reference/androidx/camera/core/ExposureState) | EV index/range/step, `isExposureCompensationSupported()` |
| R9 | [ResolutionStrategy reference](https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionStrategy) | Fallback rules, `HIGHEST_AVAILABLE_STRATEGY`, bound size |
| R10 | [Camera2Interop.Extender reference](https://developer.android.com/reference/androidx/camera/camera2/interop/Camera2Interop.Extender) | `setCaptureRequestOption`, overrides CameraX/3A risk |
| R11 | [Camera2CameraControl reference](https://developer.android.com/reference/androidx/camera/camera2/interop/Camera2CameraControl) | Options apply to repeating/single captures, override behavior |
| R12 | [Camera2CameraInfo reference](https://developer.android.com/reference/androidx/camera/camera2/interop/Camera2CameraInfo) | Reading `CameraCharacteristics` |
| R13 | [ExtensionsManager reference](https://developer.android.com/reference/androidx/camera/extensions/ExtensionsManager) | HDR/NIGHT/BOKEH modes, `isExtensionAvailable`, `isImageAnalysisSupported`, analysis restriction |
| R14 | [CameraDevice reference — `createCaptureSession`, guaranteed configurations](https://developer.android.com/reference/android/hardware/camera2/CameraDevice) | LEGACY/LIMITED/FULL stream-combination tables; failure modes |
| R15 | [CameraCharacteristics reference](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics) | `CONTROL_AE_AVAILABLE_MODES`, ISO/exposure ranges, AWB capability, manual modes |
| R16 | [CameraMetadata reference](https://developer.android.com/reference/android/hardware/camera2/CameraMetadata) | `CONTROL_AE_MODE_OFF` behavior, manual sensor/post-processing capabilities |
| R17 | [Image.Plane reference](https://developer.android.com/reference/android/media/Image.Plane) | `rowStride`, `pixelStride`, plane buffer semantics |
| R18 | [PowerManager reference](https://developer.android.com/reference/android/os/PowerManager) | Thermal status API 29, `getThermalHeadroom` API 30, listeners |
| R19 | [CameraX releases](https://developer.android.com/jetpack/androidx/releases/camera) | 1.6.2 stable, 1.7.0-rc02, 1.6 `SessionConfig`/`isSessionConfigSupported` |
| R20 | [Flutter Android platform views](https://docs.flutter.dev/platform-integration/android/platform-views) | Texture vs hybrid composition vs HCPP tradeoffs |
| R21 | [TextureRegistry.SurfaceProducer](https://api.flutter.dev/javadoc/io/flutter/view/TextureRegistry.SurfaceProducer.html) | `setSize`, `getSurface`, `setCallback`, `handlesCropAndRotation` |
| R22 | [FlutterActivity](https://api.flutter.dev/javadoc/io/flutter/embedding/android/FlutterActivity.html) | Implements `androidx.lifecycle.LifecycleOwner` |
| R23 | [camera_android_camerax Dart source](https://github.com/flutter/packages/blob/main/packages/camera/camera_android_camerax/lib/src/android_camera_camerax.dart) | Same resolution selector for Preview/ImageCapture/ImageAnalysis; preset mapping; AE lock; image stream copies; `unbindAll` |
| R24 | [camera CameraController source](https://github.com/flutter/packages/blob/main/packages/camera/camera/lib/src/camera_controller.dart) | `startImageStream` low/high guidance; EV/focus/zoom API surface |
| R25 | [camera_android_camerax pub.dev](https://pub.dev/packages/camera_android_camerax) | Android implementation/limitations, image streaming notes |
| R26 | [ML Kit Document Scanner for Android](https://developers.google.com/ml-kit/vision/doc-scanner/android) | Dynamic model/UI download, SDK-owned viewfinder/preview, 1.7 GB RAM |
| R27 | [CameraX FakeCamera source](https://android.googlesource.com/platform/frameworks/support/+/refs/heads/androidx-main/camera/camera-testing/src/main/java/androidx/camera/testing/fakes/FakeCamera.java) | `camera-testing` fake camera for session tests |
| R28 | [Camera2 capture sessions and requests](https://developer.android.com/media/camera/camera2/capture-sessions-requests) | Camera2 session/request model, manual key validation |
| R29 | [PreviewView reference](https://developer.android.com/reference/androidx/camera/view/PreviewView) | `ImplementationMode`, `getViewPort`, `getMeteringPointFactory` |

Local source references:

- `mobile/lib/capture.dart` — current `ResolutionPreset.high` + `CameraController` + `takePicture`.
- `mobile/lib/review.dart` — `onPhoto` import and post-capture `restore`/`enhance`.
- `mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt` — existing OpenCV crop/deskew/enhance pipeline.
- `mobile/android/app/src/release/AndroidManifest.xml` — no `INTERNET` / `ACCESS_NETWORK_STATE`.
- `mobile/android/app/build.gradle.kts` — `minSdk 29`, OpenCV 4.12.0, ONNX Runtime, ML Kit Deva OCR.
