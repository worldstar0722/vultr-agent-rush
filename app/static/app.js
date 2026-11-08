// GradeCase UI: Case Queue, Evidence View, Decision Desk. No build step.
// All text is inserted with textContent / createTextNode, never innerHTML.

const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
};

const state = { role: "ta", cfg: null, detail: null, msg: null, filters: {} };
try { state.role = localStorage.getItem("gc_role") || "ta"; } catch (e) { /* storage blocked */ }

async function api(path, opts = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : JSON.stringify(d) || `HTTP ${resp.status}`);
  }
  return data;
}

const num = (n) => (n == null ? "-" : Number.isInteger(n) ? String(n) : n.toFixed(2));
const when = (ts) => {
  if (!ts) return "-";
  const tz = ts.endsWith("+00:00") ? " UTC" : ts.endsWith("-07:00") ? " (UTC-7)" : "";
  return ts.slice(0, 16).replace("T", " ") + tz;
};
const slug = (s) => s.toLowerCase().replace(/[^a-z]+/g, "-");
const pill = (status) => h("span", { class: `pill s-${slug(status)}` }, status);
const ids = (list) => (list || []).filter(Boolean).map((i) => h("span", { class: "id" }, `[${i}] `));

// ------------------------------------------------------------------ chrome

function setRole(role) {
  state.role = role;
  try { localStorage.setItem("gc_role", role); } catch (e) { /* ignore */ }
  document.getElementById("role-ta").classList.toggle("on", role === "ta");
  document.getElementById("role-professor").classList.toggle("on", role === "professor");
  route();
}

function renderNav(caseId, screen) {
  const nav = document.getElementById("nav");
  const link = (label, href, active, disabled) =>
    h("a", { href, class: (active ? "active " : "") + (disabled ? "disabled" : "") }, label);
  nav.replaceChildren(
    link("Case Queue", "#/queue", screen === "queue"),
    link("Evidence View", caseId ? `#/case/${caseId}/evidence` : "#", screen === "evidence", !caseId),
    link("Decision Desk", caseId ? `#/case/${caseId}/decision` : "#", screen === "decision", !caseId),
  );
}

async function route() {
  const view = document.getElementById("view");
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "case" && parts[1]) {
      const screen = parts[2] === "decision" ? "decision" : "evidence";
      renderNav(parts[1], screen);
      if (!state.detail || state.detail.case.id !== parts[1]) {
        state.msg = null;
        state.detail = await api(`/api/cases/${parts[1]}`);
      }
      if (screen === "decision" && !state.detail.draft) {
        state.detail = await api(`/api/cases/${parts[1]}/draft`, { method: "POST" });
      }
      view.replaceChildren(screen === "decision" ? decisionView() : evidenceView());
    } else {
      renderNav(null, "queue");
      state.detail = null;
      view.replaceChildren(await queueView());
    }
  } catch (e) {
    view.replaceChildren(h("div", { class: "msg error" }, `Error: ${e.message}`));
  }
}

// ------------------------------------------------------------------ queue

async function queueView() {
  const cases = await api("/api/cases");
  const f = state.filters;
  const uniq = (xs) => [...new Set(xs)].sort();
  const select = (key, label, options) =>
    h("label", {}, label,
      h("select", { onchange: (e) => { f[key] = e.target.value; route(); } },
        h("option", { value: "" }, "All"),
        options.map((o) => h("option", { value: o, selected: f[key] === o }, o))));

  const shown = cases.filter((c) =>
    (!f.status || c.status === f.status) &&
    (!f.owner || (c.owner || "Unassigned") === f.owner) &&
    (!f.channel || c.channels.includes(f.channel)) &&
    (!f.dup || c.duplicates.length));

  const dups = new Map();
  cases.forEach((c) => c.duplicates.forEach((d) => dups.set(d.id, { ...d, a: c.id })));

  const strip = [...dups.values()].map((d) =>
    h("div", { class: "dup" },
      h("span", {}, h("strong", {}, "Possible duplicate: "), `${d.a} and ${d.other}. ${d.reason}. `,
        "Not merged until a person confirms."),
      h("button", { class: "primary", onclick: () => resolveDup(d.id, true) }, "Confirm merge"),
      h("button", { onclick: () => resolveDup(d.id, false) }, "Not a duplicate")));

  return h("div", {},
    h("h2", {}, "Case Queue"),
    state.msg && h("div", { class: "msg" }, state.msg),
    strip,
    h("div", { class: "filters" },
      select("status", "Status ", ["New", "TA review", "Awaiting professor", "Awaiting student info", "Closed"]),
      select("owner", "Owner ", uniq(cases.map((c) => c.owner || "Unassigned"))),
      select("channel", "Channel ", uniq(cases.flatMap((c) => c.channels))),
      h("label", {}, h("input", { type: "checkbox", checked: !!f.dup,
        onchange: (e) => { f.dup = e.target.checked; route(); } }), "Duplicate candidates only")),
    h("table", {},
      h("thead", {}, h("tr", {}, ["Case", "Student", "Assignment", "Issue", "Status", "Owner",
        "Last reply", "Waiting reason", "Flags"].map((t) => h("th", {}, t)))),
      h("tbody", {}, shown.map(queueRow), !shown.length && h("tr", {}, h("td", { colspan: 9 }, "No cases match.")))));
}

function queueRow(c) {
  const reply = c.last_reply ? `${c.last_reply.channel} by ${c.last_reply.by}, ${when(c.last_reply.ts)}` : "No reply yet";
  return h("tr", { class: "click", onclick: () => { location.hash = `#/case/${c.id}/evidence`; } },
    h("td", { class: "id" }, c.id),
    h("td", { class: "id" }, c.student_id),
    h("td", {}, `${c.assignment} (${c.course})`),
    h("td", {}, c.issue.replace("_", " ")),
    h("td", {}, pill(c.status)),
    h("td", {}, c.owner || "Unassigned"),
    h("td", {}, reply),
    h("td", {}, c.waiting_reason),
    h("td", {},
      c.duplicates.length ? h("span", { class: "badge solid" }, "Duplicate candidate") : null,
      c.insufficient_evidence ? h("span", { class: "badge" }, "Insufficient evidence") : null,
      c.on_hold ? h("span", { class: "badge" }, "On hold") : null));
}

async function resolveDup(id, confirm) {
  try {
    await api(`/api/duplicates/${id}/${confirm ? "confirm" : "dismiss"}`, { method: "POST", body: { role: state.role } });
    state.msg = confirm ? "Cases merged and logged." : "Marked as not a duplicate.";
  } catch (e) { state.msg = `Error: ${e.message}`; }
  route();
}

// ------------------------------------------------------------------ shared header

function caseHeader(d) {
  const c = d.case;
  return h("section", { class: "panel" },
    h("h2", {}, `${c.id}: ${c.assignment_name} (${c.course})`),
    h("div", {}, pill(c.status), " ",
      h("span", { class: "muted" }, ` student `), h("span", { class: "id" }, c.student_id),
      h("span", { class: "muted" }, `  owner `), c.owner || "Unassigned",
      h("span", { class: "muted" }, `  issue `), c.issue.replace("_", " ")),
    h("div", { class: "muted small" }, "Waiting: " + c.waiting_reason),
    c.duplicates.map((x) => h("div", { class: "dup" },
      `Possible duplicate of ${x.other}: ${x.reason}.`,
      h("a", { href: "#/queue" }, "Review in queue"))));
}

// ------------------------------------------------------------------ evidence view

function evidenceView() {
  const d = state.detail, a = d.analysis, s = a.score_state;
  return h("div", {},
    caseHeader(d),
    h("section", { class: "panel" }, h("h3", {}, "Warnings from the rule engine"),
      a.warnings.length
        ? h("ul", { class: "warn-list" }, a.warnings.map((w) => h("li", {}, w.text, " ", ids(w.evidence_ids))))
        : h("div", { class: "muted" }, "No warnings.")),
    h("div", { class: "grid2" }, attemptsPanel(a), scorePanel(s)),
    h("div", { class: "grid2" }, policyPanel(d), reviewPanel(d)),
    timelinePanel(d.evidence));
}

function attemptsPanel(a) {
  const dl = a.deadline;
  return h("section", { class: "panel" }, h("h3", {}, "Submission vs deadline"),
    h("div", {}, "Submission state: ", h("strong", {}, a.submission_state.replace("_", " "))),
    dl && h("div", {}, "Deadline: ", when(dl.ts), " ", ids([dl.ref_id])),
    h("table", {},
      h("thead", {}, h("tr", {}, ["Attempt", "Time", "State", "vs deadline", "Counted"].map((t) => h("th", {}, t)))),
      h("tbody", {}, a.attempts.map((t) => h("tr", {},
        h("td", { class: "id" }, t.ref_id), h("td", {}, when(t.ts)), h("td", {}, t.state.replace("_", " ")),
        h("td", { class: t.late ? "late" : "" },
          t.minutes_vs_deadline == null ? "-" :
          t.minutes_vs_deadline > 0 ? `${t.minutes_vs_deadline} min late` : `${-t.minutes_vs_deadline} min early`),
        h("td", {}, t.counted ? "Yes (policy default: newest)" : "")))),
      !a.attempts.length && h("tbody", {}, h("tr", {}, h("td", { colspan: 5 }, "No attempts recorded.")))));
}

function scorePanel(s) {
  const row = (label, val, src, cls) => h("tr", {},
    h("td", {}, label), h("td", { class: "num " + (cls || "") }, val), h("td", {}, ids(src)));
  const rubricIds = s.rubric_rows.map((r) => r.ref_id);
  const scoreId = s.evidence_ids.filter((i) => i.startsWith("SCORE"));
  return h("section", { class: "panel" }, h("h3", {}, "Score state (computed by code)"),
    h("table", {},
      h("thead", {}, h("tr", {}, ["Item", "Value", "Source"].map((t) => h("th", {}, t)))),
      h("tbody", {},
        row("Rubric total", `${num(s.rubric_total)} of ${num(s.rubric_max)}`, rubricIds),
        row("Late deduction recorded", num(s.late_deduction_applied), scoreId),
        row("Late deduction expected by policy", num(s.expected_deduction), [s.basis && s.basis.attempt]),
        row("Final score (rubric - expected deduction)", num(s.expected_final), []),
        row("Entered score", num(s.entered), scoreId),
        row("Posted score", num(s.posted), scoreId),
        row("Graded / posted", `${s.graded ? "graded" : "not graded"} / ${s.posted == null ? "not posted" : "posted"}`, scoreId))),
    h("h3", { style: "margin-top:10px" }, "Differences"),
    s.differences.length
      ? s.differences.map((x) => h("div", { class: "flag" }, x.text, " ", ids(x.evidence_ids)))
      : h("div", { class: "muted" }, "No differences found by the rules."),
    s.rubric_rows.length > 0 && h("details", {}, h("summary", {}, "Rubric rows"),
      h("table", {}, s.rubric_rows.map((r) => h("tr", {},
        h("td", { class: "id" }, r.ref_id), h("td", {}, r.label), h("td", { class: "num" }, `${r.awarded} of ${r.max}`))))),
    s.scenarios.length > 1 && h("div", { class: "muted small", style: "margin-top:8px" },
      "Computed what-if per attempt (information only, nothing is applied): ",
      s.scenarios.map((x) => `${x.attempt}: deduction ${num(x.deduction)}, final ${num(x.final)}. `)));
}

function policyPanel(d) {
  const a = d.analysis;
  const pol = d.evidence.find((e) => e.source_type === "policy");
  const apr = d.evidence.filter((e) => e.source_type === "approval");
  return h("section", { class: "panel" }, h("h3", {}, "Policy and approval evidence"),
    pol
      ? h("div", {}, h("span", { class: "id" }, pol.ref_id), " (version ", a.policy.version, ")",
          h("div", { class: "src-label" }, "Source text"), h("div", { class: "src" }, pol.source_text))
      : h("div", { class: "flag" }, `Policy ${a.policy.version || "(none)"} not found in the records.`),
    h("h3", { style: "margin-top:10px" }, "Professor approvals"),
    apr.length
      ? apr.map((e) => h("div", {}, h("span", { class: "id" }, e.ref_id), " ", when(e.ts), ": ", e.summary,
          e.source_text && ` - "${e.source_text}"`))
      : h("div", { class: "flag" }, "Insufficient evidence: no professor approval on file."));
}

function reviewPanel(d) {
  return h("section", { class: "panel" }, h("h3", {}, "Review items"),
    d.review_items.length
      ? h("ul", { class: "claims" }, d.review_items.map((r) => h("li", {},
          h("strong", {}, r.title), ` (route: ${r.route_to}, ${r.status}) `, ids(r.evidence_ids))))
      : h("div", { class: "muted" }, "None."),
    h("h3", { style: "margin-top:10px" }, "Rule-based suggestion"),
    h("div", {}, h("strong", {}, d.analysis.suggested_action.replace("_", " ")),
      ` (route: ${d.analysis.route.replace("_", " ")})`),
    h("ul", { class: "claims" }, d.analysis.reasons.map((r) => h("li", {}, r))));
}

function timelinePanel(evidence) {
  return h("section", { class: "panel" }, h("h3", {}, "Evidence timeline (time order, each with a source id)"),
    h("ol", { class: "timeline" }, evidence.map((e) => h("li", {},
      h("div", {}, when(e.ts)),
      h("div", {}, h("div", { class: "id" }, e.ref_id), h("div", { class: "type" }, e.source_type.replace("_", " "))),
      h("div", {}, e.summary,
        e.source_text && h("div", {}, h("div", { class: "src-label" }, "Source text"), h("div", { class: "src" }, e.source_text)))))));
}

// ------------------------------------------------------------------ decision desk

const ACTION_LABEL = { approve: "Approve", hold: "Hold", reject: "Reject",
  escalate: "Escalate to professor", request_info: "Request student info" };

function decisionView() {
  const d = state.detail, a = d.analysis, perms = d.permissions[state.role], dr = d.draft;
  const note = h("textarea", { rows: 2, id: "note", placeholder: "Note (required except for Approve)" });
  const attemptItem = d.review_items.some((r) => r.kind === "attempt_basis" && r.status === "open");
  const attemptSel = attemptItem && h("label", {}, "Counted attempt ",
    h("select", { id: "counted" }, h("option", { value: "" }, "Select..."),
      a.attempts.filter((t) => t.state === "submitted").map((t) => h("option", { value: t.ref_id }, `${t.ref_id} (${when(t.ts)})`))));
  const body = h("textarea", { rows: 12, id: "body" }, dr ? (dr.body_edited ?? dr.body_ai) : "");
  const flagBox = h("div", { id: "liveflags" });
  let timer;
  body.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await api(`/api/cases/${d.case.id}/draft/check`, { method: "POST", body: { body: body.value } });
      flagBox.replaceChildren(...r.flags.map(flagEl));
    }, 400);
  });

  const act = (name) => {
    const p = perms[name];
    return h("div", { class: "act" },
      h("button", { class: name === "approve" ? "primary" : name === "escalate" ? "warn" : "", disabled: !p.enabled,
        title: p.reason, onclick: () => submit(name, note, body, attemptSel) }, ACTION_LABEL[name]),
      h("span", { class: "muted small" }, `-> ${p.next_status}`));
  };
  const why = [...new Set(Object.values(perms).filter((p) => !p.enabled).map((p) => p.reason))];
  const sc = d.score_control;

  return h("div", {},
    caseHeader(d),
    state.msg && h("div", { class: state.msg.startsWith("Error") ? "msg error" : "msg" }, state.msg),
    h("div", { class: "grid2" },
      h("section", { class: "panel" }, h("h3", {}, "Suggested action (rules)"),
        h("div", {}, h("strong", {}, a.suggested_action.replace("_", " ")), `  route: ${a.route.replace("_", " ")}`),
        h("ul", { class: "claims" }, a.reasons.map((r) => h("li", {}, r))),
        h("div", { class: "muted small" }, "Uncertainty: " + (a.uncertainty.join(" ") || "none identified")),
        h("h3", { style: "margin-top:10px" }, "Decision"),
        h("div", {}, "Current status: ", pill(d.case.status), `   acting as ${state.role === "ta" ? "TA" : "Professor"} (demo role)`),
        attemptSel, note,
        h("div", { class: "actions" }, ["approve", "hold", "reject", "escalate", "request_info"].map(act)),
        why.length > 0 && h("div", { class: "muted small" }, why.map((w) => h("div", {}, w))),
        h("h3", { style: "margin-top:10px" }, "Score change"),
        h("button", { disabled: !sc.enabled, title: sc.reason, onclick: recordScore }, "Apply score change (records a recommendation)"),
        h("div", { class: "muted small" }, sc.recorded ? sc.recorded.rationale :
          (a.score_change ? `Professor approval exists. Recommendation would be ${num(a.score_change.from)} -> ${num(a.score_change.to)}. No Canvas write.` :
            (sc.reason || "Nothing to recommend. No Canvas write.")))),
      h("section", { class: "panel" },
        h("h3", {}, "Reply draft ", h("span", { class: "drafttag" }, "Draft only - not sent")),
        aiStatus(d, dr),
        body, flagBox,
        h("div", { class: "actions" },
          h("button", { onclick: saveDraft }, "Save edits"),
          h("button", { onclick: regenerate }, "Regenerate draft")),
        dr && claimList("Verified facts (cited)", dr.verified),
        dr && claimList("Unverified (not confirmed by records)", dr.unverified),
        dr && dr.flags.length > 0 && h("div", {}, h("h3", {}, "Guardrail flags"), dr.flags.map(flagEl)))),
    logPanel(d));
}

function aiStatus(d, dr) {
  if (!dr) return h("div", { class: "muted" }, "No draft yet.");
  const t = dr.ai_status === "unavailable" ? "AI unavailable, rules-only view (template draft from computed values)."
    : dr.ai_status === "mock" ? "Mock AI (offline, deterministic). No model was called."
    : "Drafted by the configured inference model; checked by guardrails.";
  return h("div", { class: dr.ai_status === "unavailable" ? "flag" : "muted small" }, t);
}

const flagEl = (f) => h("div", { class: "flag" }, f.message, f.code_value != null && h("strong", {}, `  Code value: ${f.code_value}`));

function claimList(title, claims) {
  return h("div", {}, h("h3", { style: "margin-top:8px" }, title),
    claims.length ? h("ul", { class: "claims" }, claims.map((c) => h("li", {}, c.text, " ", ids(c.evidence_ids),
      (c.flags || []).filter((f) => f.kind === "needs_verification").map((f) => h("span", { class: "badge solid" }, `Needs verification (code: ${f.code_value})`)))))
      : h("div", { class: "muted" }, "None."));
}

function logPanel(d) {
  return h("section", { class: "panel" }, h("h3", {}, "Decision log"),
    d.decisions.length
      ? h("table", {},
          h("thead", {}, h("tr", {}, ["Time (UTC)", "Who", "Role", "Action", "Status change", "Note"].map((t) => h("th", {}, t)))),
          h("tbody", {}, d.decisions.map((x) => h("tr", {},
            h("td", {}, when(x.ts)), h("td", {}, x.actor), h("td", {}, x.role), h("td", {}, x.action.replace(/_/g, " ")),
            h("td", {}, x.from_status ? `${x.from_status} -> ${x.to_status}` : "-"), h("td", {}, x.note)))))
      : h("div", { class: "muted" }, "No decisions yet."));
}

async function reload(message) {
  state.msg = message;
  state.detail = await api(`/api/cases/${state.detail.case.id}`);
  route();
}

async function submit(action, note, body, attemptSel) {
  try {
    const counted = attemptSel ? document.getElementById("counted").value : null;
    const out = await api(`/api/cases/${state.detail.case.id}/decision`, { method: "POST",
      body: { role: state.role, action, note: note.value, counted_attempt: counted || null, body: body.value } });
    state.detail = out;
    state.msg = `Recorded: ${ACTION_LABEL[action]}. Status is now ${out.case.status}. Nothing was sent.`;
  } catch (e) { state.msg = `Error: ${e.message}`; }
  route();
}

async function saveDraft() {
  try {
    state.detail = await api(`/api/cases/${state.detail.case.id}/draft`, { method: "PUT", body: { body: document.getElementById("body").value } });
    state.msg = "Draft edits saved (not sent).";
  } catch (e) { state.msg = `Error: ${e.message}`; }
  route();
}

async function regenerate() {
  try {
    state.detail = await api(`/api/cases/${state.detail.case.id}/draft`, { method: "POST" });
    state.msg = "Draft regenerated.";
  } catch (e) { state.msg = `Error: ${e.message}`; }
  route();
}

async function recordScore() {
  try {
    state.detail = await api(`/api/cases/${state.detail.case.id}/score-recommendation`, { method: "POST", body: { role: state.role } });
    state.msg = "Score recommendation recorded. No change was made in Canvas.";
  } catch (e) { state.msg = `Error: ${e.message}`; }
  route();
}

// ------------------------------------------------------------------ boot

async function boot() {
  state.cfg = await api("/api/config");
  document.getElementById("name").textContent = state.cfg.product_name;
  document.getElementById("tagline").textContent = state.cfg.product_tagline;
  document.getElementById("banner").textContent = state.cfg.banner;
  document.title = state.cfg.product_name;
  document.getElementById("mode").textContent = state.cfg.llm_mode === "mock"
    ? "AI: mock mode (offline, deterministic). Rules compute all numbers."
    : `AI: Vultr Serverless Inference${state.cfg.model ? " (" + state.cfg.model + ")" : ""}. Rules compute all numbers.`;
  document.getElementById("role-ta").addEventListener("click", () => setRole("ta"));
  document.getElementById("role-professor").addEventListener("click", () => setRole("professor"));
  document.getElementById("reset").addEventListener("click", async () => {
    if (!confirm("Reset all demo data (cases, decisions, drafts)?")) return;
    await api("/api/demo/reset?confirm=true", { method: "POST" });
    state.detail = null; state.msg = "Demo data reset.";
    location.hash = "#/queue"; route();
  });
  window.addEventListener("hashchange", () => { state.msg = null; route(); });
  setRole(state.role);
}
boot();
