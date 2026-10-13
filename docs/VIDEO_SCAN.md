# Capture a book from video

The experimental scanner samples a page-turning video, keeps a clear frame from
each steady view, crops a detected outer boundary, and splits an open book into
left then right pages. It runs locally with OpenCV, without a model download or
OCR during selection. An image PDF preserves the captures; optional searchable
export uses VeriScript's existing English/Nepali/Hindi OCR pipeline.

## Record and review

1. Fix the camera above the book. Keep both pages and their edges visible.
2. Use even light, avoid glare, and keep fingers off the text during each pause.
3. Hold each spread still for 1–2 seconds before turning. Record in sections if
   the recording would exceed the limits below. MP4/H.264 is the safest format.
   1080p or higher materially improves the text layer: pages of an 848x478
   recording carry ~330x478 px and OCR stays approximate; a 1080p recording
   roughly doubles it.
4. Run `python webapp/server.py`, open `/studio`, and choose **Book video**.
5. Upload the recording. Choose **Two-page spread** for open books, **Single
   page** for one page, or **Auto** to infer the layout from the cropped shape.
6. Choose **Find page frames**. Check all previews against the physical book.
   Uncheck duplicates or obstructed frames; use Earlier / Later to change order.
7. Export the selected pages. The default is the clean pristine image PDF;
   the two OCR modes cost ~3.5-8 s per page and the web request timeout caps
   their scale.

### Export modes (`--video-pdf`, web "PDF type")

| Mode | Output | Cost |
|---|---|---|
| `clean` (default) | Pristine page-image PDF: small captures are upscaled 2x
  (Lanczos + mild unsharp) so text prints crisp. No OCR. | ~0.15 s/page |
| `searchable` | The clean pages plus an invisible, selectable OCR text layer. | ~3.5-8 s/page |
| `digital` | A word-style PDF: no page images. Recognized text (same OCR path)
  re-typeset as flowing A4 paragraphs - headings centred, body justified,
  dialogue indents kept. 23 captures -> 13 text pages, ~56 KB, vs ~15 MB image. | OCR cost |

Text boundaries are trusted only inside the page: OCR tokens that touch a
crop border (the neighbour-page sliver or a sliced word stem) are dropped
before re-typeset, so the digital PDF contains no partial words. At the
reference footage's 330-px page width the text layer is a finding aid - page
numbers 58-82 extract in order, but body words carry OCR noise ("farma",
"whor") until recordings at 1080p exist.

Super-resolution was evaluated for the OCR path and rejected with numbers:
RealESRGAN x4plus/x4v3 (bundled weights) on 330-px text produces
smoother-looking images but _garbled_ readings ("Tho Lomı Jooppeord and u
roplaod") while plain Lanczos 2.5x reads layout, order and page numbers
correctly at the same cost or less. Do not wire SR into text OCR at this
source resolution; revisit with 1080p captures.

Review cannot recover a page the recording missed. Re-record missing sections.
This version does not merge multiple videos, manually adjust crops, remove
hands, flatten curved pages, dewarp the page bow near a binding, or verify
physical page numbers. Auto layout uses the detected book shape and content
and can mistake a wide single page for a spread; explicitly choose the layout
when that happens. Spread splitting detects a dark binding valley inside the
paper region and only falls back to the centre of the detected book — never
the frame — when the binding is not found.

## CLI

```powershell
python -m veriscript --mode video --input book.mp4 --output out/book --video-layout spread
python -m veriscript --mode video --input book.mp4 --output out/book --video-layout spread --video-pdf clean
python -m veriscript --mode video --input book.mp4 --output out/book --video-layout spread --video-pdf digital --lang ne
```

`--video-pdf clean|searchable|digital` picks the export mode (default clean).
`--video-searchable` still works and maps onto `--video-pdf searchable`.

The CLI writes `capture_0000.jpg`, subsequent captures, `capture.json` with
timestamps/sides/crop warnings, and `book.pdf`. It exports all captured pages in
order. Use the studio for interactive exclusion/reordering. `--video-review-only`
saves captures without exporting. Use a fresh output directory for each video.

| Option | Default | Purpose |
|---|---|---|
| `--video-layout auto\|single\|spread` | auto | Interpret each steady view |
| `--video-hold` | 0.75 s | Minimum steady interval before a candidate qualifies |
| `--video-max-pages` | 150 | Physical output pages, counting both sides |
| `--video-max-seconds` | 600 | Recording duration processed |
| `--video-searchable` | off | Run OCR during PDF export |
| `--video-review-only` | off | Save images/manifest without a PDF |

Selection samples about four frames per second. Focus, alignment, detail, and
stability determine the best frame within each view. Views are compared after
smoothing with a small translation search, so ordinary hand-held wobble does
not read as a page change. Adjacent repeated views are suppressed; returning to
a different previously seen page is retained. Similar pages can still be missed,
and a pause with an obstruction can still be selected. A spread that is not
held still for the hold interval, or a turn whose motion never drops the
similarity below the comparison floor, is not captured. When a spread yields
one normal half and one sliver (a turning leaf or hand over that page), the
sliver is dropped with a warning naming the page for re-capture rather than
exported as a torn page. Scores are relative heuristics, not probabilities.

Cropping is two-stage and deterministic: a clean convex quadrilateral (a page
or spread seen edge-on against a plain background) is perspective-rectified;
otherwise the paper region - bright, barely saturated - is segmented with an
Otsu threshold plus a saturation guard, its tail columns/rows (a curled leaf
or a finger over the page) are dropped, and its bounding rectangle is cropped.
A spread is split at a dark binding valley detected inside the paper region;
sides without a real paper region are dropped, not emitted as furniture; the
outer edges of each page are trimmed against ink evidence. When neither quad
nor paper region is found the full frame is kept and flagged for review.
These cues are heuristics: a white tablecloth the same colour as the pages
can defeat the saturation guard, a dark page (photos, chapter plate) can
defeat the brightness mask, and a forced layout with no visible binding still
splits at the book centre.

## Web limits and integration

Defaults: 512 MB upload, 10 minutes of recording, 150 physical pages, 30 MP per
frame, and a 600-second processing timeout. Captures and PDF results expire
after the existing retention window (60 minutes). The uploaded video is deleted
after capture; previews remain until pruning. On a timeout, cooperative
cancellation stops at a frame/page boundary, and the shared worker stays busy
until the thread exits.

| Environment variable | Default |
|---|---|
| `VERISCRIPT_WEB_VIDEO_UPLOAD_MB` | 512 |
| `VERISCRIPT_WEB_VIDEO_MAX_PAGES` | 150 |
| `VERISCRIPT_WEB_VIDEO_MAX_SECONDS` | 600 |
| `VERISCRIPT_WEB_VIDEO_TIMEOUT_S` | 600 |
| `VERISCRIPT_WEB_VIDEO_PAGES_PER_CLIENT` | 200 |

Image capture has its own per-visitor daily allowance so a 100-page book can
be captured without the existing 20-page OCR allowance blocking it. Capture
also consumes the shared global page budget; OCR export consumes that budget
again and the existing per-visitor OCR allowance. Image export does not charge
OCR pages. For local full-book OCR, set
`VERISCRIPT_WEB_DAILY_PAGES_PER_CLIENT=150` (or `0` to disable that allowance)
before starting the server, and allow adequate processing time.

- `POST /api/video-scan`: multipart `file`, `layout`; returns run ID, warnings,
  expiration interval, and ordered page IDs with preview URLs.
- `GET /api/runs/{id}/video-pages/{page_id}`: captured JPEG preview.
- `POST /api/runs/{id}/video-export`: JSON
  `{"pages":[0,1],"searchable":false,"lang":"en"}`; selection order defines PDF order.
- `GET /api/runs/{id}/files/book.pdf?download=1`: final PDF.

These routes use the existing authentication, request limits, shared worker,
and run store. No client-supplied filesystem paths are accepted.

## Evidence and next acceptance gate

Automated tests use encoded synthetic videos to check stability/duplicate
handling, spread splitting, single-page overrides, duration/page limits,
ordering, a 100-page export, optional OCR plumbing, and web validation/budgets/
timeout cancellation. These fixtures do not establish accuracy on real books.

First real-book recording (2026-10-12, `BookVid/VeriOCR.mp4`; 39 s, 848x478,
hand-held, fast-paced English paperback). With the original fixed-anchor pixel
comparison, this video captured zero pages: hand-held wobble shifted the text
sub-pixel and every sample read as a page change. With the motion-tolerant
comparison, it captured 24 pages / 12 spreads; the printed page numbers read
58 through 82 in order, missing one steadily held spread (78/79, a chapter
end) and carrying one obstructed half (a turning leaf). The final seconds flip
from 88 to 92 without a full hold interval, so they are correctly not captured
and must be re-recorded in sections.

The same recording initially defeated the outer-boundary detector entirely -
the patterned background, low resolution and warm light meant every capture
kept the full frame (`cropped: false`), and the spread split cut at the frame
midpoint even though the book sat left of centre, so captured halves carried
carpet, a curled leaf, and slices of the neighbouring page. The 2026-10-12
crop rework (paper-mask segmentation plus gutter detection) fixes this on the
same footage: 23 pages are cropped to the paper region (`cropped: true`),
the binding cut lands on the gutter on every spread, and the one spread half
that is mostly a turning leaf (page 71 at t=20.13s) is dropped automatically
with an explicit warning (`Right side at t=20.13s is mostly covered (turning
leaf or hand); dropped - re-record that page.`) instead of exporting a torn
page. That page must be re-recorded; the drop is detectable, not repairable.

The page remains ~330x478 px in a half of an 848x478 frame; that is a
recording-resolution limit, not a cropping limit. Re-recording at 1080p or
4K raises it proportionally. The searchable-text layer at this resolution
reads layout, line order and page numbers reliably (24/24 pages carry text;
printed page numbers 58-82 all extractable), but body-word accuracy is
modest - e.g. the reader sees "farma disappeared and weee replaced by tidy
homes" for "farms disappeared and were replaced by tidy homes" - so the text
layer is a finding aid, not a transcription, until higher-resolution
recordings exist. Recorded searchable-export speed on this footage
(DirectML, RapidOCR): about 3.5-7.5 s/page depending on machine load,
including the 2.5x Lanczos upscale and the dual-stream audit pass; a
150-page book is a long export and the 600 s web timeout caps a searchable
export at roughly 80-150 pages on a fast machine - use `--video-review-only`
plus a batch OCR run for full books, or re-record in sections.

Still open before the gate can be closed: record representative Devanagari and
Nepali books with known page sequences, flag every missed/duplicate/obstructed
page and clipped text edge, and compare searchable-export OCR accuracy with
deliberately taken still photos of the same pages. Include curved bindings,
similar layouts, shadows, and ordinary camera movement.
