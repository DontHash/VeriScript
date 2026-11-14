/** Workflow behaviour from audit Phase 3: cancel, restore after refresh,
 *  file checks, download-all and the review queue's page crops. */
import { expect, test, type Page } from "@playwright/test";
import { JOB_DONE, mockApi, RUN } from "./fixtures";

async function runExample(page: Page) {
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
}

test("a running page can be cancelled", async ({ page }) => {
  await mockApi(page);
  // The job keeps running until the user cancels it; Cancel must tell the
  // server (DELETE), not just stop waiting.
  const deletes: string[] = [];
  await page.route("**/api/jobs/*", (r) => {
    if (r.request().method() === "DELETE") {
      deletes.push(r.request().url());
      return r.fulfill({ json: { ...JOB_DONE, status: "running", cancel_requested: true, result: undefined } });
    }
    return r.fulfill({
      json: { ...JOB_DONE, status: "running", stage: "Reading page 2 of 5", page: 2, pages: 5, result: undefined },
    });
  });
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
  await expect(page.getByRole("button", { name: "Reading…" })).toBeDisabled();
  await expect(page.locator(".runbar__elapsed")).toContainText("Reading page 2 of 5");
  await expect(page.locator('[role="status"][aria-live="polite"]')).toContainText("Reading page 2 of 5");
  await expect(page.getByRole("progressbar", { name: "Pages read" })).toHaveAttribute("aria-valuenow", "1");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect.poll(() => deletes.length).toBe(1);
  expect(deletes[0]).toContain("/api/jobs/0123456789abcdef");
  await expect(page.getByRole("button", { name: "Restore and read" })).toBeEnabled();
  await expect(page.locator('[role="status"][aria-live="polite"]')).toContainText("Stopped");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("a refresh brings back the last result and staged review", async ({ page }) => {
  await mockApi(page);
  await runExample(page);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await expect(page.getByText("Your last result, from")).toBeVisible();
  // a restored result does not steal focus on load
  await expect(page.getByRole("heading", { name: "Results" })).not.toBeFocused();
});

test("an expired saved result is not restored", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((run) => {
    const saved = { savedAt: Date.now() - 2 * 3600_000, result: run, corrections: [], appliedSigs: {} };
    window.localStorage.setItem("veriscript.studio.lastRun.v1", JSON.stringify(saved));
  }, RUN);
  await page.goto("/studio");
  await expect(page.getByRole("button", { name: "Restore and read" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Results" })).toHaveCount(0);
});

test("unsupported files are refused before upload", async ({ page }) => {
  await mockApi(page);
  let uploads = 0;
  await page.route("**/api/jobs", (r) => {
    uploads++;
    return r.abort();
  });
  await page.goto("/studio");
  await page.getByLabel("Choose a page file").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("hello"),
  });
  await expect(page.getByRole("alert")).toContainText("notes.txt is not a supported file");
  expect(uploads).toBe(0);
});

test("dropping several files keeps the first and says so", async ({ page }) => {
  await mockApi(page);
  await page.goto("/studio");
  const transfer = await page.evaluateHandle(() => {
    const dt = new DataTransfer();
    dt.items.add(new File(["a"], "first.png", { type: "image/png" }));
    dt.items.add(new File(["b"], "second.png", { type: "image/png" }));
    return dt;
  });
  await page.locator(".dropzone").dispatchEvent("drop", { dataTransfer: transfer });
  await expect(page.locator(".fileticket__name")).toHaveText("first.png");
  await expect(page.getByText("1 other file was not added")).toBeVisible();
});

test("files tab offers one download for everything", async ({ page }) => {
  await mockApi(page);
  await runExample(page);
  await page.getByRole("tab", { name: "Files" }).click();
  await expect(page.getByRole("link", { name: "Download all files (.zip)" })).toHaveAttribute(
    "href",
    `/api/runs/${RUN.run_id}/files.zip`,
  );
});

test("review rows show the page pixels under each token", async ({ page }) => {
  await mockApi(page);
  await runExample(page);
  await page.getByRole("tab", { name: /^Review queue/ }).click();
  const crop = page.locator("canvas.review__crop").first();
  await expect(crop).toBeVisible();
  await expect.poll(async () => crop.evaluate((c: HTMLCanvasElement) => c.width)).toBeGreaterThan(1);
});
