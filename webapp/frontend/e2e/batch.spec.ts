/** Desktop batch reading (docs/TECH_UPGRADE_PLAN.md B2): several files are
 *  read one after another with a status per file; a failure does not stop
 *  the rest; Cancel stops the current file and skips the others. */
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { JOB_DONE, mockApi, RUN } from "./fixtures";

async function dropFiles(page: Page, names: string[]) {
  const transfer = await page.evaluateHandle((list) => {
    const dt = new DataTransfer();
    for (const name of list) dt.items.add(new File(["x"], name, { type: "image/png" }));
    return dt;
  }, names);
  await page.locator(".dropzone").dispatchEvent("drop", { dataTransfer: transfer });
}

/** Jobs numbered in upload order; `fail` lists 1-based jobs that fail;
 *  `hang` keeps a job running until cancelled. */
async function mockJobs(page: Page, opts: { fail?: number[]; hang?: number } = {}) {
  let n = 0;
  const deletes: string[] = [];
  const id = (k: number) => `${k}`.padStart(16, "0");
  await page.route("**/api/jobs", (r) => {
    n++;
    return r.fulfill({ status: 202, json: { ...JOB_DONE, job_id: id(n), status: "queued", result: undefined } });
  });
  await page.route("**/api/jobs/*", (r) => {
    const k = Number(r.request().url().split("/").pop());
    if (r.request().method() === "DELETE") {
      deletes.push(id(k));
      return r.fulfill({ json: { ...JOB_DONE, job_id: id(k), status: "running", cancel_requested: true, result: undefined } });
    }
    if (opts.hang === k) {
      return r.fulfill({ json: { ...JOB_DONE, job_id: id(k), status: "running", stage: "Reading page 1 of 4", page: 1, pages: 4, result: undefined } });
    }
    if (opts.fail?.includes(k)) {
      return r.fulfill({ json: { ...JOB_DONE, job_id: id(k), status: "failed", error: "Could not read that image.", error_status: 400, result: undefined } });
    }
    return r.fulfill({ json: { ...JOB_DONE, job_id: id(k), result: { ...RUN, run_id: id(k) } } });
  });
  await page.route("**/api/runs/*/summary", (r) =>
    r.fulfill({ json: { ...RUN, run_id: "0000000000000003", title: "c", expires_in: 0 } }),
  );
  return deletes;
}

test("several files are read in turn and a failure does not stop the rest", async ({ page }) => {
  await mockApi(page, "ok", "local");
  await mockJobs(page, { fail: [2] });
  await page.goto("/studio");
  await dropFiles(page, ["a.png", "b.png", "c.png"]);
  await expect(page.getByRole("heading", { name: "3 files" })).toBeVisible();
  const items = page.getByRole("list", { name: "Files to read" }).getByRole("listitem");
  await expect(items).toHaveCount(3);

  await page.getByRole("button", { name: "Read 3 files" }).click();
  await expect(items.nth(2)).toContainText("Done");
  await expect(items.nth(0)).toContainText("Done");
  await expect(items.nth(1)).toContainText("Could not read that image.");
  await expect(page.locator('[role="status"][aria-live="polite"]')).toContainText("2 of 3 files done, 1 failed");
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();

  await page.getByRole("button", { name: "Show c.png" }).click();
  await expect(page.getByText("c, from your library")).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test("cancel stops the current file and skips the rest", async ({ page }) => {
  await mockApi(page, "ok", "local");
  const deletes = await mockJobs(page, { hang: 2 });
  await page.goto("/studio");
  await dropFiles(page, ["a.png", "b.png", "c.png"]);
  await page.getByRole("button", { name: "Read 3 files" }).click();
  const items = page.getByRole("list", { name: "Files to read" }).getByRole("listitem");
  await expect(items.nth(1)).toContainText("Reading page 1 of 4");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(items.nth(1)).toContainText("Stopped");
  await expect(items.nth(2)).toContainText("Skipped");
  await expect(items.nth(0)).toContainText("Done");
  expect(deletes).toEqual(["0000000000000002"]);
});

test("the demo still reads one file at a time", async ({ page }) => {
  await mockApi(page);
  await page.goto("/studio");
  await dropFiles(page, ["a.png", "b.png"]);
  await expect(page.locator(".fileticket__name")).toHaveText("a.png");
  await expect(page.getByRole("button", { name: "Restore and read" })).toBeVisible();
});
