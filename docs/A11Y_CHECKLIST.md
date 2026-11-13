# Accessibility release checklist

Run this before every release, on both platforms, and record the result in the
log at the bottom. The automated gates catch regressions in what they can
measure; this checklist covers what only a person can judge (whether
announcements make sense, whether a flow can actually be completed).

Background and finding IDs (W1, A1, …): [UX_A11Y_AUDIT.md](UX_A11Y_AUDIT.md).

## Automated gates (CI, every push)

| Gate | Command | What it covers |
|------|---------|----------------|
| Web typecheck | `npm run build` in `webapp/frontend` | `tsc --noEmit` before `vite build` |
| Web axe | `npm run test:e2e` in `webapp/frontend` | WCAG 2.0/2.1 A+AA on landing, studio idle, video, error and each result tab, at desktop and phone width. Debt ratchet: `e2e/a11y-baseline.json` |
| Web keyboard | same | Skip link, focus visibility ≥ 3:1, tab arrow keys, live-region announcement, disclosure state (known debt marked `test.fail`) |
| Android guidelines | `flutter test` in `mobile` | Tap targets ≥ 48 dp, labelled tap targets, text contrast on Home, Files, Settings and Crop in both themes. Debt ratchet: `knownDebt` in `test/a11y_guidelines_test.dart` |

**Ratchet rule:** never add an entry to a baseline to make CI pass on new code.
Baselines only shrink. When a fix makes a baseline entry stale, CI fails until
you delete the entry.

## Manual pass: web studio (NVDA + Chrome, Windows)

Setup: NVDA latest, Chrome stable, browser zoom 100%, no mouse.

- [ ] **Tab order**: the first Tab reaches "Skip to content", and Enter moves into main. Every control is reachable in a logical order with a clearly visible focus ring.
- [ ] **Upload**: the drop zone is announced as a button with its purpose. Choosing a file announces the file name. Remove ("✕") is announced as "Remove file".
- [ ] **Options**: "More options" announces expanded or collapsed. Every select and checkbox reads its label.
- [ ] **Run**: starting a run announces that it started. Completion announces the result (tokens, flagged). An error is announced and focus can reach it.
- [ ] **Results tabs**: announced as tabs with a count ("tab 2 of 4"). Arrow keys move between tabs and the panel content follows.
- [ ] **Compare slider**: announced as a slider with a meaningful value. Arrow keys and Home/End move it.
- [ ] **Review queue**: each input reads the original token. Enter stages a correction, Esc reverts, and ↑/↓ move between rows. Staging is announced.
- [ ] **Downloads**: each link reads a file type and name, not "down arrow".
- [ ] **Video mode**: you can choose a video, reorder pages with Earlier/Later, and export, all without a mouse.
- [ ] **Zoom**: at 200% browser zoom and at a 320 px width there is no horizontal scroll and no clipped controls.
- [ ] **Reduced motion**: with OS "reduce motion" on, the progress bar and transitions do not animate.

## Manual pass: Android (TalkBack)

Setup: a physical phone if available, otherwise the emulator. TalkBack on. Font size and display size at maximum for the second pass.

- [ ] **Home**: every card announces its title and purpose ("Scan pages, button"). "ON DEVICE" is readable.
- [ ] **Capture**: the shutter is announced, a capture is confirmed audibly, and the recording timer is announced or can be queried.
- [ ] **Crop**: all four corners can be moved **without dragging** (A1). Apply and Reset are reachable.
- [ ] **Review**: page thumbnails announce their page number and status. Move up/down is announced with the page number.
- [ ] **Digit check**: each flagged number reads both readings and its state (conflict, unclear, agree).
- [ ] **Export**: the format choice and the share sheet can be completed with TalkBack.
- [ ] **Errors**: messages are human sentences, not exception text (A4).
- [ ] **Large text**: at maximum font size and display size, no text is clipped and every screen still scrolls to every control.
- [ ] **Dark theme**: repeat Home, Crop and Review in Night Studio.

**End-to-end flow (must pass blind):** capture → crop → recognize → fix one
digit → export a PDF. Record the time taken and any point where you had to look.

## Log

| Date | Version | Platform | Tester | Result | Notes / issues filed |
|------|---------|----------|--------|--------|----------------------|
| 2026-11-13 | 0.1.0 | Web + Android | automated baseline only | 8 web states and 1 Android screen carry known debt | No manual pass yet. Debt recorded in the baselines. |
