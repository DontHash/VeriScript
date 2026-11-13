/** The studio describes where processing happens truthfully (audit W15). */
import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

test("local mode says pages stay on this computer", async ({ page }) => {
  await mockApi(page, "ok", "local");
  await page.goto("/studio");
  await expect(page.locator(".studio__head .lede")).toContainText("processed on this computer");
  await expect(page.locator("footer")).toContainText("your pages stay on this computer");
  await expect(page.getByText(/demo/i)).toHaveCount(0);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "This copy runs on your machine" })).toBeVisible();
});

test("demo mode says the demo uses its server", async ({ page }) => {
  await mockApi(page, "ok", "demo");
  await page.goto("/studio");
  await expect(page.locator(".studio__head .lede")).toContainText("This demo processes pages on its server");
});
