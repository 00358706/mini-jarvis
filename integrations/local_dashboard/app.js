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

function conn() {
  const baseUrl = $("baseUrl").value.trim() || "http://127.0.0.1:8000";
  const apiKey = apiKeyMemory || "";
  return { baseUrl, apiKey };
}

async function apiFetch(method, path, body) {
  const { baseUrl, apiKey } = conn();
  if (!apiKey && path !== "/health") {
    const err = new Error("Missing API key");
    err.response = { error: "missing_api_key", message: "Set API key (memory only) before calling authenticated endpoints." };
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
    const compact = await apiFetch("GET", `/workspaces/${state}/${encodeURIComponent(planId)}/compact`);
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
  )
    return;
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
  )
    return;
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
  )
    return;
  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/reject`, {
      reason: "rejected via local_dashboard (client)",
    });
    setOut("outLifecycle", `Rejected.\n\n${capText(pretty(resp), 3000)}`);
  } catch (e) {
    setOut("outLifecycle", formatError(e));
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
}

init();

