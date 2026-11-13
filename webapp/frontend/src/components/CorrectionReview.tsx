import { createMemo, createSignal, For, Show } from "solid-js";
import { announce } from "../lib/announce";
import { flagMeta } from "../lib/flags";
import { TokenCrop } from "./TokenCrop";
import type { QueueItem, Suggestion } from "../lib/types";
import { type StudioState } from "../lib/studio-state";

/** Review mode: verify -> fix -> re-export (docs/CORRECTIONS.md).
 *
 *  Every queued token can be confirmed (Enter / keep) or corrected (type and
 *  press Enter; the kept alternative is one click). Staged fixes are posted in
 *  one batch and the corrected files appear below. The training export packs
 *  ONLY the items the user explicitly ticks — nothing is shared otherwise.
 */
export function CorrectionReview(props: { state: StudioState }) {
  const s = props.state;
  const rows = createMemo<QueueItem[]>(() => s.result()?.review ?? []);
  const [active, setActive] = createSignal(0);
  const [edited, setEdited] = createSignal<Record<number, string>>({});
  const [share, setShare] = createSignal<Record<number, boolean>>({});

  // Boxes are in the processed page's pixels. Multi-page runs do not say
  // which page a token is on yet, so crops are shown for single pages only.
  const cropSrc = () => {
    const r = s.result();
    return r && r.meta.pages_processed <= 1 ? r.files.restored : null;
  };

  const clampActive = () => Math.min(active(), Math.max(0, rows().length - 1));
  const pendingCount = () => s.pendingCorrections().length;

  const draftText = (row: QueueItem): string => {
    if (row.index === null) return row.text;
    return edited()[row.index] ?? row.text;
  };

  const clearEdit = (index: number) =>
    setEdited((prev) => {
      const next = { ...prev };
      delete next[index];
      return next;
    });

  const isStaged = (row: QueueItem) =>
    row.index !== null && s.correctionFor(row.index) !== undefined;

  const move = (delta: number) => {
    const list = rows();
    if (!list.length) return;
    const next = Math.max(0, Math.min(list.length - 1, clampActive() + delta));
    setActive(next);
    const key = list[next]?.index;
    if (key !== null && key !== undefined) {
      const el = document.getElementById(`review-input-${key}`) as HTMLInputElement | null;
      el?.focus();
      el?.select();
    }
  };

  const stage = (row: QueueItem, action: "changed" | "confirmed") => {
    const key = row.index;
    if (key === null) return;
    if (action === "confirmed") {
      clearEdit(key);
      s.stageCorrection({
        index: key,
        bbox: row.bbox,
        original: row.text,
        corrected: row.text,
        action: "confirmed",
      });
      announce(`Kept ${row.text}.`);
      move(1);
      return;
    }
    const text = draftText(row).trim();
    s.stageCorrection({
      index: key,
      bbox: row.bbox,
      original: row.text,
      corrected: text && text !== row.text ? text : row.text,
      action: text && text !== row.text ? "changed" : "confirmed",
    });
    announce(text && text !== row.text ? `Changed ${row.text} to ${text}.` : `Kept ${row.text}.`);
    move(1);
  };

  const useAlternative = (row: QueueItem) => {
    const key = row.index;
    if (key === null || !row.alt_text) return;
    setEdited((prev) => ({ ...prev, [key]: row.alt_text! }));
    s.stageCorrection({
      index: key,
      bbox: row.bbox,
      original: row.text,
      corrected: row.alt_text,
      action: "changed",
    });
    announce(`Changed ${row.text} to ${row.alt_text}.`);
    move(1);
  };

  /** Track D2: accept a candidate chip; the source is recorded for feedback. */
  const useSuggestion = (row: QueueItem, suggestion: Suggestion) => {
    const key = row.index;
    if (key === null || !suggestion.text) return;
    setEdited((prev) => ({ ...prev, [key]: suggestion.text }));
    s.stageCorrection({
      index: key,
      bbox: row.bbox,
      original: row.text,
      corrected: suggestion.text,
      action: "changed",
      suggested: suggestion.text,
      suggestion_source: suggestion.source,
    });
    announce(`Changed ${row.text} to ${suggestion.text}.`);
    move(1);
  };

  /** Track D1: rows whose reading is identical to this one. */
  const identicalFor = (row: QueueItem) =>
    rows().filter(
      (r) => r.index !== null && r.index !== row.index && r.text.trim() === row.text.trim(),
    );

  /** Track D1: stage the same fix (or confirmation) for every identical row. */
  const applyToIdentical = (row: QueueItem) => {
    const draft = draftText(row).trim();
    const corrected = draft && draft !== row.text ? draft : row.text;
    const action: "changed" | "confirmed" = corrected !== row.text ? "changed" : "confirmed";
    const targets = [row, ...identicalFor(row)];
    // Every staged row's input should show the text that was actually staged.
    setEdited((prev) => {
      const next = { ...prev };
      for (const r of targets) if (r.index !== null) next[r.index] = corrected;
      return next;
    });
    for (const r of targets) {
      if (r.index === null) continue;
      s.stageCorrection({
        index: r.index,
        bbox: r.bbox,
        original: r.text,
        corrected,
        action,
      });
    }
    announce(`Staged ${corrected} for ${targets.length} identical tokens.`);
    move(1);
  };

  const shared = createMemo(() =>
    Object.entries(share())
      .filter(([, on]) => on)
      .map(([index]) => Number(index)),
  );

  return (
    <div class="review">
      <div class="review__bar">
        <span class="field__hint">
          {pendingCount() > 0 || !s.corrections().length
            ? `${pendingCount()} staged`
            : `${s.corrections().length} applied`}{" "}
          · {rows().length} still in the queue
        </span>
        <button
          type="button"
          class="btn btn--primary btn--small"
          disabled={!pendingCount() || s.correcting()}
          onClick={() => void s.applyCorrections()}
        >
          {s.correcting() ? "Applying…" : `Apply corrections (${pendingCount()})`}
        </button>
      </div>

      <details class="review__keys">
        <summary>Keyboard shortcuts</summary>
        <dl>
          <dt><kbd>Enter</kbd></dt>
          <dd>Stage what is in the box (unchanged text counts as Keep) and go to the next token</dd>
          <dt><kbd>Esc</kbd></dt>
          <dd>Undo your typing in this box</dd>
          <dt><kbd>↑</kbd> <kbd>↓</kbd></dt>
          <dd>Previous or next token</dd>
        </dl>
      </details>

      <Show when={s.health()?.limits.memory}>
        <p class="field__hint">
          Local correction memory is on: suggestions come from your own previous
          fixes and never leave this machine.{" "}
          <button
            type="button"
            class="btn btn--ghost btn--small"
            disabled={s.correcting()}
            onClick={() => void s.clearMemory()}
          >
            Clear memory
          </button>
          <Show when={s.memoryCleared() !== null}>
            <span> removed {s.memoryCleared()} records.</span>
          </Show>
        </p>
      </Show>

      <Show when={s.correctionError()}>
        <p class="field__hint field__hint--error">{s.correctionError()}</p>
      </Show>
      <Show when={s.lastStats()}>
        {(stats) => (
          <p class="field__hint">
            applied: {stats().changed} changed · {stats().confirmed} confirmed ·{" "}
            {stats().skipped} skipped
            <Show when={stats().skipped > 0}>
              {" "}— skipped entries matched no token and were left untouched.
            </Show>
          </p>
        )}
      </Show>

      <Show
        when={rows().length > 0}
        fallback={
          <p class="lede">
            Nothing left to review — every queued token was confirmed or corrected.
          </p>
        }
      >
        <div class="review__list">
          <For each={rows()}>
            {(row, i) => {
              const key = row.index;
              const showSection = () => {
                const list = rows();
                const prev = i() > 0 ? list[i() - 1] : undefined;
                return row.section != null &&
                  prev?.section !== row.section;
              };
              return (
                <>
                  <Show when={showSection()}>
                    <div class="review__section">
                      {row.section === "text" ? "Text flags" : "Numbers"}
                    </div>
                  </Show>
                  <div
                    class={
                      "review__row" +
                      (clampActive() === i() ? " review__row--active" : "")
                    }
                  >
                  <div class="review__main">
                    <Show when={cropSrc() && row.bbox}>
                      <TokenCrop src={cropSrc()!} bbox={row.bbox!} />
                    </Show>
                    <span class="review__original">{row.text}</span>
                    <input
                      id={key === null ? undefined : `review-input-${key}`}
                      class="review__input"
                      value={draftText(row)}
                      aria-label={`Corrected reading of ${row.text}`}
                      aria-describedby={key === null ? undefined : `review-meta-${key}`}
                      onInput={(e) => {
                        if (key === null) return;
                        const value = e.currentTarget.value;
                        setEdited((prev) => ({ ...prev, [key]: value }));
                      }}
                      onFocus={() => setActive(i())}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          stage(row, "changed");
                        } else if (e.key === "Escape") {
                          if (key !== null) clearEdit(key);
                        } else if (e.key === "ArrowDown") {
                          e.preventDefault();
                          move(1);
                        } else if (e.key === "ArrowUp") {
                          e.preventDefault();
                          move(-1);
                        }
                      }}
                    />
                  </div>
                  <div class="review__actions">
                    <For each={row.suggestions ?? []}>
                      {(suggestion) => (
                        <button
                          type="button"
                          class="btn btn--ghost btn--small"
                          title={suggestion.why ?? ""}
                          onClick={() => useSuggestion(row, suggestion)}
                        >
                          <span aria-hidden="true">→ </span>
                          <span class="visually-hidden">Use suggestion </span>
                          {suggestion.text}
                        </button>
                      )}
                    </For>
                    <Show when={row.alt_text}>
                      <button
                        type="button"
                        class="btn btn--ghost btn--small"
                        onClick={() => useAlternative(row)}
                      >
                        Use alternative{" "}
                        <span class="deva">{row.alt_text}</span>
                      </button>
                    </Show>
                    <Show when={identicalFor(row).length > 0}>
                      <button
                        type="button"
                        class="btn btn--ghost btn--small"
                        title="stage the same reading for every identical token"
                        onClick={() => applyToIdentical(row)}
                      >
                        Apply to {identicalFor(row).length + 1} identical
                      </button>
                    </Show>
                    <button
                      type="button"
                      class="btn btn--ghost btn--small"
                      aria-label={`Keep ${row.text}`}
                      onClick={() => stage(row, "confirmed")}
                    >
                      Keep
                    </button>
                    <Show when={isStaged(row) && key !== null}>
                      <button
                        type="button"
                        class="btn btn--ghost btn--small"
                        aria-label={`Undo the change to ${row.text}`}
                        onClick={() => {
                          s.unstageCorrection(key!);
                          announce(`Undid the change to ${row.text}.`);
                        }}
                      >
                        Undo
                      </button>
                    </Show>
                  </div>
                  <div class="review__meta" id={key === null ? undefined : `review-meta-${key}`}>
                    <For each={row.flags}>
                      {(flag) => {
                        const meta = flagMeta(flag);
                        return (
                          <span class={`flag flag--${meta.tone}`}>
                            <span class="flag__dot" aria-hidden="true" />
                            {meta.label}
                          </span>
                        );
                      }}
                    </For>
                    <span class="num">
                      confidence {row.conf === null ? "—" : row.conf.toFixed(1)}
                    </span>
                    <Show when={isStaged(row)}>
                      <span class="review__done">Staged</span>
                    </Show>
                  </div>
                </div>
                </>
              );
            }}
          </For>
        </div>
      </Show>

      <Show when={s.result()?.files.corrected_pdf}>
        <div class="results__actions">
          <a class="download" href={`${s.result()!.files.corrected_pdf}?download=1`}>
            ↓ corrected.pdf
          </a>
          <a class="download" href={`${s.result()!.files.corrected_txt}?download=1`}>
            ↓ corrected.txt
          </a>
          <a class="download" href={`${s.result()!.files.corrected_json}?download=1`}>
            ↓ corrected.json
          </a>
          <a class="download" href={`${s.result()!.files.corrections_json}?download=1`}>
            ↓ corrections.json
          </a>
        </div>
      </Show>

      <Show when={s.corrections().length > 0}>
        <details class="review__export">
          <summary>Export corrections for training</summary>
          <p class="field__hint">
            Choose what to include. The archive contains the token crops and corrected text, with
            no page images.
          </p>
          <For each={s.corrections()}>
            {(correction) => (
              <label class="checkbox review__share">
                <input
                  type="checkbox"
                  checked={!!share()[correction.index]}
                  onChange={(e) =>
                    setShare((prev) => ({
                      ...prev,
                      [correction.index]: e.currentTarget.checked,
                    }))
                  }
                />
                <span>
                  <span>{correction.original || "—"}</span> →{" "}
                  <span>{correction.corrected}</span>
                </span>
              </label>
            )}
          </For>
          <div class="results__actions">
            <button
              type="button"
              class="btn btn--ghost btn--small"
              disabled={s.correcting()}
              onClick={() => void s.exportCorrections(shared())}
            >
              Build corrections.zip ({shared().length} shared)
            </button>
            <Show when={s.exportResult()}>
              {(out) => (
                <a class="download" href={`${out().file}?download=1`}>
                  ↓ corrections.zip ({out().shared} crops)
                </a>
              )}
            </Show>
          </div>
        </details>
      </Show>
    </div>
  );
}
