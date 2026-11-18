# OCR comparison, 17 October 2026

Status: desktop and offline Android measurements complete. Competitors remain unranked until they produce actual exports. These results do not support replacing the Android default globally.

## Measured results

Character error rate (CER), lower is better. These are six individual smoke cases, not estimates of customer accuracy.

| Input | Raw desktop RapidOCR | Desktop pipeline, letterpress off | Desktop pipeline, letterpress auto | Android ML Kit | Android desktop-model port |
| --- | ---: | ---: | ---: | ---: | ---: |
| Generated Nepali, clean | 5.02% | 5.02% | 5.02% | **3.34%** | 4.01% |
| Same Nepali with shadow/blur | 4.68% | 4.68% | 4.68% | **2.68%** | 3.68% |
| Generated English invoice | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |
| Same English rotated 90 degrees | 65.00% | 0.00% | 0.00% | 0.56% | 0.00% |
| Historical Hindi, saktidharasukla1930_p01 | 55.75% | 55.75% | 55.75% | **51.72%** | 53.45% |
| Historical Hindi, simha1914_p000_1 | 36.80% | 36.80% | **22.40%** | 40.68% | 33.41% |

Orientation handling clearly matters on the tested invoice. ML Kit is more accurate on both generated Nepali cases. The Android port beats ML Kit on the rotated English case and the second historical page; the desktop letterpress reader improves that same historical page further. Severe errors remain on both historical pages. There is no consistent winner and no basis for claiming market superiority.

The desktop clean Nepali result loses the decimal point in `१२,५००.७५`, producing `१२,५००७५`. ML Kit retains the decimal but substitutes Bengali zero U+09E6 for one Devanagari zero U+0966. The native port preserves the ground-truth digit sequence on all four generated cases, while still making other text errors. Same-engine digit agreement must not be marketed as proof of correctness.

Android elapsed time includes four orientation reads and same-engine digit crops: ML Kit took 10.7–36.6 seconds per page; the port took 33.9–145.3 seconds. Model/session startup is included on the first use. The emulator was under memory pressure (approximately 968 MB app resident memory observed during native inference). These are observations on this emulator, not phone speed or RAM requirements. The paired integration test passed in 8 minutes 37 seconds.

## Test integrity and limits

- `manifest.json` freezes image and ground-truth hashes. `scores.json` records per-page CER, WER, order-insensitive CER and digit results. `predictions.json` preserves the actual texts and elapsed times for inspection. All six images must have output and matching provenance before an engine receives an aggregate score.
- Nepali fixtures use HarfBuzz shaping with FreeType on Windows, or Pillow RAQM when available. Earlier unshaped Nepali fixtures were invalidated and are excluded. Reused English/historical results match the current image hashes exactly.
- Nepali/English ground truth is the exact generated text. The historical pages use upstream human-corrected ALTO from held-out books in heiDATA DOI `10.11588/data/EGOKEI`, CC BY 4.0. Historical Hindi is not evidence of modern Nepali camera accuracy.
- Shadow and rotation cases share source text with their clean versions. They are correlated transformations, not six independent documents. No photographed curved books, handwritten pages, complex tables or phone performance are validated.
- Existing Nepali line-crop labels are documented in `docs/EVALUATION.md` as machine-generated and partly misaligned; modern PDF text also has Unicode extraction errors. These sets were excluded from accuracy ranking rather than treated as human ground truth. A human-checked modern Nepali camera corpus remains necessary.
- Desktop DirectML and a resource-constrained emulator share a Windows host. Wall-clock timings include startup/contention and cannot establish relative device performance.

## Competitor execution

- [vFlat](https://vflat.com/) Android package `com.voyagerx.scanner`, version `1.16.8.260930.6c4b190386`, was downloaded as APKPure split APKs and installed on the API 35 x86_64 emulator with ARM64 translation. Initial launches timed out while Pixel Launcher and System UI also displayed ANRs. A later launch reached `com.pairip.licensecheck.LicenseActivity` and visibly required enabled, up-to-date Google Play before opening (`build/ocr-comparison/vflat-license-screen.png`). A second, separate AVD was then created with Google's official API 35 Google Play x86_64 revision 9 image, verified against the published SHA1. Installation succeeded there too. A fresh launch again entered `LicenseActivity` and redirected to Play Store's `UnauthenticatedMainActivity`, displaying **Sign in**. Evidence: `build/ocr-comparison/vflat-play-launch.txt` and `vflat-play.png`. No Google account was available in this disposable emulator. No OCR export exists; vFlat is unranked. This is an execution/access limitation, not an OCR-quality result.
- [Scandra](https://nainnielabs.com/scandra) links to [Google Play](https://play.google.com/store/apps/details?id=com.nainnielabs.scandra). The attempted public APK download returned HTTP 403. Opening its Play listing on the second, official Play AVD reached the same sign-in screen (`build/ocr-comparison/scandra-play-store.png` and `.xml`). No accessible APK or OCR export was obtained; Scandra is unranked. A signed-in Play session is the next prerequisite for this route. Download and licensing restrictions were not bypassed.

## Implementation under evaluation

Android has an experimental ONNX Runtime backend using the pinned desktop PP-OCR models. Model hashes, build-time packaging checks and upstream license texts accompany it. Settings → **Desktop reader (preview)** selects it for both page and batch recognition; ML Kit remains the application default. The native port's polygon expansion differs from upstream, and it does not include desktop layout analysis or the PyTorch letterpress reader. Sharing weights alone does not establish pipeline parity. The model files add approximately 40 MB before APK compression, plus the ONNX runtime, even when the preview setting is off.

## Verification

- 27 Python tests passed across `test_compare_apps.py`, `test_document_orientation.py` and `test_digit_content.py`.
- All 23 Flutter unit/widget tests passed, including preview-setting persistence, native failure preserving reviewed text/image, cancellation during digit processing and restoration of previous readings.
- `flutter analyze` passed with no issues.
- The real Android paired integration passed for both backends on all six pages with no active default network.
- Both release APKs built successfully (295.6 seconds). ARM64 is 121,809,715 bytes (121.8 MB / 116.2 MiB); x86_64 is 161,721,122 bytes. The previous local ARM64 APK was 61,367,525 bytes, so the current experiment adds about 60.4 MB to that artifact. Play download size has not been measured.
- Both packaged APKs contain all four models with matching SHA256 and all three license notices, use the normal application ID, omit Internet permission, and pass APK signature verification. They use the development debug key. Release APK execution and physical-device acceptance are not established by the paired debug integration test; these are test artifacts, not Play-ready releases. Exact APK hashes are recorded in `environment.json`.

Reproduce with the commands in `mobile/README.md`. Raw artifacts and diagnostic logs are under `build/ocr-comparison/`; they include the invalidated old pack separately. The native backend checks cancellation between inference stages; immediate interruption of an ONNX kernel is not established by the mocked cancellation test. Physical-phone resource measurements and a human-checked Nepali camera corpus remain acceptance requirements. Passing synthetic/emulator checks does not establish phone readiness. Use a fresh output directory and record versions when comparing a different implementation; existing desktop outputs are resumed by image hash.
