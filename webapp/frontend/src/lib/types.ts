/** API + domain types (mirrors webapp/vvweb payloads). */

export type FlagName =
  | "digit_conflict"
  | "digit_uncertain"
  | "low_conf"
  | "unknown_word"
  | "invalid_sequence"
  | "script_mismatch"
  | (string & {});

/** One candidate label for a flagged token (docs/HARNESS_PLAN.md §2). */
export interface Suggestion {
  text: string;
  source: string;
  why?: string;
}

export interface QueueItem {
  index: number | null;
  text: string;
  alt_text: string | null;
  flags: FlagName[];
  conf: number | null;
  risk: number | null;
  bbox: [number, number, number, number] | null;
  /** Additive harness evidence; absent or empty on untouched runs. */
  suggestions?: Suggestion[];
  /** Review section (Appendix AO): numbers first, text flags after. */
  section?: "number" | "text" | null;
}

export interface RunMeta {
  seconds: number;
  backend: string;
  primary_stream: string | null;
  skew_angle: number;
  resized: boolean;
  n_tokens: number;
  flagged: number;
  digit_conflicts: number;
  lang: string;
  input_kind: string;
  deskew: boolean;
  auto_rotate: boolean;
  all_pages: boolean;
  pages_processed: number;
  pages_capped: boolean;
  page_cap: number;
}

export interface RunFiles {
  restored: string;
  overlay?: string;
  pdf?: string;
  txt?: string;
  md?: string;
  json?: string;
  combined_pdf?: string;
  combined_txt?: string;
  combined_md?: string;
  tables_xlsx?: string;
  tables_csv?: string;
  corrected_pdf?: string;
  corrected_txt?: string;
  corrected_md?: string;
  corrected_json?: string;
  corrections_json?: string;
  corrections_zip?: string;
}

export interface RunPayload {
  run_id: string;
  meta: RunMeta;
  flags_summary: Record<string, number>;
  review: QueueItem[];
  transcript: string;
  status_line: string;
  files: RunFiles;
  /** Seconds the server keeps the files; 0 = until deleted (desktop). */
  expires_in: number;
}

/** docs/CORRECTIONS.md — one staged fix, keyed to a token index. */
export interface CorrectionInput {
  index: number;
  bbox: [number, number, number, number] | null;
  original: string;
  corrected: string;
  action: "changed" | "confirmed";
  /** The suggestion the human accepted, when one was used (track D2). */
  suggested?: string;
  suggestion_source?: string;
}

export interface CorrectionStats {
  changed: number;
  confirmed: number;
  skipped: number;
  skipped_indices: number[];
  reviewed: number;
}

export interface CorrectResponse {
  run_id: string;
  stats: CorrectionStats;
  flags_summary: Record<string, number>;
  review: QueueItem[];
  transcript: string;
  files: RunFiles;
}

export interface ExportResponse {
  run_id: string;
  file: string;
  shared: number;
}

/** GET /api/jobs/{id}: a document run in the background queue. */
export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  /** Plain-language step, e.g. "Reading page 3 of 12". */
  stage: string;
  page: number;
  pages: number;
  /** 1 = next to run; only while queued. */
  position?: number;
  cancel_requested: boolean;
  elapsed: number;
  result?: RunPayload;
  error?: string;
  error_status?: number;
}

/** GET /api/library: one kept document (desktop app only). */
export interface LibraryDoc {
  run_id: string;
  title: string;
  /** Unix seconds. */
  created: number;
  pages: number;
  flagged: number;
  input_kind: "image" | "pdf";
  lang?: string;
  corrected: boolean;
}

export interface Health {
  ok: boolean;
  version: string;
  /** "local": runs on this computer (desktop app); "demo": shared server */
  mode?: "local" | "demo";
  busy: boolean;
  limits: {
    max_upload_mb: number;
    video_upload_mb: number;
    video_max_pages: number;
    video_max_seconds: number;
    pages_per_client: number;
    max_image_megapixels: number;
    /** PDF pages per run with "all pages"; 0 = no limit (desktop). */
    max_pages: number;
    /** 0 = results are kept until deleted (desktop). */
    ttl_minutes: number;
    queued?: number;
    rate_max: number;
    rate_window_s: number;
    auth: boolean;
    memory: boolean;
  };
}

export type Lang = "ne" | "hi" | "en";
export type OcrEngine = "auto" | "rapidocr" | "tesseract";
/** Searchable-PDF page-image preset; the text layer is identical in all. */
export type PdfSize = "standard" | "small" | "archive";
