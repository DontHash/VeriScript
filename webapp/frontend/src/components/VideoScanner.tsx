import { createEffect, createMemo, createSignal, For, Show } from "solid-js";
import { announce } from "../lib/announce";
import { formatBytes } from "../lib/api";
import { isLocal, useHealth } from "../lib/health";

interface CapturePage {
  id: number;
  preview: string;
  timestamp: number;
  side: string;
  cropped: boolean;
  warnings: string[];
}
interface Capture {
  run_id: string;
  pages: CapturePage[];
  warnings: string[];
  expires_in: number;
}

async function responseJson(res: Response) {
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || body.detail || "Video processing failed.");
  return body;
}

/** Capture first, review physical pages, then run the optional OCR pipeline. */
export function VideoScanner() {
  let videoInput: HTMLInputElement | undefined;
  const [file, setFile] = createSignal<File | null>(null);
  const [layout, setLayout] = createSignal("auto");
  const [fingers, setFingers] = createSignal(false);
  const [lang, setLang] = createSignal("en");
  const [pdfKind, setPdfKind] = createSignal("clean");
  const [capture, setCapture] = createSignal<Capture | null>(null);
  const [order, setOrder] = createSignal<number[]>([]);
  const [excluded, setExcluded] = createSignal<number[]>([]);
  const [phase, setPhase] = createSignal<"idle" | "capture" | "export">("idle");
  const [error, setError] = createSignal<string | null>(null);
  const [pdf, setPdf] = createSignal<string | null>(null);
  const [limits, setLimits] = createSignal({ mb: 512, pages: 150, seconds: 600, ocr: 20 });
  const busy = () => phase() !== "idle";
  const selected = createMemo(() => order().filter((id) => !excluded().includes(id)));
  const pages = createMemo(() => new Map(capture()?.pages.map((p) => [p.id, p]) || []));
  const health = useHealth();
  createEffect(() => {
    const h = health();
    if (h) setLimits({
      mb: h.limits.video_upload_mb, pages: h.limits.video_max_pages,
      seconds: h.limits.video_max_seconds, ocr: h.limits.pages_per_client,
    });
  });

  const invalidate = () => setPdf(null);
  const chooseFile = (next: File | null) => {
    setFile(next); setCapture(null); setOrder([]); setExcluded([]);
    setError(null); invalidate();
  };
  const scan = async () => {
    const input = file();
    if (!input || busy()) return;
    setError(null); setCapture(null); invalidate();
    if (input.size > limits().mb * 1024 * 1024) {
      setError(`Video exceeds ${limits().mb} MB. Record a shorter section.`); return;
    }
    setPhase("capture");
    try {
      const body = new FormData();
      body.append("file", input); body.append("layout", layout());
      body.append("clean_fingers", fingers() ? "1" : "0");
      const result: Capture = await responseJson(await fetch("/api/video-scan", { method: "POST", body }));
      setCapture(result); setOrder(result.pages.map((p) => p.id)); setExcluded([]);
      announce(`Found ${result.pages.length} pages. Review them below before exporting.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Capture failed."); }
    finally { setPhase("idle"); }
  };
  const move = (id: number, delta: number) => {
    const next = [...order()]; const index = next.indexOf(id);
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setOrder(next); invalidate();
    announce(`Moved to position ${target + 1} of ${next.length}.`);
    // Reordering re-inserts the card, which drops focus: put it back on the
    // same button (or its sibling once the page reaches the first/last slot).
    queueMicrotask(() => {
      const up = document.getElementById(`video-move-up-${id}`) as HTMLButtonElement | null;
      const down = document.getElementById(`video-move-down-${id}`) as HTMLButtonElement | null;
      const [preferred, fallback] = delta < 0 ? [up, down] : [down, up];
      (preferred && !preferred.disabled ? preferred : fallback)?.focus();
    });
  };
  const exportPdf = async () => {
    const result = capture();
    if (!result || busy() || !selected().length) return;
    setPhase("export"); setError(null); invalidate();
    try {
      const body = JSON.stringify({ pages: selected(), pdf: pdfKind(), lang: lang() });
      const exported = await responseJson(await fetch(`/api/runs/${result.run_id}/video-export`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body,
      }));
      // Avoid browser cache retaining a previous export after changing order.
      setPdf(`${exported.pdf}?download=1&v=${Date.now()}`);
      announce("Your book PDF is ready to download.");
    } catch (e) { setError(e instanceof Error ? e.message : "Export failed."); }
    finally { setPhase("idle"); }
  };

  return <section class="panel stack-16" aria-label="Video book scanner">
    <h2 class="h3">Turn pages, keep recording</h2>
    <p>Keep the camera fixed above the book and pause for a second after each page turn. Two-page
      spreads become separate left and right PDF pages.</p>
    <p class="field__hint">Capture is experimental. Check every preview before exporting; curved
      bindings, hands, glare and fast turns can cause bad crops.</p>
    <div class="field">
      <span class="field__label">Book video</span>
      <input
        ref={videoInput}
        id="book-video"
        class="visually-hidden"
        type="file"
        tabindex={-1}
        aria-label="Choose a book video"
        accept=".mp4,.mov,.m4v,.avi,.webm"
        disabled={busy()}
        onChange={(e) => chooseFile(e.currentTarget.files?.[0] || null)}
      />
      <button class="btn btn--ghost" type="button" disabled={busy()} aria-describedby="video-limits"
        onClick={() => videoInput?.click()}>
        Choose a video
      </button>
      <Show when={file()}>{(f) => <span class="field__hint">{f().name} · {formatBytes(f().size)}</span>}</Show>
      <span class="field__hint" id="video-limits">Up to {limits().mb} MB · {limits().seconds / 60} minutes · {limits().pages} captured pages.
        {isLocal() ? "Processing happens on this computer." : "This demo processes videos on its server."}</span>
    </div>
    <div class="field">
      <label class="field__label" for="video-layout">Pages visible in the video</label>
      <select id="video-layout" class="select" value={layout()} disabled={busy()}
        onChange={(e) => { setLayout(e.currentTarget.value); setCapture(null); invalidate(); }}>
        <option value="auto">Auto (based on page shape)</option>
        <option value="spread">Two-page spread (left, then right)</option>
        <option value="single">Single page</option>
      </select>
    </div>
    <div class="field">
      <label class="checkbox">
        <input type="checkbox" checked={fingers()} disabled={busy()} aria-describedby="video-fingers-hint"
          onChange={(e) => { setFingers(e.currentTarget.checked); setCapture(null); invalidate(); }} />
        <span>Remove fingers at page edges</span>
      </label>
      <span class="field__hint" id="video-fingers-hint">Blanks thumbs and fingers holding the book with
        the paper colour; text is never changed. Pictures printed to the page edge can be blanked too,
        so check the margins.</span>
    </div>
    <button class="btn btn--primary" type="button" disabled={!file() || busy()} onClick={() => void scan()}>
      {phase() === "capture" ? "Finding steady pages…" : "Find page frames"}
    </button>
    <Show when={capture()}>{(result) => <div class="stack-16">
      <h3>Review {result().pages.length} captured pages · {selected().length} selected</h3>
      <For each={result().warnings}>{(warning) => <p class="field__hint">{warning}</p>}</For>
      <p class="field__hint">Uncheck duplicates or bad frames. Use Earlier / Later to correct the order.
        Click a preview to inspect it full size.{" "}
        {result().expires_in > 0
          ? `Results expire in ${Math.round(result().expires_in / 60)} minutes.`
          : "Results are kept on this computer until you delete them."}</p>
      <div class="video-pages">
        <For each={order()}>{(id, index) => {
          const page = () => pages().get(id)!;
          return <article class="video-page" data-excluded={excluded().includes(id)}>
            <a href={page().preview} target="_blank" rel="noreferrer">
              <img src={page().preview} loading="lazy" alt={`Captured page ${index() + 1}, ${page().side}`} />
              <span class="visually-hidden"> (opens full size in a new tab)</span>
            </a>
            <label class="checkbox"><input type="checkbox" checked={!excluded().includes(id)} disabled={busy()}
              onChange={(e) => { setExcluded(e.currentTarget.checked ? excluded().filter((n) => n !== id) : [...excluded(), id]); invalidate(); }} />
              <span>Page {index() + 1} · {page().side} · {page().timestamp.toFixed(1)}s</span>
            </label>
            <For each={page().warnings}>{(w) => <p class="field__hint">{w}</p>}</For>
            <div class="button-row">
              <button type="button" id={`video-move-up-${id}`} class="btn btn--ghost btn--small"
                disabled={busy() || index() === 0}
                aria-label={`Earlier: move page ${index() + 1} up`} onClick={() => move(id, -1)}>Earlier</button>
              <button type="button" id={`video-move-down-${id}`} class="btn btn--ghost btn--small"
                disabled={busy() || index() === order().length - 1}
                aria-label={`Later: move page ${index() + 1} down`} onClick={() => move(id, 1)}>Later</button>
            </div>
          </article>;
        }}</For>
      </div>
      <div class="field">
        <label class="field__label" for="video-pdf">PDF type</label>
        <select id="video-pdf" class="select" value={pdfKind()} disabled={busy()}
          onChange={(e) => { setPdfKind(e.currentTarget.value); invalidate(); }}>
          <option value="clean">Clean pristine pages (image PDF, fast)</option>
          <option value="searchable">Image pages with searchable text (OCR)</option>
          <option value="digital">Typeset text, word-style (OCR)</option>
        </select>
      </div>
      <Show when={pdfKind() !== "clean"}>
        <div class="field"><label class="field__label" for="video-lang">OCR language</label>
          <select id="video-lang" class="select" value={lang()} disabled={busy()}
            onChange={(e) => { setLang(e.currentTarget.value); invalidate(); }}>
            <option value="en">English</option><option value="ne">Nepali</option><option value="hi">Hindi</option>
          </select>
          <p class="field__hint">
            <Show when={limits().ocr}>The current OCR allowance is {limits().ocr} pages per visitor per day. </Show>
            A full book can take several minutes (~4–8 s per page). The clean image PDF preserves the captures without OCR.</p>
        </div>
      </Show>
      <button class="btn btn--primary" type="button" disabled={busy() || !selected().length} onClick={() => void exportPdf()}>
        {phase() === "export" ? "Building your book…" : `Create PDF (${selected().length} pages)`}
      </button>
      <Show when={pdf()}>{(url) => <a class="download" href={url()} download="book.pdf">
        <span aria-hidden="true">↓</span> Download book.pdf</a>}</Show>
    </div>}</Show>
    <Show when={error()}>{(message) => <div class="alert" role="alert">{message()}</div>}</Show>
    <Show when={busy()}><p class="field__hint" role="status">{phase() === "capture" ? "Selecting clear views from the recording." : "Exporting the selected pages in your chosen order."} Keep this page open.</p></Show>
  </section>;
}
