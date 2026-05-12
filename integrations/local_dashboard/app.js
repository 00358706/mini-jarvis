/* global window, document, fetch */

function $(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

function capText(text, maxChars) {
  const t = (text ?? "").toString();
  if (t.length <= maxChars) return t;
  return `${t.slice(0, maxChars)}\n… (truncated)`;
}

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

let apiKeyMemory = "";
let automationLabIndex = null;

function conn() {
  const baseUrl = $("baseUrl").value.trim() || "http://127.0.0.1:8000";
  const apiKey = apiKeyMemory || "";
  return { baseUrl, apiKey };
}

async function apiFetch(method, path, body) {
  const { baseUrl, apiKey } = conn();
  if (!apiKey && path !== "/health") {
    const err = new Error("Missing API key");
    err.response = {
      error: "missing_api_key",
      message: "Set API key (memory only) before calling authenticated endpoints.",
    };
    throw err;
  }

  const resp = await fetch(`/api${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Target-Base-Url": baseUrl,
      "X-API-Key": apiKey,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }

  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status} ${resp.statusText || ""}`.trim());
    err.response = json;
    throw err;
  }
  return json;
}

async function localJsonFetch(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = { raw: text };
  }

  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status} ${resp.statusText || ""}`.trim());
    err.response = json;
    throw err;
  }
  return json;
}

async function localTextFetch(path) {
  const resp = await fetch(path, { method: "GET" });
  const text = await resp.text();
  if (!resp.ok) {
    const err = new Error(`HTTP ${resp.status} ${resp.statusText || ""}`.trim());
    try {
      err.response = JSON.parse(text);
    } catch {
      err.response = { raw: text };
    }
    throw err;
  }
  return text;
}

function setOut(id, value) {
  $(id).textContent = capText(value, 6000);
}

function formatError(e) {
  const details = e?.response ?? {};
  const msg = e?.message ? e.message : "Unknown error";
  const hint =
    details?.error === "proxy_forbidden"
      ? "Hint: the local proxy blocks this path/method by design."
      : details?.error === "Invalid or missing X-API-Key header."
        ? "Hint: check API key (gateway rejects invalid keys)."
        : "";
  return `${msg}\n${hint ? `\n${hint}\n` : "\n"}${pretty(details)}`;
}

async function onHealth() {
  setOut("outConn", "");
  try {
    const h = await apiFetch("GET", "/health");
    setOut("outConn", pretty(h));
  } catch (e) {
    setOut("outConn", formatError(e));
  }
}

async function onPending() {
  setOut("outConn", "");
  try {
    const pending = await apiFetch("GET", "/plans/pending");
    setOut("outConn", pretty(pending));
    const plans = Array.isArray(pending?.plans) ? pending.plans : [];
    if (plans.length > 0 && !$("planId").value.trim()) {
      $("planId").value = plans[0];
    }
  } catch (e) {
    setOut("outConn", formatError(e));
  }
}

async function onPropose() {
  setOut("outPropose", "");
  try {
    const planId = `ui_dash_${new Date().toISOString().replace(/[:.]/g, "")}`;
    const body = {
      message: $("message").value.trim() || "list project files",
      agent: $("agent").value,
      plan_id: planId,
    };
    const proposal = await apiFetch("POST", "/plans/from-message", body);
    setOut("outPropose", capText(pretty(proposal), 4000));
    if (proposal?.plan_id) $("planId").value = proposal.plan_id;
  } catch (e) {
    setOut("outPropose", formatError(e));
  }
}

async function onShowCompact(state) {
  setOut("outReview", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outReview", "plan_id is required");
    return;
  }
  try {
    const compact = await apiFetch(
      "GET",
      `/workspaces/${state}/${encodeURIComponent(planId)}/compact`,
    );
    setOut("outReview", capText(pretty(compact), 5000));
  } catch (e) {
    setOut("outReview", formatError(e));
  }
}

async function onShowResultPreview() {
  setOut("outReview", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outReview", "plan_id is required");
    return;
  }
  try {
    const fileObj = await apiFetch(
      "GET",
      `/workspaces/completed/${encodeURIComponent(planId)}/files/RESULT.md`,
    );
    const content = fileObj?.content ? capText(fileObj.content, 1200) : "(no content)";
    setOut(
      "outReview",
      `RESULT.md (preview, capped)\n\n${content}\n\n(meta)\n${pretty({ exists: fileObj?.exists })}`,
    );
  } catch (e) {
    setOut("outReview", formatError(e));
  }
}

async function onApprove() {
  setOut("outLifecycle", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outLifecycle", "plan_id is required");
    return;
  }
  if (
    !window.confirm(
      `Approve plan ${planId}?\n\nThis only marks the plan as approved.\nIt does NOT execute tools.\n\nYou must click Execute separately.`,
    )
  ) {
    return;
  }

  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/approve`);
    setOut(
      "outLifecycle",
      `Approved.\n\nNext step (separate explicit click): Execute.\n\n${capText(pretty(resp), 3000)}`,
    );
  } catch (e) {
    setOut("outLifecycle", formatError(e));
  }
}

async function onExecute() {
  setOut("outLifecycle", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outLifecycle", "plan_id is required");
    return;
  }
  if (
    !window.confirm(
      `Execute plan ${planId}?\n\nThis runs the approved plan through the gateway sandbox.\nIt is a separate explicit action and only works after approval.\n\nThis does NOT auto-approve.`,
    )
  ) {
    return;
  }

  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/execute`);
    setOut("outLifecycle", `Executed.\n\n${capText(pretty(resp), 5000)}`);
  } catch (e) {
    setOut("outLifecycle", formatError(e));
  }
}

async function onReject() {
  setOut("outLifecycle", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outLifecycle", "plan_id is required");
    return;
  }
  if (
    !window.confirm(
      `Reject plan ${planId}?\n\nThis only rejects the pending plan.\nIt does NOT execute tools.`,
    )
  ) {
    return;
  }

  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/reject`, {
      reason: "rejected via local_dashboard (client)",
    });
    setOut("outLifecycle", `Rejected.\n\n${capText(pretty(resp), 3000)}`);
  } catch (e) {
    setOut("outLifecycle", formatError(e));
  }
}

function populateLabArtifacts(index) {
  automationLabIndex = index;
  const select = $("labArtifact");
  select.innerHTML = "";
  const artifacts = Array.isArray(index?.artifacts) ? index.artifacts : [];
  for (const artifact of artifacts) {
    const option = document.createElement("option");
    option.value = artifact.filename;
    option.textContent = `${artifact.filename} (${artifact.kind})`;
    select.appendChild(option);
  }
}

async function loadLabIndex(requestId) {
  const index = await localJsonFetch(
    "GET",
    `/api/automation-lab/${encodeURIComponent(requestId)}/index`,
  );
  populateLabArtifacts(index);
  return index;
}

async function loadLabSummary(requestId) {
  return localTextFetch(`/api/automation-lab/${encodeURIComponent(requestId)}/summary`);
}

async function onLabGenerate() {
  setOut("outLabGenerate", "");
  setOut("outLabReview", "");
  setOut("outLabArtifact", "");
  try {
    const body = {
      message: $("labMessage").value.trim() || "Create a tool to list new Navidrome releases",
      use_fixture: $("labUseFixture").checked,
    };
    const response = await localJsonFetch("POST", "/api/automation-lab/generate", body);
    const result = response?.result || {};
    if (result.request_id) $("labRequestId").value = result.request_id;
    if (response?.index) populateLabArtifacts(response.index);
    setOut(
      "outLabGenerate",
      [
        `request_id: ${result.request_id || "(none)"}`,
        `output_dir: ${result.output_dir || "(none)"}`,
        `primary_capability_outcome: ${result.primary_capability_outcome || "(none)"}`,
        "",
        "Artifacts:",
        ...(Array.isArray(result.artifacts) ? result.artifacts.map((name) => `- ${name}`) : []),
      ].join("\n"),
    );
    if (response?.review_summary) {
      setOut("outLabReview", response.review_summary);
    }
  } catch (e) {
    setOut("outLabGenerate", formatError(e));
  }
}

async function onLabLoadIndex() {
  setOut("outLabReview", "");
  const requestId = $("labRequestId").value.trim();
  if (!requestId) {
    setOut("outLabReview", "request_id is required");
    return;
  }
  try {
    const index = await loadLabIndex(requestId);
    setOut("outLabReview", pretty(index));
  } catch (e) {
    setOut("outLabReview", formatError(e));
  }
}

async function onLabSummary() {
  setOut("outLabReview", "");
  const requestId = $("labRequestId").value.trim();
  if (!requestId) {
    setOut("outLabReview", "request_id is required");
    return;
  }
  try {
    const summary = await loadLabSummary(requestId);
    setOut("outLabReview", summary);
  } catch (e) {
    setOut("outLabReview", formatError(e));
  }
}

async function onLabViewArtifact() {
  setOut("outLabArtifact", "");
  const requestId = $("labRequestId").value.trim();
  if (!requestId) {
    setOut("outLabArtifact", "request_id is required");
    return;
  }
  try {
    if (!automationLabIndex) {
      await loadLabIndex(requestId);
    }
    const filename = $("labArtifact").value;
    if (!filename) {
      setOut("outLabArtifact", "Select an indexed artifact first.");
      return;
    }
    const artifact = await localJsonFetch(
      "GET",
      `/api/automation-lab/${encodeURIComponent(requestId)}/artifacts/${encodeURIComponent(
        filename,
      )}`,
    );
    setOut("outLabArtifact", `${artifact.filename}\n\n${capText(artifact.content, 6000)}`);
  } catch (e) {
    setOut("outLabArtifact", formatError(e));
  }
}

async function openRecentLabRun(requestId) {
  $("labRequestId").value = requestId;
  setOut("outLabReview", "");
  setOut("outLabArtifact", "");
  try {
    await loadLabIndex(requestId);
    const summary = await loadLabSummary(requestId);
    setOut("outLabReview", summary);
  } catch (e) {
    setOut("outLabReview", formatError(e));
  }
}

function renderRecentRuns(payload) {
  const list = $("labRecentList");
  list.innerHTML = "";
  const runs = Array.isArray(payload?.runs) ? payload.runs : [];
  for (const run of runs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "runitem";
    button.textContent = [
      run.request_id,
      run.created_at || "no timestamp",
      run.proposal_kind || "unknown",
      run.primary_capability_outcome || "unknown",
      `artifacts=${run.artifact_count ?? 0}`,
    ].join(" | ");
    button.addEventListener("click", () => openRecentLabRun(run.request_id));
    list.appendChild(button);
  }
  const skipped = Array.isArray(payload?.skipped) ? payload.skipped.length : 0;
  setOut("outLabRecent", `Recent runs: ${runs.length}\nSkipped entries: ${skipped}`);
}

async function onLabRecent() {
  setOut("outLabRecent", "");
  try {
    const recent = await localJsonFetch("GET", "/api/automation-lab/recent");
    renderRecentRuns(recent);
  } catch (e) {
    setOut("outLabRecent", formatError(e));
  }
}

function onSetKey() {
  const v = $("apiKey").value;
  apiKeyMemory = (v ?? "").toString();
  $("apiKey").value = "";
  if (!apiKeyMemory) {
    setOut("outConn", "API key cleared (memory).");
    return;
  }
  setOut("outConn", "API key set in memory. (Input field cleared; key is not stored.)");
}

function init() {
  $("baseUrl").value = "http://127.0.0.1:8000";
  $("message").value = "list project files";
  $("labMessage").value = "Create a tool to list new Navidrome releases";

  $("btnSetKey").addEventListener("click", onSetKey);
  $("btnHealth").addEventListener("click", onHealth);
  $("btnPending").addEventListener("click", onPending);
  $("btnPropose").addEventListener("click", onPropose);
  $("btnShowActive").addEventListener("click", () => onShowCompact("active"));
  $("btnShowCompleted").addEventListener("click", () => onShowCompact("completed"));
  $("btnShowResult").addEventListener("click", onShowResultPreview);
  $("btnApprove").addEventListener("click", onApprove);
  $("btnExecute").addEventListener("click", onExecute);
  $("btnReject").addEventListener("click", onReject);
  $("btnLabGenerate").addEventListener("click", onLabGenerate);
  $("btnLabLoadIndex").addEventListener("click", onLabLoadIndex);
  $("btnLabSummary").addEventListener("click", onLabSummary);
  $("btnLabViewArtifact").addEventListener("click", onLabViewArtifact);
  $("btnLabRecent").addEventListener("click", onLabRecent);
}

init();

