/** Desktop library (docs/TECH_UPGRADE_PLAN.md B1): list, search, open in the
 *  studio, rename and delete; hidden on the shared demo. */
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockApi, RUN } from "./fixtures";

const DOCS = [
  { run_id: "aaaaaaaaaaaaaaaa", title: "Land record ward 7", created: 1794700000, pages: 3,
    flagged: 4, input_kind: "pdf", corrected: false },
  { run_id: "bbbbbbbbbbbbbbbb", title: "Invoice 12345", created: 1794600000, pages: 1,
    flagged: 0, input_kind: "image", corrected: true },
];

async function mockLibrary(page: Page) {
  await mockApi(page, "ok", "local");
  const calls: string[] = [];
  let docs = [...DOCS];
  await page.route("**/api/library*", (r) => {
    const q = new URL(r.request().url()).searchParams.get("q") ?? "";
    calls.push(`list:${q}`);
    const shown = docs.filter((d) => d.title.toLowerCase().includes(q.toLowerCase()));
    return r.fulfill({ json: { documents: shown, query: q } });
  });
  await page.route("**/api/runs/*/summary", (r) =>
    r.fulfill({ json: { ...RUN, run_id: "aaaaaaaaaaaaaaaa", expires_in: 0, title: DOCS[0].title } }),
  );
  await page.route(/\/api\/runs\/[a-z]{16}$/, (r) => {
    const id = r.request().url().split("/").pop()!;
    if (r.request().method() === "DELETE") {
      calls.push(`delete:${id}`);
      docs = docs.filter((d) => d.run_id !== id);
      return r.fulfill({ json: { run_id: id, deleted: true } });
    }
    const title = (r.request().postDataJSON() as { title: string }).title;
    calls.push(`rename:${id}:${title}`);
    docs = docs.map((d) => (d.run_id === id ? { ...d, title } : d));
    return r.fulfill({ json: { run_id: id, title } });
  });
  return calls;
}

test("the library lists, searches, renames and deletes", async ({ page }) => {
  const calls = await mockLibrary(page);
  await page.goto("/");
  await page.getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { name: "Your documents" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Land record ward 7", "Invoice 12345"]);
  await expect(page.getByText("3 pages · PDF · 4 to review")).toBeVisible();

  await page.getByLabel("Search titles and text").fill("invoice");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Invoice 12345"]);
  await page.getByLabel("Search titles and text").fill("");
  await expect(page.getByRole("heading", { level: 2 })).toHaveCount(2);

  await page.getByRole("button", { name: "Rename Invoice 12345" }).click();
  const box = page.getByLabel("New name for Invoice 12345");
  await box.fill("Invoice 12345 paid");
  await box.press("Enter");
  await expect(page.getByRole("heading", { name: "Invoice 12345 paid" })).toBeVisible();
  expect(calls).toContain("rename:bbbbbbbbbbbbbbbb:Invoice 12345 paid");

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete Land record ward 7" }).click();
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Invoice 12345 paid"]);
  expect(calls).toContain("delete:aaaaaaaaaaaaaaaa");
});

test("opening a document shows it in the studio", async ({ page }) => {
  await mockLibrary(page);
  await page.goto("/library");
  await page.getByRole("link", { name: "Open Land record ward 7" }).click();
  await expect(page).toHaveURL(/\/studio\?run=aaaaaaaaaaaaaaaa/);
  await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
  await expect(page.getByText("Land record ward 7, from your library")).toBeVisible();
});

test("the demo has no library", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Library" })).toHaveCount(0);
  await page.goto("/library");
  await expect(page.getByText("The library is part of the desktop app.")).toBeVisible();
});

test("the library meets WCAG 2.1 AA", async ({ page }) => {
  await mockLibrary(page);
  await page.goto("/library");
  await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});
