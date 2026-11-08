// Manual browser smoke test (not run in CI: it needs node + playwright). Mock-AI mode only.
//   DB_PATH=./gradecase.db uvicorn app.main:create_app --factory --port 8000
//   NODE_PATH=$(npm root -g) node scripts/ui_smoke.js http://localhost:8000 ./shots
// It resets the demo data first and last, walks the main flows and saves screenshots.
// It never calls a real model: run it against a server WITHOUT VULTR_INFERENCE_API_KEY.
const { chromium } = require("playwright");
const fs = require("fs");

const BASE = process.argv[2] || "http://localhost:8000";
const OUT = process.argv[3] || "./shots";
fs.mkdirSync(OUT, { recursive: true });
let failed = 0;
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`);
  if (!ok) failed++;
};
// Google Fonts may be unreachable in a sandbox; the page falls back to system fonts
const isFont = (m) => /fonts\.(googleapis|gstatic)\.com/.test((m.location() || {}).url || "");
// a valid 1x1 PNG
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");

(async () => {
  const cfg = await (await fetch(`${BASE}/api/config`)).json();
  if (cfg.ai_mode !== "mock") { console.error("Refusing to run: this server has live AI configured."); process.exit(2); }
  await fetch(`${BASE}/api/demo/reset?confirm=true`, { method: "POST" });
  const browser = await chromium.launch();

  // ---------------------------------------------------------------- layouts at three sizes
  for (const [label, vp] of [["desktop", { width: 1440, height: 1000 }], ["laptop", { width: 1280, height: 800 }], ["mobile", { width: 390, height: 844 }]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: label === "mobile" ? 2 : 1 });
    const p = await ctx.newPage();
    const errs = [];
    p.on("pageerror", (e) => errs.push("pageerror: " + e.message));
    p.on("console", (m) => m.type() === "error" && !isFont(m) && errs.push("console: " + m.text()));
    p.on("dialog", (d) => d.accept());
    const overflow = () => p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    for (const [name, hash, waitFor] of [["dashboard", "#/dashboard", ".hero"], ["queue", "#/queue", ".qrow"], ["evidence", "#/case/CASE-A/evidence", ".timeline"],
      ["decision", "#/case/CASE-A/decision", "#run-analysis"], ["intake", "#/new", ".vision"],
      ["board", "#/board", ".kcol"], ["calendar", "#/calendar", ".calgrid"]]) {
      await p.goto(BASE + "/" + hash);
      await p.waitForSelector(waitFor);
      await p.screenshot({ path: `${OUT}/${label}-${name}.png`, fullPage: true });
      check(`${label}: no horizontal overflow (${name})`, (await overflow()) <= 0, String(await overflow()));
    }
    if (label === "mobile") {
      await p.goto(BASE + "/#/dashboard");
      await p.waitForSelector(".hero");
      check("mobile: compact top bar with a hamburger and an icon-only nav", (await p.locator("#menu-btn").isVisible()) && !(await p.locator("#nav .navlabel").first().isVisible()) && (await p.locator("#rail").boundingBox()).height <= 70, String((await p.locator("#rail").boundingBox()).height));
      check("mobile: the role switch is not in the bar", !(await p.locator("#role-professor").isVisible()));
      await p.click("#menu-btn");
      check("mobile: the menu opens the full sidebar (labels, role switch, AI card)", (await p.locator("#role-professor").isVisible()) && (await p.locator("#ai").isVisible()) && (await p.locator("#nav .navlabel").first().isVisible()));
      await p.screenshot({ path: `${OUT}/mobile-menu.png` });
      await p.keyboard.press("Escape");
      check("mobile: Escape closes the menu", !(await p.locator("#role-professor").isVisible()));
    }
    check(`${label}: no console errors`, errs.length === 0, errs.join(" | "));
    await ctx.close();
  }

  // ---------------------------------------------------------------- functional flows (desktop)
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message));
  p.on("console", (m) => m.type() === "error" && !isFont(m) && errs.push(m.text()));
  p.on("dialog", (d) => d.accept());
  const go = async (hash, sel) => { await p.goto(BASE + "/" + hash); await p.waitForSelector(sel); };

  await go("#/queue", ".qrow");
  check("rail says mock / not connected", /Live AI not connected/.test(await p.locator("#ai").innerText()));
  await p.fill('input[type="search"]', "zzzz-nothing");
  check("search with no match shows the empty state", await p.locator(".empty").isVisible());
  await p.click('.empty button:has-text("Clear filters")');
  check("clear filters restores the list", (await p.locator(".qrow").count()) === 5);
  await p.focus('.caselink:has-text("Emailed file")');
  await p.keyboard.press("Enter");
  await p.waitForSelector(".timeline");
  check("keyboard Enter opens the case", /CASE-C/.test(p.url()));
  check("Case C shows the missing policy clearly", await p.locator("text=Policy not found").isVisible());

  // decision page never runs the analysis by itself
  await go("#/case/CASE-C/decision", "#run-analysis");
  check("opening Decision does not create a draft", (await p.locator("#body").count()) === 0);
  await p.click("#run-analysis");
  await p.waitForSelector("#body");
  const stages = await p.locator(".pipeline .pstep").allInnerTexts();
  check("workflow shows the 6 real stages", stages.length === 6 && /Load evidence/.test(stages[0]) && /Await human/.test(stages[5]), String(stages.length));
  check("mock run is labelled as mock (no model called)", /no AI model is called|no model was called/i.test(await p.locator(".aipanel").innerText()));
  await p.click("#role-professor");
  check("C: Approve is disabled with a visible reason", (await p.locator('button[data-action="approve"]').isDisabled()) && /Blocked/.test(await p.locator("#why-approve").innerText()));
  await p.click("#role-ta");

  await go("#/queue", ".dup");
  await p.click(".dup > summary");
  await p.click('.dup button:has-text("Merge CASE-A2 into CASE-A")');
  await p.waitForSelector(".notice.success");
  check("manual duplicate merge works", (await p.locator(".qrow").count()) === 4 && (await p.locator(".dup").count()) === 0);

  // ---- dashboard, AI transparency, guardrail demonstration
  await go("#/dashboard", ".hero");
  const dash = await p.locator("#view").innerText();
  check("dashboard: is the landing page, with the tagline and the AI-explains / humans-decide chips",
    /정보는 있는데, 사건은 없다/.test(dash) && /The data exists, but the case doesn't/.test(dash) && /Rules compute times and scores/.test(dash) && /AI explains and drafts/.test(dash) && /Humans decide/.test(dash));
  check("dashboard: four stat cards with real labels", (await p.locator(".scard").count()) === 4 && /Total cases/.test(dash) && /Need action/.test(dash) && /Closed today/.test(dash) && /Avg model latency/.test(dash));
  check("dashboard: no invented 'time saved' figure", !/time saved|~\s*12 min/i.test(dash));
  check("dashboard: a bar for each of the five statuses", (await p.locator(".dashcard .hbar").count()) === 5);
  check("dashboard: mock mode says no model is called and never claims 'Connected'", /Mock mode/.test(await p.locator(".dashgrid").innerText()) && !/Connected/.test(await p.locator("#ai").innerText()));
  check("dashboard: recent activity lists real events", (await p.locator(".feed li").count()) >= 3);
  await p.click('a:has-text("Open the demo case")');
  await p.waitForSelector(".timeline");
  check("dashboard: the demo-case button opens CASE-A", /CASE-A/.test(p.url()));
  await p.click("#run-analysis");
  await p.waitForSelector(".aicard .gtable");
  check("evidence: the AI card shows classification match and the 6-step pipeline", (await p.locator(".aicard .match .res").count()) === 1 && (await p.locator(".aicard .pipeline .pstep").count()) === 6);
  check("evidence: guardrails show 4/4 on the mock template and say no model was involved", /4\/4 passed/.test(await p.locator(".aicard").innerText()) && /No model was involved/.test(await p.locator(".aicard").innerText()));
  check("evidence: the card says AI explains, humans decide", /AI explains/.test(await p.locator(".aicard").innerText()) && /Humans decide/.test(await p.locator(".aicard").innerText()));
  await p.click('button:has-text("See the guardrails catch a bad reply")');
  await p.waitForSelector(".demo-box .gtable");
  const demo = await p.locator(".demo-box").innerText();
  check("guardrail demonstration: labelled as not from a model, checks FAIL, reply rejected", /did not come from a model/.test(demo) && /FAILED/.test(demo) && /Rejected/.test(demo) && /POL-DEMO-v9/.test(demo));
  await p.screenshot({ path: `${OUT}/desktop-evidence-ai.png`, fullPage: true });
  check("the demonstration changed nothing (still one stored run)", (await (await fetch(`${BASE}/api/cases/CASE-A`)).json()).workflow.runs.length === 1);

  // ---- Case A: the whole decision flow
  await go("#/case/CASE-A/decision", "#run-analysis");
  check("A as TA: primary is Request professor review", (await p.locator(".act.primary button").innerText()).trim() === "Request professor review");
  check("A as TA: Approve disabled with a reason", (await p.locator('button[data-action="approve"]').isDisabled()) && /Professor-only|Run the analysis/.test(await p.locator("#why-approve").innerText()));
  await p.click("#run-analysis");
  await p.waitForSelector("#body");
  await p.click(".act.primary button");
  check("note is required before recording", /required/.test(await p.locator("#note-err").innerText()));
  await p.fill("#note", "Professor ruling needed on attempt 1");
  check("decision: exactly one step is active, and finishing the note completes step 2", (await p.locator(".step.active").count()) === 1 && (await p.locator(".step").nth(1).evaluate((el) => el.classList.contains("done"))));
  await p.click(".act.primary button");
  await p.waitForSelector(".notice.success");
  check("escalation recorded: status, nothing sent", /Awaiting professor/.test(await p.locator(".notice.success").innerText()) && /Nothing was sent/.test(await p.locator(".notice.success").innerText()));
  check("waiting for professor: a TA gets no primary 'request student info'", (await p.locator(".act.primary").count()) === 0 && (await p.locator("text=This case is with the professor").count()) > 0);

  await p.click("#role-professor");
  await p.waitForSelector(".act.primary button");
  check("A as Professor: primary is Approve decision", (await p.locator(".act.primary button").innerText()).trim() === "Approve decision");
  await p.fill("#note", "Attempt 1 counts");
  await p.fill("#body", "We cannot say yet what will happen [ATT-A1].");
  let dialogs = 0;
  p.removeAllListeners("dialog");
  p.on("dialog", (d) => { dialogs++; d.dismiss(); });
  await p.click("#role-ta");
  check("unsaved edit warns before role switch (dismiss keeps role)", dialogs === 1 && (await p.locator("#role-professor").getAttribute("aria-pressed")) === "true");
  await p.selectOption("#counted", "ATT-A1");
  await p.click(".act.primary button");
  await p.waitForSelector("#form-err .notice");
  check("error keeps note, attempt and draft text", (await p.inputValue("#note")) === "Attempt 1 counts" && (await p.inputValue("#counted")) === "ATT-A1" && /cannot say yet/.test(await p.inputValue("#body")));
  p.removeAllListeners("dialog");
  p.on("dialog", (d) => d.accept());
  await p.click('button:has-text("Regenerate analysis")');
  await p.waitForSelector(".notice.info, .notice.success");
  await p.selectOption("#counted", "ATT-A1");
  await p.fill("#note", "Attempt 1 counts");
  await p.click(".act.primary button");
  await p.waitForSelector(".notice.success");
  check("professor approval closes the case", /Closed/.test(await p.locator(".notice.success").innerText()) && /No Canvas change/.test(await p.locator(".notice.success").innerText()));
  const finalBody = await p.inputValue("#body");
  check("approved reply cites APR-A-1 and has no pending claim", /APR-A-1/.test(finalBody) && !/cannot say yet/.test(finalBody));
  check("closed case: no note box, no action buttons, reply read-only",
    (await p.locator("#note").count()) === 0 && (await p.locator(".act").count()) === 0 && (await p.locator("#body").getAttribute("readonly")) !== null && (await p.locator("#run-analysis").count()) === 0);
  check("score control is labelled as a recommendation only", await p.locator('button:has-text("Record score recommendation")').isEnabled() && /never writes to Canvas/.test(await p.locator(".scorebox").innerText()));
  await p.screenshot({ path: `${OUT}/desktop-decision-A-done.png`, fullPage: true });
  await p.click('button:has-text("Record score recommendation")');
  await p.waitForSelector(".notice.success");
  await go("#/case/CASE-A/evidence", ".timeline");
  const summary = await p.locator(".summary").innerText();
  check("evidence summary reconciles after approval (gradebook still differs)", /still shows 7/.test(summary) && !/Records are consistent/.test(summary));
  check("AI card marks the analysis as generated before the decision", /generated before the decision/i.test(await p.locator(".colmain").innerText()));
  await p.reload();
  await p.waitForSelector(".timeline");
  check("refresh keeps the decision", /Closed/.test(await p.locator(".metarow").innerText()));

  // ---- board: counts, drag-and-drop through the real decision API, keyboard-accessible Move menu
  await go("#/board", ".kcol");
  const apiCases = await (await fetch(`${BASE}/api/cases`)).json();
  const badge = async (status) => Number((await p.locator(`.kcol[data-status="${status}"] .tabcount`).innerText()).trim());
  let countsOk = true;
  for (const st of ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"]) {
    if ((await badge(st)) !== apiCases.filter((c) => c.status === st).length) countsOk = false;
  }
  check("board: five columns whose count badges match the data", (await p.locator(".kcol").count()) === 5 && countsOk);
  check("board: closed cards cannot be dragged", (await p.locator('.kcol[data-status="Closed"] .kcard[draggable="true"]').count()) === 0);
  const infoBefore = await badge("Awaiting student info");
  await p.locator('.kcard[data-id="CASE-C"]').dragTo(p.locator('.kcol[data-status="New"]'));
  check("board: dropping on New is refused (no dialog)", (await p.locator("dialog.movedlg").count()) === 0);
  await p.locator('.kcard[data-id="CASE-C"]').dragTo(p.locator('.kcol[data-status="Awaiting student info"]'));
  await p.waitForSelector("dialog.movedlg[open]");
  check("board: drop opens a confirmation naming the action", /Move CASE-C to Awaiting student info/.test(await p.locator("dialog h2").innerText()) && /Request student information/.test(await p.locator("dialog").innerText()));
  await p.click('dialog button:has-text("Record move")');
  check("board: a note is required", /note/i.test(await p.locator("dialog .fielderr").innerText()) && (await p.locator("dialog[open]").count()) === 1);
  await p.screenshot({ path: `${OUT}/desktop-board-dialog.png` });
  await p.fill("#mv-note", "Ask for the forwarded email");
  await p.click('dialog button:has-text("Record move")');
  await p.waitForSelector(".notice.success");
  check("board: the card moved and the move is a logged decision",
    (await p.locator('.kcol[data-status="Awaiting student info"] .kcard[data-id="CASE-C"]').count()) === 1 && (await badge("Awaiting student info")) === infoBefore + 1
    && /Logged/.test(await p.locator(".notice.success").innerText()));
  const c = await (await fetch(`${BASE}/api/cases/CASE-C`)).json();
  check("board: server status and decision log agree", c.case.status === "Awaiting student info" && c.decisions.at(-1).action === "request_info");
  // keyboard / touch alternative, and server rules still apply (a TA may not approve a blocked case)
  await p.click('.kcard[data-id="CASE-B"] .movemenu summary');
  check("board: the move menu lists only valid targets (never New)", (await p.locator('.kcard[data-id="CASE-B"] .menu button:has-text("New")').count()) === 0 && (await p.locator('.kcard[data-id="CASE-B"] .menu button').count()) === 4);
  await p.click('.kcard[data-id="CASE-B"] .menu button:has-text("Closed")');
  await p.waitForSelector("dialog.movedlg[open]");
  await p.click('dialog button:has-text("Record move")');
  await p.waitForSelector("dialog .notice.error");
  check("board: the Move menu works and server rules still block an invalid close", /Not moved/.test(await p.locator("dialog .notice.error").innerText()) && (await p.locator('.kcol[data-status="Closed"] .kcard[data-id="CASE-B"]').count()) === 0);
  await p.click('dialog button:has-text("Cancel")');
  await p.screenshot({ path: `${OUT}/desktop-board.png`, fullPage: true });

  // ---- calendar: month navigation, dots, click a day
  await go("#/calendar", ".calgrid");
  const head = async () => (await p.locator(".calhead").innerText()).trim();
  check("calendar: events are pills with text inside the day cells", (await p.locator(".day .evpill").count()) > 0 && /Due|Opened|Decision/.test(await p.locator(".day .evpill").first().innerText()), await head());
  let guard = 0;
  while (!/November 2026/.test(await head()) && guard++ < 24) await p.click(/20(2[7-9]|3)/.test(await head()) ? 'button[aria-label="Previous month"]' : 'button[aria-label="Next month"]');
  check("calendar: month navigation reaches November 2026", /November 2026/.test(await head()));
  await p.click('button.day[aria-label^="November 5, 2026"]');
  const panel = await p.locator(".daypanel").innerText();
  check("calendar: clicking a date lists its deadline and case", /Deadline/.test(panel) && /Homework 3/.test(panel) && /CASE-A/.test(panel));
  await p.screenshot({ path: `${OUT}/desktop-calendar.png`, fullPage: true });
  await p.click('button[aria-label="Next month"]');
  check("calendar: next month changes the heading and clears the selection", /December 2026/.test(await head()) && /Select a day/.test(await p.locator(".daypanel").innerText()));
  await p.click('button[aria-label="Previous month"]');
  await p.click('button.day[aria-label^="November 6, 2026"]');
  check("calendar: colour is never the only cue (labelled and listed)", /resolved|pending|overdue/.test(await p.locator(".daypanel").innerText()) && /overdue|pending|resolved/.test(await p.locator('button.day[aria-label^="November 6, 2026"]').getAttribute("aria-label")));
  check("rail has Board and Calendar links", (await p.locator('#nav a[href="#/board"]').count()) === 1 && (await p.locator('#nav a[href="#/calendar"]').count()) === 1);

  // overdue = an OPEN case older than 7 days. Move the browser clock forward to prove the red marker.
  const late = await ctx.newPage();
  await late.clock.install({ time: new Date("2026-11-20T12:00:00-07:00") });
  late.on("dialog", (d) => d.accept());
  await late.goto(BASE + "/#/calendar");
  await late.waitForSelector(".calgrid");
  check("calendar: open cases older than 7 days show the overdue marker", (await late.locator(".day .e-overdue").count()) > 0 && /Overdue/.test(await late.locator(".legend").innerText()));
  const overdueLabel = await late.locator('button.day:has(.e-overdue)').first().getAttribute("aria-label");
  check("calendar: the overdue state is also in the accessible label", /overdue/.test(overdueLabel), overdueLabel);
  await late.close();

  // ---- intake: form validation, example, and the screenshot flow (mock: sample values)
  await go("#/new", ".modetabs");
  check("intake opens on the Upload tab with the form hidden until a file is read", (await p.locator("#tab-upload").getAttribute("aria-selected")) === "true" && !(await p.locator("form.intake").isVisible()));
  await p.click("#tab-manual");
  check("Manual entry shows the form with an Issue type dropdown", (await p.locator("form.intake").isVisible()) && (await p.locator("form.intake select").filter({ hasText: "Auto-detect" }).count()) === 1);
  await p.click('button:has-text("Score gap")');
  await p.fill("#f-message-text", "Please email me at jane.smith@example.edu");
  await p.check("#f-ack");
  await p.click('button:has-text("Create case")');
  await p.waitForSelector("#intake-summary .notice.error");
  check("validation error is shown per field and inputs are kept", /email address/.test(await p.locator("#intake-summary").innerText()) && (await p.inputValue("#f-message-text")).includes("jane.smith"));
  await p.screenshot({ path: `${OUT}/desktop-intake-error.png`, fullPage: true });
  await p.fill("#f-message-text", "My HW7 rubric shows full marks but the score is 6.");
  await p.click('button:has-text("Create case")');
  await p.waitForSelector(".timeline");
  check("valid example creates a case and opens its evidence", /CASE-10\d/.test(p.url()) && /Score does not match rubric/.test(await p.locator("h1").innerText()));

  await go("#/new", "#read-shot");
  check("Read screenshot is disabled until a file AND the acknowledgement are given", await p.locator("#read-shot").isDisabled());
  await p.setInputFiles("#f-shot", { name: "email.png", mimeType: "image/png", buffer: PNG });
  check("still disabled without the acknowledgement", await p.locator("#read-shot").isDisabled());
  await p.check("#f-vision-ack");
  check("enabled with both", await p.locator("#read-shot").isEnabled());
  await p.click("#read-shot");
  await p.waitForSelector("#vision-result .notice");
  check("the extract button is honest about mock mode", /mock mode/i.test(await p.locator("#read-shot").innerText()));
  check("mock banner says these are sample values", /Sample values, not analysed from your file/.test(await p.locator("#vision-result").innerText()));
  check("form is pre-filled and editable", (await p.inputValue("#f-student")) === "S-4B21" && (await p.inputValue("#f-assignment")) === "HW6" && /submitted on time/.test(await p.inputValue("#f-message-text")));
  await p.screenshot({ path: `${OUT}/desktop-intake-vision.png`, fullPage: true });
  await p.fill("#f-student", "S-5E0A");
  await p.check("#f-ack");
  await p.click('button:has-text("Create case")');
  await p.waitForSelector(".timeline");
  const audit = await p.evaluate(async () => (await (await fetch("/api/cases/" + location.hash.split("/")[2])).json()).evidence.find((e) => e.source_type === "message").payload.source);
  check("the confirmed case is marked as read from a screenshot", audit === "screenshot");

  // the 409 (stale reply) and 422 (intake validation) are deliberate error-path checks above
  check("no unexpected console errors in flows", errs.filter((e) => !/status of (409|422)/.test(e)).length === 0, errs.join(" | "));
  await browser.close();
  await fetch(`${BASE}/api/demo/reset?confirm=true`, { method: "POST" });
  console.log(failed ? `\n${failed} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
  process.exit(failed ? 1 : 0);
})();
