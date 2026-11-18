/**
 * Accessibility gate: axe-core (WCAG 2.0/2.1 A + AA) on every studio state.
 *
 * Ratchet: serious/critical violations fail the run unless the rule is listed
 * for that state in a11y-baseline.json (the known debt from
 * docs/UX_A11Y_AUDIT.md). A baseline entry that no longer occurs also fails,
 * so fixed debt cannot silently come back — delete the entry when you fix it.
 */
import { readFileSync } from "node:fs";
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

type Baseline = Record<string, string[]>;
const baseline: Baseline = JSON.parse(
  readFileSync(new URL("./a11y-baseline.json", import.meta.url), "utf8"),
);

const GATED = new Set(["serious", "critical"]);

async function audit(page: Page, state: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();

  await test.info().attach(`axe-${state}.json`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });

  const gated = results.violations.filter((v) => GATED.has(v.impact ?? ""));
  const found = [...new Set(gated.map((v) => v.id))].sort();
  const allowed = [...(baseline[state] ?? [])].sort();

  const unexpected = gated
    .filter((v) => !allowed.includes(v.id))
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.nodes.map((n) => n.target.join(" ")).slice(0, 5).join("\n    ")}`);
  const fixed = allowed.filter((id) => !found.includes(id));

  expect(unexpected, `new serious/critical axe violations in "${state}"`).toEqual([]);
  expect(fixed, `fixed — remove from a11y-baseline.json["${state}"]`).toEqual([]);
}

async function runExample(page: Page) {
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
}

test.describe("axe", () => {
  test("landing", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.locator("h1")).toBeVisible();
    await audit(page, "landing");
  });

  test("studio idle", async ({ page }) => {
    await mockApi(page);
    await page.goto("/studio");
    await expect(page.getByRole("button", { name: "Restore and read" })).toBeVisible();
    await audit(page, "studio-idle");
  });

  test("studio video mode", async ({ page }) => {
    await mockApi(page);
    await page.goto("/studio");
    await page.getByRole("tab", { name: "Book video" }).click();
    await expect(page.getByRole("button", { name: "Choose a video" })).toBeVisible();
    await audit(page, "studio-video");
  });

  test("studio error", async ({ page }) => {
    await mockApi(page, "error");
    await runExample(page);
    await expect(page.getByRole("alert")).toContainText("not an image");
    await audit(page, "studio-error");
  });

  for (const tab of ["Compare", "Review queue", "Transcript", "Files"]) {
    test(`studio result: ${tab}`, async ({ page }) => {
      await mockApi(page);
      await runExample(page);
      await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
      await expect(page.getByRole("tab", { name: new RegExp(`^${tab}`) })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      await audit(page, `result-${tab.toLowerCase().replace(/\s+/g, "-")}`);
    });
  }
});

test.describe("axe in dark mode", () => {
  test.use({ colorScheme: "dark" });

  test("studio idle (dark)", async ({ page }) => {
    await mockApi(page);
    await page.goto("/studio");
    await expect(page.getByRole("button", { name: "Restore and read" })).toBeVisible();
    await audit(page, "studio-idle-dark");
  });

  test("studio results (dark)", async ({ page }) => {
    await mockApi(page);
    await runExample(page);
    await page.getByRole("tab", { name: /^Review queue/ }).click();
    await expect(page.getByRole("button", { name: /^Keep/ }).first()).toBeVisible();
    await audit(page, "result-review-queue-dark");
  });

  test("landing (dark)", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await audit(page, "landing-dark");
  });
});

test("the theme switch overrides the system setting and is remembered", async ({ page }) => {
  await mockApi(page);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/studio");
  const toggle = page.getByRole("button", { name: /^Theme:/ });
  await expect(toggle).toHaveText("Theme: Auto");
  await toggle.click(); // Light
  await toggle.click(); // Dark
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe("rgb(17, 21, 27)");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /^Theme:/ }).click(); // back to Auto
  await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
});
