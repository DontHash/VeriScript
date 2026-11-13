# VeriScript UX & Accessibility Audit + Improvement Plan

Date: 2026-11-13 · Scope: web studio (`webapp/frontend`), Android app (`mobile/`),
desktop packaging (`packaging/`), CI and release.

**Method.** This is a code-level audit: every frontend component, the Flutter
screens, theme tokens, CI workflows and packaging were read. Color contrast was
computed from the tokens (WCAG 2.x formula). Nothing was run with a screen
reader (NVDA or TalkBack), on a phone, or in a browser yet. Phase 0 includes
that manual pass.

---

## 1. Executive summary

VeriScript's engine and honesty about accuracy are strong. The product around
it is not yet at a professional level. Five things hold it back:

1. **There is no desktop app.** "Desktop" today means a CLI plus a
   `localhost` web studio started with `python webapp/server.py`.
   `packaging/veriscript.spec` builds only the console CLI and says so. A normal
   user cannot install and launch VeriScript.
2. **WCAG 2.1 AA failures in core flows.** The focus ring is nearly invisible
   (1.92:1), some text and field borders fail contrast, the tab widgets have the
   wrong semantics, run progress is never announced, and on Android cropping can
   only be done by dragging.
3. **The UI is English-only.** The product is "Devanagari first", yet neither
   app has a single localized string. Nepali and Hindi speakers get an English
   interface.
4. **Long jobs give no feedback.** OCR and video runs show an indeterminate bar
   with no stages and no cancel. A page refresh loses the run and all staged
   corrections.
5. **Weak quality gates for the UI.** There are no frontend tests, the build
   does no typecheck or lint, Flutter is not in CI, and there are no automated
   a11y checks.

---

## 2. Findings

Severity: **S1** blocks a user or fails WCAG AA · **S2** significant friction ·
**S3** polish.

### 2.1 Web studio: accessibility

| # | Sev | Finding | Where |
|---|-----|---------|-------|
| W1 | S1 | Focus ring is `--accent` amber `#e8a200` on paper `#f4f0e6`, which is **1.92:1**. WCAG 1.4.11 / 2.4.7 need ≥ 3:1, so keyboard users cannot see focus. | `styles/base.css:47`, `tokens.css:137` |
| W2 | S1 | The review input sets `outline: none` and only changes the border to amber (also about 2:1). This is the main keyboard workflow, and its focus is effectively invisible. | `styles/components.css:435-437` |
| W3 | S1 | Field and button borders `--line-strong` are 2.42:1 (fails 1.4.11 at 3:1). *Corrected after the Phase 0 axe run:* `--text-4` (3.96:1) is used only for disabled buttons, which WCAG exempts, and `--flag-amber` (2.95:1) is used only for a dot next to a text label. Keep both away from text. | `tokens.css` |
| W4 | S1 | The "Photo or PDF / Book video" switch uses `aria-pressed` buttons inside a `div` that has an `aria-label` but no role, and the panels are toggled with `hidden`. It should be a radio group or a proper tablist. | `routes/Studio.tsx:22` |
| W5 | S1 | Result tabs have `role="tab"` but no `tabpanel`, no `aria-controls`/`id`, no arrow-key or Home/End navigation, and no roving `tabindex`. | `components/StudioResults.tsx:72` |
| W6 | S1 | Run state is not announced. The button text "Reading… 3.4s" changes 10 times a second, which is noisy if read and is not a live region. Completion is silent. Focus is not moved to the results or to the error. | `StudioPanel.tsx:177`, `studio-state.ts` |
| W7 | S2 | The "More options" disclosure has no `aria-expanded`/`aria-controls`. Advanced options are **open by default** (`advancedOpen = true`), which pushes the main action down. | `StudioPanel.tsx:73`, `studio-state.ts` |
| W8 | S2 | Compare slider: no `aria-valuetext` (it reads "50" with no unit). Pointer drag does not move focus to the handle. The keyboard step of 2% is slow, and Page Up/Down are not supported. | `CompareSlider.tsx` |
| W9 | S2 | Review rows: the original token is plain text with no image crop, so a screen reader user and a sighted user both review a guess without seeing the source. Flags carry meaning by color dot plus label, which is OK, but the "Staged" state is not announced. | `CorrectionReview.tsx` |
| W10 | S2 | The paste handler is global (`document` listener). Pasting an image while in *Book video* mode silently loads it into the hidden page panel. | `DropZone.tsx` |
| W11 | S2 | Download links are glyph-led ("↓ ocr.json"). Screen readers read "down arrow". They also give no description of what each file is or how big it is. | `StudioResults.tsx` |
| W12 | S3 | Video page preview links open a new tab with no warning (`target=_blank`). | `VideoScanner.tsx` |

### 2.2 Web studio: UX

| # | Sev | Finding |
|---|-----|---------|
| W13 | S1 | **No cancel** for page runs or video capture/export, and no staged progress (upload → orientation → layout → OCR → digit check → export). Book runs can take minutes. |
| W14 | S1 | **State is lost on refresh or navigation.** The run, staged corrections and video ordering all disappear, and there is no `beforeunload` guard while corrections are unsaved. |
| W15 | S2 | The copy is still written for the retired hosted demo: "files deleted after the demo", "This demo runs here", "Processing happens on the server running this studio". Run locally, this wording is confusing and undermines the offline promise. (`Landing.tsx:48,108`, `Footer.tsx:55`, `Studio.tsx`) |
| W16 | S2 | Only one file at a time. Drop takes `files[0]` and silently ignores the rest. There is no client-side type or size check before upload. |
| W17 | S2 | No run history ("Recent documents"). Results expire with no countdown shown. |
| W18 | S2 | No "Download all (.zip)". There are nine separate links. |
| W19 | S2 | Raw server errors are shown verbatim, with no recovery action (retry, or pick a different engine or language). |
| W20 | S3 | No dark mode on web (Android has one). No keyboard-shortcut help, although the review queue has shortcuts (Enter, Esc, ↑/↓). |

### 2.3 Android app: accessibility

| # | Sev | Finding | Where |
|---|-----|---------|-------|
| A1 | S1 | **Crop corners are drag-only** (`GestureDetector.onPanUpdate`). TalkBack and switch-access users cannot crop, which fails WCAG 2.5.7. There is a `Semantics` label but no increase/decrease or custom actions. | `lib/editor.dart:534` |
| A2 | S1 | Very little semantics overall. Across about 3,500 lines of UI there are only 14 `Semantics`/`tooltip` uses. Library cards (`InkWell` in a `Card`), page thumbnails and status chips have no merged semantic labels or state. | `main.dart`, `review.dart` |
| A3 | S1 | The recording timer and the "Saving…" state are not live regions. A blind user does not know recording started or how long it has run. | `lib/capture.dart:252` |
| A4 | S2 | Errors are raw exceptions (`e.toString()`, `'Could not delete document: $e'`) in snackbars. They are not human-readable and are announced with stack-like text. | `capture.dart:196,209`, `editor.dart:101,152`, `main.dart` |
| A5 | S2 | Only **Mukta Regular** is bundled, but 6+ places use `FontWeight.w600/w700`. Flutter synthesizes a fake bold, which renders Devanagari matras poorly and weakens hierarchy. | `pubspec.yaml`, `main.dart` |
| A6 | S2 | 12 sp text for the "ON DEVICE" label and the crop corner numbers. Large text-scale settings are only partly handled (`textScalerOf` appears in 2 places). Layouts were not checked at 200%. | `main.dart:451`, `editor.dart` |
| A7 | S3 | The dark-mode amber primary is used as a full card fill for "Camera". Check focus and contrast states on the `onPrimary` subtitle text. |

### 2.4 Android app: UX

| # | Sev | Finding |
|---|-----|---------|
| A8 | S2 | No first-run onboarding or permission rationale before the camera prompt. The "ON DEVICE" label is the only privacy explanation. |
| A9 | S2 | Destructive delete uses a confirm dialog only. A better pattern is to soft-delete with **Undo** in a snackbar for about 5 seconds, then delete the files. |
| A10 | S2 | `review.dart` (927 lines) and `main.dart` (814 lines) mix screens, dialogs and state. That slows UI iteration and makes widget tests brittle. |
| A11 | S3 | No haptic or shutter feedback on capture. No edge-detection overlay on the live preview (it is applied only after capture). |
| A12 | S1 (release) | Debug-key signing and version `0.1.0+1`. There is no Play-ready release pipeline, and APKs sit loose in the repo root. |

### 2.5 Cross-cutting

| # | Sev | Finding |
|---|-----|---------|
| X1 | S1 | **No localization** on either platform. Add Nepali and Hindi UI, with an option for Devanagari numerals in UI counts. |
| X2 | S1 | **No real desktop app.** No installer, no window, no file association, and "start a server" is the launch step. |
| X3 | S2 | The two design systems drift. The web tokens and the Flutter `studioTheme` duplicate hex values by hand, and Instrument Serif was removed on web but kept on mobile. |
| X4 | S2 | Quality gates: the frontend `build` is `vite build` only (no `tsc --noEmit`, no lint, no tests). CI has no Flutter job. There are no axe or Flutter accessibility-guideline tests. |
| X5 | S3 | Repo hygiene: a large uncommitted diff (40+ files), emulator logs in `mobile/`, and APKs at the root. Commit a checkpoint before refactoring. |

---

## 3. Improvement plan

Each phase ends in something shippable. The estimates are for one developer.

### Phase 0: Baseline and gates (2–3 days)

1. Commit or stash the current work-in-progress diff (X5).
2. Web: add `tsc --noEmit` to `build`, and add Playwright plus `@axe-core/playwright` smoke tests for `/` and `/studio` (idle, done and error states). Fail CI on serious or critical violations.
3. Flutter: add a CI job running `flutter analyze` and `flutter test`. Add widget tests using `androidTapTargetGuideline`, `labeledTapTargetGuideline` and `textContrastGuideline` for Library, Review, Editor and Capture.
4. Do a manual pass with a screen reader (NVDA + Chrome on web, TalkBack on Android) and at 200% text scale. Record the results in `docs/A11Y_CHECKLIST.md` and re-run that checklist each release.

### Phase 1: Accessibility blockers (1 week). Target: WCAG 2.1 AA on core flows

- **Tokens (W1–W3):** use a two-tone focus ring (`2px solid ink-900` plus a `4px amber` halo) so it is ≥ 3:1 on every surface. Darken `--text-4` to about `#6b6457` (≥ 4.5:1). Never use `--flag-amber` for text; add `--flag-amber-text` at about `#8a6200`. Darken `--line-strong` to ≥ 3:1 for form controls. Remove `outline:none` on `.review__input`.
- **Widgets (W4–W8):** build one accessible `Tabs` primitive (tablist/tab/tabpanel, roving tabindex, arrows and Home/End) and use it in both places. Make the mode switch a radio group. Add `aria-expanded` to the disclosure and close it by default. Add `aria-valuetext` ("62% input shown") and Page Up/Down to the slider.
- **Announcements (W6):** add one app-level polite live region with messages like "Reading page…", "Done: 214 tokens, 9 flagged" and the error text. Move focus to the results heading or to the alert. Show the elapsed time outside the button and keep it out of the accessibility tree.
- **Android (A1–A6):** add custom semantics actions to the crop corners (move up, down, left, right by 1% or 5%) and a visible "fine-adjust" control with arrow buttons. Wrap cards and thumbnails in `MergeSemantics` with state ("Page 3, recognized, 2 numbers to check"). Make the recording timer `Semantics(liveRegion: true)`. Bundle Mukta SemiBold and Bold. Use a 14 sp minimum. Map exceptions to human messages through one `friendlyError()` helper.

### Phase 2: A real desktop app (2–3 weeks)

**Recommended: a Tauri 2 shell around the existing Solid studio, with the Python engine as a PyInstaller "sidecar".** It reuses 100% of the current UI, ships a small native installer (MSI/NSIS, DMG, AppImage) and keeps everything offline.

- The shell starts the sidecar on a random `127.0.0.1` port with a per-launch token, waits for `/api/health`, and stops it on exit.
- Native file open and save dialogs. "Open with VeriScript" for PDF and image files. Drag files onto the window or the dock icon.
- Local mode flag from `/api/health` (`mode: "local"`), so all "demo" and "server" copy (W15) switches to local wording, and the retention window becomes "kept until you delete".
- Code signing (Windows Authenticode, macOS notarization). Updates are opt-in only, so the offline promise holds.
- Alternative if Rust tooling is unwanted: **pywebview** in the same PyInstaller bundle. This is faster to ship, with less native polish.

### Phase 3: Workflow UX (2 weeks)

- **Progress and cancel (W13):** move runs to a job model (`POST /api/jobs` → `GET /api/jobs/{id}` or SSE with stage and percent, plus `DELETE` to cancel). Show a stepper: Upload → Orient → Layout → Read → Check digits → Export. Use the same model for video.
- **Persistence (W14, W17):** save the run ID, staged corrections and video order to IndexedDB. Add a "Recent" list. Warn on `beforeunload` while there are unapplied corrections.
- **Batch input (W16):** queue multiple files and validate type and size on the client with clear messages.
- **Review queue (W9):** show the token crop beside each row. Click a row to highlight the box on the overlay. Add a `?` shortcut sheet. Add an Undo stack across the whole session.
- **Downloads (W11, W18):** add "Download all (.zip)" and a file list with a description, size and icon. Give each file an accessible name ("Searchable PDF, 1.2 MB").
- **Errors (W19, A4):** use one error catalogue shared by the API and both clients. Each error has a code, human text and a recovery action.
- **Android (A8, A9, A11):** two-screen onboarding (privacy and permissions), Undo for delete, haptic on capture, and a live edge overlay if CPU allows.

### Phase 4: Localization and design-system unification (1–2 weeks)

- Web: lightweight i18n (`@solid-primitives/i18n`) with `en`, `ne` and `hi` catalogues. Set `<html lang>` per locale and `lang` on Devanagari tokens.
- Flutter: `flutter_localizations` plus ARB files for the same three languages. Follow the device locale, with an in-app override.
- Native-speaker review of every string (do not ship machine translation unchecked).
- **Single token source (X3):** a `design/tokens.json` file that generates `tokens.css` and `lib/theme_tokens.dart`, with contrast checks run in CI. Add a web dark theme from the same tokens (W20).

### Phase 5: Release polish (1 week)

- Android: release keystore, versioning from git tags, Play listing assets, and a store accessibility statement. Remove the APKs from the repo root and publish them as release assets.
- Split `review.dart` and `main.dart` into per-screen files (A10).
- Add an accessibility statement and a feedback contact on both platforms.

---

## 3a. Phase 0 results (2026-11-13)

The gates are in place (see [A11Y_CHECKLIST.md](A11Y_CHECKLIST.md)). The automated
baseline found three issues the code read had missed:

- **W21 (S1, axe `label`, critical):** the hidden file `<input>` in `DropZone.tsx`
  has no accessible name. It appears on every studio state.
- **W22 (S2, axe `label-content-name-mismatch`, serious):** the visible text is not
  part of the accessible name on the landing page, studio idle and the transcript
  tab. Examples are the wordmark's `aria-label`, the drop zone, and the copy
  button.
- **A13 (S1, Flutter `textContrastGuideline`):** the crop screen's amber "Apply"
  `TextButton` is 1.92:1 in the light theme. This is the same amber-on-paper
  root cause as W1.

Known debt is recorded in `webapp/frontend/e2e/a11y-baseline.json`, in the
`test.fail()` lines in `e2e/keyboard.spec.ts` (W1, W5, W6, W7), and in
`knownDebt` plus the A1 test in `mobile/test/a11y_guidelines_test.dart`.
Phase 1 is done when all three are empty.

## 4. Definition of done (measurable)

- axe: 0 serious or critical violations on all studio states. Lighthouse Accessibility ≥ 95.
- Flutter guideline tests pass on Library, Capture, Editor, Review and Settings.
- The manual NVDA and TalkBack scripts can complete **capture → crop → recognize → fix a digit → export** without sight.
- Every interactive control is ≥ 44×44 CSS px on web and ≥ 48 dp on Android, and every text or non-text contrast pair meets AA (enforced by the token CI check).
- A desktop installer launches to a working studio on a clean Windows machine with networking disabled.
- Cancelling any run takes less than 1 s. A page refresh restores the in-progress review.

## 5. Suggested order of work

Phase 0 → Phase 1 (fastest user-visible win, low risk) → Phase 2 and Phase 3
(these can run in parallel because they touch different code) → Phase 4 → Phase 5.
