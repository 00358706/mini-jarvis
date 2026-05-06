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

function conn() {
  const baseUrl = $("baseUrl").value.trim() || "http://127.0.0.1:8000";
  const apiKey = $("apiKey").value;
  return { baseUrl, apiKey };
}

async function apiFetch(method, path, body) {
  const { baseUrl, apiKey } = conn();
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
    const err = new Error(`HTTP ${resp.status}`);
    err.response = json;
    throw err;
  }
  return json;
}

function setOut(id, value) {
  $(id).textContent = value;
}

function setStatusPill(ok, outId, prefix) {
  const el = $(outId);
  const title = ok ? "OK" : "ERROR";
  el.textContent = `${prefix}${title}\n\n${el.textContent}`;
}

async function onHealth() {
  setOut("outConn", "");
  try {
    const h = await apiFetch("GET", "/health");
    setOut("outConn", pretty(h));
  } catch (e) {
    setOut("outConn", `${e.message}\n\n${pretty(e.response ?? {})}`);
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
    setOut("outConn", `${e.message}\n\n${pretty(e.response ?? {})}`);
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
    setOut("outPropose", pretty(proposal));
    if (proposal?.plan_id) $("planId").value = proposal.plan_id;
  } catch (e) {
    setOut("outPropose", `${e.message}\n\n${pretty(e.response ?? {})}`);
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
    setOut("outReview", pretty(compact));
  } catch (e) {
    setOut("outReview", `${e.message}\n\n${pretty(e.response ?? {})}`);
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
    setOut("outReview", `${e.message}\n\n${pretty(e.response ?? {})}`);
  }
}

async function onApprove() {
  setOut("outLifecycle", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outLifecycle", "plan_id is required");
    return;
  }
  if (!window.confirm(`Approve plan ${planId}?\n\nThis does NOT execute tools.`)) return;
  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/approve`);
    setOut(
      "outLifecycle",
      `Approved.\n\nNext step (separate explicit click): Execute.\n\n${pretty(resp)}`,
    );
  } catch (e) {
    setOut("outLifecycle", `${e.message}\n\n${pretty(e.response ?? {})}`);
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
      `Execute plan ${planId}?\n\nThis is a separate explicit action and only works after approval.`,
    )
  )
    return;
  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/execute`);
    setOut("outLifecycle", `Executed.\n\n${pretty(resp)}`);
  } catch (e) {
    setOut("outLifecycle", `${e.message}\n\n${pretty(e.response ?? {})}`);
  }
}

async function onReject() {
  setOut("outLifecycle", "");
  const planId = $("planId").value.trim();
  if (!planId) {
    setOut("outLifecycle", "plan_id is required");
    return;
  }
  if (!window.confirm(`Reject plan ${planId}?\n\nThis does NOT execute tools.`)) return;
  try {
    const resp = await apiFetch("POST", `/plans/${encodeURIComponent(planId)}/reject`, {
      reason: "rejected via local_dashboard (client)",
    });
    setOut("outLifecycle", `Rejected.\n\n${pretty(resp)}`);
  } catch (e) {
    setOut("outLifecycle", `${e.message}\n\n${pretty(e.response ?? {})}`);
  }
}

function init() {
  $("baseUrl").value = "http://127.0.0.1:8000";
  $("message").value = "list project files";

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

