"use strict";
// GradeCase UI: Case Queue, Evidence, Decision. Plain JS, no build step.
// Every piece of data is inserted as a text node, so source text cannot inject markup.

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
};
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ state

const S = {
  role: "ta",
  cfg: null,
  detail: null,
  notice: null, // {kind: success|error|info, title, text}
  filters: { q: "", status: "", owner: "", channel: "", quick: "all" },
  ui: { caseId: null, note: "", counted: "", body: null },
  lastCase: null,
  ai: null,
  busy: false,
  hash: "#/queue",
  ignoreHash: false,
};
try { S.role = localStorage.getItem("gc_role") === "professor" ? "professor" : "ta"; } catch (e) { /* storage blocked */ }

// ------------------------------------------------------------------ helpers

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `Request failed (HTTP ${resp.status})`);
  }
  return data;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmt(ts, tz = false) {
  if (!ts) return "-";
  let out = `${MONTHS[+ts.slice(5, 7) - 1]} ${+ts.slice(8, 10)}, ${ts.slice(11, 16)}`;
  if (tz) {
    const off = ts.slice(19);
    out += off === "+00:00" || off === "Z" ? " UTC" : ` UTC${off.replace(":00", "").replace("-", "−")}`;
  }
  return out;
}
const num = (n) => (n == null ? "-" : Number.isInteger(n) ? String(n) : n.toFixed(2));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const slug = (s) => s.toLowerCase().replace(/[^a-z]+/g, "-");
const CHANNEL = { canvas_inbox: "Canvas inbox", email: "Email", submission_comment: "Submission comment" };
const channelName = (c) => CHANNEL[c] || c;
const TITLE = {
  late_flag: "On-time submission flagged late",
  score_gap: "Score does not match rubric",
  missing_submission: "Emailed file not found in Canvas",
  other: "Grading question",
};
const caseTitle = (c) => TITLE[c.issue] || TITLE.other;
const mins = (t) => {
  const m = t.minutes_vs_deadline;
  return m == null ? "" : m <= 0 ? `${plural(-m, "minute")} before the deadline` : `${plural(m, "minute")} after the deadline`;
};

function say(text) { $("live").textContent = text; }

function nextStep(c) {
  if (c.merged_into) return "Merged";
  if (c.status === "Closed") return "Closed";
  if (c.status === "Awaiting professor") return "Professor decision";
  if (c.status === "Awaiting student info") return "Waiting for student";
  return ({ escalate: "Request professor review", request_info: "Request student information",
    hold: "Place on hold", approve: "Review and close" })[c.suggested_action] || "Review";
}

// ------------------------------------------------------------------ shared components

const pill = (status) => h("span", { class: `pill s-${slug(status)}` }, status);

function idChip(ref, d) {
  const known = d && d.evidence.some((e) => e.ref_id === ref);
  if (!known) return h("span", { class: "idchip missing", title: "No record with this id exists" }, ref);
  return h("a", { href: "#", class: "idchip", title: "Show this record in the audit timeline",
    onclick: (e) => { e.preventDefault(); openRecord(ref); } }, ref);
}
const chips = (refs, d) => h("span", { class: "chips" }, (refs || []).filter(Boolean).map((r) => [idChip(r, d), " "]));

function openRecord(ref) {
  const audit = document.getElementById("audit");
  if (audit) audit.open = true;
  const el = document.getElementById(`ev-${ref}`);
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 2200);
}

function noticeEl() {
  const n = S.notice;
  if (!n) return null;
  return h("div", { class: `notice ${n.kind}`, role: n.kind === "error" ? "alert" : "status" },
    n.title && h("strong", {}, n.title + " "), n.text,
    h("button", { type: "button", class: "linkbtn dismiss", onclick: () => { S.notice = null; render(); } }, "Dismiss"));
}

function actionLabel(action, role) {
  return ({ approve: role === "professor" ? "Approve decision" : "Approve and close", hold: "Place on hold",
    reject: "Reject request", escalate: "Request professor review", request_info: "Request student information" })[action];
}

function routeLabel(d) {
  const a = d.analysis;
  if (d.case.status === "Closed") return "Closed";
  if (a.professor_approved) return "Professor decision recorded";
  return ({ escalate: "Professor decision required", request_info: "Student information needed",
    hold: "Hold: records need confirmation", approve: "TA can review and close" })[a.suggested_action];
}

function storedBody(dr) { return dr ? (dr.body_edited ?? dr.body_ai) : ""; }
function isDirty() {
  const dr = S.detail && S.detail.draft;
  return !!(S.ui.caseId && dr && S.ui.body != null && S.ui.body !== storedBody(dr));
}
function confirmDiscard(what) {
  if (!isDirty()) return true;
  const ok = confirm(`You have unsaved edits to the reply draft. Discard them and ${what}?`);
  if (ok) S.ui.body = null;
  return ok;
}

// ------------------------------------------------------------------ shell (rail, crumbs)

// ------------------------------------------------------------------ icons (built with createElementNS, never markup strings)

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  dashboard: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  queue: "M4 6h16M4 12h16M4 18h10",
  board: "M4 4h5v16H4zM10 4h5v10h-5zM16 4h4v13h-4z",
  calendar: "M5 5h14a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM4 10h16M9 3v4M15 3v4",
  plus: "M12 5v14M5 12h14",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6",
  check: "M5 13l4 4L19 7",
  x: "M6 6l12 12M18 6L6 18",
  arrow: "M5 12h14M13 6l6 6-6 6",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
};
function icon(name, cls = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
    "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  if (cls) svg.setAttribute("class", cls);
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", ICONS[name]);
  svg.append(p);
  return svg;
}

// who did the work. Rules compute, AI explains, humans decide: shown wherever it matters.
const who = (kind, text) => h("span", { class: `who ${kind}` }, text);

// ------------------------------------------------------------------ sidebar AI status card

function aiIndicator() {
  const a = S.ai, b = a && a.budget;
  if (!a) return [h("div", { class: "ai-head" }, h("span", { class: "ai-dot" }), "AI status unknown")];
  let dot = "", title, sub;
  if (a.mode === "mock") { title = "Mock mode"; sub = "Live AI not connected"; }
  else if (a.mode === "misconfigured") { dot = "warn"; title = "Not usable"; sub = "A model id is not set on the server"; }
  else if (a.last_success_at) { dot = "live"; title = "Connected"; sub = `Last call succeeded ${fmt(a.last_success_at, true)}`; }
  else { dot = "warn"; title = "Configured"; sub = "No successful call yet"; }
  const out = [h("div", { class: "ai-head" }, h("span", { class: `ai-dot ${dot}` }), title)];
  if (a.mode !== "mock" && a.model) out.push(h("div", { class: "ai-model" }, a.model));
  out.push(h("div", { class: "ai-sub" }, sub));
  if (a.mode === "configured" && a.last_failure && (!a.last_success_at || a.last_failure.at > a.last_success_at)) {
    out.push(h("div", { class: "ai-sub warn" }, `Last call failed: ${a.last_failure.kind}`));
  }
  if (a.mode !== "mock" && b) {
    const pct = b.calls_limit ? Math.min(100, Math.round((b.calls_used / b.calls_limit) * 100)) : 0;
    out.push(h("div", { class: "ai-sub" }, `${b.calls_used}/${b.calls_limit} lifetime calls (${pct}%)`),
      h("div", { class: "progress", role: "img", "aria-label": `${pct}% of the lifetime AI calls used` }, h("span", { style: `width:${pct}%` })));
  }
  return out;
}

async function refreshAi() {
  try { S.ai = await api("/api/ai/status"); } catch (e) { /* keep the previous value */ }
  $("ai").replaceChildren(...aiIndicator());
}

// ------------------------------------------------------------------ shell and routing

function renderShell(route) {
  const link = (label, href, ic, current) =>
    h("a", { href, class: "navlink", "aria-label": label, title: label, "aria-current": current ? "page" : null },
      icon(ic, "navicon"), h("span", { class: "navlabel" }, label));
  const nav = [link("Dashboard", "#/dashboard", "dashboard", route.screen === "dashboard"),
    link("Case Queue", "#/queue", "queue", route.screen === "queue"),
    link("Board", "#/board", "board", route.screen === "board"),
    link("Calendar", "#/calendar", "calendar", route.screen === "calendar"),
    h("div", { class: "navdivider", role: "separator" }),
    link("New case", "#/new", "plus", route.screen === "intake")];
  if (route.caseId) {
    nav.push(h("div", { class: "navgroup" }, h("div", { class: "label" }, "Selected case"),
      h("div", { class: "mono navcase" }, route.caseId),
      link("Evidence", `#/case/${route.caseId}/evidence`, "file", route.screen === "evidence"),
      link("Decision", `#/case/${route.caseId}/decision`, "check", route.screen === "decision")));
  }
  $("nav").replaceChildren(...nav);

  const SIMPLE = { dashboard: "Dashboard", queue: "Case Queue", intake: "New case", board: "Board", calendar: "Calendar" };
  const crumbs = [h("a", { href: "#/dashboard" }, "GradeCase")];
  if (SIMPLE[route.screen]) {
    crumbs.push(h("span", { class: "sep" }, "/"), h("span", { "aria-current": "page" }, SIMPLE[route.screen]));
  } else if (route.caseId) {
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: "#/queue" }, "Cases"));
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: `#/case/${route.caseId}/evidence` }, route.caseId));
    crumbs.push(h("span", { class: "sep" }, "/"), h("span", { "aria-current": "page" }, route.screen === "decision" ? "Decision" : "Evidence"));
  }
  $("crumbs").replaceChildren(...crumbs);

  for (const r of ["ta", "professor"]) $(`role-${r}`).setAttribute("aria-pressed", String(S.role === r));
  $("ai").replaceChildren(...aiIndicator());
  document.title = `${SIMPLE[route.screen] || route.caseId} - GradeCase`;
}

function setMenu(open) {
  document.body.classList.toggle("menu-open", open);
  $("menu-btn").setAttribute("aria-expanded", String(open));
  $("menu-btn").setAttribute("aria-label", open ? "Close menu" : "Open menu");
  $("scrim").hidden = !open;
}

function parseRoute() {
  const p = location.hash.replace(/^#\/?/, "").split("/");
  if (p[0] === "case" && p[1]) return { screen: p[2] === "decision" ? "decision" : "evidence", caseId: p[1] };
  const screens = { queue: "queue", new: "intake", board: "board", calendar: "calendar" };
  return { screen: screens[p[0]] || "dashboard", caseId: null }; // the dashboard is the landing page
}

let renderToken = 0;
async function render() {
  const route = parseRoute();
  const token = ++renderToken;
  const view = $("view");
  setMenu(false);
  renderShell(route);
  try {
    const LIST_VIEWS = { dashboard: dashboardView, queue: queueView, intake: intakeView, board: boardView, calendar: calendarView };
    if (LIST_VIEWS[route.screen]) {
      S.detail = null;
      S.ui = { caseId: null, note: "", counted: "", body: null };
      const node = await LIST_VIEWS[route.screen]();
      if (token === renderToken) view.replaceChildren(node);
      return;
    }
    if (S.ui.caseId !== route.caseId) S.ui = { caseId: route.caseId, note: "", counted: "", body: null };
    S.decisionSteps = null;
    S.lastCase = route.caseId;
    if (!S.detail || S.detail.case.id !== route.caseId || S.refetch) {
      view.replaceChildren(h("p", { class: "muted pad" }, "Loading case..."));
      S.detail = await api(`/api/cases/${route.caseId}`);
      S.refetch = false;
    }
    // Loading a page never starts an analysis: that is an explicit button, because it can cost money.
    if (token !== renderToken) return;
    view.replaceChildren(route.screen === "decision" ? decisionView() : evidenceView());
    if (S.decisionSteps) S.decisionSteps();
  } catch (e) {
    if (token !== renderToken) return;
    view.replaceChildren(h("div", { class: "pad" }, h("div", { class: "notice error", role: "alert" }, `Could not load this screen: ${e.message}`),
      h("button", { type: "button", class: "btn", onclick: () => { S.refetch = true; render(); } }, "Try again"),
      " ", h("a", { class: "btn", href: "#/queue" }, "Back to cases")));
  }
}

// ------------------------------------------------------------------ dashboard (all numbers are real)

const ago = (ts) => {
  const t = Date.parse(ts);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
const sameDay = (ts) => { const a = new Date(ts), b = new Date(); return a.toDateString() === b.toDateString(); };
const caseLink = (id) => h("a", { href: `#/case/${id}/evidence` }, id);
const ACTION_PHRASE = {
  escalate: "escalated to the professor", request_info: "student information requested", hold: "placed on hold",
  approve: "approved", reject: "rejected", merge: "merged with a duplicate", record_score_recommendation: "score recommendation recorded",
};
const SOURCE_PHRASE = { screenshot: " from a screenshot", document: " from an uploaded document", form: "" };

function describeEvent(e) {
  if (e.kind === "analysis") {
    const sec = e.latency_ms ? ` (${(e.latency_ms / 1000).toFixed(1)}s)` : "";
    if (e.outcome === "accepted") return { dot: "good", text: [caseLink(e.case_id), ` analysis completed: AI draft accepted${sec}`] };
    if (e.outcome === "rejected") return { dot: "bad", text: [caseLink(e.case_id), ` analysis rejected: guardrails caught a problem. ${e.detail || ""}`.trim()] };
    if (e.outcome === "error") return { dot: "warn", text: [caseLink(e.case_id), ` AI call failed (${e.error_kind || "error"}); rules-only draft used`] };
    if (e.outcome === "mock") return { dot: "info", text: [caseLink(e.case_id), " analysis ran in mock mode (no model called)"] };
    return { dot: "info", text: [caseLink(e.case_id), " rules-only draft prepared (no AI)"] };
  }
  if (e.kind === "decision") {
    const by = `${e.actor} (${e.role === "ta" ? "TA" : "professor"})`;
    return { dot: e.action === "approve" ? "good" : e.action === "reject" ? "bad" : "info",
      text: [caseLink(e.case_id), ` ${ACTION_PHRASE[e.action] || e.action.replace(/_/g, " ")} by ${by}`] };
  }
  return { dot: "info", text: [`New case `, caseLink(e.case_id), ` created${SOURCE_PHRASE[e.source] || ""}`] };
}

async function dashboardView() {
  const [cases, ai, feed] = await Promise.all([api("/api/cases"), api("/api/ai/status"), api("/api/activity?limit=8")]);
  S.ai = ai; $("ai").replaceChildren(...aiIndicator());
  const open = cases.filter((c) => c.status !== "Closed");
  const needAction = open.filter((c) => c.status !== "Awaiting student info");
  const closedToday = cases.filter((c) => c.status === "Closed" && c.decisions.some((d) => ["approve", "reject"].includes(d.action) && sameDay(d.ts)));
  const week = cases.filter((c) => c.opened_at && Date.now() - Date.parse(c.opened_at) < 7 * 86400000);
  const r = ai.runs, live = ai.mode !== "mock";
  const lat = r.avg_live_latency_ms;
  const demo = cases.find((c) => c.id === "CASE-A");
  const STATUSES = ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"];
  const maxN = Math.max(1, cases.length);

  const stat = (big, label, trend, flat) => h("div", { class: "scard" }, h("div", { class: "big" }, big), h("div", { class: "lab" }, label),
    h("div", { class: `trend${flat ? " flat" : ""}` }, trend));
  const bar = (label, n) => h("div", { class: "hbar" }, h("span", {}, label),
    h("span", { class: "track" }, h("span", { class: `fill${n ? "" : " zero"}`, style: `width:${(n / maxN) * 100}%` })), h("span", { class: "n" }, n));
  const answered = r.live_accepted + r.live_rejected;
  const pct = answered ? Math.round((r.live_accepted / answered) * 100) : null;
  const calls = ai.budget;
  const callPct = calls.calls_limit ? Math.min(100, Math.round((calls.calls_used / calls.calls_limit) * 100)) : 0;

  return h("div", { class: "page" }, noticeEl(),
    h("div", { class: "pagehead", style: "margin-bottom:16px" }, h("h1", { class: "page-title" }, "Dashboard")),
    h("section", { class: "hero" },
      h("p", { class: "tagline", lang: "ko" }, "정보는 있는데, 사건은 없다"),
      h("p", { class: "tagline-en" }, "The data exists, but the case doesn't."),
      h("div", { class: "principle", "aria-label": "How GradeCase divides the work" },
        who("rules", "Rules compute times and scores"), who("ai", "AI explains and drafts"), who("human", "Humans decide")),
      h("div", { class: "demo" },
        h("p", {}, h("strong", {}, "The demo case. "), "A student says “I submitted on time but it’s marked late.” GradeCase lines up both attempts against the policy, raises a review item, and the TA escalates it to the professor or closes it with an evidence-backed reply. Nothing is graded or sent for you."),
        h("a", { class: "btn primary big", href: demo ? "#/case/CASE-A/evidence" : "#/queue" }, demo ? "Open the demo case" : "Open the case queue", icon("arrow")))),
    h("div", { class: "statcards" },
      stat(cases.length, "Total cases", week.length ? `↑ ${week.length} opened in the last 7 days` : "None opened in the last 7 days", !week.length),
      stat(needAction.length, "Need action", `${open.length - needAction.length} waiting on a student`, true),
      stat(closedToday.length, "Closed today", closedToday.length ? "Decided by a person" : "No case closed today", !closedToday.length),
      stat(lat ? `${(lat / 1000).toFixed(1)}s` : "–", "Avg model latency", live ? (lat ? "Live runs since last reset" : "No live AI run yet") : "Mock mode: no model is called", true)),
    h("div", { class: "dashgrid" },
      h("section", { class: "dashcard" }, h("h2", {}, "Cases by status"), STATUSES.map((s) => bar(s, cases.filter((c) => c.status === s).length))),
      h("section", { class: "dashcard" },
        h("h2", {}, "AI performance", who(live ? "ai" : "template", live ? "Live AI" : "Mock mode")),
        h("dl", { class: "kv" },
          live && [h("dt", {}, "Lifetime calls"), h("dd", {}, `${calls.calls_used} / ${calls.calls_limit} (${callPct}%)`)],
          live && [h("dt", {}, "Accepted by the guardrails"), h("dd", {}, r.live_accepted)],
          live && [h("dt", {}, "Rejected by the guardrails"), h("dd", {}, r.live_rejected)],
          live && [h("dt", {}, "Provider errors"), h("dd", {}, r.live_errors)],
          !live && [h("dt", {}, "Mock template runs"), h("dd", {}, r.mock)],
          [h("dt", {}, "Rules-only drafts"), h("dd", {}, r.rules_only)],
          [h("dt", {}, "Avg model latency"), h("dd", {}, lat ? `${(lat / 1000).toFixed(1)}s` : "–")],
          [h("dt", {}, "AI replies caught by guardrails"), h("dd", {}, r.guardrail_rejections)]),
        live && h("div", {}, h("div", { class: "meta" }, answered ? `${pct}% of AI replies accepted` : "No live AI replies yet"),
          h("div", { class: "progress light", role: "img", "aria-label": `${pct || 0}% of AI replies accepted` }, h("span", { style: `width:${pct || 0}%` }))),
        !live && h("p", { class: "meta" }, "No model is called in mock mode, so there is no acceptance rate to show."),
        h("p", { class: "meta" }, "Counts cover runs since the last demo reset. The lifetime call count is never reset."))),
    h("section", { class: "dashcard" }, h("h2", {}, "Recent activity"),
      feed.length ? h("ul", { class: "feed" }, feed.map((e) => {
        const d = describeEvent(e);
        return h("li", {}, h("span", { class: `fdot ${d.dot}` }), h("span", {}, d.text), h("time", { datetime: e.ts }, ago(e.ts)));
      })) : h("p", { class: "muted" }, "Nothing has happened yet.")));
}

// ------------------------------------------------------------------ queue

async function queueView() {
  const cases = await api("/api/cases");
  const F = S.filters;
  const open = (c) => c.status !== "Closed";
  const quick = {
    all: () => true,
    open,
    professor: (c) => open(c) && (c.requires_professor || c.status === "Awaiting professor"),
    evidence: (c) => open(c) && c.suggested_action === "request_info",
    closed: (c) => !open(c),
  };
  const QUICK = [["all", "All"], ["open", "Open"], ["professor", "Needs professor"], ["evidence", "Needs evidence"], ["closed", "Closed"]];
  const uniq = (xs) => [...new Set(xs)].sort();
  const owners = uniq(cases.map((c) => c.owner || "Unassigned"));
  const channels = uniq(cases.flatMap((c) => c.channels));

  const tabs = h("div", { class: "tabs", role: "group", "aria-label": "Quick filter" });
  const rows = h("tbody");
  const count = h("p", { class: "muted small", "aria-live": "polite" });
  const empty = h("div", { class: "empty", hidden: true });

  const match = (c) => {
    const q = F.q.trim().toLowerCase();
    const hay = [c.id, c.student_id, c.assignment, c.assignment_name, c.issue, caseTitle(c), c.owner || "unassigned",
      c.course, c.channels.map(channelName).join(" ")].join(" ").toLowerCase();
    return quick[F.quick](c) && (!q || q.split(/\s+/).every((w) => hay.includes(w))) &&
      (!F.status || c.status === F.status) && (!F.owner || (c.owner || "Unassigned") === F.owner) &&
      (!F.channel || c.channels.includes(F.channel));
  };

  function update() {
    tabs.replaceChildren(...QUICK.map(([k, label]) =>
      h("button", { type: "button", class: "tab", "aria-pressed": String(F.quick === k),
        onclick: () => { F.quick = k; update(); } },
      label, " ", h("span", { class: "tabcount" }, cases.filter(quick[k]).length))));
    const shown = cases.filter(match);
    rows.replaceChildren(...shown.map(queueRow));
    count.textContent = `Showing ${shown.length} of ${cases.length} cases`;
    const filtered = F.q || F.status || F.owner || F.channel || F.quick !== "all";
    empty.hidden = shown.length > 0;
    table.hidden = shown.length === 0;
    empty.replaceChildren(h("strong", {}, "No cases match these filters."), h("p", { class: "muted" }, "Try a different search, or clear the filters to see every case."),
      filtered && h("button", { type: "button", class: "btn", onclick: clear }, "Clear filters"));
    clearBtn.hidden = !filtered;
  }
  function clear() {
    Object.assign(F, { q: "", status: "", owner: "", channel: "", quick: "all" });
    search.value = ""; selStatus.value = ""; selOwner.value = ""; selChannel.value = "";
    update();
  }

  const field = (label, control) => h("label", { class: "field" }, h("span", { class: "label" }, label), control);
  const search = h("input", { type: "search", class: "input", placeholder: "Case, student, assignment or issue", value: F.q,
    oninput: (e) => { F.q = e.target.value; update(); } });
  const sel = (key, options, label) => {
    const el = h("select", { class: "input", onchange: (e) => { F[key] = e.target.value; update(); } },
      h("option", { value: "" }, "All"), options.map(([v, t]) => h("option", { value: v, selected: F[key] === v }, t)));
    return el;
  };
  const selStatus = sel("status", ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"].map((s) => [s, s]));
  const selOwner = sel("owner", owners.map((o) => [o, o]));
  const selChannel = sel("channel", channels.map((c) => [c, channelName(c)]));
  const clearBtn = h("button", { type: "button", class: "btn quiet", onclick: clear }, "Clear filters");

  const table = h("table", { class: "qtable" },
    h("thead", {}, h("tr", {}, ["Case", "Assignment", "Status", "Owner", "Next step"].map((t) => h("th", { scope: "col" }, t)))), rows);

  const view = h("div", { class: "page" },
    noticeEl(),
    h("div", { class: "pagehead" }, h("h1", { class: "page-title" }, "Cases"),
      h("a", { class: "btn primary", href: "#/new" }, "New synthetic case")),
    h("p", { class: "lede" }, "Open a case to see the evidence, then record a decision. Nothing here changes a grade or sends a message."),
    duplicatePanel(cases),
    h("div", { class: "toolbar" }, tabs),
    h("div", { class: "filters" }, field("Search", search), field("Status", selStatus), field("Owner", selOwner), field("Channel", selChannel), clearBtn),
    count, table, empty);
  update();
  return view;
}

function queueRow(c) {
  const go = () => { location.hash = `#/case/${c.id}/evidence`; };
  const reply = c.last_reply ? `Last reply: ${channelName(c.last_reply.channel)}, ${c.last_reply.by}, ${fmt(c.last_reply.ts)}` : "No reply yet";
  return h("tr", { class: "qrow", "aria-current": S.lastCase === c.id ? "true" : null,
    onclick: (e) => { if (!e.target.closest("a,button")) go(); } },
    h("td", { "data-label": "Case" },
      h("a", { class: "caselink", href: `#/case/${c.id}/evidence` }, caseTitle(c)),
      h("div", { class: "meta" }, h("span", { class: "mono" }, c.id), " · student ", h("span", { class: "mono" }, c.student_id)),
      h("div", { class: "meta" }, reply),
      (c.duplicates.length > 0 || c.on_hold) && h("div", { class: "tags" },
        c.duplicates.length > 0 && h("span", { class: "tag" }, "Possible duplicate"),
        c.on_hold && h("span", { class: "tag" }, "On hold"))),
    h("td", { "data-label": "Assignment" }, h("div", {}, c.assignment_name), h("div", { class: "meta" }, `${c.assignment} · ${c.course}`)),
    h("td", { "data-label": "Status" }, pill(c.status)),
    h("td", { "data-label": "Owner" }, c.owner || h("span", { class: "muted" }, "Unassigned")),
    h("td", { "data-label": "Next step" }, h("div", { class: "next" }, nextStep(c)), h("div", { class: "meta clamp" }, c.waiting_reason)));
}

function duplicatePanel(cases) {
  const byId = new Map(cases.map((c) => [c.id, c]));
  const pairs = new Map();
  cases.forEach((c) => c.duplicates.forEach((x) => { if (!pairs.has(x.id)) pairs.set(x.id, { id: x.id, reason: x.reason, a: c.id, b: x.other }); }));
  if (!pairs.size) return null;
  const side = (id) => {
    const c = byId.get(id);
    return h("div", { class: "dupside" },
      h("div", {}, h("a", { href: `#/case/${id}/evidence`, class: "caselink" }, id), " ", pill(c.status)),
      h("div", { class: "meta" }, c.channels.map(channelName).join(", ") || "No channel", " · ", c.owner || "Unassigned"),
      h("div", { class: "meta" }, `${c.assignment_name} · student ${c.student_id}`));
  };
  return h("details", { class: "dup" },
    h("summary", {}, plural(pairs.size, "duplicate pair"), " to review", h("span", { class: "muted" }, " (nothing is merged until you confirm)")),
    [...pairs.values()].map((p) => h("div", { class: "duppair" },
      h("div", { class: "dupgrid" }, side(p.a), side(p.b)),
      h("p", { class: "meta" }, p.reason + "."),
      h("div", { class: "btnrow" },
        h("button", { type: "button", class: "btn primary", onclick: (e) => resolveDup(p, true, e.currentTarget) }, `Merge ${p.b} into ${p.a}`),
        h("button", { type: "button", class: "btn", onclick: (e) => resolveDup(p, false, e.currentTarget) }, "Not a duplicate")))));
}

async function resolveDup(p, confirmMerge, btn) {
  btn.disabled = true;
  try {
    await api(`/api/duplicates/${p.id}/${confirmMerge ? "confirm" : "dismiss"}`, { method: "POST", body: { role: S.role } });
    S.notice = { kind: "success", title: confirmMerge ? "Merged." : "Kept separate.",
      text: confirmMerge ? `${p.b} was merged into ${p.a} and the merge was logged.` : `${p.a} and ${p.b} will not be proposed again.` };
  } catch (e) { S.notice = { kind: "error", title: "Could not update the duplicate.", text: e.message }; }
  render();
}

// ------------------------------------------------------------------ case header

function caseHeader(d, screen) {
  const c = d.case;
  return h("header", { class: "casehead" },
    h("a", { class: "back", href: "#/queue" }, "← Back to cases"),
    h("div", { class: "headrow" },
      h("div", {},
        h("h1", {}, caseTitle(c)),
        h("div", { class: "metarow" }, pill(c.status),
          h("span", {}, c.assignment_name, " (", c.assignment, ", ", c.course, ")"),
          h("span", {}, "Owner: ", c.owner || "Unassigned"),
          h("span", {}, "Student ", h("span", { class: "mono" }, c.student_id)),
          h("span", { class: "mono" }, c.id))),
      h("nav", { class: "steps2", "aria-label": "Case steps" },
        h("a", { href: `#/case/${c.id}/evidence`, "aria-current": screen === "evidence" ? "step" : null }, h("span", { class: "stepno" }, "1"), "Evidence"),
        h("a", { href: `#/case/${c.id}/decision`, "aria-current": screen === "decision" ? "step" : null }, h("span", { class: "stepno" }, "2"), "Decision"))),
    c.merged_into && h("div", { class: "notice info" }, `This case was merged into ${c.merged_into}.`));
}

// ------------------------------------------------------------------ evidence screen

function factSummary(d) {
  const a = d.analysis, s = a.score_state;
  const sub = a.attempts.filter((t) => t.state === "submitted");
  const basis = a.gates.find((g) => g.code === "attempt_basis");
  const counted = a.attempts.find((t) => t.counted);
  const first = sub.find((t) => t.minutes_vs_deadline != null && t.minutes_vs_deadline <= 0);
  const rec = a.reconciliation;
  // After a professor decision the derived facts are re-reconciled: never claim "consistent" while
  // the gradebook still differs from the approved basis.
  if (a.professor_approved && rec.state !== "consistent") return [rec.text, " ", chips(a.approval_ids, d)];
  if (basis && first && counted) {
    return [idChip(first.ref_id, d), ` was submitted ${mins(first)}, but the newest attempt, `, idChip(counted.ref_id, d),
      `, was ${plural(counted.minutes_vs_deadline, "minute")} late and is the one graded, with a ${num(s.late_deduction_applied)}-point late deduction.`];
  }
  const gap = s.differences.find((x) => x.code === "entered_vs_expected");
  if (gap) {
    const dir = gap.amount < 0 ? "below" : "above";
    return [`The entered score (${num(s.entered)}) is ${num(Math.abs(gap.amount))} points ${dir} the rubric total (${num(s.rubric_total)}) and no late deduction is recorded to explain it. `, chips(gap.evidence_ids.slice(-1), d)];
  }
  const blk = a.blockers.find((b) => b.code === "insufficient_evidence") || a.blockers[0];
  if (blk) return [blk.text, " ", chips(blk.evidence_ids, d)];
  const att = sub[0];
  return [att ? [idChip(att.ref_id, d), ` was submitted ${mins(att)}. `] : "", rec.text];
}

// ------------------------------------------------------------------ AI transparency: pipeline, statements, guardrails

const PIPE_LABELS = ["Load evidence", "Compute rules", "Call AI model", "Validate claims", "Prepare draft", "Await human"];
const STEP_STATE = { done: "done", failed: "failed", skipped: "skipped", pending: "waiting for you", running: "running", waiting: "waiting" };

function stepMark(status) {
  if (status === "done") return icon("check");
  if (status === "failed") return icon("x");
  if (status === "skipped") return "–";
  return "";
}

// The stages come straight from the stored run: real operations with real durations.
function pipelineView(run, d, animate) {
  const draft = d && d.draft && d.draft.run_id === run.id ? d.draft : null;
  const blocking = ((run.validation && run.validation.flags) || []).filter((f) => ["invalid_citation", "no_citation", "needs_verification", "commitment"].includes(f.kind)).length;
  return h("ol", { class: `pipeline${animate ? " animate" : ""}`, "aria-label": "Analysis pipeline" }, run.stages.map((s, i) => {
    let state = STEP_STATE[s.status] || s.status;
    if (s.key === "call_model" && s.status === "done" && run.mode === "live" && run.latency_ms != null) state = `${(run.latency_ms / 1000).toFixed(1)}s`;
    const subs = [];
    if (s.key === "call_model" && run.mode === "live") {
      subs.push(run.provider === "vultr-serverless-inference" ? "Vultr Serverless Inference" : run.provider);
      if (run.prompt_tokens != null && run.completion_tokens != null)
        subs.push(`Prompt: ${run.prompt_tokens.toLocaleString()} tokens → Completion: ${run.completion_tokens.toLocaleString()} tokens`);
      if (run.attempts > 1) subs.push(`${run.attempts} provider attempts`);
    }
    if (s.key === "validate_evidence" && draft && run.validation && run.validation.passed !== null && s.status !== "skipped") {
      subs.push(`${draft.verified.length} verified, ${draft.unverified.length} unverified, ${blocking} blocking problem${blocking === 1 ? "" : "s"}`);
    }
    return h("li", { class: `pstep ${s.status}`, style: `--i:${i}` },
      h("span", { class: "pmark" }, stepMark(s.status)),
      h("div", { class: "pbody" },
        h("div", { class: "phead" }, h("span", { class: "plabel" }, s.label), h("span", { class: "pstate" }, state)),
        s.detail && h("div", { class: "pmeta" }, s.detail),
        subs.map((t) => h("div", { class: "psub" }, t))));
  }));
}

// Shown only while the request is in flight. It claims nothing is done: only that the call is running.
function pipelineRunning(live) {
  return h("ol", { class: "pipeline", "aria-label": "Analysis running", "aria-busy": "true" }, PIPE_LABELS.map((label, i) => {
    const running = i === 2;
    return h("li", { class: `pstep ${running ? "running" : "waiting"}` }, h("span", { class: "pmark" }, running ? "•" : ""),
      h("div", { class: "pbody" }, h("div", { class: "phead" }, h("span", { class: "plabel" }, label),
        h("span", { class: "pstate" }, running ? (live ? "calling the model..." : "running locally...") : "waiting"))));
  }));
}

const BLOCKING = ["invalid_citation", "no_citation", "needs_verification", "commitment"];
function guardChecks(val, flagsOverride) {
  const flags = flagsOverride || (val && val.flags) || [];
  const timeLabels = ["recorded times", "minutes vs deadline"];
  const rows = [
    { q: "Citation check: do all cited IDs exist?", bad: flags.filter((f) => f.kind === "invalid_citation" || f.kind === "no_citation") },
    { q: "Time check: do the AI's times match the records?", bad: flags.filter((f) => f.kind === "needs_verification" && timeLabels.includes(f.label)) },
    { q: "Number check: do scores match the computed values?", bad: flags.filter((f) => f.kind === "needs_verification" && !timeLabels.includes(f.label)) },
    { q: "Commitment check: no promised outcomes?", bad: flags.filter((f) => f.kind === "commitment") },
  ];
  if (val && val.schema_ok === false) {
    rows.unshift({ q: "Structure check: is the reply well formed?", bad: [{ message: (flags.find((f) => f.kind === "schema") || {}).message || "The reply did not match the required structure." }] });
  }
  return rows;
}

function guardrailTable(rows, verdict) {
  const passed = rows.filter((r) => !r.bad.length).length;
  return h("div", {},
    h("table", { class: "gtable" },
      h("thead", {}, h("tr", {}, h("th", { scope: "col" }, "Guardrail check"), h("th", { scope: "col" }, "Result"))),
      h("tbody", {}, rows.map((r) => h("tr", {},
        h("td", {}, r.q, r.bad.map((f) => h("div", { class: "gwhy" }, f.message))),
        h("td", {}, h("span", { class: `gres ${r.bad.length ? "bad" : "ok"}` }, r.bad.length ? "✗ FAILED" : "✓ Pass")))))),
    h("div", { class: `gtotal ${passed === rows.length ? "ok" : "bad"}` }, `${passed}/${rows.length} passed`),
    verdict && h("div", { class: `gverdict ${verdict.kind}` }, verdict.text));
}

function stmtList(title, kind, claims, d) {
  if (!claims.length) return null;
  return h("div", {}, h("div", { class: `sect-title ${kind === "verified" ? "ok" : "warn"}` },
    kind === "verified" ? "✓ Verified" : "⚠ Unverified", ` (${plural(claims.length, "statement")})`),
    h("ul", { class: "stmts" }, claims.map((c) => h("li", { class: `stmt${kind === "verified" ? "" : " unverified"}` },
      h("span", {}, c.text, (c.flags || []).filter((f) => f.kind === "needs_verification").map((f) => h("span", { class: "badge bad" }, `code value: ${f.code_value}`))),
      h("span", { class: "ids" }, chips(c.evidence_ids, d))))));
}

async function showGuardrailDemo(d, slot, btn) {
  if (S.busy) return;
  S.busy = true; btn.disabled = true;
  try {
    const r = await api(`/api/cases/${d.case.id}/guardrail-demo`, { method: "POST" });
    slot.replaceChildren(h("div", { class: "demo-box" },
      h("p", {}, who("template", "Demonstration"), " ", h("strong", {}, r.note), " Nothing was stored and no AI model or budget was used."),
      h("p", { class: "label", style: "margin-top:10px" }, "The faulty reply"), h("blockquote", {}, `${r.summary}\n\n${r.reply}`),
      guardrailTable(guardChecks(null, r.flags), { kind: "bad", text: r.rejected ? "Rejected: a reply like this would never reach a person. A rules-only draft would be shown instead." : "This reply would pass." })));
  } catch (e) { slot.replaceChildren(h("div", { class: "notice error", role: "alert" }, `Could not run the demonstration: ${e.message}`)); }
  finally { S.busy = false; btn.disabled = false; }
}

function runButtons(d, label) {
  const closed = d.case.status === "Closed";
  if (closed) return null;
  const live = d.ai.mode !== "mock";
  const b = S.ai && S.ai.budget;
  const blocked = live && (d.ai.mode === "misconfigured" || (b && b.exhausted));
  return [h("button", { type: "button", class: "btn primary", id: "run-analysis", disabled: !!(S.busy || blocked), onclick: (e) => runAnalysis({ force: d.workflow.current_valid, rules_only: false }, e.currentTarget) },
      label || (d.workflow.current_valid ? "Regenerate analysis" : "Run analysis")),
    h("button", { type: "button", class: "btn", id: "run-rules", disabled: !!S.busy, onclick: (e) => runAnalysis({ force: false, rules_only: true }, e.currentTarget) }, "Create rules-only draft (no AI)")];
}

function aiCard(d) {
  const wf = d.workflow, run = wf.latest, v = wf.view, mockMode = d.ai.mode === "mock";
  const slot = h("div", {});
  const demoBtn = h("button", { type: "button", class: "btn quiet", onclick: (e) => showGuardrailDemo(d, slot, e.currentTarget) }, "See the guardrails catch a bad reply (demonstration)");
  const head = h("h2", {}, "What the AI found",
    run && run.mode === "live" ? who("ai", "AI explains") : who("template", run ? "Template, no model called" : "Not run yet"));
  const principle = h("p", { class: "meta" }, who("ai", "AI explains"), " It classifies, summarises and drafts. ", who("human", "Humans decide"), " Nothing happens until a person records a decision.");
  if (!run) {
    return h("section", { class: "block aicard" }, head, principle,
      h("p", { class: "muted", style: "margin-top:10px" }, mockMode ? "No analysis has run for this case. Mock mode runs a free local template: no AI model is called." : "No analysis has run for this case. Nothing is sent to the AI provider until someone clicks Run analysis; each run uses one of the lifetime AI calls."),
      h("div", { class: "pipeline-slot" }), h("div", { class: "btnrow" }, runButtons(d), demoBtn), h("div", { id: "ai-err", role: "alert" }), slot);
  }
  const rules = d.case.issue.replace(/_/g, " ");
  const kids = [head, principle];
  if (v) {
    const ai = v.classification.replace(/_/g, " "), match = v.classification === d.case.issue;
    kids.push(h("div", { class: "match", style: "margin-top:12px" },
      h("span", {}, v.source === "live" ? "AI classified this as: " : "Template classified this as: ", h("strong", {}, ai)), h("span", { class: "arrow" }, "↔"),
      h("span", {}, "Rules read it as: ", h("strong", {}, rules)),
      h("span", { class: `res ${match ? "ok" : "bad"}` }, match ? "✓ Match" : "✗ They differ")));
    kids.push(h("p", { class: "lead", style: "font-size:14px" }, v.summary));
  } else {
    kids.push(h("p", { class: "flag" }, run.outcome === "rejected" ? "The AI replied, but its answer failed the guardrails and was rejected, so none of its statements are shown as findings. A rules-only draft was prepared instead."
      : run.outcome === "error" ? `The AI call failed (${run.error_message || "error"}). A rules-only draft was prepared instead.` : "This was a rules-only draft: no AI text exists to show."));
  }
  kids.push(h("div", { class: "rule" }), h("h4", {}, `Pipeline, run #${run.id}`, " ", h("span", { class: "meta", style: "text-transform:none;letter-spacing:0" }, `started ${fmt(run.started_at, true)}`)),
    h("div", { class: "pipeline-slot" }, pipelineView(run, d, S.animateRun === run.id)));
  if (v) kids.push(h("div", { class: "rule" }), stmtList("Verified", "verified", v.verified, d), stmtList("Unverified", "unverified", v.unverified, d),
    v.unresolved.length > 0 && h("div", {}, h("div", { class: "sect-title warn" }, "Unresolved decisions"), h("ul", { class: "plain", style: "margin-top:8px" }, v.unresolved.map((u) => h("li", {}, u)))));
  // guardrail results: shown whenever the reply reached validation
  const val = run.validation || {};
  kids.push(h("div", { class: "rule" }), h("h4", {}, "Guardrail results"));
  if (val.passed === undefined || val.passed === null) {
    kids.push(h("p", { class: "meta", style: "margin-top:8px" }, run.mode === "rules-only" ? "Not applicable: this draft is a rules-only template, not AI text." : "The guardrails did not run: there was no AI reply to check."));
  } else {
    kids.push(guardrailTable(guardChecks(val), run.outcome === "rejected" ? { kind: "bad", text: "AI reply REJECTED. A rules-only draft is shown instead." }
      : { kind: "ok", text: run.mode === "live" ? "All checks passed. A person must still read the reply." : "Checks passed on the mock template. No model was involved." }));
  }
  kids.push(h("p", { class: "meta", style: "margin-top:10px" }, "These checks cover citations, times, numbers and promise wording. They cannot prove every statement is true, so a person must read the reply before approving."));
  if (wf.stale) kids.push(h("p", { class: "flag" }, d.case.status === "Closed" ? "This analysis was generated before the decision was recorded." : "The evidence changed after this analysis. Run it again before approving."));
  kids.push(h("div", { class: "btnrow" }, runButtons(d), demoBtn), h("div", { id: "ai-err", role: "alert" }), slot);
  return h("section", { class: "block aicard" }, kids);
}

function evidenceView() {
  const d = S.detail, a = d.analysis;
  const closed = d.case.status === "Closed";
  const cta = closed ? h("a", { class: "btn", href: `#/case/${d.case.id}/decision` }, "View decision record")
    : h("a", { class: "btn primary big", href: `#/case/${d.case.id}/decision` }, "Review decision", icon("arrow"));
  const open = d.review_items.filter((r) => r.status === "open");
  const aside = h("aside", { class: "aside" },
    h("section", { class: "panel sticky" },
      h("h2", {}, "What needs a decision"),
      h("p", { class: "route" }, routeLabel(d)),
      h("p", { class: "meta" }, who("human", "Humans decide"), " Only a TA or professor can act."),
      open.length > 0 && h("ul", { class: "plain", style: "margin-top:12px" }, open.map((r) => h("li", {},
        h("div", {}, r.title), h("div", { class: "meta" }, `Route: ${r.route_to}`, " ", chips(r.evidence_ids, d))))),
      a.warnings.length > 0 && h("div", { class: "flags" }, h("h3", {}, "Flags"),
        h("ul", { class: "plain" }, a.warnings.map((w) => h("li", { class: "flag" }, w.text, " ", chips(w.evidence_ids, d))))),
      h("div", { class: "meta", style: "margin-top:12px" }, closed ? "Status: " : "Next: ", h("strong", {}, nextStep(d.case))),
      cta));

  return h("div", { class: "page" },
    noticeEl(),
    caseHeader(d, "evidence"),
    h("section", { class: "summary" }, h("h2", {}, "What the records show", who("rules", "Computed by rules, not AI")), h("p", { class: "lead" }, factSummary(d))),
    h("div", { class: "cols" },
      h("div", { class: "colmain" },
        aiCard(d), messagesSection(d), submissionSection(d), scoreSection(d), policySection(d), auditSection(d)),
      aside));
}

function messagesSection(d) {
  const msgs = d.evidence.filter((e) => e.source_type === "message");
  return h("section", { class: "block" }, h("h2", {}, "Messages"),
    msgs.map((m) => h("article", { class: `msg ${m.payload.direction}` },
      h("div", { class: "msghead" },
        h("strong", {}, m.payload.direction === "inbound" ? "Student message" : "Prior reply"),
        h("span", { class: "meta" }, ` ${channelName(m.payload.channel)} · ${m.payload.author} · ${fmt(m.ts, true)} `), idChip(m.ref_id, d)),
      h("blockquote", {}, m.source_text))));
}

function submissionSection(d) {
  const a = d.analysis, dl = a.deadline;
  const nodes = a.attempts.map((t) => ({ kind: "attempt", ts: t.ts, t }));
  if (dl) nodes.push({ kind: "deadline", ts: dl.ts });
  nodes.sort((x, y) => Date.parse(x.ts) - Date.parse(y.ts));
  const stateText = { unreadable: "Unreadable file", empty_file: "Empty file", alternate_evidence: "Alternate evidence, not a Canvas submission" };
  const sub = d.evidence.find((e) => e.source_type === "submission_status");
  const time = (ts) => h("div", { class: "tltime" }, h("div", { class: "clock" }, ts.slice(11, 16)), h("div", { class: "tldate" }, fmt(ts).split(",")[0]));
  const items = nodes.map((n) => {
    if (n.kind === "deadline") {
      return h("li", { class: "tl deadline" }, time(n.ts), h("div", { class: "tlrail" }, h("span", { class: "tlmark" })),
        h("div", { class: "tlbody" }, h("div", { class: "tltitle" }, h("strong", {}, "Deadline"), idChip(dl.ref_id, d)),
          h("div", { class: "meta" }, "Anything after this line is late under the policy."), h("div", { class: "dashline" })));
    }
    const t = n.t;
    const cls = t.state !== "submitted" ? "problem" : t.late ? "late" : "ontime";
    return h("li", { class: `tl attempt ${cls}` }, time(t.ts), h("div", { class: "tlrail" }, h("span", { class: "tlmark" })),
      h("div", { class: "tlbody" },
        h("div", { class: "tltitle" }, h("strong", {}, `Attempt ${a.attempts.indexOf(t) + 1}`), idChip(t.ref_id, d),
          t.state === "submitted" ? h("span", { class: `badge ${t.late ? "bad" : "ok"}`, style: "margin-left:0" }, t.late ? "LATE" : "ON TIME")
            : h("span", { class: "badge warn", style: "margin-left:0" }, stateText[t.state] || t.state),
          t.counted && h("span", { class: "badge", style: "margin-left:0" }, "graded")),
        t.state === "submitted" && h("div", { class: "meta" }, mins(t)), t.file && h("div", { class: "meta mono" }, t.file)));
  });
  if (!a.attempts.length) {
    items.push(h("li", { class: "tl attempt problem" }, h("div", { class: "tltime" }, h("div", { class: "clock" }, "--:--")),
      h("div", { class: "tlrail" }, h("span", { class: "tlmark" })),
      h("div", { class: "tlbody" }, h("div", { class: "tltitle" }, h("strong", {}, "No submission recorded"), sub && idChip(sub.ref_id, d)),
        h("div", { class: "meta" }, "Canvas shows no file for this assignment."))));
  }
  return h("section", { class: "block" }, h("h2", {}, "Submission vs deadline", who("rules", "Computed by rules")), h("ol", { class: "timeline" }, items));
}

function stat(label, value, note, emphasis) {
  return h("div", { class: `stat ${emphasis || ""}` }, h("div", { class: "statlabel" }, label), h("div", { class: "statval" }, value), note && h("div", { class: "meta" }, note));
}

function scoreSection(d) {
  const s = d.analysis.score_state;
  const hasScore = s.rubric_total != null || s.entered != null;
  const score = s.evidence_ids.filter((i) => i.startsWith("SCORE"));
  if (!hasScore) {
    return h("section", { class: "block" }, h("h2", {}, "Score reconciliation"),
      h("p", { class: "muted" }, "No rubric or entered score is recorded for this case yet."));
  }
  const diff = s.differences.find((x) => x.code === "entered_vs_expected");
  const max = s.rubric_max || s.rubric_total || 1;
  const bar = (label, v, cls) => h("div", { class: "barrow" }, h("span", { class: "barlabel" }, label),
    h("span", { class: "bartrack" }, h("span", { class: `barfill ${cls}`, style: `width:${Math.max(0, Math.min(100, (v / max) * 100))}%` })),
    h("span", { class: "barval" }, num(v)));
  return h("section", { class: "block" }, h("h2", {}, "Score reconciliation"),
    h("p", { class: "meta" }, "All values below are computed by rules from the records. Nothing is auto-corrected."),
    h("div", { class: "stats" },
      stat("Rubric total", `${num(s.rubric_total)} / ${num(s.rubric_max)}`, "Sum of rubric rows"),
      stat("Late deduction recorded", num(s.late_deduction_applied), "In the gradebook"),
      stat("Deduction expected", num(s.expected_deduction), "From policy and counted attempt"),
      stat("Final (computed)", num(s.expected_final), "Rubric total minus expected deduction"),
      stat("Entered score", num(s.entered), "Gradebook entry", diff ? "diff" : ""),
      stat("Posted to student", s.posted == null ? "Not posted" : num(s.posted), s.graded ? "Graded" : "Not graded")),
    s.rubric_total != null && s.entered != null && h("div", { class: "bars", "aria-label": "Rubric total compared with entered score" },
      bar("Rubric total", s.rubric_total, "a"), bar("Entered", s.entered, diff ? "b diff" : "b"),
      diff && h("p", { class: "diffline" }, `Entered is ${num(Math.abs(diff.amount))} ${diff.amount < 0 ? "below" : "above"} the computed final. Sources: `, chips(diff.evidence_ids, d))),
    s.differences.filter((x) => x !== diff).map((x) => h("p", { class: "flag" }, x.text, " ", chips(x.evidence_ids, d))),
    s.scenarios.length > 1 && h("p", { class: "meta" }, "What-if by attempt (information only, nothing applied): ",
      s.scenarios.map((x) => `${x.attempt}: deduction ${num(x.deduction)}, final ${num(x.final)}. `)),
    s.rubric_rows.length > 0 && h("details", { class: "more" }, h("summary", {}, `Rubric rows (${s.rubric_rows.length})`),
      h("table", { class: "mini" }, h("thead", {}, h("tr", {}, ["Row", "Awarded", "Source"].map((t) => h("th", { scope: "col" }, t)))),
        h("tbody", {}, s.rubric_rows.map((r) => h("tr", {}, h("td", {}, r.label), h("td", {}, `${r.awarded} of ${r.max}`), h("td", {}, idChip(r.ref_id, d))))))),
    h("p", { class: "meta" }, "Score record: ", chips(score, d)));
}

function policySection(d) {
  const a = d.analysis, pol = d.evidence.find((e) => e.source_type === "policy");
  const apr = d.evidence.filter((e) => e.source_type === "approval");
  let policyBody;
  if (pol) {
    const parts = pol.source_text.split(/ (?=\d\. )/);
    const p = a.policy.params;
    policyBody = [
      h("p", {}, parts.slice(0, 2).join(" "), " "), idChip(pol.ref_id, d),
      p && h("p", { class: "meta" }, `Computed rule: submissions up to ${p.max_late_hours} hours late lose ${p.late_percent}% of the maximum points; the ${p.grade_basis === "latest_attempt" ? "newest attempt is graded" : p.grade_basis}; exceptions need the ${p.exception_authority}.`),
      h("details", { class: "more" }, h("summary", {}, "Expand full policy"), h("blockquote", {}, pol.source_text)),
    ];
  } else {
    policyBody = h("div", { class: "notice warn", role: "note" }, h("strong", {}, "Policy not found. "),
      `The assignment refers to ${a.policy.version || "a policy"} but no such policy record exists, so lateness cannot be judged. The case stays on hold until a policy is confirmed.`);
  }
  return h("section", { class: "block" }, h("h2", {}, "Policy and approvals"), policyBody,
    h("h3", {}, "Professor approvals"),
    apr.length ? apr.map((e) => h("p", {}, idChip(e.ref_id, d), ` ${fmt(e.ts, true)}: ${e.summary}`, e.source_text ? ` - "${e.source_text}"` : ""))
      : h("p", { class: "flag" }, "Insufficient evidence: no professor approval on file."));
}

function auditSection(d) {
  const TYPE = { message: "Message", attempt: "Attempt", deadline: "Deadline", policy: "Policy", rubric: "Rubric", score: "Score", approval: "Approval", submission_status: "Submission status" };
  return h("section", { class: "block" },
    h("details", { id: "audit", class: "more" },
      h("summary", {}, `Full audit timeline (${d.evidence.length} records, oldest first)`),
      h("ol", { class: "audit" }, d.evidence.map((e) => h("li", { id: `ev-${e.ref_id}` },
        h("div", { class: "audtime" }, fmt(e.ts, true)),
        h("div", {}, h("span", { class: "idchip plain" }, e.ref_id), " ", h("span", { class: "meta" }, TYPE[e.source_type] || e.source_type), h("div", {}, e.summary),
          e.source_text && h("blockquote", {}, e.source_text),
          h("details", { class: "raw" }, h("summary", {}, "Raw record"), h("pre", {}, JSON.stringify(e.payload, null, 2)))))))));
}

// ------------------------------------------------------------------ decision screen


// ------------------------------------------------------------------ decision screen

const ACTION_ORDER = ["approve", "hold", "escalate", "request_info", "reject"];

function choosePrimary(role, perms, a, d, hasDraft) {
  if (d.case.status === "Closed") return null;
  if (role === "ta" && d.case.status === "Awaiting professor") return null; // waiting on someone else
  const ok = (x) => perms[x] && perms[x].enabled && !(x === "approve" && !hasDraft);
  let want = a.suggested_action;
  if (role === "professor" && want === "escalate") want = "approve";
  if (want === "approve" && !hasDraft) return null; // the reply must exist first
  if (ok(want)) return want;
  return ["request_info", "hold", "approve", "escalate", "reject"].find(ok) || null;
}

function actionReason(action, perms, hasDraft) {
  const p = perms[action];
  if (!p.enabled) return p.reason || "Not available";
  if (action === "approve" && !hasDraft) return "Run the analysis first so there is a reply to review and approve.";
  return "";
}

function analysisStatus(d) {
  const wf = d.workflow, run = wf.latest, ai = d.ai;
  const stale = !wf.stale ? "" : d.case.status === "Closed" ? " It was generated before the decision was recorded." : " The evidence changed after this ran; run it again before approving.";
  if (!run) {
    if (ai.mode === "mock") return { kind: "info", text: "Not run yet. Mock mode runs a deterministic template locally; no AI model is called." };
    if (ai.mode === "misconfigured") return { kind: "warn", text: "Live AI is not usable: the server has a key but no model id. Use the rules-only draft." };
    return { kind: "info", text: `Live AI is configured (${ai.model}) but has not been run for this case. Nothing is sent to the provider until you click Run analysis.` };
  }
  const t = run.total_tokens ? `, ${run.total_tokens} tokens` : "";
  switch (run.outcome) {
    case "accepted": return { kind: "ok", text: `Live AI succeeded: ${run.model}, ${run.latency_ms} ms${t}. The reply passed the guardrails.${stale}` };
    case "mock": return { kind: "info", text: `Mock analysis only: a deterministic template ran locally and no AI model was called.${stale}` };
    case "rules-only": return { kind: "info", text: `Rules-only draft: no model was called. This text is not AI output.${stale}` };
    case "rejected": return { kind: "warn", text: `Live AI replied, but the answer failed the guardrails and was rejected (${(run.validation.flags || []).length} problem(s)). The draft below is a rules-only template, not AI output.${stale}` };
    case "error": return { kind: "warn", text: `Live AI call failed: ${run.error_message || "unknown error"} The draft below is a rules-only template, not AI output.${stale}` };
    default: return { kind: "info", text: "An analysis is in progress." };
  }
}

function analysisPanel(d, closed) {
  const wf = d.workflow, ai = d.ai, st = analysisStatus(d), b = S.ai && S.ai.budget;
  const live = ai.mode !== "mock";
  const off = closed ? "This case is closed." : S.busy ? "An analysis is already running." : "";
  const liveBlocked = live && (ai.mode === "misconfigured" ? "Live AI is not usable until a model id is configured on the server."
    : b && b.exhausted ? "The lifetime AI budget is used up. Use the rules-only draft." : "");
  return h("div", { class: "aipanel" },
    h("div", { class: `notice ${st.kind === "ok" ? "success" : st.kind === "warn" ? "warn" : "info"}` }, st.text),
    live && b && h("p", { class: "meta" }, `Lifetime AI calls: ${b.calls_used} of ${b.calls_limit} used. Each run uses one; a retry (${b.max_retries ? "enabled" : "disabled"}) would use another. Prompts are capped at ${b.max_prompt_bytes} bytes and replies at ${b.max_completion_tokens} tokens.`),
    !closed && h("div", { class: "btnrow" }, runButtons(d)),
    !closed && h("div", { id: "ai-err", role: "alert" }),
    !closed && h("p", { class: "meta", id: "run-why" }, off || liveBlocked || (live ? "Uses one lifetime AI call. A valid analysis is reused until the evidence changes." : "Free: mock mode makes no model call.")),
    h("div", { class: "pipeline-slot" }, wf.latest && pipelineView(wf.latest, d, S.animateRun === wf.latest.id)),
    wf.rejected && h("details", { class: "more" }, h("summary", {}, "Rejected AI output (kept for audit, never used)"),
      (wf.rejected.flags || []).map(flagEl), wf.rejected.reply && h("blockquote", {}, wf.rejected.reply)),
    h("p", { class: "meta" }, "The guardrails check citations, numbers, times and promise wording. They cannot prove every statement is correct, so a person must read the reply before approving."));
}

function decisionView() {
  const d = S.detail, a = d.analysis, dr = d.draft, role = S.role, perms = d.permissions[role];
  const closed = d.case.status === "Closed";
  const approved = !!(dr && dr.approved_at);
  const waitingProf = d.case.status === "Awaiting professor";
  const primary = choosePrimary(role, perms, a, d, !!dr);
  const attemptItem = d.review_items.some((r) => r.kind === "attempt_basis" && r.status === "open");
  const step2Done = () => S.ui.note.trim().length > 0 && (!attemptItem || role !== "professor" || !!S.ui.counted);

  const noteErr = h("p", { class: "fielderr", id: "note-err", role: "alert" });
  const countedErr = h("p", { class: "fielderr", id: "counted-err", role: "alert" });
  const formErr = h("div", { id: "form-err", role: "alert" });
  const note = h("textarea", { id: "note", class: "input", rows: 3, "aria-describedby": "note-err note-help",
    oninput: (e) => { S.ui.note = e.target.value; noteErr.textContent = ""; refreshSteps(); } }, S.ui.note);
  const counted = h("select", { id: "counted", class: "input", disabled: role !== "professor", "aria-describedby": "counted-err counted-help",
    onchange: (e) => { S.ui.counted = e.target.value; countedErr.textContent = ""; refreshSteps(); } },
    h("option", { value: "" }, "Select an attempt"),
    a.attempts.filter((t) => t.state === "submitted").map((t) => h("option", { value: t.ref_id, selected: S.ui.counted === t.ref_id }, `${t.ref_id}: ${fmt(t.ts)}, ${mins(t)}`)));

  const flagBox = h("div", { id: "liveflags", "aria-live": "polite" });
  const dirtyNote = h("span", { class: "dirty", hidden: !isDirty() }, "Unsaved edits");
  let timer;
  const readonly = approved || closed;
  const body = h("textarea", { id: "body", class: "input draft", rows: 14, readonly,
    "aria-label": readonly ? "Approved reply (draft, not sent)" : "Reply to student (editable draft)",
    oninput: (e) => {
      S.ui.body = e.target.value; dirtyNote.hidden = !isDirty();
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (S.ui.body == null || !body.isConnected) return; // state was reset (analysis, save, navigation)
        try {
          const r = await api(`/api/cases/${d.case.id}/draft/check`, { method: "POST", body: { body: S.ui.body } });
          flagBox.replaceChildren(...r.flags.map(flagEl));
        } catch (err) { flagBox.replaceChildren(h("p", { class: "meta" }, `Could not check the text just now: ${err.message}`)); }
      }, 400);
    } }, S.ui.body ?? storedBody(dr));

  const whys = [];
  const mk = (action, isPrimary) => {
    const why = actionReason(action, perms, !!dr);
    const rid = `why-${action}`;
    if (why) whys.push(h("div", { class: "why", id: rid }, `${actionLabel(action, role)}: ${why}`));
    const btn = h("button", { type: "button", class: `btn ${isPrimary ? "primary big" : action === "reject" ? "danger small" : "small"}`, "data-action": action,
      disabled: !!why, title: why || null, "aria-describedby": why ? rid : null, onclick: (e) => submit(action, e.currentTarget) },
      actionLabel(action, role), isPrimary && icon("arrow"));
    return h("div", { class: `act ${isPrimary ? "primary" : ""}` }, btn, h("div", { class: "meta" }, `Moves to: ${perms[action].next_status}`));
  };
  const actions = [];
  if (!closed) {
    if (waitingProf && role === "ta") {
      actions.push(h("div", { class: "notice info" }, "This case is with the professor. A TA cannot approve or reject it. You can still add a hold or ask the student for information."));
    } else if (!primary && !dr) {
      actions.push(h("div", { class: "notice info" }, "Run the analysis in step 3 first. The recommended action appears once there is a reply to review."));
    }
    if (primary) actions.push(h("div", { class: "actions" }, mk(primary, true)));
    const others = ACTION_ORDER.filter((x) => x !== primary);
    const otherEls = others.map((x) => mk(x, false));
    actions.push(h("div", { class: "others" }, h("div", { class: "label" }, primary ? "Other actions" : "Actions"),
      h("div", { class: "row" }, otherEls), whys.length > 0 && h("div", { class: "whylist" }, whys)));
  }

  const sc = d.score_control;
  const scReason = sc.recorded ? sc.recorded.rationale : !a.professor_approved ? "Requires a professor approval first."
    : !a.score_change ? "The approved basis gives the same score as the gradebook; nothing to record." : "";
  const scBtn = h("button", { type: "button", class: "btn", disabled: !sc.enabled, "aria-describedby": "sc-why", onclick: (e) => recordScore(e.currentTarget) }, "Record score recommendation");

  // ---- numbered step cards: the active one has a brand border, finished ones a check
  const defs = [];
  const step = (title, tag, bodyNodes, isDone) => {
    const num = h("span", { class: "stepno" }, String(defs.length + 1));
    const li = h("li", { class: "step" }, h("h2", {}, num, title, tag), bodyNodes);
    defs.push({ li, num, isDone, n: defs.length + 1 });
    return li;
  };
  step("Review evidence and the recommended action", who("rules", "Computed by rules"), [
    h("p", { class: "lead" }, factSummary(d)),
    h("p", {}, h("strong", {}, routeLabel(d)), closed ? "." : [". Rules suggest: ", h("strong", {}, nextStep({ ...d.case, status: "New" })), "."]),
    !closed && h("ul", { class: "plain", style: "margin-top:8px" }, a.reasons.map((r) => h("li", {}, r))),
    !closed && h("p", { class: "meta" }, "Uncertainty: " + (a.uncertainty.join(" ") || "none identified by the rules.")),
    h("a", { href: `#/case/${d.case.id}/evidence` }, "Open the full evidence")], () => true);
  if (!closed) {
    step("Choose the attempt and add a note", who("human", "Humans decide"), [
      attemptItem ? h("div", { class: "formrow" }, h("label", { for: "counted" }, "Attempt that counts as the submission"), counted,
        h("p", { class: "meta", id: "counted-help" }, role === "professor" ? "Required to approve. This is the professor's call." : "Only the professor chooses which attempt counts. Switch the demo role to try it."), countedErr)
        : h("p", { class: "meta" }, "No attempt choice is needed for this case."),
      h("div", { class: "formrow" }, h("label", { for: "note" }, "Note for the decision log"), note,
        h("p", { class: "meta", id: "note-help" }, "Required for every action except Approve. Stored with your name, role and time."), noteErr)], step2Done);
  }
  step(closed ? "Analysis and approved reply" : "Run the analysis and review the reply", who(dr && dr.source === "llm" ? "ai" : "template", dr && dr.source === "llm" ? "AI explains" : "Template, not AI"), [
    analysisPanel(d, closed),
    h("div", { class: "draftmeta" }, h("span", { class: "drafttag" }, "Draft only — not sent"), dirtyNote),
    h("p", { class: "meta" }, provenance(d)),
    dr ? [h("label", { for: "body", class: "label" }, approved ? "Approved reply (draft, not sent)" : "Reply to student (editable draft)"), body, flagBox]
       : h("p", { class: "muted" }, "There is no reply draft yet."),
    dr && !readonly && h("div", { class: "btnrow" }, h("button", { type: "button", class: "btn", onclick: (e) => saveDraft(e.currentTarget) }, "Save edits")),
    dr && dr.flags.length > 0 && h("div", {}, h("h3", { style: "margin-top:14px" }, "Guardrail flags"), dr.flags.map(flagEl)),
    dr && claimDetails("Verified facts", "verified", dr.verified, d), dr && claimDetails("Unverified", "unverified", dr.unverified, d)],
    () => closed || approved || (!!dr && d.workflow.current_valid));
  step(closed ? "Decision and score recommendation" : "Record the decision", who("human", "Humans decide"), [
    !closed && h("p", { class: "meta" }, `Acting as ${role === "ta" ? "TA" : "Professor"} (demo role). Recording a decision changes this case's status and writes a log entry. Nothing is sent and nothing changes in Canvas.`),
    !closed && formErr, actions,
    h("div", { class: "scorebox" }, h("h3", { style: "margin:0 0 4px" }, "Score recommendation"),
      h("p", { class: "meta" }, "A professor approval authorises a recommendation only. Recording it saves a note inside GradeCase. Entering a grade in Canvas is a separate step staff do outside this tool; GradeCase never writes to Canvas."),
      scBtn, h("p", { class: "meta", id: "sc-why" }, scReason),
      a.score_change && !sc.recorded && h("p", {}, `Approved basis would recommend ${num(a.score_change.from)} → ${num(a.score_change.to)}.`))], () => closed);

  function refreshSteps() {
    let active = -1;
    defs.forEach((s, i) => { s.done = closed || s.isDone(); if (!s.done && active < 0) active = i; });
    defs.forEach((s, i) => {
      s.li.classList.toggle("done", s.done);
      s.li.classList.toggle("active", !closed && i === active);
      s.num.replaceChildren(...(s.done ? [icon("check")] : [String(s.n)]));
      if (s.done) s.num.setAttribute("aria-label", "completed"); else s.num.removeAttribute("aria-label");
    });
  }
  S.decisionSteps = refreshSteps;

  return h("div", { class: "page" },
    noticeEl(),
    caseHeader(d, "decision"),
    closed && h("div", { class: "notice info" }, "This case is closed. The decision and the approved reply are shown for the record; nothing here can be edited."),
    h("ol", { class: "flow" }, defs.map((s) => s.li)),
    logSection(d));
}
const refreshSteps = () => { if (S.decisionSteps) S.decisionSteps(); };

function provenance(d) {
  const dr = d.draft;
  if (!dr) return "No draft yet.";
  if (dr.source === "llm") return `Drafted by the live model (${d.workflow.latest ? d.workflow.latest.model : "unknown"}) and checked by the guardrails. It is still only a draft: a person must read it.`;
  if (dr.source === "mock") return "Template draft built from the computed records. Mock mode: no AI model was called.";
  if (dr.ai_status === "unavailable") return "Rules-only template. The AI reply was unavailable or rejected, so this text is NOT AI output.";
  return "Rules-only template you requested. This text is NOT AI output.";
}

const flagEl = (f) => h("div", { class: "flag" }, f.message, f.code_value != null && h("strong", {}, ` Code value: ${f.code_value}`));

function claimDetails(title, kind, claims, d) {
  return h("details", { class: "more" }, h("summary", {}, `${title} (${claims.length})`),
    claims.length ? h("ul", { class: "stmts" }, claims.map((c) => h("li", { class: `stmt${kind === "verified" ? "" : " unverified"}` },
      h("span", {}, c.text, (c.flags || []).filter((f) => f.kind === "needs_verification").map((f) => h("span", { class: "badge bad" }, `needs verification (code: ${f.code_value})`))),
      h("span", { class: "ids" }, chips(c.evidence_ids, d))))) : h("p", { class: "meta" }, "None."));
}

function logSection(d) {
  return h("section", { class: "block" }, h("h2", {}, "Decision log", who("human", "Humans decide")),
    d.decisions.length ? h("ul", { class: "activity" }, [...d.decisions].reverse().map((x) => h("li", {},
      h("div", {}, h("strong", {}, x.actor), ` (${x.role}) `, x.action.replace(/_/g, " "),
        x.from_status && x.from_status !== x.to_status && ` · ${x.from_status} → ${x.to_status}`),
      h("div", { class: "meta" }, fmt(x.ts, true)), x.note && h("div", { class: "note" }, x.note))))
      : h("p", { class: "muted" }, "No decisions recorded yet."));
}

async function runAnalysis(opts, btn) {
  if (S.busy) return;
  if (!confirmDiscard("replace the draft")) return;
  const live = S.detail.ai.mode !== "mock" && !opts.rules_only;
  if (live) {
    const left = S.ai && S.ai.budget ? S.ai.budget.calls_remaining : "?";
    if (!confirm(`This sends the case records to the AI provider and uses one of the ${left} remaining lifetime AI calls. Continue?`)) return;
  }
  S.busy = true;
  const done = setBusy(btn, live ? "Calling AI..." : "Working...");
  // While the request is in flight, show the pipeline running. Nothing is marked done until the
  // server returns the real stages.
  const slots = [...document.querySelectorAll(".pipeline-slot")];
  const saved = slots.map((s) => [...s.childNodes]);
  if (!opts.rules_only) slots.forEach((s) => s.replaceChildren(pipelineRunning(live)));
  try {
    const out = await api(`/api/cases/${S.detail.case.id}/analysis`, { method: "POST", body: opts });
    S.detail = out;
    S.ui.body = null;
    S.animateRun = out.workflow.latest ? out.workflow.latest.id : null;
    const ai = out.ai;
    S.notice = ({
      succeeded: { kind: "success", title: "AI analysis succeeded.", text: "It passed the guardrails. Read the reply before deciding." },
      mock: { kind: "info", title: "Mock analysis finished.", text: "No AI model was called." },
      cached: { kind: "info", title: "Analysis reused.", text: ai.message },
      rules_only: { kind: "info", title: "Rules-only draft created.", text: "No model was called; this text is not AI output." },
      rejected: { kind: "error", title: "AI reply rejected by the guardrails.", text: `${ai.message} A rules-only draft was prepared instead.` },
      error: { kind: "error", title: "AI call failed.", text: `${ai.message} A rules-only draft was prepared instead.` },
    })[ai.status] || { kind: "info", title: "Done.", text: "" };
  } catch (e) {
    done();
    slots.forEach((s, i) => s.replaceChildren(...saved[i]));
    showErr(e.message, "ai-err");
    S.busy = false;
    await refreshAi();
    return;
  }
  S.busy = false;
  await refreshAi();
  await render();
  S.animateRun = null;
}

function setBusy(btn, text) {
  const all = [...document.querySelectorAll(".act button, .btnrow button, .scorebox button")];
  all.forEach((b) => { b.dataset.was = b.disabled ? "1" : ""; b.disabled = true; });
  const old = btn.textContent;
  btn.textContent = text;
  return () => { all.forEach((b) => { b.disabled = b.dataset.was === "1"; }); btn.textContent = old; };
}

function showErr(text, id = "form-err") {
  const box = document.getElementById(id);
  if (box) box.replaceChildren(h("div", { class: "notice error" }, text));
  say(text);
}

async function submit(action, btn) {
  const d = S.detail;
  const attemptItem = d.review_items.some((r) => r.kind === "attempt_basis" && r.status === "open");
  const noteVal = S.ui.note.trim();
  document.getElementById("form-err").replaceChildren();
  let bad = null;
  if (action !== "approve" && !noteVal) {
    document.getElementById("note-err").textContent = "Add a note: it is required for this action.";
    bad = "note";
  }
  if (action === "approve" && S.role === "professor" && attemptItem && !S.ui.counted) {
    document.getElementById("counted-err").textContent = "Choose which attempt counts before approving.";
    bad = bad || "counted";
  }
  if (bad) { document.getElementById(bad).focus(); return; }
  const done = setBusy(btn, "Recording...");
  try {
    const before = d.case.status;
    const out = await api(`/api/cases/${d.case.id}/decision`, { method: "POST", body: {
      role: S.role, action, note: noteVal, counted_attempt: S.ui.counted || null,
      body: S.ui.body ?? storedBody(d.draft) } });
    S.detail = out;
    S.ui = { caseId: d.case.id, note: "", counted: "", body: null };
    S.notice = { kind: "success", title: "Decision recorded.",
      text: `${actionLabel(action, S.role)}. Status: ${before} → ${out.case.status}. Logged with your name and time. Nothing was sent. No Canvas change.` };
    say("Decision recorded.");
    render();
    window.scrollTo(0, 0);
  } catch (e) {
    done();
    showErr(`Not recorded: ${e.message}`); // inputs are kept so nothing needs retyping
  }
}

async function saveDraft(btn) {
  const done = setBusy(btn, "Saving...");
  try {
    S.detail = await api(`/api/cases/${S.detail.case.id}/draft`, { method: "PUT", body: { body: S.ui.body ?? storedBody(S.detail.draft) } });
    S.ui.body = null;
    S.notice = { kind: "success", title: "Draft saved.", text: "Your edits are stored. The reply is still a draft and was not sent." };
    render();
  } catch (e) { done(); showErr(`Could not save the draft: ${e.message}`); }
}

async function recordScore(btn) {
  const done = setBusy(btn, "Recording...");
  try {
    S.detail = await api(`/api/cases/${S.detail.case.id}/score-recommendation`, { method: "POST", body: { role: S.role } });
    S.notice = { kind: "success", title: "Score recommendation recorded.", text: "It exists only inside GradeCase. No Canvas change was made." };
    render();
  } catch (e) { done(); showErr(`Could not record the recommendation: ${e.message}`); }
}

// ------------------------------------------------------------------ intake (synthetic only)

const OFFSETS = [["-07:00", "UTC-7 (Mountain standard)"], ["+00:00", "UTC"]];

function fieldRow(label, control, help, fieldPath) {
  const id = `f-${fieldPath.replace(/\./g, "-")}`;
  control.id = id;
  control.setAttribute("data-field", fieldPath);
  return h("div", { class: "formrow" }, h("label", { for: id }, label), control, help && h("p", { class: "meta" }, help),
    h("p", { class: "fielderr", "data-err-for": fieldPath, role: "alert" }));
}
const textIn = (path, ph, extra = {}) => h("input", { type: "text", class: "input", placeholder: ph || "", autocomplete: "off", ...extra });
const numIn = (ph, extra = {}) => h("input", { type: "number", class: "input", step: "any", min: "0", placeholder: ph || "", ...extra });

function rowControls(container, makeRow, max, label) {
  const add = h("button", { type: "button", class: "btn", onclick: () => { if (container.children.length < max) container.append(makeRow()); } }, label);
  return add;
}

async function intakeView() {
  const cases = await api("/api/cases");
  let examples = [];
  try { examples = await api("/api/intake/examples"); } catch (e) { /* the form works without examples */ }

  const summary = h("div", { id: "intake-summary", role: "alert" });
  const mode = h("select", { class: "input", id: "f-mode", onchange: () => toggleMode() },
    h("option", { value: "new" }, "Create a new case"), h("option", { value: "existing" }, "Add a message to an existing case"));
  const existing = h("select", { class: "input" }, cases.filter((c) => !c.merged_into).map((c) => h("option", { value: c.id, "data-student": c.student_id, "data-assignment": c.assignment }, `${c.id}: ${caseTitle(c)} (${c.assignment}, ${c.student_id})`)));
  const offset = h("select", { class: "input", id: "f-offset" }, OFFSETS.map(([v, t]) => h("option", { value: v }, t)));
  const channel = h("select", { class: "input" }, ["canvas_inbox", "email", "submission_comment"].map((c) => h("option", { value: c }, channelName(c))));
  const direction = h("select", { class: "input" }, h("option", { value: "inbound" }, "From the student"), h("option", { value: "outbound" }, "Reply from staff"));
  const staff = h("select", { class: "input" }, ["TA Rivera", "TA Chen", "Prof. Demo"].map((n) => h("option", { value: n }, n)));
  const student = textIn("student", "S-4B21");
  const assignment = textIn("assignment", "HW6");
  const courseIn = textIn("course", "DEMO 3060");
  const issue = h("select", { class: "input" }, [["", "Auto-detect from the message"], ["late_flag", "Late flag"], ["score_gap", "Score gap"],
    ["missing_submission", "Missing submission"], ["other", "Other"]].map(([v, t]) => h("option", { value: v }, t)));
  let uploadSource = null; // "screenshot" | "document" when the form was pre-filled from an upload
  const msgTs = h("input", { type: "datetime-local", class: "input" });
  const msgText = h("textarea", { class: "input", rows: 4, maxlength: 2000, placeholder: "I submitted on time but it shows late." });
  const ack = h("input", { type: "checkbox", id: "f-ack", "data-field": "synthetic_ack" });
  const owner = h("select", { class: "input" }, h("option", { value: "" }, "Unassigned"), ["TA Rivera", "TA Chen"].map((n) => h("option", { value: n }, n)));

  const ctxName = textIn("c", "Homework 6");
  const ctxDeadline = h("input", { type: "datetime-local", class: "input" });
  const ctxPoints = numIn("10", { min: "1" });
  const ctxPolicy = h("select", { class: "input" },
    h("option", { value: "POL-LATE-v1" }, "POL-LATE-v1 (on file)"), h("option", { value: "POL-LATE-v9" }, "POL-LATE-v9 (not on file: the case will be put on hold)"));
  const attempts = h("div", { class: "rows" });
  const rubric = h("div", { class: "rows" });
  const scEntered = numIn("7"), scPosted = numIn("7"), scDed = numIn("0"), scGraded = h("input", { type: "checkbox", id: "f-graded" });

  const attemptRow = (v = {}) => {
    const i = attempts.children.length;
    const row = h("div", { class: "rowline", "data-field": `context.attempts.${i}` },
      h("label", { class: "field" }, h("span", { class: "label" }, `Attempt ${i + 1} time`), h("input", { type: "datetime-local", class: "input", "data-k": "ts", "data-field": `context.attempts.${i}.ts`, value: v.ts || "" })),
      h("label", { class: "field" }, h("span", { class: "label" }, "State"), h("select", { class: "input", "data-k": "state", "data-field": `context.attempts.${i}.state` },
        [["submitted", "Submitted"], ["unreadable", "File unreadable"], ["empty_file", "Empty file"], ["alternate_evidence", "Alternate evidence (screenshot/link)"]].map(([k, t]) => h("option", { value: k, selected: v.state === k }, t)))),
      h("label", { class: "field" }, h("span", { class: "label" }, "File name (optional)"), h("input", { type: "text", class: "input", "data-k": "file", "data-field": `context.attempts.${i}.file`, value: v.file || "" })),
      h("button", { type: "button", class: "btn quiet", onclick: (e) => { e.currentTarget.parentElement.remove(); } }, "Remove"),
      h("p", { class: "fielderr", "data-err-for": `context.attempts.${i}`, role: "alert" }));
    return row;
  };
  const rubricRow = (v = {}) => {
    const i = rubric.children.length;
    return h("div", { class: "rowline", "data-field": `context.rubric.${i}` },
      h("label", { class: "field" }, h("span", { class: "label" }, "Row label"), h("input", { type: "text", class: "input", "data-k": "label", "data-field": `context.rubric.${i}.label`, value: v.label || "" })),
      h("label", { class: "field" }, h("span", { class: "label" }, "Max points"), h("input", { type: "number", step: "any", min: "0", class: "input", "data-k": "max", "data-field": `context.rubric.${i}.max`, value: v.max ?? "" })),
      h("label", { class: "field" }, h("span", { class: "label" }, "Awarded"), h("input", { type: "number", step: "any", min: "0", class: "input", "data-k": "awarded", "data-field": `context.rubric.${i}.awarded`, value: v.awarded ?? "" })),
      h("button", { type: "button", class: "btn quiet", onclick: (e) => { e.currentTarget.parentElement.remove(); } }, "Remove"),
      h("p", { class: "fielderr", "data-err-for": `context.rubric.${i}`, role: "alert" }));
  };

  const ctxBox = h("fieldset", { class: "ctx" }, h("legend", {}, "Supporting records for the new case (all synthetic)"),
    h("p", { class: "meta" }, "These become the case's evidence. Anything you leave out is simply missing, and the rule engine will say so. Only POL-LATE-v1 exists as a policy in this demo."),
    fieldRow("Assignment name", ctxName, null, "context.assignment_name"),
    fieldRow("Deadline", ctxDeadline, "Uses the time zone chosen above.", "context.deadline"),
    fieldRow("Maximum points", ctxPoints, null, "context.max_points"),
    fieldRow("Late policy reference", ctxPolicy, null, "context.policy_ref"),
    h("h3", {}, "Submission attempts"), attempts, rowControls(attempts, attemptRow, 6, "Add attempt"),
    h("p", { class: "meta" }, "No attempts means the case records no submission."),
    h("h3", {}, "Rubric rows"), rubric, rowControls(rubric, rubricRow, 12, "Add rubric row"),
    h("h3", {}, "Gradebook"),
    h("div", { class: "rowline" }, h("label", { class: "field" }, h("span", { class: "label" }, "Entered score"), scEntered),
      h("label", { class: "field" }, h("span", { class: "label" }, "Posted score"), scPosted),
      h("label", { class: "field" }, h("span", { class: "label" }, "Late deduction recorded"), scDed),
      h("label", { class: "check" }, scGraded, " Graded")));

  function toggleMode() {
    const isNew = mode.value === "new";
    ctxBox.hidden = !isNew; existingRow.hidden = isNew; studentRow.hidden = !isNew; assignRow.hidden = !isNew; courseRow.hidden = !isNew;
    ownerRow.hidden = !isNew; issueRow.hidden = !isNew; dirRow.hidden = isNew; staffRow.hidden = isNew || direction.value !== "outbound";
  }
  direction.addEventListener("change", () => { staffRow.hidden = direction.value !== "outbound"; });

  const existingRow = fieldRow("Existing case", existing, "The student and assignment of that case are used.", "case_id");
  const studentRow = fieldRow("Student pseudo-ID", student, "Format S- plus 4 to 8 hex characters. Never a real name or number.", "student");
  const assignRow = fieldRow("Assignment ID", assignment, "Letters and digits, e.g. HW6.", "assignment");
  const courseRow = fieldRow("Course (optional)", courseIn, "Leave empty to use the demo course.", "course");
  const issueRow = fieldRow("Issue type", issue, "Detected from the message unless you choose one.", "issue");
  const ownerRow = fieldRow("Owner (optional)", owner, null, "owner");
  const dirRow = fieldRow("Message type", direction, null, "message.direction");
  const staffRow = fieldRow("Staff author", staff, null, "message.author");

  function fill(req) {
    uploadSource = null; visionResult.replaceChildren();
    mode.value = "new"; toggleMode(); courseIn.value = req.course || ""; issue.value = req.issue || "";
    student.value = req.student; assignment.value = req.assignment;
    channel.value = req.message.channel; msgText.value = req.message.text;
    const local = (ts) => ts.slice(0, 16);
    msgTs.value = local(req.message.ts);
    offset.value = OFFSETS.some(([v]) => req.message.ts.endsWith(v)) ? req.message.ts.slice(-6) : "-07:00";
    const c = req.context; if (!c) return;
    ctxName.value = c.assignment_name; ctxDeadline.value = local(c.deadline); ctxPoints.value = c.max_points;
    ctxPolicy.value = c.policy_ref;
    attempts.replaceChildren(...c.attempts.map((a) => attemptRow({ ...a, ts: local(a.ts) })));
    rubric.replaceChildren(...c.rubric.map((r) => rubricRow(r)));
    const sc = c.score || {};
    scEntered.value = sc.entered ?? ""; scPosted.value = sc.posted ?? ""; scDed.value = sc.late_deduction_applied ?? 0; scGraded.checked = !!sc.graded;
  }

  const iso = (local) => (local ? `${local.length === 16 ? local + ":00" : local}${offset.value}` : "");
  const numOrNull = (el) => (el.value === "" ? null : Number(el.value));

  function build() {
    const isNew = mode.value === "new";
    const sel = existing.selectedOptions[0];
    const message = { channel: channel.value, ts: iso(msgTs.value), text: msgText.value };
    const req = { synthetic_ack: ack.checked, message };
    if (isNew) {
      req.student = student.value.trim(); req.assignment = assignment.value.trim();
      if (owner.value) req.owner = owner.value;
      if (courseIn.value.trim()) req.course = courseIn.value.trim();
      if (uploadSource) req.source = uploadSource;
      if (issue.value) req.issue = issue.value;
      req.context = {
        assignment_name: ctxName.value.trim(), deadline: iso(ctxDeadline.value), max_points: numOrNull(ctxPoints),
        policy_ref: ctxPolicy.value,
        attempts: [...attempts.children].map((r) => {
          const o = { ts: iso(r.querySelector('[data-k="ts"]').value), state: r.querySelector('[data-k="state"]').value };
          const f = r.querySelector('[data-k="file"]').value.trim(); if (f) o.file = f; return o;
        }),
        rubric: [...rubric.children].map((r) => ({ label: r.querySelector('[data-k="label"]').value.trim(),
          max: Number(r.querySelector('[data-k="max"]').value), awarded: Number(r.querySelector('[data-k="awarded"]').value) })),
        score: { entered: numOrNull(scEntered), posted: numOrNull(scPosted), graded: scGraded.checked, late_deduction_applied: numOrNull(scDed) ?? 0 },
      };
    } else {
      req.student = sel.dataset.student; req.assignment = sel.dataset.assignment; req.case_id = existing.value;
      message.direction = direction.value;
      if (direction.value === "outbound") message.author = staff.value;
    }
    return req;
  }

  function showErrors(errors) {
    document.querySelectorAll(".fielderr[data-err-for]").forEach((p) => { p.textContent = ""; });
    const unmatched = [];
    let first = null;
    for (const e of errors) {
      const keys = [...document.querySelectorAll("[data-err-for]")].map((p) => p.dataset.errFor)
        .filter((k) => e.field === k || e.field.startsWith(k + ".")).sort((a, b) => b.length - a.length);
      const p = keys.length ? document.querySelector(`[data-err-for="${CSS.escape(keys[0])}"]`) : null;
      if (p) { p.textContent = e.message; first = first || document.querySelector(`[data-field="${CSS.escape(keys[0])}"]`); }
      else unmatched.push(e);
    }
    summary.replaceChildren(h("div", { class: "notice error" }, h("div", {},
      h("strong", {}, "Some fields need attention."),
      h("ul", { class: "plain" }, errors.map((e) => h("li", {}, e.field ? `${e.field}: ${e.message}` : e.message))))));
    const target = first || summary; if (target.focus) target.focus();
    if (target.scrollIntoView) target.scrollIntoView({ block: "center" });
  }


  // ---- screenshot -> fields (a person reviews and edits everything before the case exists)
  const visionResult = h("div", { id: "vision-result", "aria-live": "polite" });
  const fileIn = h("input", { type: "file", id: "f-shot", accept: "image/png,image/jpeg,image/webp,application/pdf,.pdf,.docx,.txt,.csv,.tsv,.md,.eml,text/plain,text/csv", class: "sr-only" });
  const preview = h("div", { class: "preview" });
  const visionAck = h("input", { type: "checkbox", id: "f-vision-ack" });
  const fileInfo = h("div", { class: "fileinfo", hidden: true });
  const readLabel = S.cfg.ai_mode === "mock" ? "Extract sample values (mock mode)" : "Extract with AI";
  const readBtn = h("button", { type: "button", class: "btn primary", id: "read-shot", disabled: true }, readLabel);
  const drop = h("label", { class: "drop", for: "f-shot" }, icon("file"),
    h("strong", {}, "Drop a screenshot, PDF, or document"), h("span", { class: "formats" }, "PNG, JPG, PDF, DOCX, CSV \u2014 up to 5 MB"),
    h("span", { class: "btn" }, "Browse files"));
  const MAX_IMG = 5 * 1024 * 1024;
  const canRead = () => { readBtn.disabled = !(fileIn.files && fileIn.files[0] && visionAck.checked) || S.busy; };
  const toLocal = (ts, off) => { // express a timestamp in the form's chosen offset
    const sign = off[0] === "-" ? -1 : 1, mins = sign * (Number(off.slice(1, 3)) * 60 + Number(off.slice(4, 6)));
    const d = new Date(Date.parse(ts) + mins * 60000);
    return d.toISOString().slice(0, 16);
  };
  function fillFromExtraction(ex, kind) {
    uploadSource = kind === "image" ? "screenshot" : "document";
    mode.value = "new"; toggleMode();
    issue.value = ["late_flag", "score_gap", "missing_submission"].includes(ex.issue_type) ? ex.issue_type : "";
    extracted = true; setTab("upload");
    const first = ex.message_time || ex.deadline || ex.submission_time;
    const off = first ? first.slice(-6) : "-07:00";
    if (![...offset.options].some((o) => o.value === off)) offset.append(h("option", { value: off }, `UTC${off}`));
    offset.value = off;
    const loc = (ts) => (ts ? toLocal(ts, off) : "");
    student.value = ex.student_id || ""; assignment.value = ex.assignment_id || ""; courseIn.value = ex.course || "";
    if (ex.channel) channel.value = ex.channel;
    msgText.value = ex.student_message || ""; msgTs.value = loc(ex.message_time);
    ctxName.value = ex.assignment_name || ""; ctxDeadline.value = loc(ex.deadline); ctxPoints.value = ex.max_points ?? "";
    attempts.replaceChildren(...(ex.submission_time ? [attemptRow({ ts: loc(ex.submission_time), state: "submitted" })] : []));
    rubric.replaceChildren(...(ex.rubric_total != null ? [rubricRow({ label: "Rubric total (read from screenshot)", max: ex.max_points ?? ex.rubric_total, awarded: ex.rubric_total })] : []));
    scEntered.value = ex.score_entered ?? ""; scPosted.value = ex.score_entered ?? ""; scDed.value = 0; scGraded.checked = ex.score_entered != null;
  }
  function showVision(b) {
    visionResult.replaceChildren(h("div", { class: `notice ${b.mock ? "warn" : "success"}`, role: "status" }, h("div", {},
      h("strong", {}, b.mock ? "Sample values, not analysed from your file. " : b.kind === "image" ? "The model read your screenshot. " : `The model read your ${b.kind === "pdf" ? "PDF" : b.kind === "docx" ? "Word file" : "text file"}. `),
      "Every field below is editable. Check each value against your source file: the model can misread, and nothing is created until you click Create case.",
      h("p", { class: "meta" }, b.mock ? "Mock mode: no AI model analysed the file."
        : `${b.provenance.model}, ${b.provenance.latency_ms} ms${b.provenance.total_tokens ? `, ${b.provenance.total_tokens} tokens` : ""}. Confidence: ${b.extraction.confidence}.`),
      b.problems.length > 0 && h("ul", { class: "plain" }, b.problems.map((p) => h("li", { class: "flag" }, p))),
      b.extraction.issue_type && h("p", { class: "meta" }, `Issue type read: ${b.extraction.issue_type.replace(/_/g, " ")}.`))));
  }
  async function readShot() {
    if (S.busy) return;
    const f = fileIn.files[0];
    if (!f) return;
    if (f.size > MAX_IMG) { visionResult.replaceChildren(h("div", { class: "notice error", role: "alert" }, "That image is larger than 5 MiB.")); return; }
    if (S.cfg.ai_mode !== "mock") {
      const left = S.ai && S.ai.budget ? S.ai.budget.calls_remaining : "?";
      if (!confirm(`This sends the file to the AI provider and uses one of the ${left} remaining lifetime AI calls. Continue?`)) return;
    }
    S.busy = true; canRead();
    const old = readBtn.textContent; readBtn.textContent = "Reading...";
    visionResult.replaceChildren(h("p", { class: "meta", role: "status" }, S.cfg.ai_mode === "mock" ? "Preparing sample values..." : "Reading the file with the AI model. This can take several seconds."));
    try {
      const fd = new FormData();
      fd.append("file", f); fd.append("synthetic_ack", "true");
      const resp = await fetch("/api/intake/upload", { method: "POST", body: fd });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        visionResult.replaceChildren(h("div", { class: "notice error", role: "alert" }, typeof data.detail === "string" ? data.detail : `Request failed (HTTP ${resp.status})`));
      } else { fillFromExtraction(data.extraction, data.kind); showVision(data); }
    } catch (e) {
      visionResult.replaceChildren(h("div", { class: "notice error", role: "alert" }, `Could not reach the server: ${e.message}`));
    } finally { S.busy = false; readBtn.textContent = old; canRead(); await refreshAi(); }
  }
  const sizeText = (n) => (n < 1048576 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`);
  function onFile() {
    preview.replaceChildren(); fileInfo.replaceChildren();
    const f = fileIn.files && fileIn.files[0];
    fileInfo.hidden = !f;
    if (f) {
      const ext = (f.name.includes(".") ? f.name.split(".").pop() : "file").toUpperCase();
      fileInfo.append(h("span", { class: "name" }, f.name), h("span", { class: "meta" }, sizeText(f.size)), h("span", { class: "badge", style: "margin-left:0" }, ext));
      if (/^image\//.test(f.type)) preview.append(h("img", { src: URL.createObjectURL(f), alt: "Preview of the selected screenshot" }));
      else preview.append(h("p", { class: "meta" }, "No preview for documents. The text is read on the server."));
    }
    canRead();
  }
  fileIn.addEventListener("change", onFile);
  visionAck.addEventListener("change", canRead);
  readBtn.addEventListener("click", readShot);
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => { if (e.dataTransfer && e.dataTransfer.files.length) { fileIn.files = e.dataTransfer.files; onFile(); } });
  const visionBox = h("section", { class: "vision" }, h("h2", {}, "Start from a screenshot or document"),
    h("p", { class: "meta" }, S.cfg.ai_mode === "mock"
      ? "Mock mode: files are read locally but no AI model analyses them. You get clearly labelled sample values to replace."
      : "Upload a screenshot of an email or Canvas page, a PDF, a Word file, or a text or CSV export. Images go to the vision model; documents are read on the server and their text goes to the text model. You review and edit everything before a case is created. It uses one lifetime AI call. A CSV or PDF with several students yields only the first case."),
    drop, fileIn, fileInfo, preview,
    h("label", { class: "check" }, visionAck, " This file contains only synthetic data: no real student names, emails, grades or IDs."),
    h("div", { class: "btnrow" }, readBtn), visionResult);

  const submitBtn = h("button", { type: "submit", class: "btn primary big" }, "Create case");
  const form = h("form", { class: "intake", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    if (S.busy) return;
    S.busy = true; submitBtn.disabled = true; submitBtn.textContent = "Creating...";
    summary.replaceChildren();
    try {
      const out = await fetch("/api/intake", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(build()) });
      const data = await out.json().catch(() => ({}));
      if (!out.ok) {
        if (data.errors && data.errors.length) showErrors(data.errors);
        else summary.replaceChildren(h("div", { class: "notice error" }, data.detail || `Request failed (HTTP ${out.status})`));
        return;
      }
      S.notice = { kind: "success", title: mode.value === "new" ? "Case created." : "Message added.", text: `${data.case_id} now holds ${data.message_id}. The rule engine has already checked the records.` };
      S.detail = null;
      location.hash = `#/case/${data.case_id}/evidence`;
    } catch (err) {
      summary.replaceChildren(h("div", { class: "notice error" }, `Could not reach the server: ${err.message}`));
    } finally { S.busy = false; submitBtn.disabled = false; submitBtn.textContent = "Create case"; }
  } },
    summary,
    h("div", { class: "notice warn" }, h("strong", {}, "Synthetic data only. "), "Do not type real student names, emails, phone numbers, links or ID numbers: they are rejected. Nothing is sent to Canvas or email, and the demo cases A to D use built-in records, not this form."),
    h("h2", {}, "Review the case details"),
    examples.length > 0 && h("div", { class: "btnrow examples" }, h("span", { class: "meta" }, "Load an example:"),
      examples.map((x) => h("button", { type: "button", class: "btn", onclick: () => fill(x.request) }, x.title.split(":")[0]))),
    fieldRow("What are you adding?", mode, null, "mode"),
    existingRow, studentRow, assignRow, courseRow, issueRow, ownerRow,
    fieldRow("Channel", channel, null, "message.channel"),
    dirRow, staffRow,
    fieldRow("Message time", msgTs, "Uses the time zone below.", "message.ts"),
    fieldRow("Time zone", offset, null, "tz"),
    fieldRow("Message text", msgText, "Up to 2000 characters.", "message.text"),
    ctxBox,
    h("div", { class: "formrow" }, h("label", { class: "check" }, ack, " I confirm this is synthetic data and contains no real student information."),
      h("p", { class: "fielderr", "data-err-for": "synthetic_ack", role: "alert" })),
    h("div", { class: "btnrow" }, submitBtn, h("a", { class: "btn", href: "#/queue" }, "Cancel")));

  // Two ways in: read a file with the AI model, or type it in. Both end at the same review form.
  let tab = "upload", extracted = false;
  const tabUpload = h("button", { type: "button", role: "tab", id: "tab-upload", onclick: () => setTab("upload") }, "Upload file");
  const tabManual = h("button", { type: "button", role: "tab", id: "tab-manual", onclick: () => setTab("manual") }, "Manual entry");
  const skip = h("p", { class: "meta", id: "skip-upload" }, "No file? ", h("button", { type: "button", class: "linkbtn", onclick: () => setTab("manual") }, "Enter the details by hand"), ".");
  function setTab(t) {
    tab = t;
    tabUpload.setAttribute("aria-selected", String(t === "upload")); tabManual.setAttribute("aria-selected", String(t === "manual"));
    visionBox.hidden = t !== "upload";
    skip.hidden = t !== "upload" || extracted;
    form.hidden = t === "upload" && !extracted;
    examplesRow.hidden = t !== "manual";
  }
  const examplesRow = form.querySelector(".examples");
  const view = h("div", { class: "page" }, h("h1", { class: "page-title" }, "New synthetic case"),
    h("p", { class: "lede" }, "Add a case from a screenshot, PDF or document, or type it in. The rules check the records straight away, and the usual duplicate, evidence and decision steps follow."),
    h("div", { class: "modetabs", role: "tablist", "aria-label": "How to add the case" }, tabUpload, tabManual),
    visionBox, skip, form);
  setTab("upload");
  existing.addEventListener("change", () => {});
  toggleMode();
  return view;
}

// ------------------------------------------------------------------ board (kanban)

const BOARD_COLS = ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"];
const ISSUE_LABEL = { late_flag: "Late flag", score_gap: "Score gap", missing_submission: "Missing submission", other: "Other" };
// What a drop means. Every move is a real decision: the server still enforces roles, blockers,
// notes and drafts. There is no way to move a case back to "New".
const MOVES = {
  "TA review": [{ action: "hold", label: "Place on hold", note: true }],
  "Awaiting professor": [{ action: "escalate", label: "Request professor review", note: true }],
  "Awaiting student info": [{ action: "request_info", label: "Request student information", note: true }],
  Closed: [{ action: "approve", label: "Approve and close", note: false }, { action: "reject", label: "Reject request", note: true }],
};
const canLeave = (c) => c.status !== "Closed" && !c.merged_into;
const canDropOn = (c, status) => canLeave(c) && status !== c.status && !!MOVES[status];
function ageText(c) {
  const t = Date.parse(c.opened_at);
  if (Number.isNaN(t)) return "";
  const d = Math.floor((Date.now() - t) / 86400000);
  return d <= 0 ? "opened today" : `open ${d} d`;
}

async function boardView() {
  const cases = await api("/api/cases");
  S.drag = null;
  const cols = BOARD_COLS.map((status) => {
    const items = cases.filter((c) => c.status === status);
    const list = h("div", { class: "kcards" }, items.map(boardCard), !items.length && h("p", { class: "meta kempty" }, "No cases"));
    const col = h("section", { class: "kcol", "data-status": status, "aria-labelledby": `kh-${slug(status)}` },
      h("h2", { id: `kh-${slug(status)}` }, h("span", {}, status), h("span", { class: "tabcount", "aria-label": `${items.length} cases` }, items.length)),
      list);
    col.addEventListener("dragover", (e) => {
      const c = S.drag && cases.find((x) => x.id === S.drag);
      if (c && canDropOn(c, status)) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("over"); }
    });
    col.addEventListener("dragleave", (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove("over"); });
    col.addEventListener("drop", (e) => {
      e.preventDefault(); col.classList.remove("over");
      const c = cases.find((x) => x.id === S.drag);
      if (c && canDropOn(c, status)) openMoveDialog(c, status);
    });
    return col;
  });
  return h("div", { class: "page" }, noticeEl(),
    h("div", { class: "pagehead" }, h("h1", { class: "page-title" }, "Board"), h("a", { class: "btn", href: "#/queue" }, "Open the list view")),
    h("p", { class: "lede" }, "Drag a card to a column, or use its ⋮ menu. Every move is recorded as a decision with your note, and the usual rules still apply. Nothing is sent and no grade changes."),
    h("ul", { class: "legend" }, Object.keys(ISSUE_LABEL).map((k) => h("li", {}, h("span", { class: `swatch i-${k}` }), ISSUE_LABEL[k]))),
    h("div", { class: "board board-cols" }, cols));
}

function boardCard(c) {
  const targets = BOARD_COLS.filter((s) => canDropOn(c, s));
  let menu = null;
  if (canLeave(c)) {
    menu = h("details", { class: "movemenu" },
      h("summary", { "aria-label": `Move ${c.id}`, title: "Move to..." }, "⋮"),
      h("div", { class: "menu", role: "menu" }, h("div", { class: "label" }, "Move to"),
        targets.map((s) => h("button", { type: "button", role: "menuitem", onclick: (e) => { e.currentTarget.closest("details").open = false; openMoveDialog(c, s); } }, s))));
  }
  const card = h("article", { class: `kcard i-${c.issue}`, draggable: canLeave(c) ? "true" : null, "data-id": c.id },
    canLeave(c) && h("span", { class: "draghandle", "aria-hidden": "true" }, "⋮⋮"),
    menu,
    h("a", { class: "caselink", href: `#/case/${c.id}/evidence` }, caseTitle(c)),
    h("div", { class: "mono" }, `${c.id} · ${c.student_id}`),
    h("div", { class: "meta" }, `${c.assignment_name} (${c.assignment})`),
    h("div", { class: "meta" }, c.owner || "Unassigned", " · ", ageText(c)),
    h("div", { class: "tags" }, h("span", { class: `issue i-${c.issue}` }, h("span", { class: "swatch" }), ISSUE_LABEL[c.issue] || "Other"),
      c.duplicates.length > 0 && h("span", { class: "tag" }, "Possible duplicate"), c.on_hold && h("span", { class: "tag" }, "On hold")));
  if (canLeave(c)) {
    card.addEventListener("dragstart", (e) => { S.drag = c.id; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", c.id); });
    card.addEventListener("dragend", () => { S.drag = null; card.classList.remove("dragging"); document.querySelectorAll(".kcol.over").forEach((x) => x.classList.remove("over")); });
  }
  return card;
}

function openMoveDialog(c, status) {
  const options = MOVES[status];
  const dlg = h("dialog", { class: "movedlg", "aria-labelledby": "mv-title" });
  let choice = options[0];
  const err = h("div", { role: "alert" });
  const note = h("textarea", { class: "input", id: "mv-note", rows: 3, "aria-describedby": "mv-help" });
  const help = h("p", { class: "meta", id: "mv-help" });
  const confirmBtn = h("button", { type: "submit", class: "btn primary" }, "Record move");
  const refreshHelp = () => {
    help.textContent = choice.note ? "A note is required. It is stored in the decision log with your name, role and time."
      : "Approving closes the case and needs a reviewed reply. If it says a reply is missing, use the Decision screen.";
    note.setAttribute("aria-required", String(choice.note));
  };
  const radios = options.length > 1 ? h("fieldset", { class: "choice" }, h("legend", {}, "What should this move record?"),
    options.map((o, i) => h("label", { class: "check" }, h("input", { type: "radio", name: "mv-action", value: o.action, checked: i === 0,
      onchange: () => { choice = o; refreshHelp(); } }), ` ${o.label}`))) : h("p", {}, h("strong", {}, choice.label), ".");
  refreshHelp();
  const form = h("form", { method: "dialog", onsubmit: async (e) => {
    e.preventDefault();
    if (S.busy) return;
    err.replaceChildren();
    if (choice.note && !note.value.trim()) { err.replaceChildren(h("p", { class: "fielderr" }, "Add a note: it is required for this move.")); note.focus(); return; }
    S.busy = true; confirmBtn.disabled = true; confirmBtn.textContent = "Recording...";
    try {
      const out = await api(`/api/cases/${c.id}/decision`, { method: "POST", body: { role: S.role, action: choice.action, note: note.value.trim() } });
      dlg.close();
      S.notice = { kind: "success", title: "Moved.", text: `${c.id}: ${c.status} → ${out.case.status}. Logged as "${choice.label}". Nothing was sent. No Canvas change.` };
      S.busy = false; render();
    } catch (ex) {
      S.busy = false; confirmBtn.disabled = false; confirmBtn.textContent = "Record move";
      err.replaceChildren(h("div", { class: "notice error" }, `Not moved: ${ex.message} `, h("a", { href: `#/case/${c.id}/decision` }, "Open the Decision screen")));
    }
  } },
    h("h2", { id: "mv-title" }, `Move ${c.id} to ${status}?`),
    h("p", { class: "meta" }, `${caseTitle(c)}. Currently ${c.status}. Acting as ${S.role === "ta" ? "TA" : "Professor"} (demo role).`),
    radios,
    h("div", { class: "formrow" }, h("label", { for: "mv-note" }, "Note"), note, help), err,
    h("div", { class: "btnrow" }, confirmBtn, h("button", { type: "button", class: "btn", onclick: () => dlg.close() }, "Cancel")));
  dlg.append(form);
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  note.focus();
}

// ------------------------------------------------------------------ calendar

const OVERDUE_AFTER_DAYS = 7; // this demo's own threshold for "open too long", not a policy
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const STATE_WORD = { resolved: "resolved", pending: "pending", overdue: "overdue" };
const ymd = (ts) => ts.slice(0, 10); // the date as recorded (in the timestamp's own time zone)

function caseState(c) {
  if (c.status === "Closed") return "resolved";
  const t = Date.parse(c.opened_at);
  return !Number.isNaN(t) && Date.now() - t > OVERDUE_AFTER_DAYS * 86400000 ? "overdue" : "pending";
}

function calendarEvents(cases) {
  const out = [];
  for (const c of cases) {
    const state = caseState(c);
    const tag = c.id.replace(/^CASE-/, "");
    if (c.deadline) out.push({ date: ymd(c.deadline), type: "Deadline", short: `Due ${tag}`, text: `${c.assignment_name} due ${c.deadline.slice(11, 16)}`, c, state });
    if (c.opened_at) out.push({ date: ymd(c.opened_at), type: "Case opened", short: `Opened ${tag}`, text: "First message arrived", c, state });
    for (const d of c.decisions) out.push({ date: ymd(d.ts), type: "Decision", short: `Decision ${tag}`, text: d.action.replace(/_/g, " "), c, state });
  }
  return out;
}

async function calendarView() {
  const cases = await api("/api/cases");
  const events = calendarEvents(cases);
  const today = new Date();
  const first = (() => {
    const m = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    if (events.some((e) => e.date.startsWith(m))) return { y: today.getFullYear(), m: today.getMonth() };
    const latest = events.map((e) => e.date).sort().pop(); // nothing this month: show the latest activity
    return latest ? { y: +latest.slice(0, 4), m: +latest.slice(5, 7) - 1 } : { y: today.getFullYear(), m: today.getMonth() };
  })();
  const st = { y: first.y, m: first.m, sel: null };
  const heading = h("h2", { "aria-live": "polite", class: "calhead" });
  const grid = h("div", { class: "calgrid", role: "grid", "aria-label": "Month" });
  const panel = h("section", { class: "block daypanel", "aria-live": "polite" });
  const iso = (d) => `${st.y}-${String(st.m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const SHOW = 2;

  function draw() {
    heading.textContent = `${MONTH_NAMES[st.m]} ${st.y}`;
    const lead = new Date(st.y, st.m, 1).getDay(), days = new Date(st.y, st.m + 1, 0).getDate();
    const cells = DOW.map((d) => h("div", { class: "dow", role: "columnheader" }, d));
    for (let i = 0; i < lead; i++) cells.push(h("div", { class: "day blank", "aria-hidden": "true" }));
    for (let d = 1; d <= days; d++) {
      const date = iso(d), ev = events.filter((e) => e.date === date);
      const counts = ["resolved", "pending", "overdue"].map((s) => [s, ev.filter((e) => e.state === s).length]).filter(([, n]) => n);
      cells.push(h("button", { type: "button", class: `day${date === todayIso ? " today" : ""}${st.sel === date ? " sel" : ""}`, role: "gridcell",
        "aria-pressed": String(st.sel === date),
        "aria-label": `${MONTH_NAMES[st.m]} ${d}, ${st.y}: ${ev.length ? counts.map(([s, n]) => `${n} ${STATE_WORD[s]}`).join(", ") : "no events"}`,
        onclick: () => { st.sel = date; draw(); } },
      h("span", { class: "dn" }, String(d)),
      h("span", { class: "evpills" }, ev.slice(0, SHOW).map((e) => h("span", { class: `evpill e-${e.state}`, title: `${e.type} (${STATE_WORD[e.state]})` }, e.short)),
        ev.length > SHOW && h("span", { class: "evmore" }, `+${ev.length - SHOW} more`))));
    }
    grid.replaceChildren(...cells);
    const list = st.sel ? events.filter((e) => e.date === st.sel) : [];
    panel.replaceChildren(h("h2", {}, st.sel ? `Events on ${st.sel}` : "Select a day"),
      !st.sel ? h("p", { class: "muted" }, "Click a date to see its deadlines, new cases and decisions.")
        : !list.length ? h("p", { class: "muted" }, "Nothing recorded on this day.")
        : h("ul", { class: "evlist" }, list.map((e) => h("li", {},
          h("span", { class: `dot d-${e.state}`, "aria-hidden": "true" }), " ", h("strong", {}, e.type), `: ${e.text}. `,
          h("a", { href: `#/case/${e.c.id}/evidence` }, `${caseTitle(e.c)} (${e.c.id})`), " ", pill(e.c.status),
          h("span", { class: "meta" }, ` ${STATE_WORD[e.state]}`)))));
  }
  const go = (delta) => { const d = new Date(st.y, st.m + delta, 1); st.y = d.getFullYear(); st.m = d.getMonth(); st.sel = null; draw(); };
  draw();
  return h("div", { class: "page" }, noticeEl(),
    h("div", { class: "pagehead" }, h("h1", { class: "page-title" }, "Calendar"), h("a", { class: "btn", href: "#/queue" }, "Open the list view")),
    h("p", { class: "lede" }, "Assignment deadlines, the day each case was opened, and the days decisions were recorded. Dates are shown as recorded."),
    h("ul", { class: "legend" },
      h("li", {}, h("span", { class: "dot d-resolved" }), "Resolved: the case is closed"),
      h("li", {}, h("span", { class: "dot d-pending" }), "Pending: the case is open"),
      h("li", {}, h("span", { class: "dot d-overdue" }), `Overdue: open more than ${OVERDUE_AFTER_DAYS} days (this demo's own threshold, not a policy)`)),
    h("div", { class: "calbar" },
      h("button", { type: "button", class: "btn", "aria-label": "Previous month", onclick: () => go(-1) }, "← Previous"),
      heading,
      h("button", { type: "button", class: "btn", "aria-label": "Next month", onclick: () => go(1) }, "Next →"),
      h("button", { type: "button", class: "btn quiet", onclick: () => { st.y = today.getFullYear(); st.m = today.getMonth(); st.sel = todayIso; draw(); } }, "Today")),
    grid, panel);
}

function setRole(role) {
  if (role === S.role) return;
  if (!confirmDiscard("switch role")) return;
  S.role = role;
  try { localStorage.setItem("gc_role", role); } catch (e) { /* ignore */ }
  S.notice = null;
  render();
}

async function boot() {
  try {
    S.cfg = await api("/api/config");
    $("name").textContent = S.cfg.product_name;
    $("banner").textContent = S.cfg.banner;
    $("mode").textContent = S.cfg.ai_mode === "mock"
      ? "Mock mode: reply drafts are templates built from computed records. No AI model is called."
      : S.cfg.ai_mode === "misconfigured"
        ? "AI is not usable: a key is set but no model id. Drafts fall back to rules-only templates."
        : "Live AI is configured, but only runs when someone clicks Run analysis. All numbers come from rules.";
  } catch (e) { S.cfg = { ai_mode: "mock" }; }
  await refreshAi();
  $("menu-btn").addEventListener("click", () => setMenu(!document.body.classList.contains("menu-open")));
  $("scrim").addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { setMenu(false); document.querySelectorAll(".movemenu[open]").forEach((m) => { m.open = false; }); } });
  document.addEventListener("click", (e) => { // close an open board menu when clicking elsewhere
    document.querySelectorAll(".movemenu[open]").forEach((m) => { if (!m.contains(e.target)) m.open = false; });
  });
  $("role-ta").addEventListener("click", () => setRole("ta"));
  $("role-professor").addEventListener("click", () => setRole("professor"));
  $("reset").addEventListener("click", async () => {
    if (!confirm("Reset the demo cases? This deletes recorded decisions, drafts, merges and cases you added, and restores the synthetic cases. The AI spending counters and the attempt log are NOT reset.")) return;
    try {
      await api("/api/demo/reset?confirm=true", { method: "POST" });
      S.detail = null; S.ui = { caseId: null, note: "", counted: "", body: null };
      S.notice = { kind: "info", title: "Demo data reset.", text: "The synthetic cases were restored. AI spending counters were not reset." };
      await refreshAi();
      if (location.hash !== "#/dashboard") { S.hash = "#/dashboard"; location.hash = "#/dashboard"; } else render();
    } catch (e) { S.notice = { kind: "error", title: "Reset failed.", text: e.message }; render(); }
  });
  window.addEventListener("hashchange", () => {
    if (S.ignoreHash) { S.ignoreHash = false; return; }
    if (!confirmDiscard("leave this page")) { S.ignoreHash = true; location.hash = S.hash; return; }
    S.hash = location.hash || "#/queue";
    if (!S.keepNotice) S.notice = null;
    S.keepNotice = false;
    render();
  });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("unhandledrejection", (e) => {
    const text = String((e.reason && e.reason.message) || e.reason);
    S.notice = { kind: "error", title: "Something went wrong.", text };
    say(text);
  });
  S.hash = location.hash || "#/dashboard";
  render();
}
boot();
