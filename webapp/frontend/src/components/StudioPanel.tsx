import { createEffect, For, Show } from "solid-js";
import { DropZone } from "./DropZone";
import { EXAMPLE_FILES, limitsLine, type StudioState } from "../lib/studio-state";
import type { Lang, OcrEngine } from "../lib/types";

/** The studio controls: drop a page, pick an example, set options, run.
 *  `compact` is the homepage hero treatment. */
export function StudioPanel(props: { state: StudioState; compact?: boolean }) {
  const s = props.state;
  const running = () => s.phase() === "running";
  const suffix = props.compact ? "hero" : "page";
  let alertEl: HTMLDivElement | undefined;

  // Move focus to a new error so keyboard and screen-reader users land on it.
  createEffect(() => {
    if (s.phase() === "error" && s.error()) queueMicrotask(() => alertEl?.focus());
  });

  return (
    <div class="panel">
      <DropZone
        file={s.file()}
        onFiles={s.chooseFiles}
        onClear={s.clearFile}
        disabled={running()}
      />

      <Show when={s.notice()}>
        <p class="field__hint" role="status">
          {s.notice()}
        </p>
      </Show>

      <div class="panel__examples">
        <p class="field__hint">Or try a real example</p>
        <div class="button-row">
          <For each={EXAMPLE_FILES}>
            {(ex) => (
              <button
                class="btn btn--ghost btn--small"
                type="button"
                disabled={running()}
                onClick={() => void s.pickExample(ex.path, ex.name)}
              >
                {ex.label}
              </button>
            )}
          </For>
        </div>
      </div>

      <div class="panel__options">
        <div class="field">
          <label class="field__label" for={`lang-${suffix}`}>
            Language
          </label>
          <select
            id={`lang-${suffix}`}
            class="select"
            value={s.lang()}
            disabled={running()}
            onChange={(e) => s.setLang(e.currentTarget.value as Lang)}
          >
            <option value="ne">Nepali (Devanagari)</option>
            <option value="hi">Hindi (Devanagari)</option>
            <option value="en">English / Latin</option>
          </select>
        </div>

        <label class="checkbox">
          <input
            type="checkbox"
            checked={s.deskew()}
            disabled={running()}
            onChange={(e) => s.setDeskew(e.currentTarget.checked)}
          />
          <span>Deskew small rotations</span>
        </label>

        <button
          class="btn btn--ghost btn--small"
          type="button"
          aria-expanded={s.advancedOpen()}
          aria-controls={`options-${suffix}`}
          disabled={running()}
          onClick={() => s.setAdvancedOpen(!s.advancedOpen())}
        >
          {s.advancedOpen() ? "Fewer options" : "More options"}
        </button>
      </div>

      <div class="stack-16" id={`options-${suffix}`} hidden={!s.advancedOpen()}>
        <div class="field">
          <label
            class="field__label"
            for={`ocr-${suffix}`}
          >
            OCR engine
          </label>
          <select
            id={`ocr-${suffix}`}
            class="select"
            value={s.ocr()}
            disabled={running()}
            onChange={(e) => s.setOcr(e.currentTarget.value as OcrEngine)}
          >
            <option value="auto">Auto (best available)</option>
            <option value="rapidocr">RapidOCR (recommended)</option>
            <option value="tesseract">Tesseract (optional install)</option>
          </select>
        </div>

        <label class="checkbox">
          <input
            type="checkbox"
            checked={s.autoRotate()}
            disabled={running()}
            onChange={(e) => s.setAutoRotate(e.currentTarget.checked)}
          />
          <span>Auto-rotate sideways / upside-down pages</span>
        </label>

        <label class="checkbox">
          <input
            type="checkbox"
            checked={s.allPages()}
            disabled={running()}
            onChange={(e) => s.setAllPages(e.currentTarget.checked)}
          />
          <span>All pages of a PDF (first page by default)</span>
        </label>

        <div class="field">
          <span class="field__label">Files to write</span>
          <div class="button-row">
            <label class="checkbox">
              <input
                type="checkbox"
                checked={s.wantOverlay()}
                disabled={running()}
                onChange={(e) => s.setWantOverlay(e.currentTarget.checked)}
              />
              <span>Overlay</span>
            </label>
            <label class="checkbox">
              <input
                type="checkbox"
                checked={s.wantPdf()}
                disabled={running()}
                onChange={(e) => s.setWantPdf(e.currentTarget.checked)}
              />
              <span>Searchable PDF</span>
            </label>
            <label class="checkbox">
              <input
                type="checkbox"
                checked={s.wantTxt()}
                disabled={running()}
                onChange={(e) => s.setWantTxt(e.currentTarget.checked)}
              />
              <span>Transcript</span>
            </label>
            <label class="checkbox">
              <input
                type="checkbox"
                checked={s.wantMd()}
                disabled={running()}
                onChange={(e) => s.setWantMd(e.currentTarget.checked)}
              />
              <span>Markdown</span>
            </label>
          </div>
        </div>
      </div>

      <Show when={!props.compact}>
        <p class="field__hint">
          The wrong script lowers accuracy; it is not detected per token. Devanagari models
          download once, then run offline.
        </p>
      </Show>

      <div class="runbar">
        <button
          class="btn btn--primary btn--block"
          type="button"
          disabled={!s.file() || running()}
          onClick={() => void s.start()}
        >
          {running() ? "Reading…" : "Restore and read"}
        </button>
        <Show when={running()}>
          <button class="btn btn--ghost btn--small" type="button" onClick={() => s.cancel()}>
            Cancel
          </button>
          <div class="progress" role="progressbar" aria-label="Reading the page">
            <div class="progress__fill" />
          </div>
          {/* Ticks 10×/s: visible only, the live region announces start/end. */}
          <span class="runbar__elapsed" aria-hidden="true">
            {s.elapsed().toFixed(1)} s
          </span>
        </Show>
        <div class="runbar__status">
          <span>{limitsLine(s.health())}</span>
          <Show when={s.health()?.busy}>
            <span>The engine is busy. Your page will start when it is free.</span>
          </Show>
        </div>
      </div>

      <Show when={s.phase() === "error" && s.error()}>
        <div class="alert" role="alert" tabindex={-1} ref={alertEl}>
          {s.error()}
        </div>
      </Show>
    </div>
  );
}
