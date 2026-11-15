/** Studio state — one factory, used by the homepage hero and the full studio
 *  page, so the product behaves identically wherever it is embedded. */
import { createEffect, createMemo, createSignal, onCleanup, onMount } from "solid-js";
import { announce } from "./announce";
import { clearMemory as clearMemoryApi, correctRun, exportRunCorrections, runJob } from "./api";
import { refreshHealth, retentionText, useHealth } from "./health";
import type {
  CorrectionInput,
  CorrectionStats,
  ExportResponse,
  Health,
  JobStatus,
  Lang,
  OcrEngine,
  PdfSize,
  RunPayload,
} from "./types";

export type StudioPhase = "idle" | "running" | "done" | "error";

/** Accepted inputs; mirrors the server's validate_upload. */
export const ACCEPTED_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".pdf"];

/** Why a file cannot be read, or null when it can. */
export function fileProblem(file: File, maxMb: number): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `${file.name} is not a supported file. Use a PNG, JPG, WebP, TIFF or PDF.`;
  }
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > maxMb * 1024 * 1024) {
    return `${file.name} is larger than ${maxMb} MB. Use a smaller file, or split the PDF into parts.`;
  }
  return null;
}

/** The last finished run, kept in this browser so a refresh does not lose
 *  the review. Per-viewer convenience only; the server copy expires. */
const SAVED_KEY = "veriscript.studio.lastRun.v1";
interface SavedRun {
  savedAt: number;
  result: RunPayload;
  corrections: CorrectionInput[];
  appliedSigs: Record<number, string>;
}

function loadSavedRun(): SavedRun | null {
  try {
    const raw = window.localStorage.getItem(SAVED_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as SavedRun;
    // expires_in 0: the server keeps results until they are deleted.
    const ttl = saved.result?.expires_in ?? 0;
    const expired = ttl > 0 && Date.now() >= saved.savedAt + ttl * 1000;
    if (!saved.result?.run_id || expired) {
      window.localStorage.removeItem(SAVED_KEY);
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

function storeSavedRun(saved: SavedRun | null) {
  try {
    if (saved) window.localStorage.setItem(SAVED_KEY, JSON.stringify(saved));
    else window.localStorage.removeItem(SAVED_KEY);
  } catch {
    /* storage full or blocked: the run simply is not restored */
  }
}

export function createStudioState() {
  const [file, setFile] = createSignal<File | null>(null);
  const [lang, setLang] = createSignal<Lang>("ne");
  const [deskew, setDeskew] = createSignal(false);
  const [ocr, setOcr] = createSignal<OcrEngine>("auto");
  const [allPages, setAllPages] = createSignal(false);
  const [autoRotate, setAutoRotate] = createSignal(true);
  const [wantOverlay, setWantOverlay] = createSignal(true);
  const [wantPdf, setWantPdf] = createSignal(true);
  const [wantTxt, setWantTxt] = createSignal(true);
  const [wantMd, setWantMd] = createSignal(true);
  const [pdfSize, setPdfSize] = createSignal<PdfSize>("standard");
  const [advancedOpen, setAdvancedOpen] = createSignal(false);
  const [phase, setPhase] = createSignal<StudioPhase>("idle");
  const [result, setResult] = createSignal<RunPayload | null>(null);
  const [error, setError] = createSignal<string | null>(null);
  const [elapsed, setElapsed] = createSignal(0);
  /** Latest job status while a run is in flight (queue position, page n of m). */
  const [job, setJob] = createSignal<JobStatus | null>(null);
  const health = useHealth();
  const [inputUrl, setInputUrl] = createSignal<string | null>(null);
  const [showBoxes, setShowBoxes] = createSignal(true);
  const [corrections, setCorrections] = createSignal<CorrectionInput[]>([]);
  const [correcting, setCorrecting] = createSignal(false);
  const [correctionError, setCorrectionError] = createSignal<string | null>(null);
  const [lastStats, setLastStats] = createSignal<CorrectionStats | null>(null);
  const [exportResult, setExportResult] = createSignal<ExportResponse | null>(null);
  const [memoryCleared, setMemoryCleared] = createSignal<number | null>(null);
  // Signature of every correction that has already been applied. The batch is
  // kept after applying (the export panel and the next POST need it), so the
  // pending count must ignore what was already sent — otherwise "apply" stays
  // enabled and re-posts the same corrections.
  const [appliedSigs, setAppliedSigs] = createSignal<Record<number, string>>({});
  /** When the shown result came back from a previous visit (ms), else null. */
  const [restoredAt, setRestoredAt] = createSignal<number | null>(null);
  /** Title of a document reopened from the desktop library, else null. */
  const [openedTitle, setOpenedTitle] = createSignal<string | null>(null);
  /** A short notice about the last file choice (e.g. extra files ignored). */
  const [notice, setNotice] = createSignal<string | null>(null);
  let savedAt = Date.now();

  const correctionSig = (c: CorrectionInput) =>
    [c.index, c.corrected, c.action, c.suggested ?? "", c.suggestion_source ?? ""].join("\u0000");

  const pendingCorrections = createMemo(() =>
    corrections().filter((c) => appliedSigs()[c.index] !== correctionSig(c)),
  );

  const resetCorrections = () => {
    setCorrections([]);
    setAppliedSigs({});
    setCorrectionError(null);
    setLastStats(null);
    setExportResult(null);
  };

  let timer: number | undefined;
  let controller: AbortController | undefined;

  // Bring back the last result after a refresh or a closed tab.
  const saved = loadSavedRun();
  if (saved) {
    savedAt = saved.savedAt;
    setResult(saved.result);
    setCorrections(saved.corrections ?? []);
    setAppliedSigs(saved.appliedSigs ?? {});
    setRestoredAt(saved.savedAt);
    setPhase("done");
  }

  createEffect(() => {
    const r = result();
    storeSavedRun(
      phase() === "done" && r
        ? { savedAt, result: r, corrections: corrections(), appliedSigs: appliedSigs() }
        : null,
    );
  });

  // Staged corrections live only in this page until they are applied.
  onMount(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (pendingCorrections().length === 0) return;
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    onCleanup(() => window.removeEventListener("beforeunload", guard));
  });

  onCleanup(() => {
    if (timer) window.clearInterval(timer);
    controller?.abort();
    if (inputUrl()) URL.revokeObjectURL(inputUrl()!);
  });

  const maxUploadMb = () => health()?.limits.max_upload_mb ?? 12;

  /** Take the first file; say so when more were offered, and refuse files
   *  the server would reject before uploading them. */
  const chooseFiles = (files: File[]) => {
    const [first] = files;
    if (!first) return;
    const problem = fileProblem(first, maxUploadMb());
    if (problem) {
      setNotice(null);
      setError(problem);
      setPhase("error");
      return;
    }
    chooseFile(first);
    setNotice(
      files.length > 1
        ? `Using ${first.name}. The studio reads one image or PDF at a time; ${files.length - 1} other ${files.length === 2 ? "file was" : "files were"} not added.`
        : null,
    );
  };

  const chooseFile = (next: File) => {
    if (inputUrl()) URL.revokeObjectURL(inputUrl()!);
    setNotice(null);
    setRestoredAt(null);
    setInputUrl(next.type.startsWith("image/") ? URL.createObjectURL(next) : null);
    setFile(next);
    setResult(null);
    setError(null);
    setPhase("idle");
    resetCorrections();
  };

  /** Show a kept result from the desktop library. */
  const openKept = (payload: RunPayload, title: string, createdMs: number) => {
    controller?.abort();
    resetCorrections();
    savedAt = createdMs;
    setFile(null);
    setInputUrl(null);
    setError(null);
    setNotice(null);
    setResult(payload);
    setRestoredAt(createdMs);
    setOpenedTitle(title);
    setPhase("done");
    announce(`Opened ${title} from your library.`);
  };

  const clearFile = () => {
    if (inputUrl()) URL.revokeObjectURL(inputUrl()!);
    setNotice(null);
    setRestoredAt(null);
    setInputUrl(null);
    setFile(null);
    setResult(null);
    setError(null);
    setPhase("idle");
    resetCorrections();
  };

  const pickExample = async (path: string, name: string) => {
    try {
      const res = await fetch(path);
      if (!res.ok) throw new Error("could not load the example");
      const blob = await res.blob();
      chooseFile(new File([blob], name, { type: blob.type || "image/jpeg" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load the example");
      setPhase("error");
    }
  };

  const start = async () => {
    const f = file();
    if (!f || phase() === "running") return;
    setOpenedTitle(null);
    setPhase("running");
    setError(null);
    setElapsed(0);
    setJob(null);
    controller = new AbortController();
    announce(`Reading ${f.name}. This can take a minute.`);
    const startedAt = performance.now();
    timer = window.setInterval(() => setElapsed((performance.now() - startedAt) / 1000), 100);
    try {
      let lastStage = "";
      const payload = await runJob(f, {
        lang: lang(),
        deskew: deskew(),
        ocr: ocr(),
        allPages: allPages(),
        autoRotate: autoRotate(),
        pdfSize: pdfSize(),
        outputs: {
          overlay: wantOverlay(),
          pdf: wantPdf(),
          txt: wantTxt(),
          md: wantMd(),
        },
      }, {
        signal: controller.signal,
        onProgress: (status) => {
          setJob(status);
          // Announce page changes for screen readers, not every poll.
          if (status.pages > 1 && status.stage !== lastStage) {
            lastStage = status.stage;
            announce(status.stage);
          }
        },
      });
      savedAt = Date.now();
      setResult(payload);
      setPhase("done");
      resetCorrections();
      const { n_tokens, flagged } = payload.meta;
      announce(
        `Done. ${n_tokens} tokens read, ${flagged} ${flagged === 1 ? "needs" : "need"} review.`,
      );
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        setPhase("idle");
        announce("Stopped. Your file is still selected.");
      } else {
        setError(e instanceof Error ? e.message : "The run failed.");
        setPhase("error");
      }
    } finally {
      controller = undefined;
      setJob(null);
      if (timer) window.clearInterval(timer);
      refreshHealth();
    }
  };

  /** Stop the run. The server finishes the page it is reading, then stops
   *  and deletes the partial result; nothing else is processed. */
  const cancel = () => {
    controller?.abort();
  };

  const stageCorrection = (correction: CorrectionInput) => {
    setCorrectionError(null);
    setCorrections((prev) => [
      ...prev.filter((c) => c.index !== correction.index),
      correction,
    ]);
  };

  const unstageCorrection = (index: number) => {
    setCorrections((prev) => prev.filter((c) => c.index !== index));
  };

  const correctionFor = (index: number) =>
    corrections().find((c) => c.index === index);

  const applyCorrections = async () => {
    const p = result();
    // Post only what is new; the server applies it on top of the run's
    // current corrected state (cumulative), so already-applied corrections
    // are neither re-counted nor re-recorded.
    const list = pendingCorrections();
    if (!p || !list.length || correcting()) return;
    setCorrecting(true);
    setCorrectionError(null);
    try {
      const res = await correctRun(p.run_id, list);
      setResult({
        ...p,
        review: res.review,
        flags_summary: res.flags_summary,
        transcript: res.transcript,
        files: { ...p.files, ...res.files },
      });
      setLastStats(res.stats);
      setExportResult(null);
      announce(
        `Applied: ${res.stats.changed} changed, ${res.stats.confirmed} confirmed. Corrected files are ready.`,
      );
      setAppliedSigs((prev) => ({
        ...prev,
        ...Object.fromEntries(list.map((c) => [c.index, correctionSig(c)])),
      }));
    } catch (e) {
      setCorrectionError(e instanceof Error ? e.message : "Could not apply the corrections.");
    } finally {
      setCorrecting(false);
    }
  };

  const exportCorrections = async (share: number[]) => {
    const p = result();
    const list = corrections();
    if (!p || !list.length || correcting()) return;
    setCorrecting(true);
    setCorrectionError(null);
    try {
      const out = await exportRunCorrections(p.run_id, list, share);
      setExportResult(out);
      announce(`corrections.zip is ready with ${out.shared} crops.`);
    } catch (e) {
      setCorrectionError(
        e instanceof Error ? e.message : "Could not build the corrections archive.",
      );
    } finally {
      setCorrecting(false);
    }
  };

  const clearMemory = async () => {
    setCorrectionError(null);
    try {
      const out = await clearMemoryApi();
      setMemoryCleared(out.removed);
      announce(`Correction memory cleared: ${out.removed} records removed.`);
    } catch (e) {
      setCorrectionError(
        e instanceof Error ? e.message : "Could not clear the local memory.",
      );
    }
  };

  return {
    file,
    lang,
    setLang,
    deskew,
    setDeskew,
    ocr,
    setOcr,
    allPages,
    setAllPages,
    autoRotate,
    setAutoRotate,
    wantOverlay,
    setWantOverlay,
    wantPdf,
    setWantPdf,
    wantTxt,
    setWantTxt,
    wantMd,
    pdfSize,
    setPdfSize,
    setWantMd,
    advancedOpen,
    setAdvancedOpen,
    phase,
    result,
    error,
    elapsed,
    health,
    inputUrl,
    showBoxes,
    setShowBoxes,
    chooseFile,
    chooseFiles,
    openKept,
    openKeptFailed: () => {
      setError("That document is no longer in your library.");
      setPhase("error");
    },
    openedTitle,
    job,
    clearFile,
    cancel,
    notice,
    restoredAt,
    pickExample,
    start,
    corrections,
    pendingCorrections,
    correcting,
    correctionError,
    lastStats,
    exportResult,
    stageCorrection,
    unstageCorrection,
    correctionFor,
    applyCorrections,
    exportCorrections,
    memoryCleared,
    clearMemory,
  };
}

export type StudioState = ReturnType<typeof createStudioState>;

export const EXAMPLE_FILES = [
  { label: "Invoice photo", path: "/examples/invoice-photo.png", name: "invoice-photo.png" },
  { label: "1955 letterpress", path: "/examples/letterpress-input.jpg", name: "letterpress.jpg" },
  { label: "Clean invoice", path: "/examples/clean-invoice.png", name: "clean-invoice.png" },
];

export function limitsLine(health: Health | null): string {
  if (!health) return "Up to 12 MB · first page of PDFs · results kept 60 minutes";
  const { max_upload_mb, max_pages, ttl_minutes } = health.limits;
  const pages = max_pages > 0 ? `up to ${max_pages} PDF pages` : "any number of PDF pages";
  const kept = ttl_minutes > 0 ? `results kept ${retentionText(ttl_minutes)}` : "results kept until you delete them";
  return `Up to ${max_upload_mb} MB · ${pages} · ${kept}`;
}

/** What the running bar says: queue position, or the server's current step. */
export function jobLine(job: JobStatus | null): string {
  if (!job) return "Uploading…";
  if (job.cancel_requested) return "Stopping after the current page…";
  if (job.status === "queued") {
    return job.position && job.position > 1
      ? `Waiting · ${job.position - 1} ${job.position === 2 ? "file" : "files"} ahead`
      : "Waiting for the reader…";
  }
  return job.stage || "Reading…";
}
