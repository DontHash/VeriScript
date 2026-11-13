# Flutter `camera` 0.12.1 on Android — capabilities and limits for a document-scanning camera

**Research date:** 2026-11-07  
**Project:** `D:\Code\VectorScaling\mobile`  
**Resolved packages (from `pubspec.lock`):**

| Package | Version | Notes |
|---|---|---|
| `camera` | **0.12.1** | Project dependency is `camera: ^0.12.1` |
| `camera_android_camerax` | **0.7.5+1** | Endorsed Android implementation; CameraX **1.6.2** |
| `camera_platform_interface` | **2.15.0** | Defines enums and platform API |
| Flutter | 3.44.9 / Dart 3.12.2 | Local toolchain |

At the time of writing, pub.dev’s latest versions are `camera 0.12.2` and `camera_android_camerax 0.7.6+1`. The project lockfile pins the older pair above. A fresh `flutter pub upgrade` could move to 0.12.2/0.7.6+1; the API differences are noted where relevant.

> **Short answer:** the stock plugin gives you **EV compensation, AE lock, one-shot AF/AE point metering, AF lock, torch, zoom, orientation lock, high-resolution JPEG capture, and a YUV/NV21 analysis stream**. It does **not** give you manual ISO, shutter speed, white-balance lock, manual focus distance, continuous AF/AE at a chosen point, separate photo-vs-stream resolution, RAW/HDR/night processing, or a supported way to share the CameraX session with custom native code. The single `ResolutionPreset` is the biggest architectural blocker: it controls preview, image analysis, still capture, and video quality simultaneously.

---

## 0. Evidence legend

Local source abbreviations used below:

| Tag | Full path |
|---|---|
| `CC` | `D:\pub-cache\hosted\pub.dev\camera-0.12.1\lib\src\camera_controller.dart` |
| `CX` | `D:\pub-cache\hosted\pub.dev\camera_android_camerax-0.7.5+1\lib\src\android_camera_camerax.dart` |
| `PI` | `D:\pub-cache\hosted\pub.dev\camera_platform_interface-2.15.0\lib\src\platform_interface\camera_platform.dart` |
| `J-IA` | `D:\pub-cache\hosted\pub.dev\camera_android_camerax-0.7.5+1\android\src\main\java\io\flutter\plugins\camerax\ImageAnalysisProxyApi.java` |
| `J-PP` | `...\camerax\PlaneProxyProxyApi.java` |
| `J-IC` | `...\camerax\ImageCaptureProxyApi.java` |
| `J-CC` | `...\camerax\CameraControlProxyApi.java` |
| `J-C2` | `...\camerax\Camera2CameraControlProxyApi.java` |
| `J-PCP` | `...\camerax\ProcessCameraProviderProxyApi.java` |
| `J-REG` | `...\camerax\ProxyApiRegistrar.java` |

Upstream sources:

- CameraX `CameraControl` — <https://developer.android.com/reference/androidx/camera/core/CameraControl>
- CameraX `FocusMeteringAction` — <https://developer.android.com/reference/androidx/camera/core/FocusMeteringAction>
- CameraX `FocusMeteringAction.Builder` — <https://developer.android.com/reference/androidx/camera/core/FocusMeteringAction.Builder>
- CameraX `DisplayOrientedMeteringPointFactory` — <https://developer.android.com/reference/androidx/camera/core/DisplayOrientedMeteringPointFactory>
- CameraX `ImageCapture` — <https://developer.android.com/reference/androidx/camera/core/ImageCapture>
- CameraX `ImageAnalysis` — <https://developer.android.com/reference/androidx/camera/core/ImageAnalysis>
- CameraX `ResolutionSelector` — <https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionSelector>
- CameraX `ResolutionStrategy` — <https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionStrategy>
- CameraX architecture / use-case combinations — <https://developer.android.com/media/camera/camerax/architecture>
- CameraX coordinate transforms — <https://developer.android.com/media/camera/camerax/transform-output>
- Android `CaptureRequest.CONTROL_AE_LOCK` — <https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#CONTROL_AE_LOCK>
- Android `CONTROL_AE_COMPENSATION_RANGE` — <https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#CONTROL_AE_COMPENSATION_RANGE>
- Flutter camera issue tracker — <https://github.com/flutter/flutter/issues?q=is%3Aissue+label%3A%22p%3A+camera%22>

---

## 1. Exact Dart API surface relevant to document capture

`CameraController` is the app-facing API. The Android implementation is `camera_android_camerax`; the old `camera_android` (Camera2) implementation is **not** in this project.

### 1.1 Constructor-level settings

| Setting | Exact API | Evidence | Notes |
|---|---|---|---|
| Resolution preset | `CameraController(description, ResolutionPreset preset, { ... })` | `CC:247-262` | One preset controls preview, still capture, image analysis, and video quality. No separate photo/video preset. |
| Image stream format | Constructor parameter `ImageFormatGroup? imageFormatGroup` | `CC:247-262`, `CC:286-289` | **There is no `setImageFormatGroup()` method.** It is final and can only be set at construction. |
| Target FPS | Constructor `int? fps` | `CC:249-261`, `CX:393-396` | Passed to CameraX as a fixed `CONTROL_AE_TARGET_FPS_RANGE` for preview, analysis, and video. Not an image-stream-only option. |
| Audio | `enableAudio` | `CC:249-261` | No relevance to still capture; disable for document scanning. |

### 1.2 Methods

| Method | Exact signature | Evidence | Android behavior |
|---|---|---|---|
| `initialize()` | `Future<void> initialize()` | `CC:315-390` | Creates camera, binds Preview + ImageCapture + ImageAnalysis. |
| `takePicture()` | `Future<XFile> takePicture()` | `CC:465-482` | Guards concurrent captures; returns JPEG file path. |
| `startImageStream()` | `Future<void> startImageStream(onLatestImageAvailable onAvailable)` | `CC:501-527` | Subscribes to a frame stream; on CameraX this installs an `ImageAnalysis.Analyzer`. |
| `stopImageStream()` | `Future<void> stopImageStream()` | `CC:536-553` | Cancels subscription and clears the analyzer. |
| `setFlashMode()` | `Future<void> setFlashMode(FlashMode mode)` | `CC:800-807` | Off / auto / always / torch. |
| `setExposureMode()` | `Future<void> setExposureMode(ExposureMode mode)` | `CC:810-817` | Auto / locked. Android uses Camera2 interop `CONTROL_AE_LOCK`. |
| `setExposurePoint()` | `Future<void> setExposurePoint(Offset? point)` | `CC:823-836` | Normalized 0..1 point; one-shot AE region metering. |
| `getMinExposureOffset()` | `Future<double>` | `CC:839-846` | EV units. |
| `getMaxExposureOffset()` | `Future<double>` | `CC:849-856` | EV units. |
| `getExposureOffsetStepSize()` | `Future<double>` | `CC:861-868` | EV step; Android returns **-1** when unsupported. |
| `setExposureOffset()` | `Future<double> setExposureOffset(double offset)` | `CC:881-913` | EV units; checks range and rounds to step; returns rounded EV. |
| `setFocusMode()` | `Future<void> setFocusMode(FocusMode mode)` | `CC:935-942` | Auto / locked. |
| `setFocusPoint()` | `Future<void> setFocusPoint(Offset? point)` | `CC:958-970` | Normalized 0..1 point; one-shot AF region + AF scan. |
| `setZoomLevel()` | `Future<void> setZoomLevel(double zoom)` | `CC:709-716` | Ratio; CameraX `setZoomRatio`. |
| `getMinZoomLevel()` / `getMaxZoomLevel()` | `Future<double>` | `CC:685-702` | CameraX `ZoomState`. |
| `lockCaptureOrientation()` | `Future<void> lockCaptureOrientation([DeviceOrientation?])` | `CC:918-932` | Sets target rotation for capture/analysis; **not Preview** (see bug §8). |
| `unlockCaptureOrientation()` | `Future<void> unlockCaptureOrientation()` | `CC:945-952` | Clears lock flag. |
| `setJpegImageQuality()` | `Future<void> setJpegImageQuality(int quality)` | `CC:981-990` | 1..100; recreates `ImageCapture`; default is CameraX default (95). |
| `supportsImageStreaming()` | `bool` | `CC:992-993` | Always true on Android CameraX (`CX:1254-1255`). |
| `dispose()` | `Future<void> dispose()` | `CC:995-1008` | Unbinds all CameraX use cases. |

**There is no API for:** `setResolution`, `setCaptureMode`, `setWhiteBalanceMode`, `setIso`, `setShutterSpeed`, `setFocusDistance`, `setTorchStrength`, `setLowLightBoost`, `getActualCaptureResolution`, `getImageAnalysisResolution`, or `getCameraXInstance`.

### 1.3 Enums

| Enum | Values | Evidence |
|---|---|---|
| `ResolutionPreset` | `low`, `medium`, `high`, `veryHigh`, `ultraHigh`, `max` | `camera_platform_interface-2.15.0\lib\src\types\resolution_preset.dart` |
| `ExposureMode` | `auto`, `locked` | `...\types\exposure_mode.dart` |
| `FocusMode` | `auto`, `locked` | `...\types\focus_mode.dart` |
| `FlashMode` | `off`, `auto`, `always`, `torch` | `...\types\flash_mode.dart` |
| `ImageFormatGroup` | `unknown`, `yuv420`, `bgra8888`, `jpeg`, `nv21` | `...\types\image_format_group.dart` |

On Android CameraX, only **`unknown` (defaults to YUV), `yuv420`, and `nv21`** produce a usable stream. `jpeg` and `bgra8888` are ignored and fall back to YUV; see §5.

---

## 2. What is actually wired on Android/CameraX

### 2.1 Control matrix

| Control | Wired on Android? | Underlying mechanism | Evidence | Confidence |
|---|---|---|---|---|
| Exposure mode auto/lock | **Yes** | `Camera2CameraControl.addCaptureRequestOptions(CONTROL_AE_LOCK)` | `CX:802-820`; `J-C2:45-65` | High |
| EV compensation (read range/step) | **Yes** | `CameraInfo.exposureState` | `CX:618-628`, `CX:711-720` | High |
| EV compensation (set/sweep) | **Yes** | `CameraControl.setExposureCompensationIndex` | `CX:736-773`; `J-CC:145-170` | High |
| Manual ISO | **No** | Not exposed by plugin | No method in `CC`; only two Camera2 keys are wrapped (`CaptureRequestProxyApi.java`: `controlAELock`, `controlVideoStabilizationMode`) | High |
| Manual shutter speed | **No** | Not exposed by plugin | Same as above | High |
| Manual white balance / AWB lock | **No** | Not exposed by plugin | No `setWhiteBalanceMode` in `CC`; issue #108871 is open | High |
| Focus mode auto/lock | **Yes** | `FocusMeteringAction` with `FLAG_AF` and `disableAutoCancel` | `CX:639-705`, `CX:1681-1785` | High |
| AF point | **Yes, one-shot** | `FocusMeteringAction` at a `DisplayOrientedMeteringPointFactory` point | `CX:784-795`, `CX:1632-1658` | High |
| Continuously tracking AF at a chosen point | **No** | Action auto-cancels after 5 s by default; then continuous AF resumes without a point | CameraX `FocusMeteringAction` docs; `CX:1632-1658` | High |
| AE point | **Yes, one-shot** | `FocusMeteringAction` with `FLAG_AE` | `CX:603-614` | High |
| Continuous AE at a chosen point | **No** | Same 5 s auto-cancel; AE region is cleared | CameraX docs; plugin never sets `setAutoCancelDuration` | High |
| Manual focus distance / focus sweep | **No** | Not exposed | No API in `CC`; CameraX `FocusMeteringAction` only triggers AF | High |
| Flash off/auto/always | **Yes** | `ImageCapture.setFlashMode` | `CX:1058-1082`; `J-IC:73-86` | High |
| Torch during preview/stream | **Yes** | `CameraControl.enableTorch(true)` | `CX:1058-1082`, `CX:1806-1812` | High |
| Torch during `takePicture` | **Yes** | CameraX keeps torch on during photo capture; plugin sets ImageCapture flash off when torch is enabled | `CX:1022-1031`; CameraX `CameraControl.enableTorch` docs | High |
| Zoom ratio | **Yes** | `CameraControl.setZoomRatio` | `CX:824-867` | High |
| Lens selection / lens type | **Partial** | Multiple back cameras can appear in `availableCameras`, but `lensType` is not populated | `CX:292-334` constructs `CameraDescription(name, lensDirection, sensorOrientation)`; `CameraLensType` defaults to `unknown` | High |
| Resolution presets | **Yes** | CameraX `ResolutionSelector` | `CX:1543-1595` | High |
| Separate photo/stream resolution | **No** | Single selector for all use cases | `CX:391`, `CX:407-418`, `CX:469-473` | High |
| Change resolution after init | **No** | Must dispose/recreate controller | No setter in `CC`; `resolutionPreset` is getter-only (`CC:267-273`) | High |
| RAW / HDR / night / OEM extensions | **No** | Not exposed | No API in `CC`; `ImageCapture` is created with defaults (`CX:414-418`) | High |
| ZSL (zero shutter lag) | **No in 0.12.1** | Added in `camera 0.12.2` / `camerax 0.7.6` | `camera` changelog 0.12.2 | High |

### 2.2 Is EV compensation supported while previewing/streaming?

**Yes.** `setExposureOffset()` works while the preview and image stream are running; CameraX applies exposure compensation to the repeating request, which affects preview, analysis, and still capture.

A subtle but important point: **Android Camera2 explicitly honors exposure compensation even when AE lock is ON**:

> “When `CONTROL_AE_EXPOSURE_COMPENSATION` is changed, even if the AE lock is ON, the camera device will still adjust its exposure value.”

Source: <https://developer.android.com/reference/android/hardware/camera2/CaptureRequest#CONTROL_AE_LOCK>

This means a practical auto-exposure routine can be:

1. `setExposureMode(ExposureMode.auto)` and converge.
2. Sweep `setExposureOffset()` while measuring frame luminance.
3. `setExposureMode(ExposureMode.locked)` to freeze the chosen exposure.
4. Optionally fine-tune EV again — Camera2 says it still applies while locked.
5. `takePicture()`.
6. `setExposureMode(ExposureMode.auto)` to resume AE.

Two caveats:

- **AE lock availability is not checked.** `setExposureMode` writes `CONTROL_AE_LOCK` through Camera2 interop, catches `PlatformException`, logs it to the camera error stream, and still sets `_currentExposureMode = mode` (`CX:802-820`). On a device without `CONTROL_AE_LOCK_AVAILABLE`, the lock can silently fail.
- **Rapid EV changes can cancel each other.** CameraX documents that only one `setExposureCompensationIndex` runs at a time; a newer call cancels the previous future. The plugin returns the rounded value even when canceled (`CX:745-758`). Await each change and allow the AE pipeline to settle; don’t fire a 20-step sweep without pacing.

### 2.3 Practical EV range/step

The plugin returns exactly what CameraX/HAL reports:

- `getMinExposureOffset()` = `range.lower * step`
- `getMaxExposureOffset()` = `range.upper * step`
- `getExposureOffsetStepSize()` = `step`; **-1** if unsupported

Evidence: `CX:618-628`, `CX:711-720`.

Android’s compatibility rule for `CONTROL_AE_COMPENSATION_RANGE` says that on `LIMITED` and `FULL` devices, if compensation is supported, the range must reach **at least -2 EV and +2 EV**; `LEGACY` devices may support a smaller range. Source: <https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#CONTROL_AE_COMPENSATION_RANGE>.

The step is device-specific (`CONTROL_AE_COMPENSATION_STEP`). Common implementations use **1/3 EV (0.3333)** or **1/6 EV (0.1667)**; some use other rational steps. Do **not** hardcode ±2 EV or 1/3 EV; query at runtime, cache the values, and snap to the reported step. `CameraController.setExposureOffset` already rounds to the step (`CC:895-906`).

### 2.4 Manual ISO/shutter/white balance

Not exposed by the stock plugin. Even the `camera_android_camerax` public wrapper only defines two CaptureRequest keys:

- `CaptureRequest.controlAELock`
- `CaptureRequest.controlVideoStabilizationMode`

Evidence: `CaptureRequestProxyApi.java` in the CameraX Android source; `CX:886-893` uses the stabilization key. There is no `SENSOR_EXPOSURE_TIME`, `SENSOR_SENSITIVITY`, `CONTROL_AWB_LOCK`, or `CONTROL_AWB_MODE` key in the wrapper.

Therefore:

- **Manual ISO:** requires a native Camera2/CameraX layer.
- **Manual shutter speed:** requires a native layer.
- **White-balance lock or manual WB:** requires a native layer.
- Even with a native layer, check `REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR`; not every Android camera supports full manual control.

---

## 3. Focus/exposure point semantics (coordinates, one-shot vs continuous)

### 3.1 Coordinates

`setFocusPoint(Offset)` and `setExposurePoint(Offset)` accept values in **normalized 0..1** coordinates. The Dart layer rejects values outside `(0,0)..(1,1)` (`CC:823-826`, `CC:958-961`). The Android layer also validates (`CX:1639-1644`).

The point is converted with:

```dart
DisplayOrientedMeteringPointFactory(
  width: 1.0,
  height: 1.0,
  cameraInfo: cameraInfo!,
)
```

Evidence: `CX:1646-1651`.

CameraX documents this factory’s coordinate system as:

> “a coordinate left-top (0, 0) - right-bottom (width, height) which represents the full camera preview FOV in the display’s orientation.”

Source: <https://developer.android.com/reference/androidx/camera/core/DisplayOrientedMeteringPointFactory>

So:

- **Origin is top-left** of the full, un-cropped preview FOV in the current display orientation.
- The factory accounts for display rotation and front-camera mirroring.
- It does **not** account for Flutter widget scaling/cropping. If your `CameraPreview` is inside a `FittedBox`, `BoxFit.cover`, or a custom crop, you must transform tap coordinates back to the full preview FOV before calling the plugin. CameraX explicitly puts this responsibility on the app.
- The practical way to avoid mapping bugs is to make the preview widget exactly the preview aspect ratio (`CameraPreview` already does this with `AspectRatio`) and not crop it, or to implement the inverse crop transform in Dart.

### 3.2 One-shot vs continuous

The Android implementation uses a `FocusMeteringAction`:

- `setFocusPoint(point)` → `MeteringMode.af`; triggers an AF scan and locks AF at the point if successful.
- `setExposurePoint(point)` → `MeteringMode.ae`; updates the AE metering region; does not trigger AF.
- Both can be combined: the plugin keeps at most one AF point and one AE point in `currentFocusMeteringAction` (`CX:1681-1785`).
- **Default auto-cancel is 5 seconds.** CameraX’s `FocusMeteringAction.Builder` defaults to a 5 s auto-cancel; after that, `cancelFocusAndMetering()` is called, regions are cleared, and continuous AF resumes. The plugin does not shorten or lengthen this except by calling `disableAutoCancel()` when focus is locked.
- `setFocusPoint` sets `disableAutoCancel: _currentFocusMode == FocusMode.locked` (`CX:790-794`).
- `setExposurePoint` **also** uses `disableAutoCancel: _currentFocusMode == FocusMode.locked` (`CX:609-613`) — i.e. the AE point’s persistence is tied to **focus** lock, not exposure lock. This is an implementation quirk worth knowing.

Consequences:

| Scenario | Result |
|---|---|
| `setFocusPoint(p)` while `FocusMode.auto` | One AF scan + AF lock at `p` for ~5 s, then clears and returns to continuous AF. |
| `setFocusPoint(p)` then `setFocusMode(FocusMode.locked)` | Locks the current AF point indefinitely; `setFocusMode(FocusMode.auto)` unlocks and restores continuous AF. |
| `setFocusMode(FocusMode.locked)` without a point | Locks the center of the sensor area by default (`CX:670-679`). |
| `setExposurePoint(p)` while `FocusMode.auto` | AE region updated for ~5 s; AE remains automatic (not locked); then region clears. |
| `setExposurePoint(p)` while `FocusMode.locked` | AE region persists (auto-cancel disabled), but AE itself is still automatic unless you call `setExposureMode(locked)`. |
| `setExposureMode(ExposureMode.locked)` | Locks AE values independently of the focus/metering action (`CX:802-820`). |
| `setFocusMode(auto)` after locked | Rebuilds an action with the previous AF point, starts AF, then auto-cancels after 5 s; continuous AF resumes. |

**There is no “continuous AF at this point” and no “continuous AE weighted at this point” mode.** For document scanning, the useful pattern is: trigger AF at a text-rich point, measure sharpness, then lock AF; lock AE after measuring luminance; capture. If the document distance changes, you must re-trigger AF.

### 3.3 Success feedback is weak

- `CameraController.setFocusMode()` and `setFocusPoint()` return `Future<void>`; the platform may fail to acquire focus, but Dart updates `value.focusMode` regardless. The Android implementation returns early if `isFocusSuccessful` is false (`CX:691-697`), but the Dart layer does not see that.
- `setExposureMode()` catches platform exceptions and only logs them; it still updates `_currentExposureMode` (`CX:810-820`). The Dart `CameraValue.exposureMode` therefore reflects the requested value, not necessarily the effective one.
- `setZoomLevel()` catches `PlatformException` and only adds to the error stream (`CX:858-866`).
- `setFlashMode(torch)` catches torch-enable failures and only logs (`CX:1806-1812`).
- `CameraValue.exposurePointSupported` and `focusPointSupported` are hardcoded `true` in the Android initialization event (`CX:493-499`); they are not capability probes. Do not use them to decide whether metering regions work.

**Practical rule:** treat every control as “best effort” and verify via image statistics. Do not trust `CameraValue` or the absence of an exception.

---

## 4. Resolution behavior

### 4.1 Preset mapping under CameraX

The exact mapping is in `_getResolutionSelectorFromPreset` (`CX:1543-1595`):

| Preset | Target bound size | Aspect ratio strategy | Fallback | Notes |
|---|---|---|---|---|
| `low` | 320 × 240 | 4:3 | closest lower then higher | Enum docs say “~240p”; exact target is 320×240. |
| `medium` | 720 × 480 | none (default 4:3 preferred) | closest lower then higher | Not 640×480; CameraX may choose 640×480 4:3. |
| `high` | 1280 × 720 | 16:9 | closest lower then higher | This is what the project currently uses (`lib/capture.dart:44-48`). |
| `veryHigh` | 1920 × 1080 | 16:9 | closest lower then higher | ~2 MP; 16:9 crops a 4:3 sensor vertically. |
| `ultraHigh` | 3840 × 2160 | 16:9 | closest lower then higher | ~8.3 MP; 16:9 is bad for A4/Letter documents because it crops top/bottom. |
| `max` | highest available | default 4:3 (fallback auto) | highest strategy | Uses `PREFER_HIGHER_RESOLUTION_OVER_CAPTURE_RATE`. No bound size. |

Evidence for `max`:

```dart
resolutionStrategy = ResolutionStrategy.highestAvailableStrategy;
return ResolutionSelector(
  resolutionStrategy: resolutionStrategy,
  allowedResolutionMode:
      ResolutionSelectorAllowedResolutionMode.preferHigherResolutionOverCaptureRate,
);
```

`CX:1565-1572`.

### 4.2 What `ResolutionPreset.max` actually gives on modern phones

It gives the **highest output size CameraX can bind for each use case**, subject to the camera pipeline and the combination of bound use cases. It is **not** a guarantee of “full sensor resolution.”

Critical limitation from CameraX’s `ResolutionSelector` docs:

- `PREFER_HIGHER_RESOLUTION_OVER_CAPTURE_RATE` considers `StreamConfigurationMap.getOutputSizes()` and `getHighResolutionOutputSizes()`.
- It **does not** consider `SCALER_STREAM_CONFIGURATION_MAP_MAXIMUM_RESOLUTION`, which is where Android 12+ exposes “maximum resolution sensor pixel” modes (e.g. 108 MP / 200 MP modes).
- Therefore a 108 MP or 200 MP phone will usually **not** return a 108/200 MP JPEG through this path; it will return the largest normal or “high-resolution” JPEG size, commonly **12 MP (4000×3000)**, sometimes 48/50 MP if the HAL exposes that as a high-resolution output size.
- The `max` strategy is applied to **Preview, ImageCapture, and ImageAnalysis alike** (`CX:407-418`, `CX:469-473`). It may select a high-resolution preview/analysis stream too, which is expensive; CameraX may reduce it based on the device’s supported combination, but the plugin gives you no control or guarantee.

Sources:

- <https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionSelector#PREFER_HIGHER_RESOLUTION_OVER_CAPTURE_RATE>
- <https://developer.android.com/reference/androidx/camera/core/resolutionselector/ResolutionStrategy#HIGHEST_AVAILABLE_STRATEGY>

**Practical recommendation for documents:** use `ResolutionPreset.max` (default 4:3 preference) rather than `ultraHigh` (forced 16:9). 12 MP is sufficient for A4 at 300 dpi (~8.7 MP); 16:9 crops the page and loses text near the top/bottom.

### 4.3 Does `takePicture()` capture at the preview resolution or full sensor?

- `ImageCapture` is constructed with the **same** `ResolutionSelector` as Preview and ImageAnalysis (`CX:414-418`).
- CameraX selects the actual `ImageCapture` resolution independently of the Preview use case. The reported `CameraValue.previewSize` comes from `preview.getResolutionInfo()` only (`CX:490-505`); it is **not** the photo resolution.
- The plugin does **not** expose `imageCapture.getResolutionInfo()`. To know the actual photo size, read the JPEG dimensions after capture.
- `takePicture()` captures at the **configured preset’s selected ImageCapture resolution**, not necessarily the preview resolution, and not full sensor.
- Capture mode is CameraX’s default (`MINIMIZE_LATENCY`), and JPEG quality defaults to 95. The plugin never calls `setCaptureMode(CAPTURE_MODE_MAXIMIZE_QUALITY)`. `setJpegImageQuality(100)` can raise JPEG quality, but it does not change capture mode or resolution.
- No RAW, HDR, night mode, or OEM extensions. The stock plugin produces a single-frame JPEG.

### 4.4 Does `startImageStream` force a lower resolution?

**No explicit force.** `ImageAnalysis` gets the same `_presetResolutionSelector` (`CX:469-473`). CameraX may choose a lower actual size for analysis because of hardware limits or the combination of bound use cases, but the plugin does not request a lower stream resolution.

Practical implications:

- With `ResolutionPreset.high` (720p), the stream is ~720p and the photo is ~720p — too low for dense document OCR.
- With `ResolutionPreset.max` (e.g. 12 MP), the analysis stream may be 12 MP if CameraX selects it; that is far too much data for a Dart-side analyzer (see §5).
- There is **no API** to say “preview/analysis at 720p, photo at 12 MP.” This is a long-standing feature request: [#46082](https://github.com/flutter/flutter/issues/46082), [#130958](https://github.com/flutter/flutter/issues/130958), [#194208](https://github.com/flutter/flutter/issues/194208).

### 4.5 Can you change resolution after initialization?

**No.**

- `resolutionPreset` is getter-only (`CC:267-273`).
- `CameraController` has no `setResolution`.
- `setDescription()` disposes and re-initializes with the same `mediaSettings` (same preset) (`CC:448-460`).
- `setJpegImageQuality()` recreates only `ImageCapture`, with the same resolution selector (`CX:1091-1106`).
- To change resolution, dispose the controller and create a new one. That reopens the camera, resets AE/AF/AWB/torch/zoom, and causes a visible preview restart.

**Workaround for this app:** the capture screen already knows `recordMode` (`lib/capture.dart:6-18`); instantiate `ResolutionPreset.max` for photo mode and keep `ResolutionPreset.high` for video mode. That avoids changing resolution at runtime and avoids forcing 10-minute book videos to the highest quality.

---

## 5. Android image stream details

### 5.1 Format

CameraX `ImageAnalysis` is configured with an output format:

- `ImageFormatGroup.yuv420` → `OUTPUT_IMAGE_FORMAT_YUV_420_888` (1)
- `ImageFormatGroup.nv21` → `OUTPUT_IMAGE_FORMAT_NV21` (3)
- Anything else (`unknown`, `jpeg`, `bgra8888`) → `null`, which leaves CameraX’s default YUV_420_888.

Evidence: `CX:1415-1424`, `CX:466-473`.

Therefore:

- **YUV420_888 is the normal stream.** It has **three planes** (Y, U, V), each a separate `Uint8List`.
- **NV21 is available** and produces **one plane** containing Y followed by interleaved VU. The plugin converts the three CameraX planes into one NV21 buffer (`CX:1326-1344`; `ImageProxyUtils.planesToNV21`).
- **JPEG and BGRA streams are not supported** on Android CameraX through this plugin. They fall back to YUV.
- README/comment discrepancy: the README and a code comment say that NV21-initialized streams still report `ImageFormatGroup.yuv420` while the data is NV21 (`CX:1266-1268`, README “Configuring NV21 image format”). The current implementation actually overwrites the reported group to `nv21` when NV21 was requested (`CX:1360-1366`). Treat the reported `format.group` as advisory and check the data layout/plane count at runtime.

### 5.2 Planes, strides, and “concatenated” bytes

For YUV420:

- `CameraImage.planes.length == 3`.
- `plane.bytes` is a copy of that plane’s `ByteBuffer`.
- `plane.bytesPerRow` = CameraX `rowStride`.
- `plane.bytesPerPixel` = CameraX `pixelStride`.
- On Android, `plane.width` and `plane.height` are **null** (the `CameraImagePlane` is constructed without them).
- U and V planes may be interleaved with `pixelStride == 2`; do not assume `bytes.length == width * height` for chroma. Use `rowStride`, `pixelStride`, and the image width/height.

Evidence: `CX:1346-1354`; `camera-0.12.1\lib\src\camera_image.dart` `Plane` fields; `camera_platform_interface-2.15.0\lib\src\types\camera_image_data.dart`.

For NV21:

- `planes.length == 1`.
- `bytesPerRow = width`, `bytesPerPixel = 1`.
- Data is Y (width×height) followed by VU (width×height/2).
- The plugin’s conversion allocates a new `byte[]` and copies row by row to remove padding (`ImageProxyUtils.planesToNV21`).

**Bytes are not concatenated for YUV420.** They are three separate buffers. For NV21 they are concatenated into one buffer.

### 5.3 Resolution and FPS

- Resolution: same `ResolutionSelector` as the rest of the session (`CX:469-473`); actual size is whatever CameraX picks. Read `CameraImage.width/height` on the first frame; there is no API to query it beforehand.
- FPS: no per-stream option. `startImageStream` accepts only a callback; `CameraImageStreamOptions` is an empty class and is ignored (`CC:500-527`, `camera_platform_interface` `CameraImageStreamOptions`).
- The only FPS control is the `fps` constructor parameter, which sets a fixed target range for Preview, ImageAnalysis, and VideoCapture (`CX:393-396`; `ImageAnalysisProxyApi.java` applies `CONTROL_AE_TARGET_FPS_RANGE`). It is not a stream-only setting and is not guaranteed to be honored exactly.
- Default behavior when `fps` is null is CameraX’s default for the use case, typically around 30 fps for preview/analysis at moderate resolutions, lower at high resolution.

### 5.4 Memory copies and threading

This is the most important implementation detail for real-time analysis.

The per-frame path is:

1. CameraX calls the analyzer on **the Android main executor**:

   ```java
   pigeonInstance.setAnalyzer(
       ContextCompat.getMainExecutor(getPigeonRegistrar().getContext()), analyzer);
   ```

   Evidence: `J-IA:68-75`.

2. The Dart analyzer callback calls `imageProxy.getPlanes()` (a Pigeon call back to the host).
3. For each plane, the host copies the `ByteBuffer` into a new `byte[]`:

   ```java
   byte[] bytes = new byte[buffer.remaining()];
   buffer.get(bytes, 0, bytes.length);
   return bytes;
   ```

   Evidence: `J-PP:23-30`.

4. Pigeon/StandardMessageCodec sends the `Uint8List` to Dart (another copy).
5. The plugin adds the `CameraImageData` to a `StreamController` and closes the `ImageProxy` (`CX:1375-1388`).
6. The `StreamController` is a normal unbounded controller; `add()` does not wait for the Dart listener to finish. If analysis is slower than frame production, frames queue in Dart memory. CameraX’s default backpressure is `STRATEGY_KEEP_ONLY_LATEST`, but because the plugin closes the `ImageProxy` immediately after `add()`, CameraX considers the analyzer finished and keeps delivering; the backlog moves into the Dart stream queue.

For NV21, there is an additional full-frame allocation and copy in `ImageProxyUtils.planesToNV21` before step 3.

**Data volume** (raw YUV420 = 1.5 bytes/pixel; one host copy; the plugin makes at least two copies including the channel transfer):

| Resolution | Raw frame | At 30 fps |
|---|---:|---:|
| 320×240 | 0.115 MB | 3.5 MB/s |
| 720×480 | 0.518 MB | 15.5 MB/s |
| 1280×720 | 1.38 MB | 41.5 MB/s |
| 1920×1080 | 3.11 MB | 93.3 MB/s |
| 3840×2160 | 12.44 MB | 373 MB/s |
| 4000×3000 (12 MP) | 18.0 MB | 540 MB/s |

This is why `ResolutionPreset.max` + `startImageStream` is not a viable continuous pipeline on most devices. Even if the actual analysis resolution is capped lower by CameraX, the plugin gives you no guarantee; measure the first frame.

### 5.5 Does analysis while streaming block `takePicture()`?

**Not by an explicit lock, but yes in practice on many devices.**

- CameraX can run `Preview + ImageCapture + ImageAnalysis` concurrently; the plugin binds all three at initialization (`CX:478-482`) and does not stop analysis during `takePicture`.
- However:
  - The analyzer runs on the **main thread** (`J-IA:68-75`), competing with UI rendering and the `takePicture` callback (which is also dispatched on the main executor, `J-IC:90-110`).
  - Every frame copies all planes and crosses the platform channel; at 1080p/4K this can saturate the main thread.
  - The Dart stream has no backpressure; if your Dart processing is slower than frame arrival, the queue grows and memory pressure increases.
  - At high resolutions, binding all three use cases may force CameraX to choose lower resolutions for one or more use cases, or fail to configure on constrained devices. CameraX explicitly warns that “depending on camera capability, some cameras may support the combination at lower resolution modes, but can not support the same combination at some higher resolutions.” Source: <https://developer.android.com/media/camera/camerax/architecture>
- Known issues:
  - Intermittent black JPEGs at `veryHigh`/`ultraHigh` on many devices: [#195584](https://github.com/flutter/flutter/issues/195584).
  - `takePicture()` hangs after `pausePreview()` with a flash mode set on some devices: [#176288](https://github.com/flutter/flutter/issues/176288).
  - Flash mode is re-applied on every capture, adding ~250–300 ms: [#195468](https://github.com/flutter/flutter/issues/195468).
  - Image stream can stall on some devices: [#114862](https://github.com/flutter/flutter/issues/114862); a previous memory-leak-related stream stop was fixed in the CameraX implementation (issue [#152763](https://github.com/flutter/flutter/issues/152763) closed; the plugin now shortens the native InstanceManager cleanup interval for analysis, `J-IA:68-72`).

### 5.6 Starting/stopping the stream around capture

There is no “pause stream” API. `stopImageStream()` cancels the subscription, which calls `imageAnalysis.clearAnalyzer()` (`CX:1408-1410`). It does **not** unbind the `ImageAnalysis` use case. Restarting calls `_configureImageAnalysis`, which re-binds if needed and sets the analyzer again (`CX:1307-1388`).

Practical consequences:

- Calling `stopImageStream()` before every `takePicture()` and `startImageStream()` afterward is expensive: it tears down/rebuilds the analyzer, may reconfigure the CameraX session, and can cause a visible preview glitch.
- `startImageStream()` sets `value.isStreamingImages = true` immediately, but the actual analyzer setup happens asynchronously in the stream’s `onListen` (`CX:1276-1280`). A failure during `_configureImageAnalysis` is not surfaced through the `startImageStream` future.
- If you need a clean capture, prefer to keep the stream running but make the analyzer cheap, or stop the stream once and accept the glitch. Do not pause/resume the preview around capture (#176288).

---

## 6. Flash vs torch

### 6.1 Mapping

| Dart `FlashMode` | CameraX action | Evidence |
|---|---|---|
| `off` | `ImageCapture.FLASH_MODE_OFF` | `CX:1065-1067`; `J-IC:73-86` |
| `auto` | `ImageCapture.FLASH_MODE_AUTO` | `CX:1068-1069` |
| `always` | `ImageCapture.FLASH_MODE_ON` | `CX:1070-1071` |
| `torch` | `CameraControl.enableTorch(true)`, `_currentFlashMode = null` | `CX:1072-1081` |

Switching away from `torch` disables the torch first (`CX:1058-1063`). Setting `torch` again is a no-op if already enabled.

### 6.2 Torch during preview/stream and capture

- Torch is a **continuous** light: it stays on during preview, image analysis, and still capture.
- CameraX documents: “When the torch is enabled, the torch will remain enabled during photo capture regardless of the flashMode setting.” Source: <https://developer.android.com/reference/androidx/camera/core/CameraControl#enableTorch(boolean)>
- The plugin implements this by setting `ImageCapture` flash to `OFF` when torch is enabled (`CX:1027-1030`), so the capture does not try to double-fire the flash.

### 6.3 Does `FlashMode.always` fire the flash on `takePicture`?

Yes, on devices with a flash unit. `ImageCapture.FLASH_MODE_ON` is “always flash”; CameraX fires it for the still capture. Caveats:

- Some `LEGACY` devices have broken auto-flash; CameraX disables auto-flash internally on known-bad devices. `always` is less affected.
- Flash timing can be slow; older issue [#84957](https://github.com/flutter/flutter/issues/84957) reports the flash firing before/after the capture on some devices.
- On some devices the flash LED remains lit after capture ([#97501](https://github.com/flutter/flutter/issues/97501)); toggling torch on/off or disposing the controller is a workaround.
- Flash is usually undesirable for document capture: it creates a specular hotspot and uneven illumination. A continuous torch (diffused) is generally better, or no flash at all.

### 6.4 Constraints and silent failures

- If the camera has no flash unit, `enableTorch` fails; the plugin catches and logs it, and `CameraValue.flashMode` still says `torch` (`CX:1806-1812`). There is no `hasFlashUnit` API.
- Torch and low-light boost are mutually exclusive in CameraX; the plugin does not expose low-light boost, so this only matters if you add native code.
- Torch can thermally throttle or shut off on long sessions; monitor frame brightness.

---

## 7. Camera lifecycle, ownership, and coexistence

### 7.1 Who owns the camera

- `camera_android_camerax` obtains the process-wide `ProcessCameraProvider` singleton via `ProcessCameraProvider.getInstance()` (`CX:297`, `CX:403`; `J-PCP:46-60`).
- At camera creation it calls `unawaited(processCameraProvider!.unbindAll())` (`CX:404`).
- At dispose it calls `processCameraProvider?.unbindAll()` (`CX:519`).
- It binds `Preview + ImageCapture + ImageAnalysis` to the current Activity lifecycle (`CX:478-482`; lifecycle owner from `J-REG:109-116` / `J-PCP:64-72`).

### 7.2 Can plugin and custom CameraX code coexist?

**Not safely.**

- The `ProcessCameraProvider` is a per-process singleton, so a custom CameraX layer would share the same provider.
- The plugin calls `unbindAll()` when it creates or disposes a camera. That will unbind **your** custom use cases too.
- CameraX allows one active camera at a time; binding a different camera selector or adding/removing use cases can reconfigure the session and reset 3A/zoom.
- If custom code binds use cases to the same lifecycle owner/camera and does not call `unbindAll`, they may run concurrently with the plugin’s use cases, but you have no supported handle on the plugin’s `ImageCapture`/`ImageAnalysis`/`Preview`, and the plugin can unbind everything at any time.

### 7.3 Can plugin and custom Camera2 code coexist?

**No.** Android camera devices are exclusive:

- CameraX is built on Camera2. Opening the same camera ID with a separate `CameraManager.openCamera()` while CameraX holds it will conflict (`CAMERA_IN_USE`, `MAX_CAMERAS_IN_USE`, or eviction depending on client priority).
- The plugin maps CameraX `CameraStateErrorCode.cameraInUse` to “The camera was already in use, possibly by a higher-priority camera client” (`CX:1472-1501`).
- You cannot have the stock plugin and a custom Camera2 session on the same camera simultaneously.

### 7.4 Does the plugin expose the CameraX instance?

**Not through `CameraController`.** There is no getter for `Camera`, `CameraControl`, `ProcessCameraProvider`, `ImageCapture`, or `ImageAnalysis` on `CameraController`.

However, technically:

- `CameraPlatform.instance` is a global singleton, and on Android it is an `AndroidCameraCameraX`.
- `package:camera_android_camerax/camera_android_camerax.dart` exports `AndroidCameraCameraX`, but **does not** export the generated `camerax_library` wrapper classes. To name their types you would have to import `package:camera_android_camerax/src/camerax_library.dart` (a `src/` import, explicitly outside the public API).
- `AndroidCameraCameraX` has public fields: `processCameraProvider`, `camera`, `cameraControl`, `imageCapture`, `imageAnalysis`, `preview`. They are annotated `@visibleForTesting` (lint only, not access control). See `CX:44-96`.
- You can cast:

  ```dart
  final platform = CameraPlatform.instance as AndroidCameraCameraX;
  final camera = platform.camera; // public but @visibleForTesting
  ```

This is **unsupported, version-fragile, and not a substitute for a native layer**. It may let you inspect or replace use cases, but the plugin’s `dispose()`/`createCamera()` still call `unbindAll()`, and the public field names can change between patch releases.

Also, even if you get `cameraControl`, the Dart CameraX wrapper only exposes two Camera2 capture-request keys (`CONTROL_AE_LOCK`, `CONTROL_VIDEO_STABILIZATION_MODE`). It does **not** give you ISO/shutter/WB keys. You would need to fork/patch the Pigeon API or write native code.

---

## 8. Known open bugs/limitations relevant to a document scanner

Status checked 2026-11-07. “Open” means open in `flutter/flutter` at that time.

| Issue | Status | Impact | Evidence / notes |
|---|---|---|---|
| [#195584](https://github.com/flutter/flutter/issues/195584) `takePicture()` intermittently returns a fully black JPEG while preview looks normal | **Open** | **High.** High-res capture (`veryHigh`/`ultraHigh`, long-lived controller) can silently produce black JPEGs on many Android devices. Reported on `camera 0.12.1` + `camerax 0.7.5+1` (same as this project), even on a screen that uses no flash, exposure, focus, or image-stream calls. | No root cause yet; reported on Samsung/Xiaomi/Honor/Motorola/Realme/OPPO/OnePlus. File is black as written by the plugin. Validate every capture and retake. |
| [#195468](https://github.com/flutter/flutter/issues/195468) `takePicture` sets an unchanged flash mode on every capture | **Open, P1** | **Medium–High.** Adds ~250–300 ms per capture whenever `setFlashMode` has been called (including `off`). Torch mode also calls `setFlashMode(off)` on each capture. | `CX:1025-1031` unconditionally re-applies; issue measured on `camerax 0.7.6`, same code shape in 0.7.5+1. Patch/fork or accept latency. |
| [#194524](https://github.com/flutter/flutter/issues/194524) Preview use case does not set/update target rotation | **Open, P1** | **High** for preview/capture alignment after orientation changes. `lockCaptureOrientation` updates ImageCapture/ImageAnalysis/VideoCapture but not Preview. | `CX:569-584`; `Preview` is created without `targetRotation` (`CX:407-410`). Lock app orientation before init or recreate on rotation. |
| [#181770](https://github.com/flutter/flutter/issues/181770) Support image stream and preview alignment for scanner overlays | **Open, P2** | **High** if you draw document boundaries/quality overlays. No `cropRect` or `rotationDegrees` exposed to Dart; preview and analysis may have different FOV/crop. | CameraX `ImageProxy.cropRect`/`ImageInfo.rotationDegrees` are not surfaced by the plugin. Custom layer with `UseCaseGroup` + `ViewPort` is the proper fix. |
| [#46082](https://github.com/flutter/flutter/issues/46082) Allow different resolution for `takePicture` and `imageStream` | **Open since 2019** | **High.** Cannot do low-res real-time analysis + high-res photo with stock plugin. | Single `ResolutionPreset`; `CX:391`, `CX:407-418`, `CX:469-473`. |
| [#130958](https://github.com/flutter/flutter/issues/130958) / [#194208](https://github.com/flutter/flutter/issues/194208) Separate preview/photo/video resolutions | **Open** | **High.** Same root cause; affects video vs photo too. | Single preset for all use cases; current app uses `high` for both photo and video (`lib/capture.dart:44-48`). |
| [#195466](https://github.com/flutter/flutter/issues/195466) ZSL has no effect with `ResolutionPreset.max` | **Open, P2** | Medium (only if upgrading to 0.12.2+). `max` sets `preferHigherResolutionOverCaptureRate`, which disables ZSL. | `camera_android_camerax 0.7.6`; not exposed in 0.12.1 anyway. |
| [#176288](https://github.com/flutter/flutter/issues/176288) `takePicture()` not working after `pausePreview()` | **Open, P3** | Medium. Avoid pause/resume around capture; hang on some devices when flash mode is set. | `pausePreview` unbinds Preview (`CX:933-938`), then capture + flash can deadlock. |
| [#176772](https://github.com/flutter/flutter/issues/176772) Photos have no EXIF `ExposureTime` on Honor devices | **Open, P2** | Medium. Don’t rely on EXIF exposure/ISO for quality control. | `CameraImage` metadata is also null on Android (see §5.7). |
| [#114862](https://github.com/flutter/flutter/issues/114862) `startImageStream` gets stuck on some devices | **Open, P2** | Medium. Device-specific preview freeze on Xiaomi 10 Ultra etc. | Old report, but streaming still has main-thread/backpressure risks. Test target devices for long sessions. |
| [#97501](https://github.com/flutter/flutter/issues/97501) Flash remains lit after taking a picture | **Open, P3** | Medium if using flash. LED can stay on like a torch. | Toggling torch/off or disposing controller is a workaround; test. |
| [#84957](https://github.com/flutter/flutter/issues/84957) Taking pictures is too slow on some devices | **Open, P3** | Medium. 0.5–1.5 s captures; flash timing can miss. | Combined with #195468, capture latency can be ~0.8–1.1 s. |
| [#154132](https://github.com/flutter/flutter/issues/154132) Example app’s `setExposureOffset` is not robust | **Open, P3** | Low–Medium. Older versions returned an index instead of EV; 0.7.5+1 changelog says the return value was fixed. | Verify the returned value on your device; cache min/max/step. |
| [#148521](https://github.com/flutter/flutter/issues/148521) Exposure compensation cancellation/freeze | **Closed** | Fixed in `camerax 0.7.5+1` (“Fix exposure offset slider freezing camera preview and fix setExposureOffset return value”). | Project lock includes the fix; older 0.7.x may still exhibit it. |
| [#187782](https://github.com/flutter/flutter/issues/187782) `setFocusMode(auto)` throws `StateError` | **Closed** | Fixed in `camerax 0.7.4+1`. | Project lock includes the fix. |
| [#152763](https://github.com/flutter/flutter/issues/152763) Image stream randomly stopping | **Closed** | Historical memory-leak/InstanceManager issue; current code shortens cleanup interval for analysis. | Still monitor long streams; see `J-IA:68-72`. |
| [#112614](https://github.com/flutter/flutter/issues/112614) Support ISO/shutter control | **Open proposal** | **High** if manual exposure is required. | Confirms no stock API. |
| [#108871](https://github.com/flutter/flutter/issues/108871) White balance lock | **Open proposal** | Medium for consistent page color. | No stock API. |
| [#91247](https://github.com/flutter/flutter/issues/91247) Support choosing lenses | **Open** | Medium. `lensType` is not populated; multiple back cameras may be listed but hard to identify. | `CX:292-334`. |

### 8.1 Additional state/behavioral quirks

- **`exposurePointSupported`/`focusPointSupported` are always true** after init (`CX:493-499`). They are not device capability checks.
- **`CameraValue.focusMode`/`exposureMode` can diverge from the hardware** because platform failures are swallowed (`CX:691-697`, `CX:810-820`).
- **`takePicture()` validates only “not already taking a picture”**, not stream state, flash readiness, or output validity (`CC:465-482`).
- **`startImageStream()` sets `isStreamingImages` before the analyzer is installed**; a setup failure is asynchronous (`CX:1276-1280`).
- **`setJpegImageQuality()` unbinds/recreates `ImageCapture`**; the next `takePicture()` rebinds it, which can reconfigure the session and disturb preview/AE/AF (`CX:1091-1106`).
- **`setExposureMode(locked)` uses Camera2 interop**, which CameraX warns can override internal CameraX configuration and interfere with 3A routines. Source: <https://developer.android.com/reference/androidx/camera/core/CameraControl#applyInteropAsync(androidx.camera.core.InteropConfigurator)>. It is the only way to lock AE with the stock plugin, so use it but validate.

---

## 9. What automatic tuning can we reliably build with the stock plugin?

### 9.1 Reliable / workable

| Capability | Recipe | Caveats |
|---|---|---|
| **EV sweep** | Cache `getMin/MaxExposureOffset` and `getExposureOffsetStepSize`; sweep in 1–3 step increments; measure Y-plane mean/histogram; settle 2–5 frames between steps. | Range/step device-specific; rapid changes cancel; preview may glitch briefly. |
| **AE lock** | After convergence, `setExposureMode(ExposureMode.locked)`; capture; `setExposureMode(ExposureMode.auto)` afterward. | Lock support not checked; failure is silent. |
| **EV adjust while locked** | `setExposureOffset()` still applies under AE lock per Camera2 docs. | Validate on target devices; CameraX interop may behave differently by HAL. |
| **AF at a point** | `setFocusPoint(Offset)` at a text-rich area; optionally `setFocusMode(FocusMode.locked)` to hold it. | One-shot; 5 s auto-cancel unless focus locked; no success feedback; no continuous tracking. |
| **AF lock** | `setFocusMode(FocusMode.locked)` after AF converges; `setFocusMode(FocusMode.auto)` to release. | Locks center if no point; fixed focus while locked; re-trigger if distance changes. |
| **Torch** | `setFlashMode(FlashMode.torch)` once; keep on during preview/stream/capture; `setFlashMode(FlashMode.off)` to turn off. | No flash-unit detection; failure silent; thermal; may add capture latency via repeated `setFlashMode(off)` (#195468). |
| **Flash capture** | `setFlashMode(FlashMode.always)` before capture; `off` after. | Adds per-capture latency; glare; flash may stay lit on some devices. |
| **Zoom** | `getMin/MaxZoomLevel`; `setZoomLevel(ratio)` during preview/stream. | Digital; no lens selection; `lensType` unknown; failure silent. |
| **High-res JPEG** | Use `ResolutionPreset.max` in photo mode; validate JPEG dimensions/luminance; retry on black/empty. | Actual size device-dependent; not full sensor; no HDR/night; black-JPEG bug. |
| **Capture orientation** | `lockCaptureOrientation(DeviceOrientation.portraitUp)` after init. | Works for capture/analysis/video, **not Preview** (#194524); lock app orientation too. |
| **JPEG quality** | `setJpegImageQuality(100)` for text detail. | Recreates ImageCapture; larger files; still min-latency capture mode. |

### 9.2 Not reliable / not possible with stock plugin

| Requirement | Why | What it would take |
|---|---|---|
| Low-res real-time analysis + high-res still capture | Single `ResolutionPreset` for Preview/ImageAnalysis/ImageCapture. | Custom CameraX layer with separate `ResolutionSelector`s. |
| Manual ISO / shutter speed | Not exposed; no Camera2 keys wrapped. | Native Camera2/CameraX interop; check `MANUAL_SENSOR`. |
| White-balance lock / manual WB | Not exposed. | Native `CONTROL_AWB_LOCK` / `CONTROL_AWB_MODE`. |
| Manual focus distance / focus sweep | Not exposed; only AF point triggers. | Native `LENS_FOCUS_DISTANCE` on supported devices. |
| Continuous AF/AE at a chosen point | FocusMeteringAction auto-cancels after 5 s; no continuous mode. | Native repeating AF/AE regions or custom CameraX `CameraControl` loop. |
| Focus/AE success feedback | Platform failures swallowed; no callbacks. | Native Camera2 capture-result callbacks (`CONTROL_AF_STATE`, `CONTROL_AE_STATE`) or image-metric inference. |
| Precise preview/stream overlay alignment | No `cropRect`/`rotationDegrees`; preview and analysis may differ. | CameraX `UseCaseGroup` + `ViewPort`, expose crop/rotation. |
| Full sensor 50/108/200 MP capture | CameraX excludes max-resolution sensor mode. | Camera2 max-resolution session; device-specific. |
| RAW / HDR / night / OEM processing | Not exposed. | CameraX Extensions or Camera2; significant work. |
| Guaranteed valid high-res capture | Black-JPEG bug #195584. | Validation + retry; possibly custom layer. |
| Camera session sharing with custom code | Plugin calls `unbindAll()`; Camera2 exclusive. | One owner: custom layer replaces plugin. |

---

## 10. Bottom-line recommendation

### 10.1 If the goal is “better document photos with simple auto-tuning”

The stock plugin is sufficient for a **guided capture** experience:

1. **Change photo mode from `ResolutionPreset.high` to `ResolutionPreset.max`.** The current app captures ~720p photos (`lib/capture.dart:44-48`), which is marginal for OCR of dense text. `max` gives the largest 4:3 JPEG CameraX can bind, commonly 12 MP and often enough for A4 at 300 dpi.
2. **Keep `ResolutionPreset.high` for the video/book-recording mode.** `ResolutionPreset` also controls video quality; using `max` in video mode would force the highest video quality and huge 10-minute files. The existing `recordMode` flag makes it easy to choose per screen.
3. **Add an EV/AE tuning loop** using `getMin/MaxExposureOffset`, `getExposureOffsetStepSize`, `setExposureOffset`, and `setExposureMode(locked)`. Measure luminance from a few captured frames or from a low-frequency stream; settle and lock.
4. **Use torch, not flash, for documents.** A continuous diffused torch gives stable illumination and avoids specular flash hotspots. Turn it off for glossy paper if it causes glare.
5. **Trigger AF at a text-rich point and lock it.** `setFocusPoint` then `setFocusMode(FocusMode.locked)`. Re-trigger when the user moves the camera or changes zoom.
6. **Validate every capture.** Check file size, JPEG decode, mean luminance, and sharpness; retake once or twice. This is mandatory because of #195584 and the empty-file-on-abort behavior.
7. **Do not pause preview around capture, and do not call `setFlashMode` repeatedly.** Avoid #176288 and reduce #195468 latency.

This will produce a solid “auto-exposure + torch + autofocus + high-res” document camera, but it will **not** give real-time low-resolution preview analysis alongside high-resolution capture.

### 10.2 If the goal is a true auto-tuning document camera with real-time preview analysis

**You need a custom native camera layer.** The decisive blockers are:

1. **Single resolution preset** — no way to run ImageAnalysis at 720p while ImageCapture runs at 12 MP. This is the core architectural mismatch.
2. **No manual ISO/shutter/WB** — EV + AE lock is the only exposure control; low-light motion blur/noise cannot be bounded.
3. **No continuous AF point / no focus distance** — AF is one-shot; no focus sweep; no focus-state feedback.
4. **No stream/preview alignment metadata** — no `cropRect`/`rotationDegrees`, so scanner overlays and ROI mapping are approximate.
5. **Heavy image-stream copies on the main thread** — 1080p/4K YUV at 30 fps is tens to hundreds of MB/s through Pigeon; not suitable for real-time analysis at high resolution.
6. **High-res black-JPEG bug** — stock high-res capture is not reliable enough to be the only path.

A minimal custom CameraX layer should:

- Own the single `ProcessCameraProvider` (no stock plugin use on the same camera).
- Build **separate** `ResolutionSelector`s:
  - `Preview`: display-appropriate, e.g. 1080p or 4:3 1440×1080.
  - `ImageAnalysis`: 720p–1080p, `STRATEGY_KEEP_ONLY_LATEST`, background executor, YUV Y-plane only if possible.
  - `ImageCapture`: highest 4:3 JPEG, `CAPTURE_MODE_MAXIMIZE_QUALITY` (or ZSL if available).
- Bind them in a `UseCaseGroup` with a `ViewPort` so `ImageProxy.cropRect` and preview transform are aligned; expose `cropRect`/`rotationDegrees` to Flutter for overlays.
- Use Camera2 interop for `CONTROL_AE_LOCK`, `CONTROL_AWB_LOCK`, and optionally `SENSOR_EXPOSURE_TIME` / `SENSOR_SENSITIVITY` / `LENS_FOCUS_DISTANCE` on devices with `MANUAL_SENSOR`.
- Run analysis on a background executor with explicit backpressure, and hand only downsampled/ROI data to Dart.
- Keep a Kotlin `CameraSession` object with a method channel for control and a texture for preview; the app already has Kotlin/OpenCV/ONNX/ML Kit code, so this is a bounded addition, not a rewrite.

### 10.3 Hybrid interim option

If the real-time analysis requirement can be relaxed:

- Use `ResolutionPreset.max` for photo mode; keep `high` for video mode.
- Do **not** run a continuous high-res stream. Instead, when the user taps “auto-tune,” start the stream briefly, collect 3–5 frames, stop it, compute luminance/sharpness, adjust EV/AF, then capture. Test for preview stalls and stream restart glitches on target devices.
- For quality checks after capture, analyze the JPEG itself (the app already has OpenCV/ML Kit); this is more reliable than streaming at max resolution.

This gives most of the tuning benefit with much less risk, but it is not a continuous real-time preview analyzer.

---

## Appendix A — Capability matrix

**Legend:** “Stock” = `camera 0.12.1` + `camera_android_camerax 0.7.5+1` on Android. Confidence reflects code evidence vs. device-dependent behavior.

| Feature | Stock Flutter camera 0.12.1 | Evidence | Confidence | Workaround |
|---|---|---|---|---|
| Exposure mode auto | Yes | `CC:810-817`; `CX:802-820` | High | — |
| Exposure mode lock (AE) | Yes, via Camera2 interop | `CX:802-820`; `J-C2:45-65` | High (code); Medium (device support) | Validate brightness stability; no capability flag |
| EV min/max range | Yes | `CX:618-628`; `CC:839-856` | High | Query at runtime; clamp |
| EV step size | Yes; Android returns -1 if unsupported | `CX:711-720`; `CC:861-868` | High | Check > 0; disable UI if -1 |
| EV set/sweep | Yes | `CX:736-773`; `CC:881-913` | High | Await each step; settle frames |
| EV while AE locked | Yes, per Camera2 docs | Android `CONTROL_AE_LOCK` docs | Medium–High | Validate on target devices |
| Manual ISO | **No** | No API in `CC`; only 2 Camera2 keys wrapped | High | Native Camera2/CameraX layer |
| Manual shutter speed | **No** | Same | High | Native layer; `MANUAL_SENSOR` check |
| White-balance lock/manual WB | **No** | No API; #108871 open | High | Native `CONTROL_AWB_LOCK`/`AWB_MODE` |
| Focus mode auto | Yes | `CC:935-942`; `CX:639-705` | High | — |
| Focus mode lock (AF) | Yes | `CX:639-705` | High | Lock after AF converges |
| AF point | Yes, one-shot | `CX:784-795`; `CX:1632-1658` | High | Call again to refocus; lock to persist |
| Continuous AF at point | **No** | 5 s auto-cancel; no continuous point mode | High | Native repeating AF regions |
| AE point | Yes, one-shot region | `CX:603-614` | High | Combine with `setExposureMode(locked)` for AE lock |
| Continuous AE at point | **No** | 5 s auto-cancel; region cleared | High | Native repeating AE regions |
| Manual focus distance / sweep | **No** | No API | High | Native `LENS_FOCUS_DISTANCE` |
| Focus/AE success feedback | **No reliable feedback** | `CX:691-697`, `CX:810-820` | High | Infer from sharpness/luminance |
| `exposurePointSupported`/`focusPointSupported` flags | Always true after init | `CX:493-499` | High | Do not use as capability checks |
| Flash off/auto/always | Yes | `CX:1058-1082`; `J-IC:73-86` | High | — |
| Torch preview/stream | Yes | `CX:1058-1082`, `CX:1806-1812` | High | No `hasFlashUnit`; failure silent |
| Torch during capture | Yes | `CX:1022-1031`; CameraX docs | High | Use torch for documents |
| Flash fires on `always` | Yes, if flash unit | `ImageCapture.FLASH_MODE_ON`; `CX:1070-1071` | High | Avoid for glossy paper |
| Zoom ratio | Yes | `CX:824-867` | High | Digital; no lens selection |
| Lens type | Not populated | `CX:292-334`; `CameraDescription` default `unknown` | High | Select by camera name/ID; not reliable |
| Resolution presets | Yes | `CX:1543-1595` | High | `max` for 4:3 photos |
| `max` = full sensor | **No guarantee** | CameraX docs: max-resolution mode excluded | High | 12 MP is usually enough; custom Camera2 for full sensor |
| Separate photo/stream/video resolution | **No** | Single selector; #46082/#130958/#194208 | High | Custom native layer, or separate controller/screen |
| Change resolution after init | **No** | No setter; reinit required | High | Choose preset per `recordMode` |
| `takePicture` at preview resolution | No; at ImageCapture-selected size | `CX:414-418`; `previewSize` from Preview only | High | Read JPEG dimensions |
| `takePicture` at full sensor | No | CameraX resolution strategy | High | Accept 12 MP or custom layer |
| JPEG quality control | Yes, 1–100 | `CC:981-990`; `CX:1091-1106` | High | `setJpegImageQuality(100)` |
| Capture mode maximize quality | **No** | Plugin never sets it | High | Custom layer |
| RAW / HDR / night / OEM extensions | **No** | No API | High | Custom layer |
| Image stream YUV420 | Yes, 3 planes | `CX:1415-1424`, `CX:1346-1354` | High | Use Y plane; handle row/pixel stride |
| Image stream NV21 | Yes, 1 plane | `CX:1326-1344`; `ImageUtils` | High | Check format/docs discrepancy |
| Image stream JPEG/BGRA | **No** (falls back to YUV) | `CX:1415-1424` | High | Encode yourself if needed |
| Stream resolution control | Only via global preset | `CX:469-473`; no stream options | High | Custom layer |
| Stream FPS control | Only global constructor `fps` | `CX:393-396`; `CameraImageStreamOptions` empty | High | Custom layer |
| Stream backpressure/zero-copy | **No**; main-thread, copies, unbounded queue | `J-IA:68-75`; `J-PP:23-30`; `CX:1375-1388` | High | Custom native analyzer |
| Stream alignment/crop/rotation | **No metadata** | `CX:1375-1381`; #181770 | High | CameraX `UseCaseGroup`+`ViewPort` |
| Stream ISO/exposure metadata | **Null** | `CameraImageData` constructed without metadata; `CX:1376-1381` | High | Native capture-result callbacks |
| Capture while streaming | Yes, but can slow/black-frame | `CX:1022-1043`; #195584/#195468 | Medium | Validate/retry; lower stream resolution |
| Orientation lock for capture | Yes | `CX:569-584` | High | Also lock app orientation |
| Preview rotation after lock | **Buggy/not updated** | `CX:569-584`; #194524 | High (code); Medium (device) | Re-init on rotation; avoid runtime rotation |
| CameraX instance access | Not supported; fields public `@visibleForTesting` | `CX:44-96`; `camera_android_camerax.dart` export | Medium | Do not rely; custom layer |
| Coexist with custom CameraX | **No** | Plugin `unbindAll` at `CX:404`, `CX:519` | High | Single owner |
| Coexist with custom Camera2 | **No** | Camera exclusive; `CX:1472-1501` | High | Single owner |
| Zero-shutter-lag (ZSL) | No in 0.12.1 | `camera` 0.12.2 changelog | High | Upgrade, but `max` incompatible (#195466) |
| Guaranteed valid high-res JPEG | **No** | #195584 | High | Validate file/luminance; retry |

---

## Appendix B — Suggested device validation plan

Run these on at least: a Samsung mid-range, a Xiaomi/Redmi, a Pixel, and one low-end `LEGACY`/`LIMITED` device.

1. **EV range/step**: log `getMin/MaxExposureOffset`, `getExposureOffsetStepSize`; verify at least ±2 EV on modern devices; sweep and confirm monotonic brightness response.
2. **AE lock**: lock in a changing-light scene; confirm frame luminance stays stable; adjust EV while locked and confirm it responds (Camera2 guarantee).
3. **AF point/lock**: tap a text region; measure Laplacian variance over 2 s; confirm 5 s auto-cancel returns to continuous AF; confirm `setFocusMode(locked)` holds focus; verify no `StateError`.
4. **Capture resolution**: for each preset, capture a test chart and read JPEG dimensions; confirm `max` is 4:3 and not 16:9; confirm `ultraHigh` is 16:9; confirm no full-sensor 108/200 MP expectation.
5. **Black-frame rate**: 100 captures at `max` on a long-lived controller; validate every file (size, decode, mean luminance); record black/empty rate; test re-init recovery.
6. **Flash latency**: measure `takePicture` median with no `setFlashMode`, with `setFlashMode(off)`, with `torch`, and with `always`; confirm #195468 impact.
7. **Stream format**: log `image.format.group`, `planes.length`, width/height, rowStride/pixelStride; verify YUV 3 planes and NV21 1 plane; test `jpeg`/`bgra8888` fallback.
8. **Stream stability**: 10-minute 720p/1080p stream; monitor memory and frame gaps; confirm no stall on target devices.
9. **Preview/stream alignment**: overlay a grid; capture at 0°, 90°, 180°, 270°; compare corners; verify #194524/#181770 impact.
10. **Capture while streaming**: 20 captures with stream active at 720p and at `max`; record latency, black frames, and preview stalls.
11. **Lifecycle**: background/foreground, screen lock, rotation, camera switch; ensure `dispose`/re-init; confirm no `cameraInUse`.
12. **Coexistence** (only if attempting): bind a custom CameraX use case; confirm it is unbound by plugin create/dispose; confirm Camera2 open fails while plugin active.

---

## Appendix C — Key source locations (full paths)

- `D:\pub-cache\hosted\pub.dev\camera-0.12.1\lib\src\camera_controller.dart`
  - constructor 247–262; initialize 315–390; takePicture 465–482; startImageStream 501–527; stopImageStream 536–553; zoom 685–716; flash 800–807; exposure mode 810–817; exposure point 823–836; exposure range 839–868; exposure offset 881–913; orientation lock 918–932; focus mode 935–942; focus point 958–970; JPEG quality 981–990; dispose 995–1008.
- `D:\pub-cache\hosted\pub.dev\camera_android_camerax-0.7.5+1\lib\src\android_camera_camerax.dart`
  - availableCameras 292–334; createCamera 366–437; initialize 451–512; dispose 516–528; lockCaptureOrientation 569–584; exposure point 603–614; exposure range 618–628; focus mode 639–705; exposure step 711–720; exposure offset 736–773; focus point 784–795; exposure mode 802–820; zoom 824–867; takePicture 1022–1043; flash 1058–1082; JPEG quality 1091–1106; supports streaming 1254–1255; onStreamedFrameAvailable 1272–1281; bind use case 1292–1305; configure analysis 1308–1388; clear analyzer 1408–1410; format mapping 1415–1440; resolution selector 1543–1595; quality selector 1602–1628; focus/metering point 1632–1658; focus/metering action 1681–1785; torch 1806–1812.
- `D:\pub-cache\hosted\pub.dev\camera_android_camerax-0.7.5+1\android\src\main\java\io\flutter\plugins\camerax\...`
  - `ImageAnalysisProxyApi.java`: setAnalyzer 68–75 (main executor).
  - `PlaneProxyProxyApi.java`: buffer copy 23–30.
  - `ImageProxyUtils.java`: planesToNV21 20+.
  - `ImageCaptureProxyApi.java`: setFlashMode 73–86; takePicture 90–110 (main executor).
  - `CameraControlProxyApi.java`: setExposureCompensationIndex 145–170.
  - `Camera2CameraControlProxyApi.java`: addCaptureRequestOptions 45–65.
  - `ProcessCameraProviderProxyApi.java`: bindToLifecycle 64–72.
  - `ProxyApiRegistrar.java`: getLifecycleOwner 109–116.
  - `CaptureRequestProxyApi.java`: only `controlAELock` and `controlVideoStabilizationMode` keys.
- `D:\pub-cache\hosted\pub.dev\camera_platform_interface-2.15.0\lib\src\...`
  - `types\resolution_preset.dart`, `exposure_mode.dart`, `focus_mode.dart`, `flash_mode.dart`, `image_format_group.dart`, `camera_image_data.dart`.
- `D:\pub-cache\hosted\pub.dev\camera-0.12.1\lib\src\camera_image.dart`
  - `Plane`/`CameraImage` fields; Android `bytesPerRow`/`bytesPerPixel`; `height`/`width` null on Android.
- Project:
  - `D:\Code\VectorScaling\mobile\lib\capture.dart:44-48` — current `ResolutionPreset.high`; `102-140` — current `takePicture` flow.
  - `D:\Code\VectorScaling\mobile\pubspec.yaml` — `camera: ^0.12.1`.
  - `D:\Code\VectorScaling\mobile\pubspec.lock` — `camera 0.12.1`, `camera_android_camerax 0.7.5+1`, `camera_platform_interface 2.15.0`.

---

*End of report.*
