/** Phone -> desktop bundles (docs/TECH_UPGRADE_PLAN.md B4): the desktop
 *  studio accepts a .veriscript file and says what came from the phone;
 *  the shared demo points to the desktop app instead. */
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { JOB_DONE, mockApi, RUN } from "./fixtures";

async function dropFile(page: Page, name: string) {
  const transfer = await page.evaluateHandle((n) => {
    const dt = new DataTransfer();
    dt.items.add(new File(["PK"], n, { type: "application/octet-stream" }));
    return dt;
  }, name);
  await page.locator(".dropzone").dispatchEvent("drop", { dataTransfer: transfer });
}

test("the desktop reads a phone bundle and says what came from the phone", async ({ page }) => {
  await mockApi(page, "ok", "local");
  const result = {
    ...RUN,
    meta: { ...RUN.meta, input_kind: "bundle", pages_processed: 3,
            from_phone: { pages: 3, corrected_lines: 2, confirmed_lines: 5 } },
    files: { ...RUN.files, phone_reading: "/api/runs/run-test-0001/files/phone_reading.json" },
  };
  await page.route("**/api/jobs", (r) =>
    r.fulfill({ status: 202, json: { ...JOB_DONE, status: "queued", result: undefined } }),
  );
  await page.route("**/api/jobs/*", (r) => r.fulfill({ json: { ...JOB_DONE, result } }));
  await page.goto("/studio");
  await expect(page.getByText("or a bundle from the phone app")).toBeVisible();
  await dropFile(page, "Ward 7.veriscript");
  await expect(page.locator(".fileticket__name")).toHaveText("Ward 7.veriscript");
  await page.getByRole("button", { name: "Restore and read" }).click();
  await expect(page.getByText("From the phone app: 3 pages, read again here.")).toBeVisible();
  await expect(page.getByText(/2 corrected and 5 confirmed lines from the phone/)).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test("the demo points phone bundles to the desktop app", async ({ page }) => {
  await mockApi(page);
  await page.goto("/studio");
  await dropFile(page, "Ward 7.veriscript");
  await expect(page.getByText("is a phone bundle. Open it in VeriScript Desktop.")).toBeVisible();
});

test("review shows the phone's corrections beside the desktop's reading", async ({ page }) => {
  await mockApi(page, "ok", "local");
  const [first, ...rest] = RUN.review;
  const result = {
    ...RUN,
    meta: { ...RUN.meta, input_kind: "bundle",
            from_phone: { pages: 1, corrected_lines: 1, confirmed_lines: 0 } },
    review: [
      { ...first, suggestions: [...(first.suggestions ?? []),
        { text: "१२३८", source: "phone", why: "Corrected on the phone (page 1)" }],
        phone: { agrees: false, page: 1, before: "जम्मा १२३४", after: "जम्मा १२३८" } },
      ...rest,
    ],
  };
  await page.route("**/api/jobs", (r) =>
    r.fulfill({ status: 202, json: { ...JOB_DONE, status: "queued", result: undefined } }),
  );
  await page.route("**/api/jobs/*", (r) => r.fulfill({ json: { ...JOB_DONE, result } }));
  await page.goto("/studio");
  await dropFile(page, "Ward 7.veriscript");
  await page.getByRole("button", { name: "Restore and read" }).click();
  await page.getByRole("tab", { name: /^Review/ }).click();
  await expect(page.getByText("Changed on the phone (page 1):")).toBeVisible();
  await page.getByRole("button", { name: "Use suggestion १२३८" }).click();
  await expect(page.getByRole("button", { name: /Apply corrections \(1\)/ })).toBeVisible();

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});
