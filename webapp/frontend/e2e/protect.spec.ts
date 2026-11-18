/** Password-protected PDFs (docs/TECH_UPGRADE_PLAN.md E5): the Files tab
 *  offers a protected download; the password is checked before sending
 *  and the server's refusal is shown. */
import { AxeBuilder } from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

test("a PDF can be downloaded with a password", async ({ page }) => {
  await mockApi(page);
  let sent: { file: string; password: string } | null = null;
  await page.route("**/api/runs/*/protect", async (r) => {
    sent = r.request().postDataJSON();
    if (sent!.password === "server-refuses") {
      return r.fulfill({ status: 400, json: { detail: "That password is too long; use at most 127 bytes." } });
    }
    return r.fulfill({ body: "%PDF-1.7 encrypted", contentType: "application/pdf" });
  });
  await page.goto("/studio");
  await page.getByRole("button", { name: "Invoice photo" }).click();
  await page.getByRole("button", { name: "Restore and read" }).click();
  await page.getByRole("tab", { name: /^Files/ }).click();
  await page.getByText("Download a PDF with a password").click();

  await page.getByLabel("Password", { exact: true }).fill("ward-7-record");
  await page.getByLabel("Password again").fill("ward-7-recrd");
  await expect(page.getByRole("alert")).toHaveText("The two passwords differ.");

  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  expect(serious.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  await page.getByLabel("Password again").fill("ward-7-record");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download protected PDF" }).click();
  expect((await download).suggestedFilename()).toBe("searchable-protected.pdf");
  expect(sent).toEqual({ file: "searchable.pdf", password: "ward-7-record" });
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");

  await page.getByLabel("Password", { exact: true }).fill("server-refuses");
  await page.getByLabel("Password again").fill("server-refuses");
  await page.getByRole("button", { name: "Download protected PDF" }).click();
  await expect(page.getByRole("alert")).toContainText("too long");
});
