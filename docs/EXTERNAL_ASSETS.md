# External tools, models and test data (local only)

Downloaded 2026-11-16 into `data/external/` (git-ignored). Nothing here is
redistributed or shipped in an app; each item is used locally for testing or
evaluation. Re-fetch with the commands below and check the SHA-256.

| Item | Use | Source | Licence | SHA-256 |
|---|---|---|---|---|
| veraPDF 1.30.4 (`verapdf-installer.zip`, 33 MB) | PDF/A conformance checks for E4 (CI and local) | <https://downloads.verapdf.org/rel/verapdf-installer.zip> | MPL 2.0 / GPL 3.0 (dual); a test tool, not bundled | `04415ef3f149526a3048b9889723e81320ddf013bd891bcc7f0f297f3eadcc23` |
| UVDoc model (`model/best_model.pkl`, 32 MB, 8.0 M parameters) | curved-page flattening candidate for F1 | <https://github.com/tanguymagne/UVDoc> @ `4c9b82b` | MIT (repository LICENSE) | `7e90861b8a516eb4bc51f84bd889cb77275743d2d1d3ca8091951ec9f2b7da23` |
| DocUNet benchmark, cropped photos (`crop.zip`, 281 MB, 130 photos of 65 documents) | real phone photos for F1 gates and photo robustness | <http://vision.cs.stonybrook.edu/~kema/docwarp/crop.zip> | **none stated**; the authors ask for a citation (Ma et al., DocUNet, CVPR 2018). Local evaluation only. | `30e385f4a8c7bb47ec93cb61c73e40d91ed390fbf86b22cf1c5e4e8898df4e81` |
| DocUNet benchmark, flatbed scans (`scan.zip`, 416 MB, 65 scans) | flat references for the photos above | <http://vision.cs.stonybrook.edu/~kema/docwarp/scan.zip> | as above | `28b97e256c657a9a2d6320c54517cb378af13f5f3ca27bde0f915c6da02e2bd2` |

## Notes

- **veraPDF** was installed unattended
  (`java -jar verapdf-izpack-installer-1.30.4.jar auto-install.xml`, GUI and
  CLI packs) into `data/external/verapdf/app`. Check a file with
  `verapdf.bat --format text -f 2b file.pdf`. On 2026-11-16 the studio's
  searchable PDFs failed PDF/A-2b on three rules: no XMP metadata stream
  (6.6.2.1), stream keyword line endings (6.1.7.1), and DeviceGray without
  an output intent (6.2.4.3).
- **UVDoc** is a Python pickle. Load it only with
  `torch.load(path, weights_only=True)`, which refuses arbitrary objects; the
  checkpoint holds just `model_state`. Its `model.py` imports only PyTorch.
  Do not import its `utils.py` (it shells out to `pip`); the two helpers it
  provides (`load_model`, `bilinear_unwarping`) are a few lines and are
  reproduced where needed. Smoke test: a 12 MP page in 0.5 s on CPU.
- **DocUNet** has no OCR ground truth. The flatbed scan of each document
  serves as the reference: OCR the scan and the photo (before and after
  flattening) and compare, which measures how much distortion costs OCR.
  It is English; it does not measure Nepali accuracy.
- **Not found:** a public set of consented phone photos of printed
  Devanagari/Nepali with ground truth under an open licence. The closest
  published set is "available on request". The plan's F4 (print pages that
  already have exact ground truth and photograph them) remains the way to
  get one.
