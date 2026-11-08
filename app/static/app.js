// Minimal UI: start a run, then render the SSE event log as a timeline.
// Uses textContent everywhere (never innerHTML) so event data can't inject markup.

const $ = (id) => document.getElementById(id);
let runId = null;
let source = null;

async function loadConfig() {
  const cfg = await (await fetch("/api/config")).json();
  $("name").textContent = cfg.product_name; // set via PRODUCT_NAME env / app/config.py
  $("tagline").textContent = cfg.product_tagline;
  document.title = cfg.product_name;
  $("modes").textContent =
    `LLM: ${cfg.llm_mode}${cfg.model ? " (" + cfg.model + ")" : ""} · sandbox: ${cfg.sandbox}`;
}

function describe(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "plan":
      return d.steps.map((s, i) => `${i + 1}. ${s.tool} - ${s.reason || ""}`).join("\n");
    case "tool_call":
      return `${d.tool}(${JSON.stringify(d.args)})  [attempt ${d.attempt}]`;
    case "tool_result":
      return `${d.ok ? "ok" : "failed"}: ${d.output || ""}`;
    case "verify":
      return `${d.ok ? "passed" : "not ok"} - ${d.reason}`;
    case "approval_requested":
      return `Waiting for a human: ${d.tool}(${JSON.stringify(d.args)})`;
    case "approval_granted":
      return `Approved: ${d.tool}`;
    case "approval_denied":
      return `Rejected (${d.by}): ${d.tool}`;
    case "blocked":
      return `CONTAINED: ${d.reason}`;
    case "error":
      return d.message;
    case "done":
      return `${d.summary} (completed ${d.completed}, blocked ${d.blocked}, skipped ${d.skipped})`;
    default:
      return JSON.stringify(d);
  }
}

function addEvent(ev) {
  const li = document.createElement("li");
  li.className = ev.type;
  const type = document.createElement("div");
  type.className = "type";
  type.textContent = ev.type.replace("_", " ");
  const body = document.createElement("div");
  body.className = "body";
  body.textContent = describe(ev);
  li.append(type, body);
  $("timeline").append(li);
  li.scrollIntoView({ block: "nearest" });

  if (ev.type === "approval_requested") {
    $("approval-text").textContent = body.textContent;
    $("approval").hidden = false;
  }
  if (["approval_granted", "approval_denied", "done", "error"].includes(ev.type)) {
    $("approval").hidden = true;
  }
}

async function startRun(task) {
  if (source) source.close();
  $("timeline").replaceChildren();
  $("approval").hidden = true;
  $("start").disabled = true;
  const resp = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
  });
  if (!resp.ok) {
    $("start").disabled = false;
    return alert("Could not start run: " + resp.status);
  }
  runId = (await resp.json()).id;
  source = new EventSource(`/api/runs/${runId}/events`);
  source.onmessage = (m) => addEvent(JSON.parse(m.data));
  source.addEventListener("end", () => {
    source.close(); // without this the browser would reconnect forever
    $("start").disabled = false;
  });
}

async function decide(approved) {
  $("approval").hidden = true;
  await fetch(`/api/runs/${runId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
}

$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  startRun($("task").value.trim());
});
$("approve").addEventListener("click", () => decide(true));
$("reject").addEventListener("click", () => decide(false));
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => { $("task").value = c.dataset.task; }));

loadConfig();
