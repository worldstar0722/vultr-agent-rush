// Manual browser smoke test (not run in CI). Needs node + playwright and a running server:
//   DB_PATH=./gradecase.db uvicorn app.main:create_app --factory --port 8000
//   NODE_PATH=$(npm root -g) node scripts/ui_smoke.js http://localhost:8000 ./shots
// Resets the demo data first, then walks the main flows and saves screenshots.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.argv[2] || "http://localhost:8000";
const OUT = process.argv[3] || "./shots";
fs.mkdirSync(OUT, { recursive: true });
let failed = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`); if (!ok) failed++; };

(async () => {
  await fetch(`${BASE}/api/demo/reset?confirm=true`, { method: "POST" });
  const browser = await chromium.launch();
  for (const [label, vp] of [["desktop", { width: 1440, height: 1000 }], ["laptop", { width: 1280, height: 800 }], ["mobile", { width: 390, height: 844 }]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: label === "mobile" ? 2 : 1 });
    const p = await ctx.newPage();
    const errs = [];
    p.on("pageerror", (e) => errs.push("pageerror: " + e.message));
    p.on("console", (m) => m.type() === "error" && errs.push("console: " + m.text()));
    p.on("dialog", (d) => d.accept());
    await p.goto(BASE + "/#/queue");
    await p.waitForSelector(".qrow");
    const overflow = () => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await p.screenshot({ path: `${OUT}/${label}-queue.png`, fullPage: true });
    check(`${label}: queue has 5 rows`, (await p.locator(".qrow").count()) === 5);
    check(`${label}: no horizontal overflow (queue)`, (await overflow()) <= 0, String(await overflow()));
    await p.goto(BASE + "/#/case/CASE-A/evidence");
    await p.waitForSelector(".timeline");
    await p.screenshot({ path: `${OUT}/${label}-evidence.png`, fullPage: true });
    check(`${label}: no horizontal overflow (evidence)`, (await overflow()) <= 0, String(await overflow()));
    await p.goto(BASE + "/#/case/CASE-A/decision");
    await p.waitForSelector("#body");
    await p.screenshot({ path: `${OUT}/${label}-decision.png`, fullPage: true });
    check(`${label}: no horizontal overflow (decision)`, (await overflow()) <= 0, String(await overflow()));
    check(`${label}: no console errors`, errs.length === 0, errs.join(" | "));
    await ctx.close();
  }

  // ---- functional flows (desktop)
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message));
  p.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  p.on("dialog", (d) => d.accept());
  await p.goto(BASE + "/#/queue");
  await p.waitForSelector(".qrow");

  await p.fill('input[type="search"]', "zzzz-nothing");
  check("search with no match shows the empty state", await p.locator(".empty").isVisible());
  await p.screenshot({ path: `${OUT}/desktop-queue-empty.png` });
  await p.click('.empty button:has-text("Clear filters")');
  check("clear filters restores the list", (await p.locator(".qrow").count()) === 5);
  await p.fill('input[type="search"]', "hw4");
  check("search by assignment narrows to Case B", (await p.locator(".qrow").count()) === 1 && /Score does not match rubric/.test(await p.locator(".qrow").innerText()));
  await p.fill('input[type="search"]', "");

  await p.focus('.caselink:has-text("Emailed file")');
  await p.keyboard.press("Enter");
  await p.waitForSelector(".timeline");
  check("keyboard Enter on a case link opens the case", /CASE-C/.test(p.url()));
  await p.screenshot({ path: `${OUT}/desktop-evidence-C.png`, fullPage: true });
  check("Case C shows the missing policy clearly", await p.locator("text=Policy not found").isVisible());
  await p.goto(BASE + "/#/case/CASE-B/evidence");
  await p.waitForSelector(".bars");
  await p.screenshot({ path: `${OUT}/desktop-evidence-B.png`, fullPage: true });
  const bars = await p.locator(".bars").innerText();
  check("Case B shows rubric 10 vs entered 8", /Rubric total\s*10/.test(bars) && /Entered\s*8/.test(bars));

  await p.goto(BASE + "/#/case/CASE-C/decision");
  await p.waitForSelector("#body");
  await p.click("#role-professor");
  const apr = p.locator('button[data-action="approve"]');
  check("C: Approve is disabled with a visible reason", (await apr.isDisabled()) && /Blocked/.test(await p.locator("#why-approve").innerText()));
  await p.click("#role-ta");
  await p.screenshot({ path: `${OUT}/desktop-decision-C.png`, fullPage: true });

  await p.goto(BASE + "/#/queue");
  await p.waitForSelector(".dup");
  await p.click(".dup > summary");
  await p.screenshot({ path: `${OUT}/desktop-queue-dup.png` });
  await p.click('.dup button:has-text("Merge CASE-A2 into CASE-A")');
  await p.waitForSelector(".notice.success");
  check("manual duplicate merge works", (await p.locator(".qrow").count()) === 4 && (await p.locator(".dup").count()) === 0);

  await p.goto(BASE + "/#/case/CASE-A/decision");
  await p.waitForSelector("#body");
  const primary = (await p.locator(".act.primary button").innerText()).trim();
  check("A as TA: primary action is Request professor review", primary === "Request professor review", primary);
  check("A as TA: Approve disabled with reason", (await p.locator('button[data-action="approve"]').isDisabled()) && /Professor-only/.test(await p.locator("#why-approve").innerText()));
  await p.click(".act.primary button");
  check("note is required before recording", /required/.test(await p.locator("#note-err").innerText()));
  await p.fill("#note", "Professor ruling needed on attempt 1");
  await p.click(".act.primary button");
  await p.waitForSelector(".notice.success");
  check("escalation recorded with status and nothing-sent text", /Awaiting professor/.test(await p.locator(".notice.success").innerText()) && /Nothing was sent/.test(await p.locator(".notice.success").innerText()));

  // unsaved edit guard + preserved fields on error
  await p.click("#role-professor");
  await p.waitForSelector(".act.primary button");
  check("A as Professor: primary action is Approve decision", (await p.locator(".act.primary button").innerText()).trim() === "Approve decision");
  await p.fill("#note", "Attempt 1 counts");
  await p.fill("#body", "We cannot say yet what will happen [ATT-A1].");
  let dialogs = 0;
  p.removeAllListeners("dialog");
  p.on("dialog", (d) => { dialogs++; d.dismiss(); });
  await p.click("#role-ta");
  check("unsaved edit warns before role switch (dismissed keeps role)", dialogs === 1 && (await p.locator("#role-professor").getAttribute("aria-pressed")) === "true");
  await p.selectOption("#counted", "ATT-A1");
  await p.click(".act.primary button");
  await p.waitForSelector("#form-err .notice");
  check("error keeps note, attempt and draft text", (await p.inputValue("#note")) === "Attempt 1 counts" && (await p.inputValue("#counted")) === "ATT-A1" && /cannot say yet/.test(await p.inputValue("#body")));
  p.removeAllListeners("dialog");
  p.on("dialog", (d) => d.accept());
  await p.click('button:has-text("Regenerate draft")');
  await p.waitForSelector(".notice.info");
  await p.selectOption("#counted", "ATT-A1");
  await p.fill("#note", "Attempt 1 counts");
  await p.click(".act.primary button");
  await p.waitForSelector(".notice.success");
  const txt = await p.locator(".notice.success").innerText();
  check("professor approval closes the case", /Closed/.test(txt) && /No Canvas change/.test(txt));
  const finalBody = await p.inputValue("#body");
  check("approved reply cites APR-A-1 and has no pending claim", /APR-A-1/.test(finalBody) && !/cannot say yet/.test(finalBody));
  check("score recommendation control enabled, labelled correctly", await p.locator('button:has-text("Record score recommendation")').isEnabled());
  await p.screenshot({ path: `${OUT}/desktop-decision-A-done.png`, fullPage: true });
  await p.click('button:has-text("Record score recommendation")');
  await p.waitForSelector(".notice.success");
  await p.reload();
  await p.waitForSelector("#body");
  check("refresh keeps the decision", /Closed/.test(await p.locator(".metarow").innerText()) && (await p.locator(".activity li").count()) >= 3);
  // The one 409 is the intentional "stale pending wording" rejection above; anything else is a bug.
  const unexpected = errs.filter((e) => !/status of 409/.test(e));
  check("no unexpected console errors in flows", unexpected.length === 0, unexpected.join(" | "));
  await browser.close();
  await fetch(`${BASE}/api/demo/reset?confirm=true`, { method: "POST" });
  console.log(failed ? `\n${failed} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
  process.exit(failed ? 1 : 0);
})();
