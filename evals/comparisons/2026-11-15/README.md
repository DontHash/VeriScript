# Android C1/D1 measurement, 15 November 2026

What changed (docs/TECH_UPGRADE_PLAN.md):

- **C1, resolution.** Import, alignment and enhancement keep up to 4096 px
  (was 2500). The native RapidOCR port detects on a ≤2000 px copy but cuts
  each text line from the full-resolution page.
- **D1, orientation.** Read the page as given and stop when its lines look
  upright; otherwise the line angles pick the next rotation to try. All four
  rotations are read only when none looks upright. RapidOCR on Devanagari
  keeps the four-way comparison (its line angles cannot tell up from down).
- **RapidOCR memory.** ONNX Runtime's CPU arena and memory patterns are off.

Status: ML Kit (the app default) passes the plan's gates. RapidOCR (the opt-in
"Desktop reader (preview)") no longer gets killed for memory but is slower.

## Pack

16 pages (`manifest.json`, hashes frozen):

- 10 **camera proxies** from `python -m evals.harness.compare_apps prepare-camera`:
  12 MP (3024×4032) frames of an A4 page on a desk, 7–8 pt text, mild blur
  and noise, JPEG. Nepali and English, upright and turned 90/180/270 degrees
  with the expected correction recorded. They go through the app's real
  import (alignment + enhancement) before OCR. **Synthetic**: they test
  resolution handling and orientation, not real-photo accuracy.
- The 6-page smoke pack from 2026-10-17, read directly as before.

Run with `python mobile/tool/compare_ocr.py --pack c1d1 --tag <tag>` on the
API 35 x86_64 emulator (2.5 GB RAM, 4 cores), networking off. Baseline =
commit f1a0fc0 plus timing/rotation instrumentation only.

## Results

| Reader | Run | Nepali camera CER | English camera CER | Orientation (turned + upright camera pages) | Mean s/page | Peak memory |
|---|---|---:|---:|---:|---:|---:|
| ML Kit (default) | baseline | 0.040 | 0.001 | 10/10 | 10.3 | not sampled |
| ML Kit (default) | new | **0.027** | 0.001 | 10/10 | **8.2** | 1.0 GB (whole run) |
| RapidOCR (preview) | baseline | 0.039 (5 pages) | 0.000 (3 pages) | 8/8 before being killed | 30–308 | **killed at 1.7 GB**, page 9 |
| RapidOCR (preview) | new | see note | 0.000 | 8/10 | 160 | 1.0 GB |

- **ML Kit.** Nepali camera CER fell on all five pages (−32% relative);
  English and the six smoke pages are unchanged. Upright pages need one
  read, turned pages two (`tried` in each output JSON). OCR + import time for
  all 16 pages: 181 s → 190 s (+5%, gate: ≤ +30%); the smoke pages, read
  directly, are 2–3× faster.
- **RapidOCR orientation.** The run above used early stopping for every
  reader and got two Nepali pages wrong (upside-down kept as is, 90° turned
  the wrong way: CER 0.89–0.91, hence the Nepali mean). The final code
  restores the four-way comparison for RapidOCR on Devanagari, which is the
  baseline behaviour (5/5 there); **that change was not re-run on the
  emulator.**
- **RapidOCR speed.** Arena off is slow (about 2–4× per read on Nepali
  pages; English pages take ~5 minutes on this emulator either way, from the
  very large English character set). A 3-page trial with the arena on and
  bucketed line widths was faster per read but peaked at 1.38 GB, so it was
  not adopted for this preview reader.

## Limits

- Emulator wall-clock time shares a Windows host; single-page timings vary
  by 2× or more between runs. Treat per-page times as rough, totals as
  indicative.
- Synthetic camera proxies are clean rendered text. Real phone photos
  (curvature, glare, focus) and physical phones remain unmeasured.
- Raw outputs and logs: `build/ocr-comparison/c1d1/`, `c1d1-*.out`,
  `c1d1-new2-memory.txt`, `rapid3/` (git-ignored).
