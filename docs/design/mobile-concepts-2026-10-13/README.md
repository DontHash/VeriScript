# VeriScript mobile theme concepts

Created 2026-10-13. The user selected **Paper & Ink as light mode** and **Night Studio as dark mode**. These are generated design concepts, not implemented screens or proof of APK feature parity.

Open `index.html` to compare the selected light and dark modes and inspect their exact palette values. Original generation prompts and palette tokens accompany the images. Clear Blue is retained as an unselected exploration.

## Selected theme system

**Light mode: A / Paper & Ink. Dark mode: C / Night Studio.** These are two appearances of one app. Keep the same screen structure, typography, spacing, controls, and feature access when switching modes; change the palette. The current raster boards are mood references and still show some layout differences to reconcile in the detailed screen designs.

Plan an Appearance setting with System, Light, and Dark options; default to System and remember a manual override. Keep captured document pages light in both modes. The selected mapping is recorded in `selected-theme.json`.

| Direction | Background | Surface | Main text | Primary action | Supporting color |
| --- | --- | --- | --- | --- | --- |
| A / Paper & Ink | #F4F0E6 | #FCFAF4 | #120E08 | #E8A200 | #D9D2C2 stone surface |
| C / Night Studio | #11151B | #1D2530 | #F4F1E8 | #F2B544 | #A6B2C3 secondary text |

The original A board uses 8dp corners and C uses 12dp; choose one shared corner scale in detailed screen design. Use Mukta for body text, controls, and Devanagari in both modes. Instrument Serif can remain a Latin display-heading accent in both modes; typography must not change when switching appearance.

Primary button foregrounds: light #120E08; dark #11151B. Do not use white text on amber.
Amber is an action/selection accent; error and warning status should also have explicit text and distinct semantics.

## Workflow decisions represented

- Home gives direct access to Scan document, Book from video, and Import image or PDF.
- Home / Files / Settings navigation and local recents are proposed mobile conveniences.
- Focused page review drops global navigation to make room for page thumbnails and export.
- Captured pages stay light in both modes.
- Book review supports inclusion/exclusion and reorder; expose Move up / Move down alternatives to dragging.
- Open-book spreads split into left then right pages; single-page capture stays available.
- PDF export offers Image, Searchable, and Typeset.

The two screens are representative. Detailed designs must cover every existing OCR, restoration, editing/correction, import, export, processing/cancellation, error/retry, and video-scan option before mobile feature parity can be claimed. The feature inventory should be checked against the current repository at that stage.

## Batch photo capture and document export

Requested 2026-10-13; planned mobile scope, not implemented APK behavior.

- Keep the camera open for successive page photos, with a captured-page count and thumbnail tray. Run final conversion after the user taps Done.
- Also allow multiple gallery images to be selected into the same document. Show their order explicitly before conversion.
- Save capture drafts and originals locally. Allow adding or retaking a page, deleting/excluding pages, reordering, and inspecting each page before export.
- Export selected pages into one combined document by default. Offer Image PDF (appearance), Searchable PDF (page images plus OCR text), and Typeset PDF (reflowed OCR text). Typeset PDF currently exists in the video-book workflow; applying it to photo batches is planned expansion.
- Add DOCX export: editable OCR text as the primary Word option, with an optional image-per-page document for preserving appearance. Editable DOCX cannot promise exact reproduction of complex tables or page layout. DOCX is a new feature, not current web parity.
- Keep existing text/Markdown exports available where applicable. Allow correction of OCR before searchable, typeset, or editable output.

## Automatic geometry and page review

For mobile, plan automatic orientation, small-angle straightening, and page boundary detection/crop with perspective correction when supported by the capture pipeline. Expose manual rotation and crop adjustment in review, and retain originals so users can recover from a bad automatic result.

Verified web baseline: autoRotate starts enabled in `webapp/frontend/src/lib/studio-state.ts`; deskew starts disabled. `veriscript/document/restore.py` estimates small skew within +/-8 degrees. Video scanning already crops detected page regions, rectifies quadrilaterals when found, and supports left/right spread splitting. This is not general curved-page dewarping, hand removal, or a guarantee of perfect alignment. Still-photo boundary detection and manual crop review must be implemented for mobile.

## Provisional Android hardware targets

These are engineering targets for an offline processing build, not measured minimum requirements or framework limits. Confirm them only after selecting the mobile OCR/runtime and testing an APK on physical phones.

| Item | Initial minimum target | Recommended |
| --- | --- | --- |
| Android | Android 10+ proposed app baseline | Android 12+ |
| CPU | 64-bit ARM processor; exact floor unmeasured | Recent midrange 64-bit ARM processor |
| RAM | 4 GB device RAM | 6 GB+ for video-book processing |
| Free storage | 2 GB initial working-space target | 4 GB+ for video and large batches; depends on source size |
| Camera | Autofocus and legible page capture | Clear 1080p video for book scanning; good light |

No dedicated GPU should be required for the baseline; verify this against the chosen OCR runtime. Internet requirements remain dependent on architecture: offline operation requires all necessary models on-device; server processing reduces phone workload but requires network access. Model/download size and final APK size are not established.

Store full-resolution captures on disk, show downsampled thumbnails, process a bounded number of pages at once, and sample video frames without loading a whole video into RAM. A 4000x3000 ARGB_8888 image consumes about 48 MB before OCR/intermediate buffers ([Android bitmap memory guidance](https://developer.android.com/topic/performance/memory/guide/bitmaps)). Draft persistence and recovery must survive app backgrounding/process termination.

Validate the requirements with multi-photo PDF/DOCX exports, Nepali/Hindi/English OCR, and real book video on 4 GB and 6 GB phones. Measure peak app memory, duration, storage, heat, and recovery before publishing a supported-device floor.

## Implementation rules for the selected theme

- At least 48dp touch targets and visible labels alongside icons.
- Primary actions near the bottom, with Android safe-area and keyboard clearance.
- Page tap opens an inspection view; don't force users to assess OCR or crop quality from thumbnails.
- Use Mukta for English, Nepali, and Hindi. Restrict Instrument Serif to supported Latin headings.
- Meet WCAG AA text contrast and check focus/selection visibility on actual screens.
- Keep primary controls, selection states, and feedback consistent across every workflow.
- Use flat exact tokens from palettes.json. The raster concepts contain illustrative content, fictional recents, and incidental shading; they are not pixel specifications.
- Validate on a real Android device after implementation, including font scaling, small screens, permissions, and long-running video processing.

## Generation and files

Mode: built-in imagegen, three independent generations with the same Home and Review screen brief.
Prompts: generation-prompts.json.
Images: a-paper-and-ink.png, b-clear-blue.png, c-night-studio.png.
Comparison: index.html.
Tokens: palettes.json. Selected mode mapping: selected-theme.json.

The application source was not changed by this design exploration.

