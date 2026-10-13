# Android verification — 2026-10-13

This records the initial mobile baseline before P1. See [P1 implementation and checks](P1.md) for the subsequent changes and current APK evidence.

See [P2 appearance and review checks](P2.md) for the subsequent UI changes and their verification.

This is a development build, not a claim of desktop feature parity or physical-phone certification.

## Automated evidence

- `flutter analyze`: no issues.
- `flutter test`: eight tests passed. Coverage includes digit-group boundaries and script normalization, upright-versus-upside-down angle scoring, uncertain-number review, Unicode DOCX structure, concurrent draft persistence/reorder/exclusion, cancel/confirm in the digit dialog, and both themes at 360×800.
- `python tool/verify_android.py`: one Android integration test passed on the API 35 x86_64 emulator. The final run took 1:37 after installation; this is emulator test time, not a phone processing benchmark.
- Before launch, Android `dumpsys connectivity` reported **Active default network: none**, with Wi-Fi disabled and airplane mode enabled. Bundled English and Devanagari OCR worked without an active network. Flutter's test transport used ADB loopback.
- The synthetic 900×1200 page was enhanced to 1800×2400. OCR recovered English `Invoice 12345` and Nepali `नेपाल सुन्दर देश हो`. A deliberately sideways English page ended upright, with its heading near the top.
- Digit crops were enlarged/contrast-adjusted and re-read. Agreement retained both readings and still required human confirmation. Screen checks covered cancelling an edit and confirming a correction without overwriting the first or alternative OCR evidence.
- Native perspective cropping, restoration, crossed-corner rejection, PDF import/rendering, draft persistence and all seven export formats passed.
- A 6.5-second synthetic video containing two steady spreads and page turns produced exactly four pages. Automated checks verified left/right/left/right ordering and first-spread OCR. Visual inspection of all four captured images confirmed `LEFT PAGE 1`, `RIGHT PAGE 1`, `LEFT PAGE 2`, `RIGHT PAGE 2`, with body text retained.

## Export inspection

Exported two-page PDFs were opened with pypdf and rendered with Poppler. Page images and searchable scans were visually inspected, including the physically upright English scan. Searchable PDF text preserved `12345` and `नेपाल`; editable DOCX contained valid XML with both strings. Digital PDF rendering shaped Devanagari correctly, but extraction omitted some conjunct characters; searchable scans or DOCX are recommended when Nepali copy/search fidelity matters.

Local evidence is in ignored `build/verification/`: Android integration log, disconnected-network report, synthetic video, pulled private documents, PDF previews and captured book-page comparison. Fixtures and reports are not packaged in the production app.

## Artemis

Project Auto's Artemis was installed into a separate local runtime. CLI help and diagnostics ran; Python/configuration and connected ADB passed. Autonomous testing remains unrun because the model-provider key and scrcpy are missing, with an integration-host warning. These Flutter/ADB checks are not an Artemis AI acceptance run. See [ARTEMIS.md](ARTEMIS.md).

## Remaining acceptance work

Physical camera capture, Android sharing into real recipient apps, permission-denial behavior on a phone, background interruption, real curved/shadowed book recordings, long-document memory/battery/performance and production signing remain unverified. Hardware figures in README are provisional targets.

Digit re-reading uses the same engine and is not independent verification. Bodhan, desktop calibration/date validation, learned correction memory, training-crop export and neural photo super-resolution remain unported. Enhancement is classical document processing and Lanczos enlargement, not learned recovery of lost text.

## Release packaging

`flutter build apk --release --target-platform android-arm64,android-x64 --split-per-abi` succeeded. R8 uses six specific warning suppressions for the plugin's unbundled Chinese/Japanese/Korean options; Latin and Devanagari remain bundled. A release-only OCR smoke test exposed stripped no-argument constructors in manifest-discovered Firebase/ML Kit component registrars (`NoSuchMethodException`). The keep rules now explicitly retain those constructors and component methods; debug-test success alone did not catch this packaging defect.

| APK | Bytes | SHA-256 |
| --- | ---: | --- |
| ARM64 phone | 61,207,485 | `86fd37522471df3d009db2cab40f645c326d9459267869772e3446c7448a050e` |
| x86_64 emulator | 95,646,646 | `17993d9b2af24d2894ce3cd4bb69f26a47d8575eb77c458dc4ddd6adb9276bf9` |

Artifacts are in `build/app/outputs/flutter-apk/`. AAPT inspected the actual ARM64 APK: VeriScript 0.1.0, split version code 2001, minimum API 29, target API 36, ARM64 native libraries. **Neither INTERNET nor ACCESS_NETWORK_STATE permission is present.** Declared permissions are CAMERA, RECORD_AUDIO (from the camera dependency; recording disables audio), READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE capped at API 28, and the app's private dynamic-receiver permission. API 28 storage writing is outside the supported OS range.

`apksigner verify --print-certs` succeeded. The certificate is Android Debug; these are development APKs and need production signing before distribution.

The x86_64 release APK installed successfully and cold-launched on API 35 with no active default network. Home, Settings and both themes were exercised and screenshots saved as `build/verification/release-home.png` and `release-night.png`. Android System UI briefly showed its own unresponsive dialog during host build load; after dismissing it, VeriScript remained running and both themes rendered correctly. This does not establish physical-phone performance.

After the registrar fix, the release APK imported the two-page synthetic image PDF through Android Downloads, enhanced both pages, and completed offline OCR/digit re-reading using the default Devanagari setting. The text-review screen showed `नेपाल सुन्दर देश हो`, `यो एउटा किताब हो`, and `पृष्ठ नम्बर १२३`; the numeric line said “Digit re-read agrees · confirm against the image.” Searchable PDF export opened Android's share sheet with `New document_searchablePdf_1791890893745.pdf`. Connectivity still reported no active default network. Evidence includes `release-nepali.png`, `release-nepali.xml`, `release-export.xml` and the before-fix initializer log. No recipient app was used to send the export.
