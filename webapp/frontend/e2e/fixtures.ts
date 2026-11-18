import type { Page } from "@playwright/test";
import type { Health, RunPayload } from "../src/lib/types";

export const HEALTH: Health = {
  ok: true,
  version: "test",
  busy: false,
  limits: {
    max_upload_mb: 12,
    video_upload_mb: 512,
    video_max_pages: 150,
    video_max_seconds: 600,
    pages_per_client: 20,
    max_image_megapixels: 40,
    max_pages: 10,
    ttl_minutes: 60,
    rate_max: 30,
    rate_window_s: 60,
    auth: false,
    memory: true,
  },
};

export const RUN: RunPayload = {
  run_id: "run-test-0001",
  meta: {
    seconds: 4.2,
    backend: "rapidocr",
    primary_stream: null,
    skew_angle: 0,
    resized: false,
    n_tokens: 214,
    flagged: 3,
    digit_conflicts: 1,
    lang: "ne",
    input_kind: "image",
    deskew: false,
    auto_rotate: true,
    all_pages: false,
    pages_processed: 1,
    pages_capped: false,
    page_cap: 10,
  },
  flags_summary: { digit_conflict: 1, low_conf: 2 },
  review: [
    {
      index: 12,
      text: "१२३४",
      alt_text: "१२३८",
      flags: ["digit_conflict"],
      conf: 61.5,
      risk: 0.8,
      bbox: [10, 10, 80, 30],
      suggestions: [{ text: "१२३४", source: "memory", why: "seen before" }],
      section: "number",
    },
    {
      index: 40,
      text: "रकम",
      alt_text: null,
      flags: ["low_conf"],
      conf: 48.0,
      risk: 0.5,
      bbox: [100, 10, 160, 30],
      section: "text",
    },
    {
      index: 41,
      text: "रकम",
      alt_text: null,
      flags: ["low_conf"],
      conf: 49.0,
      risk: 0.5,
      bbox: [170, 10, 230, 30],
      section: "text",
    },
  ],
  transcript: "बिल नं. १२३४\nरकम रकम",
  status_line: "1 page · rapidocr",
  files: {
    restored: "/examples/invoice-restored.jpg",
    overlay: "/examples/invoice-overlay.jpg",
    pdf: "/api/runs/run-test-0001/files/searchable.pdf",
    txt: "/api/runs/run-test-0001/files/transcript.txt",
    md: "/api/runs/run-test-0001/files/transcript.md",
    json: "/api/runs/run-test-0001/files/ocr.json",
  },
  expires_in: 3600,
};

/** A finished background job carrying `RUN`. */
export const JOB_DONE = {
  job_id: "0123456789abcdef",
  status: "done",
  stage: "Done",
  page: 1,
  pages: 1,
  cancel_requested: false,
  elapsed: 1.2,
  result: RUN,
};

/** Mock the backend. `restore` decides how a submitted job ends: POST
 *  /api/jobs queues it, the first poll of GET /api/jobs/{id} finishes it. */
export async function mockApi(
  page: Page,
  restore: "ok" | "error" = "ok",
  mode: "demo" | "local" = "demo",
) {
  await page.route("**/api/health", (r) => r.fulfill({ json: { ...HEALTH, mode } }));
  await page.route("**/api/jobs", (r) =>
    restore === "ok"
      ? r.fulfill({
          status: 202,
          json: { ...JOB_DONE, status: "queued", stage: "Waiting for the reader", result: undefined, position: 1 },
        })
      : r.fulfill({ status: 422, json: { error: "That file is not an image or PDF." } }),
  );
  await page.route("**/api/jobs/*", (r) => r.fulfill({ json: JOB_DONE }));
}
