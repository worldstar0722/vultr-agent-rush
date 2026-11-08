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

function renderShell(route) {
  const link = (label, href, current) =>
    h("a", { href, class: "navlink", "aria-current": current ? "page" : null }, label);
  const nav = [link("Case Queue", "#/queue", route.screen === "queue")];
  if (route.caseId) {
    nav.push(h("div", { class: "navgroup" }, h("div", { class: "label" }, "Selected case"),
      h("div", { class: "mono navcase" }, route.caseId),
      link("Evidence", `#/case/${route.caseId}/evidence`, route.screen === "evidence"),
      link("Decision", `#/case/${route.caseId}/decision`, route.screen === "decision")));
  }
  $("nav").replaceChildren(...nav);

  const crumbs = [h("a", { href: "#/queue" }, "Cases")];
  if (route.caseId) {
    crumbs.push(h("span", { class: "sep" }, "/"), h("a", { href: `#/case/${route.caseId}/evidence` }, route.caseId));
    crumbs.push(h("span", { class: "sep" }, "/"), h("span", { "aria-current": "page" }, route.screen === "decision" ? "Decision" : "Evidence"));
  }
  $("crumbs").replaceChildren(...crumbs);

  for (const r of ["ta", "professor"]) $(`role-${r}`).setAttribute("aria-pressed", String(S.role === r));
  const live = S.cfg && S.cfg.llm_mode !== "mock";
  $("ai").replaceChildren(
    h("div", { class: "ai-title" }, live ? "Live AI connected" : "Rules + demo drafts"),
    h("div", { class: "ai-sub" }, live ? "Vultr Serverless Inference" : "Live AI not connected"));
  document.title = `${route.screen === "queue" ? "Cases" : route.caseId} - GradeCase`;
}

// ------------------------------------------------------------------ routing

function parseRoute() {
  const p = location.hash.replace(/^#\/?/, "").split("/");
  if (p[0] === "case" && p[1]) return { screen: p[2] === "decision" ? "decision" : "evidence", caseId: p[1] };
  return { screen: "queue", caseId: null };
}

let renderToken = 0;
async function render() {
  const route = parseRoute();
  const token = ++renderToken;
  const view = $("view");
  renderShell(route);
  try {
    if (route.screen === "queue") {
      S.detail = null;
      S.ui = { caseId: null, note: "", counted: "", body: null };
      const node = await queueView();
      if (token === renderToken) view.replaceChildren(node);
      return;
    }
    if (S.ui.caseId !== route.caseId) S.ui = { caseId: route.caseId, note: "", counted: "", body: null };
    S.lastCase = route.caseId;
    if (!S.detail || S.detail.case.id !== route.caseId || S.refetch) {
      view.replaceChildren(h("p", { class: "muted pad" }, "Loading case..."));
      S.detail = await api(`/api/cases/${route.caseId}`);
      S.refetch = false;
    }
    if (route.screen === "decision" && !S.detail.draft) {
      view.replaceChildren(h("p", { class: "muted pad" }, "Preparing the reply draft from computed records..."));
      S.detail = await api(`/api/cases/${route.caseId}/draft`, { method: "POST" });
    }
    if (token !== renderToken) return;
    view.replaceChildren(route.screen === "decision" ? decisionView() : evidenceView());
  } catch (e) {
    if (token !== renderToken) return;
    view.replaceChildren(h("div", { class: "pad" }, h("div", { class: "notice error", role: "alert" }, `Could not load this screen: ${e.message}`),
      h("button", { type: "button", class: "btn", onclick: () => { S.refetch = true; render(); } }, "Try again"),
      " ", h("a", { class: "btn", href: "#/queue" }, "Back to cases")));
  }
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
    h("h1", {}, "Cases"),
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
  return [att ? [idChip(att.ref_id, d), ` was submitted ${mins(att)}. `] : "", "No late flag or score difference was found in the records."];
}

function evidenceView() {
  const d = S.detail, a = d.analysis;
  const cta = h("a", { class: "btn primary big", href: `#/case/${d.case.id}/decision` }, "Review decision");
  const open = d.review_items.filter((r) => r.status === "open");
  const aside = h("aside", { class: "aside" },
    h("section", { class: "panel sticky" },
      h("h2", {}, "What needs a decision"),
      h("p", { class: "route" }, routeLabel(d)),
      open.length > 0 && h("ul", { class: "plain" }, open.map((r) => h("li", {},
        h("div", {}, r.title), h("div", { class: "meta" }, `Route: ${r.route_to}`, " ", chips(r.evidence_ids, d))))),
      a.warnings.length > 0 && h("div", { class: "flags" }, h("h3", {}, "Flags"),
        h("ul", { class: "plain" }, a.warnings.map((w) => h("li", { class: "flag" }, w.text, " ", chips(w.evidence_ids, d))))),
      h("div", { class: "meta" }, "Rules suggest: ", h("strong", {}, nextStep({ ...d.case, status: "New", suggested_action: a.suggested_action }))),
      d.case.status !== "Closed" ? cta : h("a", { class: "btn", href: `#/case/${d.case.id}/decision` }, "View decision")));

  return h("div", { class: "page" },
    noticeEl(),
    caseHeader(d, "evidence"),
    h("section", { class: "summary" }, h("h2", {}, "What the records show"), h("p", { class: "lead" }, factSummary(d))),
    h("div", { class: "cols" },
      h("div", { class: "colmain" },
        messagesSection(d), submissionSection(d), scoreSection(d), policySection(d), auditSection(d)),
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
  const items = nodes.map((n) => {
    if (n.kind === "deadline") {
      return h("li", { class: "tl deadline" }, h("div", { class: "tltime" }, h("div", { class: "clock" }, n.ts.slice(11, 16)), h("div", { class: "meta" }, fmt(n.ts).split(",")[0])),
        h("div", { class: "tlbody" }, h("strong", {}, "Deadline"), " ", idChip(dl.ref_id, d), h("div", { class: "meta" }, "Anything after this line is late under the policy.")));
    }
    const t = n.t;
    const cls = t.state !== "submitted" ? "problem" : t.late ? "late" : "ontime";
    return h("li", { class: `tl attempt ${cls}` },
      h("div", { class: "tltime" }, h("div", { class: "clock" }, t.ts.slice(11, 16)), h("div", { class: "meta" }, fmt(t.ts).split(",")[0])),
      h("div", { class: "tlbody" },
        h("div", {}, h("strong", {}, `Attempt ${a.attempts.indexOf(t) + 1}`), " ", idChip(t.ref_id, d), " ",
          t.state === "submitted" ? h("span", { class: `badge ${t.late ? "warn" : "ok"}` }, t.late ? "Late" : "On time") : h("span", { class: "badge warn" }, stateText[t.state] || t.state),
          t.counted && h("span", { class: "badge" }, "Graded attempt")),
        t.state === "submitted" && h("div", { class: "meta" }, mins(t)), t.file && h("div", { class: "meta mono" }, t.file)));
  });
  if (!a.attempts.length) {
    items.push(h("li", { class: "tl attempt problem" }, h("div", { class: "tltime" }, h("div", { class: "clock" }, "--:--")),
      h("div", { class: "tlbody" }, h("strong", {}, "No submission recorded"), " ", sub && idChip(sub.ref_id, d),
        h("div", { class: "meta" }, "Canvas shows no file for this assignment."))));
  }
  return h("section", { class: "block" }, h("h2", {}, "Submission vs deadline"), h("ol", { class: "timeline" }, items));
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

function choosePrimary(role, perms, a) {
  const ok = (x) => perms[x] && perms[x].enabled;
  let want = a.suggested_action;
  if (role === "professor" && want === "escalate") want = "approve";
  if (ok(want)) return want;
  return ["request_info", "hold", "approve", "escalate", "reject"].find(ok) || null;
}

function decisionView() {
  const d = S.detail, a = d.analysis, dr = d.draft, role = S.role, perms = d.permissions[role];
  const closed = d.case.status === "Closed";
  const approved = !!(dr && dr.approved_at);
  const primary = closed ? null : choosePrimary(role, perms, a);
  const attemptItem = d.review_items.some((r) => r.kind === "attempt_basis" && r.status === "open");
  const NOTE_REQ = ["hold", "reject", "escalate", "request_info"];

  const noteErr = h("p", { class: "fielderr", id: "note-err", role: "alert" });
  const countedErr = h("p", { class: "fielderr", id: "counted-err", role: "alert" });
  const formErr = h("div", { id: "form-err", role: "alert" });
  const note = h("textarea", { id: "note", class: "input", rows: 3, "aria-describedby": "note-err note-help",
    oninput: (e) => { S.ui.note = e.target.value; noteErr.textContent = ""; } }, S.ui.note);
  const counted = h("select", { id: "counted", class: "input", disabled: role !== "professor" || closed, "aria-describedby": "counted-err counted-help",
    onchange: (e) => { S.ui.counted = e.target.value; countedErr.textContent = ""; } },
    h("option", { value: "" }, "Select an attempt"),
    a.attempts.filter((t) => t.state === "submitted").map((t) => h("option", { value: t.ref_id, selected: S.ui.counted === t.ref_id }, `${t.ref_id}: ${fmt(t.ts)}, ${mins(t)}`)));

  const flagBox = h("div", { id: "liveflags", "aria-live": "polite" });
  const dirtyNote = h("span", { class: "dirty", hidden: !isDirty() }, "Unsaved edits");
  let timer;
  const body = h("textarea", { id: "body", class: "input draft", rows: 14, readonly: approved || closed,
    oninput: (e) => {
      S.ui.body = e.target.value; dirtyNote.hidden = !isDirty();
      clearTimeout(timer);
      timer = setTimeout(async () => {
        if (S.ui.body == null || !body.isConnected) return; // state was reset (regenerate, save, navigation)
        try {
          const r = await api(`/api/cases/${d.case.id}/draft/check`, { method: "POST", body: { body: S.ui.body } });
          flagBox.replaceChildren(...r.flags.map(flagEl));
        } catch (err) { flagBox.replaceChildren(h("p", { class: "meta" }, `Could not check the text just now: ${err.message}`)); }
      }, 400);
    } }, S.ui.body ?? storedBody(dr));

  const buttons = [];
  const reasons = [];
  const mk = (action, isPrimary) => {
    const p = perms[action];
    const rid = `why-${action}`;
    const btn = h("button", { type: "button", class: `btn ${isPrimary ? "primary big" : action === "reject" ? "danger" : ""}`, "data-action": action,
      disabled: !p.enabled, "aria-describedby": !p.enabled ? rid : null, onclick: (e) => submit(action, e.currentTarget) },
      actionLabel(action, role));
    return h("div", { class: `act ${isPrimary ? "primary" : ""}` }, btn,
      h("div", { class: "meta" }, `Moves to: ${p.next_status}`),
      !p.enabled && h("div", { class: "why", id: rid }, p.reason || "Not available"));
  };
  if (!closed) {
    if (primary) buttons.push(mk(primary, true));
    const others = ["approve", "hold", "escalate", "request_info", "reject"].filter((x) => x !== primary);
    buttons.push(h("div", { class: "others" }, h("div", { class: "label" }, primary ? "Other actions" : "Actions"), others.map((x) => mk(x, false))));
  }

  const sc = d.score_control;
  const scReason = sc.recorded ? sc.recorded.rationale : !a.professor_approved ? "Requires a professor approval first." :
    !a.score_change ? "The approved basis gives the same score as the gradebook; nothing to record." : "";
  const scBtn = h("button", { type: "button", class: "btn", disabled: !sc.enabled, "aria-describedby": "sc-why", onclick: (e) => recordScore(e.currentTarget) }, "Record score recommendation");

  return h("div", { class: "page" },
    noticeEl(),
    caseHeader(d, "decision"),
    closed && h("div", { class: "notice info" }, "This case is closed. The decision and the approved reply are shown below for the record."),
    h("ol", { class: "flow" },
      h("li", { class: "step" }, h("h2", {}, h("span", { class: "stepno" }, "1"), "Review evidence and the recommended action"),
        h("p", { class: "lead" }, factSummary(d)),
        h("p", {}, h("strong", {}, routeLabel(d)), ". Rules suggest: ", h("strong", {}, nextStep({ ...d.case, status: "New", suggested_action: a.suggested_action })), "."),
        h("ul", { class: "plain" }, a.reasons.map((r) => h("li", {}, r))),
        h("p", { class: "meta" }, "Uncertainty: " + (a.uncertainty.join(" ") || "none identified by the rules.")),
        h("a", { href: `#/case/${d.case.id}/evidence` }, "Open the full evidence")),
      h("li", { class: "step" }, h("h2", {}, h("span", { class: "stepno" }, "2"), "Choose the attempt and add a note"),
        attemptItem ? h("div", { class: "formrow" }, h("label", { for: "counted" }, "Attempt that counts as the submission"), counted,
          h("p", { class: "meta", id: "counted-help" }, role === "professor" ? "Required to approve. This is the professor's call." : "Only the professor chooses which attempt counts. Switch the demo role to try it."), countedErr)
          : h("p", { class: "meta" }, "No attempt choice is needed for this case."),
        h("div", { class: "formrow" }, h("label", { for: "note" }, "Note for the decision log"), note,
          h("p", { class: "meta", id: "note-help" }, "Required for every action except Approve. Stored with your name, role and time."), noteErr)),
      h("li", { class: "step" }, h("h2", {}, h("span", { class: "stepno" }, "3"), "Review the reply"),
        h("div", { class: "draftmeta" }, h("span", { class: "drafttag" }, "Draft only - not sent"), dirtyNote),
        h("p", { class: "meta" }, provenance(dr)),
        h("label", { for: "body", class: "label" }, approved ? "Approved reply (draft, not sent)" : "Reply to student (editable draft)"), body, flagBox,
        !approved && !closed && h("div", { class: "btnrow" },
          h("button", { type: "button", class: "btn", onclick: (e) => saveDraft(e.currentTarget) }, "Save edits"),
          h("button", { type: "button", class: "btn", onclick: (e) => regenerate(e.currentTarget) }, "Regenerate draft")),
        dr && dr.flags.length > 0 && h("div", {}, h("h3", {}, "Guardrail flags"), dr.flags.map(flagEl)),
        dr && claimBlock("Verified facts (each cites a record)", dr.verified, d), dr && claimBlock("Unverified (not confirmed by the records)", dr.unverified, d)),
      h("li", { class: "step" }, h("h2", {}, h("span", { class: "stepno" }, "4"), "Record the decision"),
        h("p", { class: "meta" }, `Acting as ${role === "ta" ? "TA" : "Professor"} (demo role). Recording a decision changes this case's status and writes a log entry. Nothing is sent and nothing changes in Canvas.`),
        formErr, buttons,
        h("div", { class: "scorebox" }, h("h3", {}, "Score recommendation"),
          h("p", { class: "meta" }, "Records a recommendation inside GradeCase only. No Canvas change."),
          scBtn, h("p", { class: "meta", id: "sc-why" }, scReason),
          a.score_change && !sc.recorded && h("p", {}, `Approved basis would recommend ${num(a.score_change.from)} → ${num(a.score_change.to)}.`)))),
    logSection(d));
}

function provenance(dr) {
  if (!dr) return "No draft yet.";
  if (dr.ai_status === "unavailable") return "AI unavailable, rules-only view. This is a template built from the computed records.";
  if (dr.ai_status === "mock") return "Template draft built from the computed records. Mock mode: no AI model was called.";
  return "Drafted by the configured model, then checked by guardrails.";
}

const flagEl = (f) => h("div", { class: "flag" }, f.message, f.code_value != null && h("strong", {}, ` Code value: ${f.code_value}`));

function claimBlock(title, claims, d) {
  return h("details", { class: "more" }, h("summary", {}, `${title} (${claims.length})`),
    claims.length ? h("ul", { class: "plain" }, claims.map((c) => h("li", {}, c.text, " ", chips(c.evidence_ids, d),
      (c.flags || []).filter((f) => f.kind === "needs_verification").map((f) => h("span", { class: "badge warn" }, `Needs verification (code: ${f.code_value})`)))))
      : h("p", { class: "meta" }, "None."));
}

function logSection(d) {
  return h("section", { class: "block" }, h("h2", {}, "Decision log"),
    d.decisions.length ? h("ul", { class: "activity" }, [...d.decisions].reverse().map((x) => h("li", {},
      h("div", {}, h("strong", {}, x.actor), ` (${x.role}) `, x.action.replace(/_/g, " "),
        x.from_status && x.from_status !== x.to_status && ` · ${x.from_status} → ${x.to_status}`),
      h("div", { class: "meta" }, fmt(x.ts, true)), x.note && h("div", { class: "note" }, x.note))))
      : h("p", { class: "muted" }, "No decisions recorded yet."));
}

// ------------------------------------------------------------------ decision actions

function setBusy(btn, text) {
  const all = [...document.querySelectorAll(".act button, .btnrow button, .scorebox button")];
  all.forEach((b) => { b.dataset.was = b.disabled ? "1" : ""; b.disabled = true; });
  const old = btn.textContent;
  btn.textContent = text;
  return () => { all.forEach((b) => { b.disabled = b.dataset.was === "1"; }); btn.textContent = old; };
}

function showErr(text) {
  const box = document.getElementById("form-err");
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

async function regenerate(btn) {
  if (!confirmDiscard("regenerate the draft")) return;
  const done = setBusy(btn, "Regenerating...");
  try {
    S.detail = await api(`/api/cases/${S.detail.case.id}/draft`, { method: "POST" });
    S.ui.body = null;
    S.notice = { kind: "info", title: "Draft regenerated.", text: "Review it before recording a decision." };
    render();
  } catch (e) { done(); showErr(`Could not regenerate the draft: ${e.message}`); }
}

async function recordScore(btn) {
  const done = setBusy(btn, "Recording...");
  try {
    S.detail = await api(`/api/cases/${S.detail.case.id}/score-recommendation`, { method: "POST", body: { role: S.role } });
    S.notice = { kind: "success", title: "Score recommendation recorded.", text: "It exists only inside GradeCase. No Canvas change was made." };
    render();
  } catch (e) { done(); showErr(`Could not record the recommendation: ${e.message}`); }
}

// ------------------------------------------------------------------ boot

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
    $("mode").textContent = S.cfg.llm_mode === "mock"
      ? "Mock mode: reply drafts are templates built from computed records. No AI model is called."
      : `Reply drafts use Vultr Serverless Inference${S.cfg.model ? " (" + S.cfg.model + ")" : ""}; all numbers are computed by rules.`;
  } catch (e) { S.cfg = { llm_mode: "mock" }; }
  $("role-ta").addEventListener("click", () => setRole("ta"));
  $("role-professor").addEventListener("click", () => setRole("professor"));
  $("reset").addEventListener("click", async () => {
    if (!confirm("Reset all demo data? This deletes recorded decisions, drafts and merges and restores the synthetic cases.")) return;
    try {
      await api("/api/demo/reset?confirm=true", { method: "POST" });
      S.detail = null; S.ui = { caseId: null, note: "", counted: "", body: null };
      S.notice = { kind: "info", title: "Demo data reset.", text: "The synthetic cases were restored." };
      if (location.hash !== "#/queue") { S.hash = "#/queue"; location.hash = "#/queue"; } else render();
    } catch (e) { S.notice = { kind: "error", title: "Reset failed.", text: e.message }; render(); }
  });
  window.addEventListener("hashchange", () => {
    if (S.ignoreHash) { S.ignoreHash = false; return; }
    if (!confirmDiscard("leave this page")) { S.ignoreHash = true; location.hash = S.hash; return; }
    S.hash = location.hash || "#/queue";
    S.notice = null;
    render();
  });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("unhandledrejection", (e) => {
    const text = String((e.reason && e.reason.message) || e.reason);
    S.notice = { kind: "error", title: "Something went wrong.", text };
    say(text);
  });
  S.hash = location.hash || "#/queue";
  render();
}
boot();
