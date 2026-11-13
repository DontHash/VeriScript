# Scan camera - Phase 0 results

**Status:** implementation complete for the emulator; physical-device capture and OCR baseline still pending.
**Date:** 2026-11-07 (verification re-run 2026-11-09)
**Plan:** [`SCAN_CAMERA_PLAN.md`](SCAN_CAMERA_PLAN.md)

Phase 0 had three goals: prove the risky device assumptions, ship a safe interim
photo-resolution fix, and create a capability readout that can be collected on a
real phone. The first two are implemented; the third is implemented and verified
on the emulator.

---

## 1. What changed

### Interim capture fix

`mobile/lib/capture.dart`

- Photos now use `ResolutionPreset.max`; video keeps `ResolutionPreset.high`.
- If `max` is rejected, photo mode falls back to `veryHigh`, then `high`, rather
  than making the camera unusable.
- Photo mode requests JPEG quality 95 when the controller supports it.
- Every capture is validated through a new native `jpegInfo` call. A clearly
  black/empty frame is discarded and retried once; low resolution is logged but
  does not block the user.
- The camera controller is only assigned after successful initialization.

### Cheap native capture metadata

`mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/OfflinePages.kt`

- New `jpegInfo` method: decodes only a ~512 px sample, returns:
  - actual JPEG width/height;
  - file bytes;
  - mean luma;
  - dark/bright pixel fractions.
- It does not decode the full 12 MP image, so it is safe between captures.

`mobile/lib/capture_quality.dart`
`mobile/lib/documents.dart`

- `CaptureInfo` model, black-frame/low-resolution checks, summary string.
- `readCaptureInfo(path)` wraps the native method.

### Read-only capability probe

New package:
`mobile/android/app/src/main/kotlin/com/veriscript/veriscript_mobile/scan/`

- `ScanCapabilityProbe.kt`: Camera2 characteristics only; never opens the camera.
  Reports camera IDs, facing, hardware level, manual sensor/post-processing, RAW,
  flash, AE compensation EV range + step + index range, AF/AWB modes, sensor
  orientation, pixel array, and JPEG output sizes.
- `ScanCameraPlugin.kt`: `veriscript/scan_camera` MethodChannel with
  `getCapabilities` and `getDiagnostics`. Registered in `MainActivity`.

New Dart:
`mobile/lib/scan/scan_camera_api.dart`
`mobile/lib/scan/scan_models.dart`
`mobile/lib/scan/scan_diagnostics_screen.dart`

- Typed capability models, readable/JSON reports, and a read-only diagnostics
  screen under **Settings -> Camera diagnostics**. It does not open the camera,
  take photos, or use the network.

### Build foundation

`mobile/android/app/build.gradle.kts`

- Added explicit CameraX 1.6.2 dependencies (`core`, `camera2`, `lifecycle`) so
  the Phase 1 native session can be built against the same CameraX generation as
  `camera_android_camerax`.

---

## 2. Verification results

### Static and unit tests

- `flutter analyze`: **no issues**.
- `flutter test --concurrency=1`: **31 tests passed**.
- Default parallel `flutter test` intermittently times out in the existing
  `review_test.dart` `pumpAndSettle` at `settleDisk`. The same test passes alone
  and in the serial run. This is a timing-sensitive test flake to fix separately;
  it is not a camera-probe failure. Do not use the parallel full-suite result as
  a camera gate.
- `flutter build apk --debug`: **succeeded** with CameraX 1.6.2 and the native
  probe.

### Integration tests on the emulator

Device: Google `sdk_gphone64_x86_64`, Android 15 / API 35, one back camera.

`integration_test/scan_capability_test.dart`: **passed**

Reported:

- camera `1`, back, hardware level `LEVEL_3`;
- manual sensor: yes, manual post-processing: yes, RAW: yes, flash: yes;
- AE compensation raw index range `-9..9`, step `0.333`; the probe now reports
  the normalized `-3.0..3.0 EV` range plus the raw indices for the Phase 1 loop;
- AF modes `0, 1, 2, 3, 4`; AWB modes `0, 1, 2, 3, 5, 8`;
- sensor orientation 90 degrees;
- pixel array `1856 x 1392`;
- JPEG sizes max out at `1856 x 1392` (2.58 MP).

The emulator's virtual camera is only 2.58 MP. This is expected. It does **not**
prove the 12 MP physical-phone target; that remains a real-device gate.

`integration_test/scan_capture_info_test.dart`: **passed**

- 1600x1200 white JPEG: mean luma > 200, usable;
- 800x600 black JPEG: classified as black, not usable.

`integration_test/camera_capture_smoke_test.dart`: **passed**

- camera plugin with `ResolutionPreset.max` on the emulator;
- captured `1856x1392`, 0.1 MB, mean luma 208, usable.

This validates the interim photo preset, the camera plugin path, and the native
JPEG validation together. It does not validate 12 MP, focus, glare, or OCR.

---

## 3. What is still pending

1. **Physical-device capture baseline.**
   - Confirm the actual `ResolutionPreset.max` JPEG dimensions, aspect ratio
     (4:3 vs 16:9), file size, and black-frame rate on at least one real phone.
   - Confirm `max` does not select an unwanted 48 MP mode.
   - Measure capture latency and repeated-capture stability.
2. **OCR baseline.**
   - Capture the same pages at the old 720p preset and the new max preset.
   - Run ML Kit and RapidOCR through the existing harness.
   - Record CER/WER/digit exact before any downstream resolution change.
3. **Phase 1 native session.**
   - Preview + ImageAnalysis + ImageCapture bind, texture preview, 12 MP 4:3
     capture, actual resolution reporting, validation/retry.
4. **Fix the parallel test flake.**
   - Treat it as test infrastructure work; the serial suite is the current
     trustworthy gate.

---

## 4. How to reproduce

```powershell
# From mobile/
flutter pub get
flutter analyze
flutter test --concurrency=1
flutter build apk --debug
```

On a connected Android device:

```powershell
flutter test integration_test/scan_capability_test.dart -d <device>
flutter test integration_test/scan_capture_info_test.dart -d <device>
flutter test integration_test/camera_capture_smoke_test.dart -d <device>
```

If the camera permission is not granted for the smoke test:

```powershell
adb shell pm grant com.veriscript.veriscript_mobile android.permission.CAMERA
```

Manual capability report: **Settings -> Camera diagnostics -> Copy readable
report** (or copy the JSON report from the app bar).

---

## 5. Phase 0 decision

Proceed to Phase 1. The native plugin/channel boundary works, CameraX 1.6.2
resolves and builds, and the emulator proves the probe and JPEG validation. The
next risk is the real CameraX stream combination and actual capture size on
physical hardware, which is exactly what Phase 1's first task should check.
