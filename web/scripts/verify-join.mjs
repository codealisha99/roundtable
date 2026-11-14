// Verifies the web client end to end: it loads, joins the LiveKit room as a human with a fake microphone,
// and reports the connection state. Requires the token API on 4501, the web app on 4500, and LiveKit on 7880.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const WEB = process.env.ROUNDTABLE_WEB ?? "http://127.0.0.1:4500";
const OUT = fileURLToPath(new URL("../../out/web/", import.meta.url));
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  headless: true,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const context = await browser.newContext({ permissions: ["microphone"], viewport: { width: 1280, height: 820 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err.message}`));
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok, detail });

try {
  await page.goto(WEB, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Roundtable" }).waitFor({ timeout: 15000 });
  check("join page renders", true);
  await page.screenshot({ path: `${OUT}join.png`, fullPage: true });

  await page.getByLabel("Your name").fill("Verifier");
  await page.getByRole("button", { name: "Take a seat" }).click();
  await page.getByText(/· live$/).waitFor({ timeout: 30000 });
  check("joined the LiveKit room", true);

  await page.getByRole("button", { name: /^Mute$/ }).waitFor({ timeout: 15000 });
  const micPressed = await page.getByRole("button", { name: /^Mute$/ }).getAttribute("aria-pressed");
  check("microphone enabled after join", micPressed === "true", `aria-pressed=${micPressed}`);

  await page.getByRole("heading", { name: "Agent" }).waitFor({ timeout: 10000 });
  const agentChip = await page.locator(".chip").first().textContent();
  check("agent panel renders state", Boolean(agentChip), `chip=${agentChip}`);

  const seats = await page.locator(".seat__name").allTextContents();
  check("participant tile for self", seats.some((s) => s.includes("Verifier")), `seats=${JSON.stringify(seats)}`);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}room.png`, fullPage: true });
} catch (err) {
  check("verification flow completed", false, err instanceof Error ? err.message : String(err));
  await page.screenshot({ path: `${OUT}failure.png`, fullPage: true }).catch(() => {});
} finally {
  // Leave the room cleanly so the server does not keep a ghost participant after the browser closes.
  await page.getByRole("button", { name: "Leave" }).click({ timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(800);
  await browser.close();
}

const relevantErrors = consoleErrors.filter((e) => !/favicon|fonts\.g|ERR_NAME|Failed to load resource/.test(e));
check("no uncaught page errors", relevantErrors.filter((e) => e.startsWith("pageerror")).length === 0, relevantErrors.slice(0, 3).join(" | "));
for (const c of checks) console.log(`${c.ok ? "PASS" : "FAIL"}  ${c.name}${c.detail ? `  (${c.detail})` : ""}`);
process.exit(checks.every((c) => c.ok) ? 0 : 1);
