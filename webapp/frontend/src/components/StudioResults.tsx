import { createMemo, createSignal, For, onMount, Show } from "solid-js";
import { CodeBlock } from "./CodeBlock";
import { CompareSlider } from "./CompareSlider";
import { CorrectionReview } from "./CorrectionReview";
import { TabPanel, Tabs } from "./Tabs";
import { retentionText } from "../lib/health";
import { type StudioState } from "../lib/studio-state";
import type { RunFiles } from "../lib/types";

type Tab = "compare" | "queue" | "transcript" | "files";

/** Every downloadable artifact of a run, in display order. */
const DOWNLOADS: { key: keyof RunFiles; name: string; what: string }[] = [
  { key: "pdf", name: "searchable.pdf", what: "Searchable PDF" },
  { key: "combined_pdf", name: "combined.pdf", what: "Searchable PDF, all pages" },
  { key: "restored", name: "restored.png", what: "Cleaned page image" },
  { key: "overlay", name: "overlay.png", what: "Review overlay image" },
  { key: "txt", name: "transcript.txt", what: "Plain-text transcript" },
  { key: "combined_txt", name: "combined.txt", what: "Plain-text transcript, all pages" },
  { key: "md", name: "transcript.md", what: "Markdown transcript" },
  { key: "combined_md", name: "combined.md", what: "Markdown transcript, all pages" },
  { key: "json", name: "ocr.json", what: "OCR data: tokens, flags and review queue" },
  {
    key: "tables_xlsx",
    name: "tables.xlsx",
    what: "Tables as a spreadsheet; numbers to check are highlighted and listed",
  },
  { key: "tables_csv", name: "tables.csv", what: "Tables as CSV" },
  {
    key: "phone_reading",
    name: "phone_reading.json",
    what: "What the phone read, with the corrections made there",
  },
];

/** Everything a finished run produces, organised in tabs. */
export function StudioResults(props: { state: StudioState }) {
  const s = props.state;
  const [tab, setTab] = createSignal<Tab>("compare");
  let heading: HTMLHeadingElement | undefined;

  // A finished run replaces the idle stage: move focus to its heading so
  // keyboard and screen-reader users start reading at the results. A result
  // restored on page load is not announced and does not take focus.
  onMount(() => {
    if (s.restoredAt() === null) heading?.focus();
  });

  const afterUrl = createMemo(() => {
    const p = s.result();
    if (!p) return null;
    return s.showBoxes() && p.files.overlay ? p.files.overlay : p.files.restored;
  });

  const tabs = createMemo(() => {
    const n = s.result()?.review.length ?? 0;
    return [
      { id: "compare" as const, label: "Compare" },
      { id: "queue" as const, label: `Review queue (${n})` },
      { id: "transcript" as const, label: "Transcript" },
      { id: "files" as const, label: "Files" },
    ];
  });

  return (
    <Show when={s.result()}>
      {(result) => (
        <section class="results__panel" aria-labelledby="results-heading">
          <h2 class="h3" id="results-heading" tabindex={-1} ref={heading}>
            Results
          </h2>
          <dl class="stats">
            <div>
              <dt class="stat__label">Time</dt>
              <dd class="stat__value">{result().meta.seconds.toFixed(1)} s</dd>
            </div>
            <div>
              <dt class="stat__label">Tokens</dt>
              <dd class="stat__value">{result().meta.n_tokens}</dd>
            </div>
            <div>
              <dt class="stat__label">Flagged</dt>
              <dd class="stat__value stat__value--accent">{result().meta.flagged}</dd>
            </div>
            <div>
              <dt class="stat__label">Digit conflicts</dt>
              <dd class="stat__value">{result().meta.digit_conflicts}</dd>
            </div>
            <Show when={result().meta.pages_processed > 1}>
              <div>
                <dt class="stat__label">Pages</dt>
                <dd class="stat__value">{result().meta.pages_processed}</dd>
              </div>
            </Show>
          </dl>

          <Show when={s.restoredAt()}>
            {(at) => (
              <p class="field__hint" role="status">
                {s.openedTitle() ? `${s.openedTitle()}, from your library: saved ` : "Your last result, from "}
                {new Date(at()).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}.
                The original image is not kept in the browser, so Compare shows the result only.
              </p>
            )}
          </Show>
          <Show when={result().meta.from_phone}>
            {(phone) => (
              <p class="field__hint" role="status">
                From the phone app: {phone().pages} {phone().pages === 1 ? "page" : "pages"}, read again
                here. {phone().corrected_lines + phone().confirmed_lines > 0
                  ? `${phone().corrected_lines} corrected and ${phone().confirmed_lines} confirmed lines from the phone are shown beside the matching words in Review, and kept in phone_reading.json. They were not copied into this reading.`
                  : "No lines were corrected on the phone."}
              </p>
            )}
          </Show>
          <Show when={result().meta.resized}>
            <p class="field__hint">
              Large page: downscaled to 2500 px before processing; the review boxes
              match the processed size.
            </p>
          </Show>
          <Show when={result().meta.pages_capped}>
            <p class="field__hint">
              Only the first {result().meta.page_cap} pages were processed — split
              larger PDFs into parts.
            </p>
          </Show>

          <div>
            <Tabs
              label="Result views"
              idPrefix="result"
              items={tabs()}
              selected={tab()}
              onSelect={setTab}
            />

            <TabPanel idPrefix="result" id="compare" selected={tab() === "compare"}>
              <div class="stack-16">
                <label class="checkbox">
                  <input
                    type="checkbox"
                    checked={s.showBoxes()}
                    onChange={(e) => s.setShowBoxes(e.currentTarget.checked)}
                  />
                  <span>Show the review boxes</span>
                </label>
                <Show
                  when={s.inputUrl()}
                  fallback={
                    <div class="result-image">
                      <img
                        src={result().files.overlay ?? result().files.restored}
                        alt="Restored page with review overlay"
                      />
                    </div>
                  }
                >
                  <CompareSlider
                    before={s.inputUrl()!}
                    after={afterUrl()!}
                    alt="restored page"
                    beforeLabel="input"
                    afterLabel={s.showBoxes() ? "review overlay" : "restored"}
                  />
                </Show>
                <p class="field__hint">
                  The overlay is the pipeline's own output: one box per token, coloured by its
                  flag. Alternative readings sit above conflicting digits.
                </p>
              </div>
            </TabPanel>

            <TabPanel idPrefix="result" id="queue" selected={tab() === "queue"}>
              <div class="stack-16">
                <CorrectionReview state={s} />
                <p class="field__hint">
                  Confirm or fix each queued token; the corrected artifacts and
                  the optional training export appear here. Corrections stay in
                  this run until you download them.
                </p>
              </div>
            </TabPanel>

            <TabPanel idPrefix="result" id="transcript" selected={tab() === "transcript"}>
              <div class="stack-16">
                <pre class="transcript" tabindex={0} aria-label="Transcript text">
                  {result().transcript || "— no text —"}
                </pre>
                <CodeBlock label="transcript" code={result().transcript} />
              </div>
            </TabPanel>

            <TabPanel idPrefix="result" id="files" selected={tab() === "files"}>
              <div class="stack-16">
                <a
                  class="btn btn--primary download-all"
                  href={`/api/runs/${result().run_id}/files.zip`}
                  download={`veriscript-${result().run_id}.zip`}
                >
                  Download all files (.zip)
                </a>
                <ul class="downloads" aria-label="Files from this run">
                  <For each={DOWNLOADS.filter((d) => result().files[d.key])}>
                    {(d) => (
                      <li>
                        <a class="download" href={`${result().files[d.key]}?download=1`} download={d.name}>
                          <span aria-hidden="true">↓</span>
                          <span class="download__name">{d.name}</span>
                          <span class="download__what">{d.what}</span>
                        </a>
                      </li>
                    )}
                  </For>
                </ul>
                <p class="field__hint">
                  Run <span class="mono">{result().run_id}</span> · {result().status_line}.{" "}
                  {result().expires_in > 0
                    ? `Files are kept for ${retentionText(Math.round(result().expires_in / 60))}, then deleted.`
                    : "Files are kept on this computer until you delete them."}
                </p>
              </div>
            </TabPanel>
          </div>
        </section>
      )}
    </Show>
  );
}
