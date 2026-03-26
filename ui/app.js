const config = window.APP_CONFIG;

const playForm = document.getElementById("play-form");
const playButton = document.getElementById("scene-play-button");
const resetButton = document.getElementById("reset-button");
const sceneButton = document.getElementById("scene-button");
const graphButton = document.getElementById("graph-button");
const outputButton = document.getElementById("output-button");
const clearLogButton = document.getElementById("clear-log");
const finalOutput = document.getElementById("final-output");
const runState = document.getElementById("run-state");
const lastRun = document.getElementById("last-run");
const runIdLabel = document.getElementById("run-id-label");
const sceneStatus = document.getElementById("scene-status");
const flowStageTitle = document.getElementById("flow-stage-title");
const flowStageDetail = document.getElementById("flow-stage-detail");
const topologyActivity = document.getElementById("topology-activity");
const topologyActivityName = document.getElementById("topology-activity-name");
const traceTree = document.getElementById("trace-tree");
const presetOptions = document.getElementById("preset-options");
const scenarioOptions = document.getElementById("scenario-options");
const sceneModal = document.getElementById("scene-modal");
const outputModal = document.getElementById("output-modal");
const graphModal = document.getElementById("graph-modal");
const detailTitle = document.getElementById("detail-title");
const detailMeta = document.getElementById("detail-meta");
const detailSummary = document.getElementById("detail-summary");
const detailInput = document.getElementById("detail-input");
const detailOutput = document.getElementById("detail-output");

const nodes = {
  user: document.querySelector('[data-node="user"]'),
  ui: document.querySelector('[data-node="ui"]'),
  kong: document.querySelector('[data-node="kong"]'),
  orchestrator: document.querySelector('[data-node="orchestrator"]'),
  "support-agent": document.querySelector('[data-node="support-agent"]'),
  "success-agent": document.querySelector('[data-node="success-agent"]'),
  openai: document.querySelector('[data-node="openai"]'),
  gemini: document.querySelector('[data-node="gemini"]'),
  mcp: document.querySelector('[data-node="mcp"]'),
  "backend-api": document.querySelector('[data-node="backend-api"]'),
};

const lineMap = {
  "user-ui": document.getElementById("line-user-ui"),
  "ui-kong": document.getElementById("line-ui-kong"),
  "kong-orchestrator": document.getElementById("line-kong-orchestrator"),
  "kong-support": document.getElementById("line-kong-support"),
  "kong-success": document.getElementById("line-kong-success"),
  "kong-openai": document.getElementById("line-kong-openai"),
  "kong-gemini": document.getElementById("line-kong-gemini"),
  "kong-mcp": document.getElementById("line-kong-mcp"),
  "mcp-backend": document.getElementById("line-mcp-backend"),
};

let traceSocket;
let selectedTraceId = null;
let traceState = createInitialTraceState();
let mcpAnimationTimer = null;
let failoverResetTimer = null;
let llmSuccessTimer = null;
let pendingMcpActivationTimer = null;
let orchestratorLlmVisibleUntil = 0;
let failoverActivationTimer = null;
let activeScenario = "normal";

const scenePresets = {
  acme_default: {
    customer_id: "cust_acme",
    account_name: "Acme Health",
    issue_summary: "Customer reports a billing dispute and workflow-agent sync delays.",
    product_issue: "workflow agent sync delays",
    billing_issue: "billing overcharge on enterprise add-ons",
    incident_id: "INC-1007",
  },
  northwind_exports: {
    customer_id: "cust_northwind",
    account_name: "Northwind Logistics",
    issue_summary: "Customer reports invoice reconciliation errors and delayed connector export jobs.",
    product_issue: "connector job backlog delaying finance exports",
    billing_issue: "invoice reconciliation mismatch on enterprise exports",
    incident_id: "INC-2042",
  },
  contoso_peak: {
    customer_id: "cust_contoso",
    account_name: "Contoso Retail",
    issue_summary: "Customer reports duplicate usage billing and order automation queue delays during peak traffic.",
    product_issue: "workflow automation queue delays during peak traffic",
    billing_issue: "duplicate usage charges on premium connectors",
    incident_id: "INC-3099",
  },
};

document.querySelectorAll("[data-close-modal]").forEach((button) => {
  button.addEventListener("click", () => {
    const modal = document.getElementById(button.dataset.closeModal);
    modal?.close();
  });
});

function createInitialTraceState() {
  return {
    runId: null,
    scenario: "normal",
    rootIds: [],
    nodes: {},
    actorRoots: {},
    toolNodes: {},
    llmNodes: {},
    systemNodes: {},
  };
}

function labelForScenario(scenario) {
  const labels = {
    normal: "Normal",
    llm_failover: "LLM Failover",
    token_limit: "AI Token Limit",
    prompt_enhancement: "Prompt Decorator",
  };
  return labels[scenario] || "Normal";
}

function createTraceNode(id, level, title, summary, meta = {}) {
  return {
    id,
    level,
    title,
    summary,
    meta,
    input: undefined,
    output: undefined,
    timestamp: meta.timestamp || null,
    durationMs: meta.durationMs,
    status: meta.status || "active",
    children: [],
  };
}

function addTraceNode(node, parentId = null) {
  traceState.nodes[node.id] = node;
  if (parentId) {
    traceState.nodes[parentId].children.push(node.id);
  } else {
    traceState.rootIds.push(node.id);
  }
  if (!selectedTraceId) {
    selectedTraceId = node.id;
  }
}

function touchActivity(timestamp) {
  lastRun.textContent = formatTime(timestamp || new Date().toISOString());
}

function setRunState(state) {
  runState.textContent = state;
  sceneStatus.classList.toggle("live", state !== "idle");
}

function setFlowStage(title, detail) {
  flowStageTitle.textContent = title;
  flowStageDetail.textContent = detail;
}

function formatTime(value) {
  if (!value) {
    return "n/a";
  }
  return new Date(value).toLocaleTimeString();
}

function pretty(value) {
  if (value === undefined || value === null) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function applyScenePreset(presetId) {
  const preset = scenePresets[presetId];
  if (!preset) {
    return;
  }

  Object.entries(preset).forEach(([key, value]) => {
    const field = playForm.elements.namedItem(key);
    if (field) {
      field.value = value;
    }
  });
}

function applyScenarioChoice(scenario) {
  activeScenario = scenario || "normal";
  const hiddenField = playForm.elements.namedItem("governance_scenario");
  if (hiddenField) {
    hiddenField.value = activeScenario;
  }
}

function unwrapStructuredValue(value) {
  if (Array.isArray(value)) {
    if (value.length === 1 && value[0]?.type === "text" && typeof value[0]?.text === "string") {
      try {
        return JSON.parse(value[0].text);
      } catch {
        return value[0].text;
      }
    }
    return value.map((item) => unwrapStructuredValue(item));
  }
  if (value && typeof value === "object" && value.type === "text" && typeof value.text === "string") {
    try {
      return JSON.parse(value.text);
    } catch {
      return value.text;
    }
  }
  return value;
}

function renderDefinitionList(fields) {
  const rows = fields.filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!rows.length) {
    return `<p class="output-empty">No values available.</p>`;
  }
  return `
    <dl class="output-kv-list">
      ${rows
        .map(
          ([label, value]) => `
            <div class="output-kv-item">
              <dt>${escapeHtml(label)}</dt>
              <dd>${escapeHtml(value)}</dd>
            </div>
          `,
        )
        .join("")}
    </dl>
  `;
}

function renderBulletList(items) {
  const values = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!values.length) {
    return `<p class="output-empty">No items available.</p>`;
  }
  return `
    <ul class="output-bullets">
      ${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
    </ul>
  `;
}

function renderTextBlock(text) {
  if (!text) {
    return `<p class="output-empty">No text available.</p>`;
  }
  return `<div class="output-text-block">${escapeHtml(text)}</div>`;
}

function clearDetailPane() {
  detailTitle.textContent = "No step selected";
  detailSummary.textContent = "The selected trace step will show timing, request input, and output payload here.";
  detailInput.textContent = "-";
  detailOutput.textContent = "-";
  detailMeta.innerHTML = "";
  detailMeta.appendChild(makeMetaChip("Click a trace row"));
}

function makeMetaChip(label) {
  const chip = document.createElement("span");
  chip.className = "meta-chip";
  chip.textContent = label;
  return chip;
}

function updateSelectedDetail() {
  const node = selectedTraceId ? traceState.nodes[selectedTraceId] : null;
  if (!node) {
    clearDetailPane();
    return;
  }

  detailTitle.textContent = node.title;
  detailSummary.textContent = node.summary || "No summary available.";
  detailInput.textContent = pretty(node.input);
  detailOutput.textContent = pretty(node.output);
  detailMeta.innerHTML = "";

  const chips = [
    node.meta.actor ? makeMetaChip(labelForActor(node.meta.actor)) : null,
    node.meta.model ? makeMetaChip(node.meta.model) : null,
    node.timestamp ? makeMetaChip(formatTime(node.timestamp)) : null,
    node.durationMs !== undefined ? makeMetaChip(`${node.durationMs} ms`) : null,
    makeMetaChip(node.status),
  ].filter(Boolean);

  chips.forEach((chip) => detailMeta.appendChild(chip));
}

function renderTraceTree() {
  if (!traceState.rootIds.length) {
    traceTree.innerHTML = `
      <div class="trace-empty">
        <h3>No run yet</h3>
        <p>Press Play to stream the execution tree in real time.</p>
      </div>
    `;
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "trace-tree-list";

  const renderNode = (nodeId) => {
    const node = traceState.nodes[nodeId];
    const row = document.createElement("button");
    row.type = "button";
    row.className = `trace-row${selectedTraceId === nodeId ? " active" : ""}`;
    row.style.setProperty("--indent", `${node.level * 18}px`);
    row.addEventListener("click", () => {
      selectedTraceId = nodeId;
      renderTraceTree();
      updateSelectedDetail();
    });

    const title = document.createElement("span");
    title.className = "trace-row-title";
    title.textContent = node.title;

    const timeBadge = document.createElement("span");
    timeBadge.className = "trace-row-badge";
    timeBadge.textContent = node.timestamp ? formatTime(node.timestamp) : "--";

    const durationBadge = document.createElement("span");
    durationBadge.className = `trace-row-badge${node.status === "complete" ? " success" : node.status === "error" ? " warn" : ""}`;
    durationBadge.textContent = node.durationMs !== undefined ? `${node.durationMs} ms` : node.status;

    row.append(title, timeBadge, durationBadge);
    wrap.appendChild(row);

    node.children.forEach(renderNode);
  };

  traceState.rootIds.forEach(renderNode);
  traceTree.innerHTML = "";
  traceTree.appendChild(wrap);
}

function labelForActor(actor) {
  if (actor === "support-agent") {
    return "Support Agent";
  }
  if (actor === "success-agent") {
    return "Success Agent";
  }
  return "Orchestrator";
}

function ensureActorRoot(actor) {
  if (traceState.actorRoots[actor]) {
    return traceState.actorRoots[actor];
  }

  const rootId = `actor:${actor}`;
  const title = actor === "orchestrator" ? "Orchestrator called" : `${labelForActor(actor)} called`;
  const node = createTraceNode(rootId, 1, title, "Routed through Kong.", { actor });
  addTraceNode(node, "run");
  traceState.actorRoots[actor] = rootId;
  return rootId;
}

function upsertSystemNode(key, parentId, title, summary, payload) {
  let nodeId = traceState.systemNodes[key];
  if (!nodeId) {
    nodeId = `system:${key}`;
    traceState.systemNodes[key] = nodeId;
    const node = createTraceNode(nodeId, traceState.nodes[parentId].level + 1, title, summary, {
      actor: payload.actor,
      timestamp: payload.timestamp,
      durationMs: payload.duration_ms,
      status: payload.duration_ms !== undefined ? "complete" : "active",
    });
    addTraceNode(node, parentId);
  }

  const node = traceState.nodes[nodeId];
  node.timestamp = payload.timestamp || node.timestamp;
  node.durationMs = payload.duration_ms ?? node.durationMs;
  node.status = payload.duration_ms !== undefined ? "complete" : node.status;
  node.output = payload.tools || payload.output || node.output;
  return node;
}

function upsertToolNode(payload) {
  const parentId = ensureActorRoot(payload.actor || "orchestrator");
  const key = `${payload.actor}:${payload.tool}`;
  let nodeId = traceState.toolNodes[key];
  if (!nodeId) {
    nodeId = `tool:${key}`;
    traceState.toolNodes[key] = nodeId;
    const node = createTraceNode(
      nodeId,
      traceState.nodes[parentId].level + 1,
      `Tool invoked: ${payload.tool}`,
      "MCP tool call routed through Kong.",
      { actor: payload.actor, timestamp: payload.timestamp },
    );
    addTraceNode(node, parentId);
  }

  const node = traceState.nodes[nodeId];
  node.timestamp = payload.timestamp || node.timestamp;
  if (payload.input !== undefined) {
    node.input = payload.input;
  }
  if (payload.output !== undefined) {
    node.output = payload.output;
  }
  if (payload.duration_ms !== undefined) {
    node.durationMs = payload.duration_ms;
    node.status = "complete";
  }
  return node;
}

function upsertLlmNode(payload) {
  const actor = payload.actor || "orchestrator";
  const parentId = ensureActorRoot(actor);
  const key = `${actor}:${payload.stage}`;
  let nodeId = traceState.llmNodes[key];
  if (!nodeId) {
    nodeId = `llm:${key}`;
    traceState.llmNodes[key] = nodeId;
    const node = createTraceNode(
      nodeId,
      traceState.nodes[parentId].level + 1,
      `LLM call: ${payload.stage}`,
      "AI Proxy Advanced request routed through Kong.",
      { actor, timestamp: payload.timestamp },
    );
    addTraceNode(node, parentId);
  }

  const node = traceState.nodes[nodeId];
  node.timestamp = payload.timestamp || node.timestamp;
  if (payload.input !== undefined) {
    node.input = payload.input;
  }
  if (payload.output !== undefined) {
    node.output = payload.output;
  }
  if (payload.model) {
    node.meta.model = payload.model;
  }
  if (payload.duration_ms !== undefined) {
    node.durationMs = payload.duration_ms;
    node.status = "complete";
  }
  return node;
}

function resetTopology() {
  if (failoverResetTimer) {
    clearTimeout(failoverResetTimer);
    failoverResetTimer = null;
  }
  if (llmSuccessTimer) {
    clearTimeout(llmSuccessTimer);
    llmSuccessTimer = null;
  }
  if (pendingMcpActivationTimer) {
    clearTimeout(pendingMcpActivationTimer);
    pendingMcpActivationTimer = null;
  }
  if (failoverActivationTimer) {
    clearTimeout(failoverActivationTimer);
    failoverActivationTimer = null;
  }
  orchestratorLlmVisibleUntil = 0;
  Object.values(nodes).forEach((node) => node?.classList.remove("active", "complete", "error"));
  Object.values(lineMap).forEach((line) => line?.classList.remove("active", "complete", "error"));
  hideTopologyActivity();
}

function markNode(name, state) {
  const node = nodes[name];
  if (!node) {
    return;
  }
  if (state === "active") {
    node.classList.remove("complete", "error");
    node.classList.add("active");
  }
  if (state === "complete") {
    node.classList.remove("active", "error");
    node.classList.remove("complete");
  }
  if (state === "error") {
    node.classList.remove("active", "complete");
    node.classList.add("error");
  }
}

function markLine(name, state) {
  const line = lineMap[name];
  if (!line) {
    return;
  }
  if (state === "active") {
    line.classList.remove("complete", "error");
    line.classList.add("active");
  }
  if (state === "complete") {
    line.classList.remove("active", "error");
    line.classList.remove("complete");
  }
  if (state === "error") {
    line.classList.remove("active", "complete");
    line.classList.add("error");
  }
}

function showTopologyActivity(label) {
  topologyActivityName.textContent = label;
  topologyActivity.hidden = false;
}

function hideTopologyActivity() {
  topologyActivity.hidden = true;
  topologyActivityName.textContent = "-";
}

function activateActorPath(actor, state = "active") {
  markNode("kong", state);
  if (actor === "support-agent") {
    markNode("support-agent", state);
    markLine("kong-support", state);
    return;
  }
  if (actor === "success-agent") {
    markNode("success-agent", state);
    markLine("kong-success", state);
    return;
  }
  markNode("orchestrator", state);
  markLine("kong-orchestrator", state);
}

function activateToolPath(actor, state = "active") {
  activateActorPath(actor, state);
  markNode("mcp", state);
  markNode("backend-api", state);
  markLine("kong-mcp", state);
  markLine("mcp-backend", state);
}

function showModelFailure(model) {
  if (model === "openai") {
    markNode("openai", "error");
    markLine("kong-openai", "error");
    return;
  }
  if (model === "gemini") {
    markNode("gemini", "error");
    markLine("kong-gemini", "error");
  }
}

function resetModelPath(model, delayMs = 1200) {
  if (failoverResetTimer) {
    clearTimeout(failoverResetTimer);
    failoverResetTimer = null;
  }
  failoverResetTimer = window.setTimeout(() => {
    if (model === "openai") {
      markNode("openai", "complete");
      markLine("kong-openai", "complete");
    }
    if (model === "gemini") {
      markNode("gemini", "complete");
      markLine("kong-gemini", "complete");
    }
    failoverResetTimer = null;
  }, delayMs);
}

function showFailurePath(kind = "orchestrator") {
  markNode("ui", "error");
  markNode("kong", "error");
  markLine("ui-kong", "error");

  if (kind === "mcp") {
    markNode("orchestrator", "error");
    markNode("mcp", "error");
    markNode("backend-api", "error");
    markLine("kong-orchestrator", "error");
    markLine("kong-mcp", "error");
    markLine("mcp-backend", "error");
    return;
  }

  markNode("orchestrator", "error");
  markLine("kong-orchestrator", "error");

  if (kind === "openai") {
    showModelFailure("openai");
    return;
  }

  if (kind === "gemini") {
    showModelFailure("gemini");
  }
}

function setMcpPathState(state, lingerMs = 0) {
  if (mcpAnimationTimer) {
    clearTimeout(mcpAnimationTimer);
    mcpAnimationTimer = null;
  }
  if (pendingMcpActivationTimer) {
    clearTimeout(pendingMcpActivationTimer);
    pendingMcpActivationTimer = null;
  }

  if (state === "active") {
    const remainingVisibleMs = Math.max(0, orchestratorLlmVisibleUntil - Date.now());
    if (remainingVisibleMs > 0) {
      pendingMcpActivationTimer = window.setTimeout(() => {
        clearOrchestratorLlmPath();
        activateToolPath("orchestrator", "active");
        pendingMcpActivationTimer = null;
      }, remainingVisibleMs);
      return;
    }
    clearOrchestratorLlmPath();
    activateToolPath("orchestrator", "active");
    return;
  }

  activateToolPath("orchestrator", "active");
  mcpAnimationTimer = window.setTimeout(() => {
    activateToolPath("orchestrator", "complete");
    hideTopologyActivity();
    mcpAnimationTimer = null;
  }, lingerMs || 900);
}

function clearModelActiveState(model) {
  if (model === "openai") {
    nodes.openai?.classList.remove("active");
    lineMap["kong-openai"]?.classList.remove("active");
    return;
  }
  if (model === "gemini") {
    nodes.gemini?.classList.remove("active");
    lineMap["kong-gemini"]?.classList.remove("active");
  }
}

function setOrchestratorModelStates({ openai = "complete", gemini = "complete" } = {}) {
  markNode("openai", openai);
  markLine("kong-openai", openai);
  markNode("gemini", gemini);
  markLine("kong-gemini", gemini);
}

function markLlmPath(payload, state = "active") {
  activateActorPath(payload.actor || "orchestrator", state);
  const model = String(payload.model || "").toLowerCase();
  if (payload.actor === "orchestrator") {
    if (model.includes("gemini")) {
      clearModelActiveState("openai");
      markNode("gemini", state);
      markLine("kong-gemini", state);
      return;
    }
    clearModelActiveState("gemini");
    markNode("openai", state);
    markLine("kong-openai", state);
    return;
  }
  markNode("gemini", state);
  markLine("kong-gemini", state);
}

function lingerLlmSuccessPath(payload, delayMs = 1400) {
  if (llmSuccessTimer) {
    clearTimeout(llmSuccessTimer);
    llmSuccessTimer = null;
  }
  orchestratorLlmVisibleUntil = Date.now() + delayMs;
  markLlmPath(payload, "active");
  llmSuccessTimer = window.setTimeout(() => {
    markLlmPath(payload, "complete");
    orchestratorLlmVisibleUntil = 0;
    llmSuccessTimer = null;
  }, delayMs);
}

function clearOrchestratorLlmPath() {
  if (llmSuccessTimer) {
    clearTimeout(llmSuccessTimer);
    llmSuccessTimer = null;
  }
  orchestratorLlmVisibleUntil = 0;
  markNode("openai", "complete");
  markLine("kong-openai", "complete");
  markNode("gemini", "complete");
  markLine("kong-gemini", "complete");
}

function renderFinalOutput(result) {
  const executiveSummary = result.executive_brief?.summary || result.recommended_summary || "";
  const accountContext = unwrapStructuredValue(result.account_context);
  const renewalRisk = unwrapStructuredValue(result.renewal_risk);
  const supportIncident = unwrapStructuredValue(result.support_track?.incident);
  const supportRunbook = unwrapStructuredValue(result.support_track?.runbook);
  const successReply = unwrapStructuredValue(result.success_track?.customer_reply);
  const successTask = unwrapStructuredValue(result.success_track?.followup_task);

  finalOutput.innerHTML = `
    <section class="output-hero">
      <p class="output-kicker">Final Output</p>
      <h3>${escapeHtml(result.headline)}</h3>
      <p class="output-section-copy">Governance scenario: <strong>${escapeHtml(labelForScenario(result.governance_scenario || activeScenario))}</strong></p>
      <p class="output-section-copy">Executive summary created by the orchestrator LLM after combining orchestrator context, support-agent output, and success-agent output.</p>
      <div class="output-summary">${escapeHtml(executiveSummary)}</div>
    </section>
    <div class="output-grid">
      <section class="output-section output-section-wide">
        <strong>MCP Tool Usage</strong>
        <p class="output-section-copy">These are the MCP tools that were actually called during this run, grouped by agent.</p>
        <div class="output-subgrid">
          <div class="output-subsection">
            <span>Orchestrator</span>
            ${renderBulletList(result.mcp_tools_by_agent?.["orchestrator"] || result.called_mcp_tools)}
          </div>
          <div class="output-subsection">
            <span>Support Agent</span>
            ${renderBulletList(result.mcp_tools_by_agent?.["support-agent"])}
          </div>
          <div class="output-subsection">
            <span>Success Agent</span>
            ${renderBulletList(result.mcp_tools_by_agent?.["success-agent"])}
          </div>
        </div>
      </section>
      <section class="output-section">
        <strong>Account Context</strong>
        <p class="output-section-copy">Created by the orchestrator using the MCP tool <code>get_customer_account</code> before any sub-agent work starts.</p>
        ${renderDefinitionList([
          ["Customer ID", accountContext?.customer_id],
          ["Account Name", accountContext?.account_name],
          ["Segment", accountContext?.segment],
          ["Health Score", accountContext?.health_score],
          ["Renewal Date", accountContext?.renewal_date],
          ["CSM", accountContext?.csm],
          ["ARR", accountContext?.arr],
        ])}
      </section>
      <section class="output-section">
        <strong>Renewal Risk</strong>
        <p class="output-section-copy">Created by the orchestrator using the MCP tool <code>get_renewal_risk</code> to show the current renewal score and its drivers.</p>
        ${renderDefinitionList([
          ["Score", renewalRisk?.score],
          ["Level", renewalRisk?.level],
        ])}
        ${renderBulletList(renewalRisk?.drivers)}
      </section>
      <section class="output-section">
        <strong>Support Track</strong>
        <p class="output-section-copy">Created by the support agent using <code>get_incident_status</code>, <code>search_runbook</code>, and its Gemini summary step.</p>
        ${renderTextBlock(result.support_track?.technical_response)}
        ${renderBulletList(result.support_track?.recommended_actions)}
      </section>
      <section class="output-section">
        <strong>Success Plan</strong>
        <p class="output-section-copy">Created by the success agent using <code>draft_customer_reply</code>, <code>create_followup_task</code>, and its Gemini summary step.</p>
        ${renderBulletList(result.success_track?.success_plan)}
      </section>
      <section class="output-section output-section-wide">
        <strong>Full Support Payload</strong>
        <p class="output-section-copy">Full support-agent output, built from <code>get_incident_status</code>, <code>search_runbook</code>, and the support-agent LLM summary.</p>
        <div class="output-subgrid">
          <div class="output-subsection">
            <span>Incident</span>
            ${renderDefinitionList([
              ["Incident ID", supportIncident?.incident_id],
              ["Status", supportIncident?.status],
              ["Severity", supportIncident?.severity],
              ["Customer Impact", supportIncident?.customer_impact],
              ["ETA", supportIncident?.eta],
            ])}
          </div>
          <div class="output-subsection">
            <span>Runbook Matches</span>
            ${renderBulletList((supportRunbook?.results || []).map((item) => `${item.id}: ${item.title} - ${item.summary}`))}
          </div>
          <div class="output-subsection output-subsection-wide">
            <span>Support LLM Summary</span>
            ${renderTextBlock(result.support_track?.llm_summary?.summary)}
          </div>
        </div>
      </section>
      <section class="output-section output-section-wide">
        <strong>Full Success Payload</strong>
        <p class="output-section-copy">Full success-agent output, built from <code>draft_customer_reply</code>, <code>create_followup_task</code>, and the success-agent LLM summary.</p>
        <div class="output-subgrid">
          <div class="output-subsection output-subsection-wide">
            <span>Draft Customer Reply</span>
            <p class="output-section-copy">Created by the success agent using the MCP tool <code>draft_customer_reply</code>. This is the customer-facing message draft.</p>
            ${renderTextBlock(successReply?.draft)}
          </div>
          <div class="output-subsection">
            <span>Follow-up Task</span>
            <p class="output-section-copy">Created by the success agent using the MCP tool <code>create_followup_task</code>. This is the internal account-team follow-up record.</p>
            ${renderDefinitionList([
              ["Task ID", successTask?.task_id],
              ["Status", successTask?.status],
              ["Owner", successTask?.owner],
              ["Due Date", successTask?.due_date],
            ])}
            ${renderBulletList(successTask?.action_items)}
          </div>
          <div class="output-subsection">
            <span>Success LLM Summary</span>
            <p class="output-section-copy">Created by the success-agent Gemini step after reviewing the reply draft and follow-up task. This is the concise business summary of customer posture and next actions.</p>
            ${renderTextBlock(result.success_track?.llm_summary?.summary)}
          </div>
        </div>
      </section>
    </div>
  `;
}

function resetTraceState() {
  if (mcpAnimationTimer) {
    clearTimeout(mcpAnimationTimer);
    mcpAnimationTimer = null;
  }
  if (failoverResetTimer) {
    clearTimeout(failoverResetTimer);
    failoverResetTimer = null;
  }
  if (llmSuccessTimer) {
    clearTimeout(llmSuccessTimer);
    llmSuccessTimer = null;
  }
  if (pendingMcpActivationTimer) {
    clearTimeout(pendingMcpActivationTimer);
    pendingMcpActivationTimer = null;
  }
  if (failoverActivationTimer) {
    clearTimeout(failoverActivationTimer);
    failoverActivationTimer = null;
  }
  orchestratorLlmVisibleUntil = 0;
  traceState = createInitialTraceState();
  selectedTraceId = null;
  runIdLabel.textContent = "not started";
  lastRun.textContent = "not started";
  traceTree.innerHTML = `
    <div class="trace-empty">
      <h3>No run yet</h3>
      <p>Press Play to stream the execution tree in real time.</p>
    </div>
  `;
  clearDetailPane();
}

function initializeRun(payload) {
  traceState = createInitialTraceState();
  traceState.runId = payload.run_id;
  traceState.scenario = payload.governance_scenario || "normal";
  runIdLabel.textContent = payload.run_id;
  touchActivity(payload.timestamp);

  const runNode = createTraceNode("run", 0, `Run started: ${payload.run_id}`, `Top-level workflow started for ${labelForScenario(traceState.scenario)}.`, {
    timestamp: payload.timestamp,
    status: "active",
  });
  runNode.input = payload.input;
  addTraceNode(runNode);
  selectedTraceId = "run";
  renderTraceTree();
  updateSelectedDetail();
}

function connectTraceSocket() {
  if (traceSocket) {
    traceSocket.close();
  }
  traceSocket = new WebSocket(config.traceWsUrl);

  traceSocket.addEventListener("open", () => {
    traceSocket.send("subscribe");
  });

  traceSocket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    handleTraceEvent(payload);
  });
}

function handleTraceEvent(payload) {
  if (payload.type === "run_started") {
    initializeRun(payload);
  }
  if (!traceState.nodes.run) {
    return;
  }

  touchActivity(payload.timestamp);

  switch (payload.type) {
    case "run_started":
      setRunState("running");
      setFlowStage("Request entered Kong", `${labelForScenario(traceState.scenario)} scenario started through Kong.`);
      markNode("user", "complete");
      markNode("ui", "complete");
      markLine("user-ui", "complete");
      markLine("ui-kong", "active");
      activateActorPath("orchestrator", "active");
      break;

    case "scenario_selected": {
      const parentId = ensureActorRoot(payload.actor || "orchestrator");
      const node = upsertSystemNode(
        `scenario:${payload.scenario}`,
        parentId,
        `Scenario selected: ${labelForScenario(payload.scenario)}`,
        payload.summary || "Governance scenario selected.",
        payload,
      );
      node.output = payload.output;
      node.status = "complete";
      setFlowStage(labelForScenario(payload.scenario), payload.summary || "Governance scenario selected.");
      break;
    }

    case "planning":
      ensureActorRoot("orchestrator");
      setFlowStage("Gathering account context", payload.message);
      setMcpPathState("active");
      break;

    case "tool_list_received": {
      const actor = payload.actor || "orchestrator";
      const parentId = ensureActorRoot(actor);
      const node = upsertSystemNode(
        `tool-list:${actor}`,
        parentId,
        "Tool list returned",
        "Kong resolved the allowed tool set for this consumer.",
        payload,
      );
      node.output = payload.tools;
      node.status = "complete";
      setMcpPathState("complete", 1000);
      break;
    }

    case "tool_call_started":
      upsertToolNode(payload);
      setFlowStage(`Tool call: ${payload.tool}`, `${labelForActor(payload.actor || "orchestrator")} is calling an MCP tool through Kong.`);
      showTopologyActivity(payload.tool);
      setMcpPathState("active");
      break;

    case "tool_call_completed":
      upsertToolNode(payload);
      setMcpPathState("complete", 1100);
      break;

    case "tool_calls_completed":
      setMcpPathState("complete", 1300);
      break;

    case "llm_started":
      upsertLlmNode(payload);
      setFlowStage(`LLM call: ${payload.stage}`, `${labelForActor(payload.actor || "orchestrator")} is calling its AI route through Kong.`);
      if (
        traceState.scenario === "llm_failover" &&
        payload.actor === "orchestrator" &&
        !String(payload.model || "").toLowerCase().includes("gemini")
      ) {
        activateActorPath("orchestrator", "active");
        setOrchestratorModelStates({ openai: "active", gemini: "complete" });
        break;
      }
      markLlmPath(payload, "active");
      break;

    case "llm_completed":
      upsertLlmNode(payload);
      if (
        traceState.scenario === "llm_failover" &&
        payload.actor === "orchestrator" &&
        String(payload.model || "").toLowerCase().includes("gemini")
      ) {
        lingerLlmSuccessPath(payload, 1700);
      } else {
        markLlmPath(payload, "complete");
      }
      break;

    case "policy_event": {
      const actor = payload.actor || "orchestrator";
      const llmStage = payload.llm_stage;
      const parentId = llmStage
        ? upsertLlmNode({ actor, stage: llmStage, timestamp: payload.timestamp }).id
        : ensureActorRoot(actor);
      const decoratorPolicy =
        payload.stage === "prompt_decoration"
          ? payload.output?.decorator_prompt ||
            payload.output?.decorated_system_prompt ||
            payload.summary
          : null;
      const titleMap = {
        prompt_decoration: "Decorator policy applied",
        token_limit: "Kong token policy blocked request",
        failover_primary_failed: "Primary model path failed",
        failover: "Kong selected fallback model",
      };
      const node = upsertSystemNode(
        `policy:${payload.stage}:${llmStage || "actor"}:${payload.timestamp}`,
        parentId,
        titleMap[payload.stage] || `Policy event: ${payload.stage}`,
        decoratorPolicy || payload.summary || "Kong governance policy event.",
        payload,
      );
      node.input = payload.input;
      node.output =
        payload.stage === "prompt_decoration"
          ? {
              applied_policy: payload.output?.decorator_prompt || null,
              decorated_system_prompt: payload.output?.decorated_system_prompt || null,
              decorated_user_prompt: payload.output?.decorated_user_prompt || null,
            }
          : payload.output;
      node.status = "complete";
      setFlowStage(
        payload.stage === "prompt_decoration" ? "Decorator policy applied" : `Policy: ${payload.stage}`,
        decoratorPolicy || payload.summary || "Kong governance policy event.",
      );
      if (payload.stage === "failover") {
        if (failoverActivationTimer) {
          clearTimeout(failoverActivationTimer);
          failoverActivationTimer = null;
        }
        activateActorPath("orchestrator", "active");
        setOrchestratorModelStates({ openai: "error", gemini: "active" });
        orchestratorLlmVisibleUntil = Date.now() + 1200;
        resetModelPath("openai", 1100);
        setFlowStage("Failover engaged", payload.summary || "Kong redirected the orchestrator from OpenAI to Gemini.");
      }
      if (payload.stage === "failover_primary_failed") {
        showModelFailure("openai");
        markNode("gemini", "complete");
        markLine("kong-gemini", "complete");
        setFlowStage("Primary model failed", payload.summary || "The OpenAI primary path failed.");
        if (!failoverActivationTimer) {
          failoverActivationTimer = window.setTimeout(() => {
            activateActorPath("orchestrator", "active");
            setOrchestratorModelStates({ openai: "error", gemini: "active" });
            orchestratorLlmVisibleUntil = Date.now() + 1200;
            setFlowStage("Failover engaged", "Kong is redirecting the orchestrator to Gemini.");
            failoverActivationTimer = null;
          }, 450);
        }
      }
      if (payload.stage === "token_limit") {
        showFailurePath("openai");
      }
      break;
    }

    case "subagent_invoking": {
      const actorId = ensureActorRoot(payload.agent);
      const actorNode = traceState.nodes[actorId];
      actorNode.input = payload.input;
      actorNode.timestamp = payload.timestamp;
      actorNode.summary = "Sub-agent request routed through Kong.";
      setFlowStage(`Calling ${labelForActor(payload.agent)}`, "The orchestrator is handing off the current state to the sub-agent.");
      activateActorPath(payload.agent, "active");
      break;
    }

    case "subagent_responded": {
      const actorId = ensureActorRoot(payload.agent);
      const actorNode = traceState.nodes[actorId];
      actorNode.input = payload.input;
      actorNode.output = payload.output;
      actorNode.durationMs = payload.duration_ms;
      actorNode.timestamp = payload.timestamp;
      actorNode.status = "complete";
      activateActorPath(payload.agent, "complete");
      break;
    }

    case "final_response": {
      const finalNode = createTraceNode(
        "final-response",
        1,
        "Final response assembled",
        "The orchestrator merged context, sub-agent outputs, and the executive brief.",
        { timestamp: payload.timestamp, status: "complete" },
      );
      finalNode.output = payload.output;
      addTraceNode(finalNode, "run");
      setFlowStage("Run complete", "The orchestrator completed synthesis and the final output is ready.");
      activateActorPath("orchestrator", "complete");
      markNode("kong", "complete");
      markLine("ui-kong", "complete");
      break;
    }

    case "run_completed": {
      const runNode = traceState.nodes.run;
      runNode.output = payload.output;
      runNode.durationMs = payload.duration_ms;
      runNode.timestamp = payload.timestamp;
      if (payload.output?.policy_outcome === "blocked") {
        runNode.status = "error";
        setRunState("error");
      } else {
        runNode.status = "complete";
        setRunState("complete");
      }
      break;
    }

    default:
      break;
  }

  renderTraceTree();
  updateSelectedDetail();
}

async function play() {
  const formData = new FormData(playForm);
  const payload = Object.fromEntries(formData.entries());

  resetTopology();
  resetTraceState();
  setRunState("starting");
  setFlowStage("Starting run", "Kong is about to accept the request and begin the orchestrated workflow.");
  finalOutput.innerHTML = "<h3>Run in progress</h3><p class=\"result-card-copy\">The output will appear here once the workflow completes.</p>";

  try {
    const response = await fetch(`${config.apiBaseUrl}/play`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        apikey: config.apiKey,
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    const data = await response.json();
    renderFinalOutput(data.result);
  } catch (error) {
    setRunState("error");
    setFlowStage("Run failed", error.message);
    showFailurePath("orchestrator");
    const runNode = traceState.nodes.run;
    if (runNode) {
      runNode.status = "error";
      runNode.output = { error: error.message };
      renderTraceTree();
      updateSelectedDetail();
    } else {
      finalOutput.innerHTML = `<h3>Run failed</h3><p>${error.message}</p>`;
    }
  }
}

playButton.addEventListener("click", (event) => {
  event.preventDefault();
  sceneModal.close();
  play();
});

presetOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "scene_preset") {
    return;
  }
  applyScenePreset(target.value);
});

scenarioOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "scenario_choice") {
    return;
  }
  applyScenarioChoice(target.value);
});

resetButton.addEventListener("click", () => {
  playForm.reset();
  const selectedScenario = scenarioOptions?.querySelector('input[name="scenario_choice"]:checked');
  applyScenarioChoice(selectedScenario?.value || "normal");
  resetTopology();
  resetTraceState();
  setRunState("idle");
  setFlowStage("Waiting for a run", "Press Play to see Kong route the request across AI, sub-agent, and MCP paths.");
  finalOutput.innerHTML = "<h3>Awaiting run</h3><p>Open View Scene and start the orchestrated demo flow from the scene popup.</p>";
});

clearLogButton.addEventListener("click", () => {
  resetTraceState();
});

sceneButton.addEventListener("click", () => sceneModal.showModal());
graphButton.addEventListener("click", () => graphModal.showModal());
outputButton.addEventListener("click", () => outputModal.showModal());

connectTraceSocket();
applyScenePreset("acme_default");
applyScenarioChoice("normal");
resetTraceState();
setRunState("idle");
setFlowStage("Waiting for a run", "Press Play to see Kong route the request across AI, sub-agent, and MCP paths.");
