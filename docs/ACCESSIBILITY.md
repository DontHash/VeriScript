# Accessibility statement

VeriScript aims to be usable by everyone who needs to turn paper into
searchable text, including people who use screen readers, keyboards, switch
access, large text or high contrast.

## Target

**WCAG 2.1 level AA** for the web studio, the desktop app (the same studio
in a native window) and the Android app.

## How it is checked

On every change, CI runs:

- **axe-core** on every studio state (idle, video, error, each result tab),
  in light and dark themes, at desktop and phone widths. Serious or critical
  violations fail the build.
- **keyboard tests**: skip link, a visible focus indicator with at least
  3:1 contrast on every focus stop, arrow keys in tabs, live announcements,
  and disclosure state.
- **Flutter accessibility guidelines** on the Android screens in both themes:
  tap targets of at least 48 dp, labelled controls and text contrast.
- **colour tokens**: 20 foreground/background pairs checked against their
  WCAG minimums in both palettes.

Before each release, a person runs the manual
[NVDA and TalkBack checklist](A11Y_CHECKLIST.md). The release is not done
until a blind user can complete capture → crop → recognize → fix a digit →
export.

## What works today

- Full keyboard use of the studio, with visible focus and the tabs pattern
  from WAI-ARIA.
- Screen-reader announcements when a page starts, finishes, fails or is
  cancelled, and for each review action.
- Review rows read the token, its flags and its confidence. Each row shows
  the page pixels next to the token, so a reading can be checked against the
  source.
- On Android, crop corners can be moved without dragging: use TalkBack
  actions, or pick a corner and use the arrow buttons.
- Errors are written as sentences that say what to do next.
- Light and dark themes, both meeting contrast.

## Known limitations

- **Interface language:** English only for now. Nepali and Hindi are planned
  and need a native-speaker review first ([I18N_PLAN.md](I18N_PLAN.md)).
- **Android font weights:** only Mukta Regular is bundled, so bold Devanagari
  text is synthesized.
- **Progress:** long runs show elapsed time but not the pipeline stage.
- **Manual testing:** the NVDA and TalkBack passes are pending on physical
  devices. The automated checks above pass.

## Feedback

If something gets in your way, please open an issue at
<https://github.com/DontHash/VeriScript/issues> with the `accessibility`
label. Say which app, what you were trying to do, and which assistive
technology you use. Accessibility problems are treated as bugs.
