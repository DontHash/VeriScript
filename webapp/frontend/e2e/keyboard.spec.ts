/**
 * Keyboard and screen-reader behaviour that axe cannot see.
 *
 * Tests marked `test.fail()` (none today) are known debt from docs/UX_A11Y_AUDIT.md: they
 * are expected to fail today. When a fix lands Playwright reports them as
 * "unexpectedly passed", which fails the run — remove the `test.fail()` line
 * then, so the behaviour stays locked in.
 */
import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

/** WCAG relative-luminance contrast of two `rgb(...)` strings. */
function contrast(a: string, b: string): number {
  const lum = (c: string) => {
    const [r, g, bl] = (c.match(/[\d.]+/g) ?? ["0", "0", "0"]).slice(0, 3).map((v) => {
      const s = Number(v) / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Tab through the page; return the focus outline/background of each stop. */
async function focusStops(page: Page, max = 25) {
  const stops: { label: string; outline: string; width: number; bg: string }[] = [];
  for (let i = 0; i < max; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      let bgEl: HTMLElement | null = el.parentElement;
      let bg = "rgb(255, 255, 255)";
      while (bgEl) {
        const c = getComputedStyle(bgEl).backgroundColor;
        if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") {
          bg = c;
          break;
        }
        bgEl = bgEl.parentElement;
      }
      return {
        label: (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40),
        outline: cs.outlineStyle === "none" ? "none" : cs.outlineColor,
        width: parseFloat(cs.outlineWidth) || 0,
        bg,
      };
    });
    if (!info) break;
    stops.push(info);
  }
  return stops;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("skip link is the first stop and lands on main", async ({ page, isMobile }) => {
  test.skip(isMobile, "no hardware keyboard");
  await page.goto("/studio");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main$/);
});

for (const path of ["/", "/studio"]) {
  test(`every focus stop on ${path} has a visible indicator ≥ 3:1 (WCAG 2.4.7 / 1.4.11)`, async ({
    page,
    isMobile,
  }) => {
    test.skip(isMobile, "no hardware keyboard");
    await page.goto(path);
    const stops = await focusStops(page, 40);
    expect(stops.length).toBeGreaterThan(5);
    const weak = stops
      .filter((s) => s.outline === "none" || s.width < 2 || contrast(s.outline, s.bg) < 3)
      .map((s) => `${s.label}: ${s.outline} on ${s.bg}`);
    expect(weak).toEqual([]);
  });
}

test("result tabs move with arrow keys (APG tabs pattern)", async ({ page, isMobile }) => {
  test.skip(isMobile, "no hardware keyboard");
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
  const compare = page.getByRole("tab", { name: "Compare" });
  await compare.focus();
  await page.keyboard.press("ArrowRight");
  const queue = page.getByRole("tab", { name: /^Review queue/ });
  await expect(queue).toBeFocused();
  await expect(queue).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(`#${await queue.getAttribute("aria-controls")}`)).toBeVisible();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "Files" })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(compare).toBeFocused();
});

test("run completion is announced in a live region", async ({ page }) => {
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
  await expect(page.getByRole("tab", { name: "Compare" })).toBeVisible();
  await expect(page.locator('[role="status"][aria-live="polite"]')).toContainText(/^Done\./);
  await expect(page.getByRole("heading", { name: "Results" })).toBeFocused();
});

test("options disclosure exposes aria-expanded", async ({ page }) => {
  await page.goto("/studio");
  const toggle = page.getByRole("button", { name: /options/i });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByLabel("OCR engine")).toBeHidden();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByLabel("OCR engine")).toBeVisible();
});
