const config = window.APP_CONFIG;

const playForm = document.getElementById("play-form");
const playButton = document.getElementById("scene-play-button");
const resetButton = document.getElementById("reset-button");
const sceneButton = document.getElementById("scene-button");
const graphButton = document.getElementById("graph-button");
const outputButton = document.getElementById("output-button");
const resetObservabilityButton = document.getElementById("reset-observability-button");
const clearLogButton = document.getElementById("clear-log");
const finalOutput = document.getElementById("final-output");
const runState = document.getElementById("run-state");
const lastRun = document.getElementById("last-run");
const runIdLabel = document.getElementById("run-id-label");
const runHistorySelect = document.getElementById("run-history-select");
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
const noticeModal = document.getElementById("notice-modal");
const policyModal = document.getElementById("policy-modal");
const kongPolicyButton = document.getElementById("kong-policy-button");
const semanticCacheControls = document.getElementById("semantic-cache-controls");
const semanticCacheSeedPayload = document.getElementById("semantic-cache-seed-payload");
const semanticCacheHitPayload = document.getElementById("semantic-cache-hit-payload");
const semanticCacheSeedButton = document.getElementById("semantic-cache-seed-button");
const semanticCacheHitButton = document.getElementById("semantic-cache-hit-button");
const semanticCacheClearButton = document.getElementById("semantic-cache-clear-button");
const semanticGuardControls = document.getElementById("semantic-guard-controls");
const semanticGuardPayloadPreview = document.getElementById("semantic-guard-payload");
const llmJudgeControls = document.getElementById("llm-judge-controls");
const llmJudgePromptOptions = document.getElementById("llm-judge-prompt-options");
const llmJudgePayloadPreview = document.getElementById("llm-judge-payload");
const piiSanitizerControls = document.getElementById("pii-sanitizer-controls");
const piiModeOptions = document.getElementById("pii-mode-options");
const piiModePayload = document.getElementById("pii-mode-payload");
const piiSendButton = document.getElementById("pii-send-button");
const noticeKicker = document.getElementById("notice-kicker");
const noticeTitle = document.getElementById("notice-title");
const noticeMessage = document.getElementById("notice-message");
const policyTitle = document.getElementById("policy-title");
const policyIntro = document.getElementById("policy-intro");
const policyPlainEnglish = document.getElementById("policy-plain-english");
const policyWhy = document.getElementById("policy-why");
const policyConfig = document.getElementById("policy-config");
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
  "judge-model": document.querySelector('[data-node="judge-model"]'),
  redis: document.querySelector('[data-node="redis"]'),
  "pii-service": document.querySelector('[data-node="pii-service"]'),
  observability: document.querySelector('[data-node="observability"]'),
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
  "kong-judge": document.getElementById("line-kong-judge"),
  "kong-redis": document.getElementById("line-kong-redis"),
  "kong-pii": document.getElementById("line-kong-pii"),
  "kong-observability": document.getElementById("line-kong-observability"),
  "kong-mcp": document.getElementById("line-kong-mcp"),
  "mcp-backend": document.getElementById("line-mcp-backend"),
};

let traceSocket;
let selectedTraceId = null;
let selectedRunViewId = null;
let traceState = createInitialTraceState();
let mcpAnimationTimer = null;
let failoverResetTimer = null;
let llmSuccessTimer = null;
let pendingMcpActivationTimer = null;
let orchestratorLlmVisibleUntil = 0;
let failoverActivationTimer = null;
let semanticRedisHandoffTimer = null;
let semanticCacheOpenAiResetTimer = null;
let semanticCacheReturnTimer = null;
let semanticCacheUiTimer = null;
let semanticGuardSettleTimer = null;
let judgeSettleTimer = null;
let judgeReturnTimer = null;
let judgeUiTimer = null;
let judgeCompleteTimer = null;
let piiSanitizerHandoffTimer = null;
let piiModelHandoffPending = false;
let piiResponseCompleteTimer = null;
let activeScenario = "normal";
let semanticCacheMissReturnPending = false;
let semanticCacheProbeResolved = false;
let semanticCacheModelVisibleUntil = 0;

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

function createRunId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `run-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function shortRunId(runId) {
  if (!runId) {
    return "unknown";
  }
  if (runId.length <= 12) {
    return runId;
  }
  return `${runId.slice(0, 8)}…${runId.slice(-4)}`;
}

function labelForScenario(scenario) {
  const labels = {
    normal: "Normal",
    llm_failover: "LLM Failover",
    token_limit: "AI Token Limit",
    prompt_enhancement: "Prompt Decorator",
    semantic_guard: "Semantic Guard",
    semantic_cache: "Semantic Cache",
    llm_as_judge: "LLM as Judge",
    pii_sanitizer: "PII Sanitization",
  };
  return labels[scenario] || "Normal";
}

function currentPiiMode() {
  return document.querySelector('input[name="pii_mode_choice"]:checked')?.value ||
    playForm.elements.namedItem("pii_sanitizer_mode")?.value ||
    "placeholder";
}

function policyDetailsForScenario(scenario) {
  const common = {
    normal: {
      title: "Normal",
      intro: "Kong fronts the full happy-path orchestration and applies the standard routing, auth, and tool exposure needed for the demo.",
      plainEnglish: [
        "Kong authenticates the request from the hosted UI before anything else runs.",
        "Kong exposes the mock REST API as MCP tools, so the orchestrator and sub-agents can call tools instead of raw endpoints.",
        "Kong routes the orchestrator’s LLM traffic to the primary OpenAI model and routes the sub-agent LLM traffic to Gemini.",
      ],
      why: "This is the baseline governed flow: one gateway handles auth, tool exposure, LLM routing, and service-to-service policy in one place.",
      config: [
        ["UI access", "Key-auth using the UI consumer key"],
        ["Tool exposure", "AI MCP Proxy exposes only the allowed tools per consumer group"],
        ["Orchestrator LLM route", "AI Proxy Advanced to OpenAI 4o mini"],
        ["Sub-agent LLM route", "AI Proxy Advanced to Gemini 2.5 Flash"],
      ],
    },
    llm_failover: {
      title: "LLM Failover",
      intro: "Kong tries the primary OpenAI route first and then moves the orchestrator to Gemini when the primary path fails.",
      plainEnglish: [
        "The failover scene uses AI Proxy Advanced with a primary OpenAI target and a secondary Gemini target.",
        "The current demo wiring intentionally points the primary upstream at a simulated failure path so Kong can evaluate the failover criteria.",
        "Supported failover triggers configured on this route include transport errors, timeouts, invalid headers, and HTTP 403, 404, 429, 500, 502, 503, and 504.",
      ],
      why: "This is meant to show resilience at the gateway layer, where Kong decides whether to stay on the primary model or move to the fallback target.",
      config: [
        ["Primary model", "OpenAI 4o mini"],
        ["Fallback model", "Gemini 2.5 Flash"],
        ["Plugin", "AI Proxy Advanced"],
        ["Balancer algorithm", "priority"],
        ["Retries", "3"],
        ["Configured triggers", "error, timeout, invalid_header, http_403, http_404, http_429, http_500, http_502, http_503, http_504, non_idempotent"],
      ],
    },
    token_limit: {
      title: "AI Token Limit",
      intro: "Kong applies a token governance policy and blocks the later orchestrator LLM call once the demo threshold is exceeded.",
      plainEnglish: [
        "This scene applies AI Rate Limiting Advanced directly on the orchestrator token-demo route.",
        "The plugin is configured for the OpenAI provider with limit 1 over a 300-second window.",
        "Once the first allowed call consumes the budget, the next orchestrator model call is rejected with 429 instead of being forwarded upstream.",
      ],
      why: "This demonstrates that Kong can enforce cost and usage guardrails without changing the application logic.",
      config: [
        ["Protected route", "Orchestrator AI route"],
        ["Policy", "AI Rate Limiting Advanced"],
        ["Provider key", "openai"],
        ["Configured limit", "1 request"],
        ["Window", "300 seconds"],
        ["Expected outcome", "A later orchestrator LLM call is blocked with HTTP 429"],
      ],
    },
    prompt_enhancement: {
      title: "Prompt Decorator",
      intro: "Kong adds extra governance instructions to the orchestrator prompt before it reaches the model.",
      plainEnglish: [
        "The application still sends its normal orchestration prompt to Kong.",
        "Kong prepends two system messages before forwarding the request upstream.",
        "Those injected instructions force an executive escalation structure and require enterprise-safe tone, regulatory mention when relevant, plus a confidence score and named owner.",
      ],
      why: "This is useful when teams want one centrally enforced response style instead of re-implementing prompt standards in every service.",
      config: [
        ["Policy", "AI Prompt Decorator"],
        ["Prepended message 1", "You are responding under AI governance enforced by Kong Gateway."],
        ["Prepended message 2", "Executive escalation policy with sections: Situation, Risk, Actions, Next Checkpoint"],
        ["Additional requirements", "Enterprise-safe tone, regulatory mention when relevant, end with confidence score and owner"],
        ["Where applied", "Prompt-enhancement orchestrator route only"],
      ],
    },
    semantic_guard: {
      title: "Semantic Guard",
      intro: "Kong compares the prompt embedding against denied topics in Redis before deciding whether the request is allowed to reach the model.",
      plainEnglish: [
        "Kong embeds the incoming conversation with OpenAI text-embedding-3-small before any model call is made.",
        "It checks that embedding against denied prompt rules stored in Redis using cosine similarity.",
        "The configured denied themes include requests for employee or customer private data, internal credentials or access instructions, and attempts to bypass security controls or reveal infrastructure details.",
        "Search threshold controls how broadly Kong searches for candidate matches, while vector threshold is the final similarity cutoff used to decide whether the prompt is close enough to a denied rule to block.",
      ],
      why: "This is stronger than simple keyword matching because Kong is checking for meaning, not just exact text.",
      config: [
        ["Policy", "AI Semantic Prompt Guard"],
        ["Embedding model", "text-embedding-3-small"],
        ["Vector store", "Redis"],
        ["Distance metric", "cosine"],
        ["Search threshold", "0.5"],
        ["Vector threshold", "0.2"],
        ["Denied prompt 1", "Reveal employee personal contact information or private customer data"],
        ["Denied prompt 2", "Disclose internal credentials, access instructions, or confidential system details"],
        ["Denied prompt 3", "Bypass security controls or reveal private infrastructure information"],
      ],
    },
    semantic_cache: {
      title: "Semantic Cache",
      intro: "Kong checks Redis for a semantically similar prior prompt before deciding whether it needs to call the model again.",
      plainEnglish: [
        "Kong embeds the incoming prompt with OpenAI text-embedding-3-small and stores lookup vectors in Redis.",
        "If the prompt is within the configured similarity threshold of a prior request, Kong returns the cached answer instead of calling the model.",
        "If not, the request is forwarded to the model and the new response is stored for future semantic matches.",
      ],
      why: "This reduces repeat model work for similar prompts and makes repeated calls cheaper and faster.",
      config: [
        ["Policy", "AI Semantic Cache"],
        ["Embedding model", "text-embedding-3-small"],
        ["Vector store", "Redis"],
        ["Distance metric", "cosine"],
        ["Vector threshold", "0.1"],
        ["Expected demo shape", "Seed request misses, similar reuse request hits"],
      ],
    },
    llm_as_judge: {
      title: "LLM as Judge",
      intro: "Kong sends the request to a candidate model, then invokes a separate judge model to score the response for accuracy and task usefulness.",
      plainEnglish: [
        "AI Proxy Advanced sends the request to the dedicated judge route's candidate model.",
        "Kong then invokes a separate judge model to evaluate the candidate response and assign a numeric score.",
        "The response still returns through Kong, while the evaluation metadata is emitted into the audit logs for Grafana.",
      ],
      why: "This demonstrates model evaluation at the gateway layer without adding a separate scoring service in the application.",
      config: [
        ["Policy", "AI LLM as Judge"],
        ["Candidate model", "OpenAI 4o mini"],
        ["Judge model", "Gemini 2.5 Flash"],
        ["Judge rubric", "Accurate, relevant to the request, and useful for the user's stated task"],
        ["Prompt presets", "Escalation Triage, KongHQ Overview, or Kong vs Apigee/AWS"],
        ["Expected outcome", "One response is returned and Kong logs judge latency plus an accuracy score"],
      ],
    },
    pii_sanitizer: {
      title: "PII Sanitization",
      intro: "Kong sanitizes sensitive data before it leaves the gateway and sanitizes the model response before it returns to the UI.",
      plainEnglish: [
        "Kong sends the request through the AI PII Service before forwarding anything to the model.",
        "The sanitizer is configured in BOTH directions, so request content and response content are both inspected.",
        "This scene protects all supported PII plus credentials, and the active mode decides whether sensitive values are replaced with placeholders, synthetic values, or fully blocked.",
      ],
      why: "This lets teams protect sensitive information at the gateway layer, instead of depending on every application and model call to do it correctly.",
      config: [
        ["Policy", "AI Sanitizer"],
        ["Protected directions", "Request and response"],
        ["Protected categories", "all_and_credentials"],
        ["Backend service", "ai-pii-service:8080"],
        ["Mode", currentPiiMode()],
      ],
    },
  };

  return common[scenario] || common.normal;
}

function renderPolicyModal() {
  const scenario = activeScenario || "normal";
  const details = policyDetailsForScenario(scenario);
  if (!policyTitle || !policyIntro || !policyPlainEnglish || !policyWhy || !policyConfig) {
    return;
  }
  policyTitle.textContent = `${details.title} Policy Details`;
  policyIntro.textContent = details.intro;
  policyPlainEnglish.innerHTML = details.plainEnglish
    .map((point) => `<p class="policy-point">${escapeHtml(point)}</p>`)
    .join("");
  policyWhy.textContent = details.why;
  policyConfig.innerHTML = details.config
    .map(
      ([label, value]) => `
        <div class="policy-kv-item">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(value)}</span>
        </div>`,
    )
    .join("");
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

function formatRunOptionLabel(run) {
  const parts = [];
  if (run.started_at) {
    parts.push(formatTime(run.started_at));
  }
  parts.push(labelForScenario(run.governance_scenario || "normal"));
  if (run.status) {
    parts.push(run.status);
  }
  parts.push(shortRunId(run.run_id));
  return parts.join(" · ");
}

function updateRunHistoryOptions(runs, preferredRunId = selectedRunViewId) {
  if (!runHistorySelect) {
    return null;
  }

  runHistorySelect.innerHTML = "";

  if (!runs.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No saved runs";
    runHistorySelect.appendChild(option);
    runHistorySelect.disabled = true;
    selectedRunViewId = null;
    return null;
  }

  runHistorySelect.disabled = false;
  runs.forEach((run) => {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = formatRunOptionLabel(run);
    option.title = run.headline || run.summary || run.run_id;
    runHistorySelect.appendChild(option);
  });

  const selectedRunId = runs.some((run) => run.run_id === preferredRunId)
    ? preferredRunId
    : runs[0].run_id;
  runHistorySelect.value = selectedRunId;
  selectedRunViewId = selectedRunId;
  return selectedRunId;
}

async function refreshRunHistory(preferredRunId = selectedRunViewId, { autoLoad = false } = {}) {
  try {
    const response = await fetch(`${config.apiBaseUrl}/trace/runs`, {
      headers: {
        apikey: config.apiKey,
      },
    });
    if (!response.ok) {
      throw new Error(`Failed to load run history (${response.status})`);
    }

    const data = await response.json();
    const runs = Array.isArray(data.runs) ? data.runs : [];
    const selectedRunId = updateRunHistoryOptions(runs, preferredRunId);

    if (autoLoad && selectedRunId && !traceState.nodes.run) {
      await loadRunTrace(selectedRunId);
    }
  } catch (error) {
    if (runHistorySelect && !runHistorySelect.options.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Run history unavailable";
      runHistorySelect.appendChild(option);
      runHistorySelect.disabled = true;
    }
    console.error(error);
  }
}

function replayTraceEvents(events) {
  resetTopology();
  resetTraceState();
  setRunState("loading");
  setFlowStage("Loading run", "Replaying the stored trace for the selected run.");

  if (!events.length) {
    return;
  }

  events.forEach((event) => handleTraceEvent(event));
}

async function loadRunTrace(runId) {
  if (!runId) {
    selectedRunViewId = null;
    resetTopology();
    resetTraceState();
    setRunState("idle");
    setFlowStage("Waiting for a run", "Press Play to see Kong route the request across AI, sub-agent, and MCP paths.");
    return;
  }

  const response = await fetch(`${config.apiBaseUrl}/trace/runs/${encodeURIComponent(runId)}`, {
    headers: {
      apikey: config.apiKey,
    },
  });
  if (!response.ok) {
    throw new Error(`Failed to load run ${runId} (${response.status})`);
  }

  const data = await response.json();
  selectedRunViewId = runId;
  if (runHistorySelect) {
    runHistorySelect.value = runId;
  }
  replayTraceEvents(Array.isArray(data.events) ? data.events : []);
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
  const cacheField = playForm.elements.namedItem("semantic_cache_step");
  if (cacheField) {
    cacheField.value = "single";
  }
  const piiField = playForm.elements.namedItem("pii_sanitizer_mode");
  if (piiField) {
    piiField.value = "placeholder";
  }
  const isSemanticCache = activeScenario === "semantic_cache";
  const isSemanticGuard = activeScenario === "semantic_guard";
  const isLlmJudge = activeScenario === "llm_as_judge";
  const isPiiSanitizer = activeScenario === "pii_sanitizer";
  if (semanticCacheControls) {
    semanticCacheControls.hidden = !isSemanticCache;
  }
  if (semanticGuardControls) {
    semanticGuardControls.hidden = !isSemanticGuard;
  }
  if (llmJudgeControls) {
    llmJudgeControls.hidden = !isLlmJudge;
  }
  if (piiSanitizerControls) {
    piiSanitizerControls.hidden = !isPiiSanitizer;
  }
  if (playButton) {
    playButton.hidden = isSemanticCache || isPiiSanitizer;
  }
  updateScenarioInfraVisibility(activeScenario);
  if (isSemanticCache) {
    renderSemanticCachePayloads();
  }
  if (isSemanticGuard) {
    renderSemanticGuardPayload();
  }
  if (isLlmJudge) {
    renderLlmJudgePayload();
  }
  if (isPiiSanitizer) {
    renderPiiSanitizerPayloads();
  }
}

function currentFormPayload() {
  const formData = new FormData(playForm);
  return Object.fromEntries(formData.entries());
}

function selectedLlmJudgePromptChoice() {
  const selected = llmJudgePromptOptions?.querySelector('input[name="llm_judge_prompt_choice"]:checked');
  return selected instanceof HTMLInputElement ? selected.value : "escalation";
}

function semanticCachePayload(step) {
  const base = currentFormPayload();
  const systemPrompt =
    "You are an executive escalation triage assistant. Return a concise response with two sections: Situation and Recommended action.";
  const userPrompt =
    step === "reuse"
      ? [
          "Create an executive triage note for an enterprise customer escalation.",
          `Account: ${base.account_name}`,
          "Context: The customer is disputing recent premium-add-on charges and is also reporting lag in workflow-agent synchronization across production jobs.",
          "Business summary: Customer leadership wants immediate clarity on the billing dispute and the workflow sync lag before renewal discussions continue.",
          "Product signal: workflow-agent synchronization lag across production jobs",
          "Billing signal: disputed premium add-on charges on the current enterprise invoice",
          "Write two sections only:",
          "1) Situation",
          "2) Recommended action",
          "Keep the wording executive-friendly, concise, and action-oriented.",
        ].join("\n")
      : [
          "Create an executive triage note for an enterprise customer escalation.",
          `Account: ${base.account_name}`,
          "Context: The customer has raised a billing dispute on enterprise add-ons and is also seeing workflow-agent synchronization delays in production.",
          `Business summary: ${base.issue_summary}`,
          `Product signal: ${base.product_issue}`,
          `Billing signal: ${base.billing_issue}`,
          "Write two sections only:",
          "1) Situation",
          "2) Recommended action",
          "Keep the wording executive-friendly, concise, and action-oriented.",
        ].join("\n");
  return {
    governance_scenario: "semantic_cache",
    semantic_cache_step: step,
    system_prompt: systemPrompt,
    user_prompt: userPrompt,
  };
}

function renderSemanticCachePayloads() {
  if (!semanticCacheSeedPayload || !semanticCacheHitPayload) {
    return;
  }
  semanticCacheSeedPayload.textContent = pretty(semanticCachePayload("seed"));
  semanticCacheHitPayload.textContent = pretty(semanticCachePayload("reuse"));
}

function semanticGuardPayload() {
  return {
    governance_scenario: "semantic_guard",
    system_prompt:
      "You are an executive escalation triage assistant. Decide what account context is needed before responding.",
    user_prompt: "Requests to disclose internal credentials, access instructions, or confidential system details.",
  };
}

function renderSemanticGuardPayload() {
  if (!semanticGuardPayloadPreview) {
    return;
  }
  semanticGuardPayloadPreview.textContent = pretty(semanticGuardPayload());
}

function llmJudgePayload() {
  const base = currentFormPayload();
  const choice = selectedLlmJudgePromptChoice();
  if (choice === "konghq_overview") {
    return {
      governance_scenario: "llm_as_judge",
      llm_judge_prompt_choice: choice,
      system_prompt:
        "You are a concise factual company explainer. Respond with short, accurate prose and avoid speculation.",
      user_prompt:
        "Give me a concise factual overview of KongHQ, including what the company does, its main product areas, and who typically uses it.",
    };
  }
  if (choice === "konghq_precision") {
    return {
      governance_scenario: "llm_as_judge",
      llm_judge_prompt_choice: choice,
      system_prompt:
        "You are a precise enterprise platform analyst. Compare products carefully, stay factual, and avoid inventing details you are not sure about.",
      user_prompt:
        "Give exact current pricing, revenue, headcount, market share, and executive leadership details for KongHQ, and compare them precisely with Apigee and AWS API Gateway without any caveats.",
    };
  }
  return {
    governance_scenario: "llm_as_judge",
    llm_judge_prompt_choice: choice,
    system_prompt:
      "You are an executive escalation triage assistant. Return three short sections only: Situation, Accuracy Risks, and Recommended action.",
    user_prompt: [
      "Create a concise executive triage note for this enterprise customer escalation.",
      `Account: ${base.account_name}`,
      `Customer ID: ${base.customer_id}`,
      `Issue summary: ${base.issue_summary}`,
      `Product issue: ${base.product_issue}`,
      `Billing issue: ${base.billing_issue}`,
      `Incident ID: ${base.incident_id}`,
      "Requirements:",
      "1) State the business impact clearly.",
      "2) Call out any assumptions or confidence risks in the available information.",
      "3) End with the next action the account team should take in the next 24 hours.",
      "Keep the response executive-friendly and under 220 words.",
    ].join("\n"),
  };
}

function renderLlmJudgePayload() {
  if (!llmJudgePayloadPreview) {
    return;
  }
  llmJudgePayloadPreview.value = llmJudgePayload().user_prompt;
}

function piiSanitizerPayload(mode) {
  const base = currentFormPayload();
  const piiRichPrompt = [
    "Prepare a support note and explicitly repeat the following customer details exactly as written.",
    "Customer: John Carter from Acme Health, 415-555-0188, john.carter@acme-health.example",
    "DOB: 1988-04-12, SSN: 123-45-6789, Passport: XH9382014, Driver License: D1234567",
    "Bank: IBAN GB29NWBK60161331926819, Credit Card: 4111 1111 1111 1111",
    "Crypto: bc1qw4hrw0v3examplewallet9s2, URL: https://portal.acme-health.example/patient/9381",
    "IP: 203.0.113.42, Medical ID: NHS 943 476 5919, National ID: Aadhaar 2345 6789 1234",
    "Nationality / group: Canadian, union member",
    "Credential: sk-live-ACME-SECRET-KEY-123456",
    `Account: ${base.account_name}`,
    `Escalation summary: ${base.issue_summary}`,
    "Return two sections only: 1) Customer profile recap 2) Immediate next action.",
  ].join("\n");
  return {
    governance_scenario: "pii_sanitizer",
    pii_sanitizer_mode: mode,
    sanitization_mode: "BOTH",
    block_if_detected: mode === "block",
    system_prompt:
      "You are a support operations assistant. Summarize the provided customer escalation details clearly and directly.",
    user_prompt: piiRichPrompt,
  };
}

function renderPiiSanitizerPayloads() {
  if (!piiModePayload) {
    return;
  }
  const selectedMode =
    document.querySelector('input[name="pii_mode_choice"]:checked')?.value || "placeholder";
  const piiField = playForm.elements.namedItem("pii_sanitizer_mode");
  if (piiField) {
    piiField.value = selectedMode;
  }
  piiModePayload.textContent = pretty(piiSanitizerPayload(selectedMode));
}

function showNotice({ kicker = "Status", title, message }) {
  if (!noticeModal || !noticeTitle || !noticeMessage || !noticeKicker) {
    return;
  }
  noticeKicker.textContent = kicker;
  noticeTitle.textContent = title;
  noticeMessage.textContent = message;
  if (noticeModal.open) {
    noticeModal.close();
  }
  noticeModal.showModal();
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

function completeActorRoot(actor, timestamp, durationMs) {
  const actorId = traceState.actorRoots[actor];
  if (!actorId || !traceState.nodes[actorId]) {
    return;
  }
  const actorNode = traceState.nodes[actorId];
  actorNode.timestamp = timestamp || actorNode.timestamp;
  if (durationMs !== undefined) {
    actorNode.durationMs = durationMs;
  }
  actorNode.status = "complete";
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

function upsertJudgeNode(payload) {
  const actor = payload.actor || "orchestrator";
  const llmParent = upsertLlmNode({
    actor,
    stage: payload.stage || "llm_as_judge_probe",
    timestamp: payload.timestamp,
  });
  const key = `judge:${actor}:${payload.stage || "llm_as_judge_probe"}`;
  let nodeId = traceState.systemNodes[key];
  if (!nodeId) {
    nodeId = `system:${key}`;
    traceState.systemNodes[key] = nodeId;
    const node = createTraceNode(
      nodeId,
      traceState.nodes[llmParent.id].level + 1,
      `Judge model invoked: ${payload.judge_model || "Gemini 2.5 Flash"}`,
      "Kong is sending the candidate response to the judge model for scoring.",
      {
        actor,
        timestamp: payload.timestamp,
        model: payload.judge_model || "Gemini 2.5 Flash",
      },
    );
    addTraceNode(node, llmParent.id);
  }

  const node = traceState.nodes[nodeId];
  node.timestamp = payload.timestamp || node.timestamp;
  node.meta.model = payload.judge_model || node.meta.model || "Gemini 2.5 Flash";
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

function upsertSemanticCacheProbeNode(payload, status = "active") {
  const actor = payload.actor || "orchestrator";
  const parentId = ensureActorRoot(actor);
  const key = `semantic-cache-probe:${actor}`;
  let nodeId = traceState.systemNodes[key];
  if (!nodeId) {
    nodeId = `system:${key}`;
    traceState.systemNodes[key] = nodeId;
    const node = createTraceNode(
      nodeId,
      traceState.nodes[parentId].level + 1,
      "Redis semantic cache lookup",
      "Kong is checking Redis for a semantically similar cached response before calling the model.",
      {
        actor,
        timestamp: payload.timestamp,
        status,
      },
    );
    addTraceNode(node, parentId);
  }

  const node = traceState.nodes[nodeId];
  node.timestamp = payload.timestamp || node.timestamp;
  node.status = status;
  if (payload.summary) {
    node.summary = payload.summary;
  }
  if (payload.input !== undefined) {
    node.input = payload.input;
  }
  if (payload.output !== undefined) {
    node.output = payload.output;
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
  if (semanticRedisHandoffTimer) {
    clearTimeout(semanticRedisHandoffTimer);
    semanticRedisHandoffTimer = null;
  }
  if (semanticCacheOpenAiResetTimer) {
    clearTimeout(semanticCacheOpenAiResetTimer);
    semanticCacheOpenAiResetTimer = null;
  }
  if (semanticCacheReturnTimer) {
    clearTimeout(semanticCacheReturnTimer);
    semanticCacheReturnTimer = null;
  }
  if (semanticCacheUiTimer) {
    clearTimeout(semanticCacheUiTimer);
    semanticCacheUiTimer = null;
  }
  if (semanticGuardSettleTimer) {
    clearTimeout(semanticGuardSettleTimer);
    semanticGuardSettleTimer = null;
  }
  if (judgeSettleTimer) {
    clearTimeout(judgeSettleTimer);
    judgeSettleTimer = null;
  }
  if (judgeReturnTimer) {
    clearTimeout(judgeReturnTimer);
    judgeReturnTimer = null;
  }
  if (judgeUiTimer) {
    clearTimeout(judgeUiTimer);
    judgeUiTimer = null;
  }
  if (judgeCompleteTimer) {
    clearTimeout(judgeCompleteTimer);
    judgeCompleteTimer = null;
  }
  if (piiSanitizerHandoffTimer) {
    clearTimeout(piiSanitizerHandoffTimer);
    piiSanitizerHandoffTimer = null;
  }
  if (piiResponseCompleteTimer) {
    clearTimeout(piiResponseCompleteTimer);
    piiResponseCompleteTimer = null;
  }
  piiModelHandoffPending = false;
  semanticCacheMissReturnPending = false;
  semanticCacheProbeResolved = false;
  semanticCacheModelVisibleUntil = 0;
  orchestratorLlmVisibleUntil = 0;
  Object.values(nodes).forEach((node) => node?.classList.remove("active", "complete", "error"));
  Object.values(lineMap).forEach((line) => line?.classList.remove("active", "complete", "error"));
  hideTopologyActivity();
  updateScenarioInfraVisibility(activeScenario);
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
    node.classList.add("complete");
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
    line.classList.add("complete");
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

function setScenarioVisibility(name, visible) {
  const targetNode = nodes[name];
  if (targetNode) {
    targetNode.classList.toggle("scenario-hidden", !visible);
  }
}

function setLineVisibility(name, visible) {
  const targetLine = lineMap[name];
  if (targetLine) {
    targetLine.classList.toggle("scenario-hidden", !visible);
  }
}

function updateScenarioInfraVisibility(scenario) {
  const showRedis = scenario === "semantic_guard" || scenario === "semantic_cache";
  const showJudge = scenario === "llm_as_judge";
  const showPii = scenario === "pii_sanitizer";
  const focusedScenario = showRedis || showJudge || showPii;

  setScenarioVisibility("redis", showRedis);
  setLineVisibility("kong-redis", showRedis);

  setScenarioVisibility("judge-model", showJudge);
  setLineVisibility("kong-judge", showJudge);

  setScenarioVisibility("pii-service", showPii);
  setLineVisibility("kong-pii", showPii);
  setScenarioVisibility("openai", true);
  setLineVisibility("kong-openai", true);

  setScenarioVisibility("gemini", scenario === "llm_failover" || (!focusedScenario));
  setLineVisibility("kong-gemini", scenario === "llm_failover" || (!focusedScenario));

  setScenarioVisibility("support-agent", !focusedScenario);
  setScenarioVisibility("success-agent", !focusedScenario);
  setScenarioVisibility("mcp", !focusedScenario);
  setScenarioVisibility("backend-api", !focusedScenario);
  setLineVisibility("kong-support", !focusedScenario);
  setLineVisibility("kong-success", !focusedScenario);
  setLineVisibility("kong-mcp", !focusedScenario);
  setLineVisibility("mcp-backend", !focusedScenario);
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

function activateRedisPath(state = "active") {
  markNode("redis", state);
  markNode("kong", state);
  markLine("kong-redis", state);
}

function activateJudgePath(state = "active") {
  markNode("judge-model", state);
  markNode("kong", state);
  markLine("kong-judge", state);
}

function setObservabilityPath(state = "active") {
  markNode("observability", state);
  markLine("kong-observability", state);
}

function completeRedisPath() {
  activateRedisPath("complete");
}

function completeRedisProbeKeepKongActive() {
  markNode("redis", "complete");
  markLine("kong-redis", "complete");
  markNode("kong", "active");
}

function scheduleSemanticCacheReturn(delayMs = 900) {
  if (semanticCacheReturnTimer) {
    clearTimeout(semanticCacheReturnTimer);
  }
  semanticCacheReturnTimer = window.setTimeout(() => {
    if (traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending) {
      activateActorPath("orchestrator", "complete");
      markNode("kong", "active");
    }
    semanticCacheReturnTimer = null;
  }, delayMs);
}

function scheduleSemanticCacheUiComplete(delayMs = 1600) {
  if (semanticCacheUiTimer) {
    clearTimeout(semanticCacheUiTimer);
  }
  semanticCacheUiTimer = window.setTimeout(() => {
    if (traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending) {
      markNode("ui", "complete");
      markLine("ui-kong", "complete");
      markNode("kong", "complete");
      semanticCacheMissReturnPending = false;
    }
    semanticCacheUiTimer = null;
  }, delayMs);
}

function scheduleJudgeSettle(delayMs = 1200) {
  if (judgeSettleTimer) {
    clearTimeout(judgeSettleTimer);
  }
  judgeSettleTimer = window.setTimeout(() => {
    if (traceState.scenario === "llm_as_judge") {
      activateJudgePath("complete");
      markNode("kong", "active");
    }
    judgeSettleTimer = null;
  }, delayMs);
}

function scheduleJudgeReturnSettle(delayMs = 1200) {
  if (judgeReturnTimer) {
    clearTimeout(judgeReturnTimer);
  }
  judgeReturnTimer = window.setTimeout(() => {
    if (traceState.scenario === "llm_as_judge") {
      activateJudgePath("complete");
      activateActorPath("orchestrator", "active");
      markNode("kong", "active");
    }
    judgeReturnTimer = null;
  }, delayMs);
}

function scheduleJudgeUiReturn(delayMs = 800) {
  if (judgeUiTimer) {
    clearTimeout(judgeUiTimer);
  }
  judgeUiTimer = window.setTimeout(() => {
    if (traceState.scenario === "llm_as_judge") {
      activateActorPath("orchestrator", "complete");
      markNode("kong", "active");
      markNode("ui", "active");
      markLine("ui-kong", "active");
    }
    judgeUiTimer = null;
  }, delayMs);
}

function scheduleJudgeFlowComplete(delayMs = 800) {
  if (judgeCompleteTimer) {
    clearTimeout(judgeCompleteTimer);
  }
  judgeCompleteTimer = window.setTimeout(() => {
    if (traceState.scenario === "llm_as_judge") {
      markNode("kong", "complete");
      markNode("ui", "complete");
      markLine("ui-kong", "complete");
    }
    judgeCompleteTimer = null;
  }, delayMs);
}

function settleSemanticGuardTopology() {
  hideTopologyActivity();
  markNode("user", "complete");
  markNode("ui", "complete");
  markNode("kong", "complete");
  markNode("redis", "complete");
  markNode("openai", "complete");
  markNode("gemini", "complete");
  markLine("user-ui", "complete");
  markLine("ui-kong", "complete");
  markLine("kong-redis", "complete");
  markLine("kong-openai", "complete");
  markLine("kong-gemini", "complete");
  markNode("orchestrator", "complete");
  markLine("kong-orchestrator", "complete");
}

function activatePiiPath(state = "active") {
  activateActorPath("orchestrator", state);
  markNode("pii-service", state);
  markLine("kong-pii", state);
}

function activatePiiRequestPath(state = "active") {
  activatePiiPath(state);
}

function activatePiiResponsePath(state = "active") {
  activatePiiPath(state);
}

function setOpenAiNodeState(state = "active") {
  markNode("openai", state);
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
  const piiProbe = result.pii_sanitizer_probe;
  const judgeProbe = result.llm_judge_probe;
  const isFocusedProbe = Boolean(result.semantic_cache_probe || piiProbe || judgeProbe);

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
      ${
        result.semantic_cache_probe
          ? `
      <section class="output-section output-section-wide">
        <strong>Semantic Cache Probe</strong>
        <p class="output-section-copy">Created by the orchestrator in the semantic-cache scenario. This run sends either the first cache-seed request or the second cache-reuse request through Kong.</p>
        <div class="output-subgrid">
          <div class="output-subsection">
            <span>${result.semantic_cache_probe?.step === "seed" ? "First Request" : "Second Request"}</span>
            ${renderDefinitionList([
              ["Step", result.semantic_cache_probe?.step],
              ["X-Cache-Status", result.semantic_cache_probe?.headers?.["x-cache-status"]],
              ["X-Cache-Key", result.semantic_cache_probe?.headers?.["x-cache-key"]],
              ["X-Cache-TTL", result.semantic_cache_probe?.headers?.["x-cache-ttl"]],
              ["Age", result.semantic_cache_probe?.headers?.age],
            ])}
          </div>
        </div>
      </section>`
          : ""
      }
      ${
        judgeProbe
          ? `
      <section class="output-section output-section-wide">
        <strong>LLM as Judge Probe</strong>
        <p class="output-section-copy">Created by the orchestrator in the LLM as Judge scenario. Kong evaluates the returned answer with a separate judge model and emits the score into the audit logs for Grafana.</p>
        <div class="output-subgrid">
          <div class="output-subsection">
            <span>Evaluation Route</span>
            ${renderDefinitionList([
              ["Scenario", "LLM as Judge"],
              ["Candidate Models", "OpenAI 4o mini, Gemini 2.5 Flash"],
              ["Judge Model", judgeProbe.judge_model || "Gemini 2.5 Flash"],
            ])}
            ${renderTextBlock(judgeProbe.scoring_note)}
          </div>
          <div class="output-subsection output-subsection-wide">
            <span>Original Request Prompt</span>
            ${renderTextBlock(judgeProbe.original_prompt?.user_prompt)}
          </div>
        </div>
      </section>`
          : ""
      }
      ${
        piiProbe
          ? `
      <section class="output-section output-section-wide">
        <strong>PII Sanitizer Probe</strong>
        <p class="output-section-copy">Created by the orchestrator in the AI PII Sanitizer scenario. Kong sanitizes or blocks the upstream request before the model call, and sanitizes the downstream response when the request is allowed.</p>
        <div class="output-subgrid">
          <div class="output-subsection">
            <span>Sanitization Policy</span>
            ${renderDefinitionList([
              ["Mode", piiProbe.mode],
              ["Sanitization Direction", piiProbe.sanitization_mode],
              ["Block If Detected", piiProbe.block_if_detected ? "true" : "false"],
              ["Anonymize", (piiProbe.anonymize || []).join(", ")],
            ])}
            ${renderTextBlock(
              piiProbe.mode === "synthetic"
                ? "Synthetic mode replaces supported detected values with category-matched synthetic values. Some credential-like secrets may still appear masked rather than replaced with natural-looking values."
                : piiProbe.mode === "placeholder"
                  ? "Placeholder mode replaces supported detected values with placeholder tokens."
                  : "Block mode stops the request before it reaches the model when supported PII or credentials are detected."
            )}
            ${renderBulletList(piiProbe.anonymized_categories)}
          </div>
          <div class="output-subsection output-subsection-wide">
            <span>Original Request Prompt</span>
            ${renderTextBlock(piiProbe.original_prompt?.user_prompt)}
          </div>
          <div class="output-subsection output-subsection-wide">
            <span>Sanitized Response Returned Through Kong</span>
            ${renderTextBlock(piiProbe.sanitized_response)}
          </div>
        </div>
      </section>`
          : ""
      }
      ${
        isFocusedProbe
          ? ""
          : `
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
      </section>`
      }
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
  if (semanticRedisHandoffTimer) {
    clearTimeout(semanticRedisHandoffTimer);
    semanticRedisHandoffTimer = null;
  }
  if (semanticCacheOpenAiResetTimer) {
    clearTimeout(semanticCacheOpenAiResetTimer);
    semanticCacheOpenAiResetTimer = null;
  }
  if (semanticCacheReturnTimer) {
    clearTimeout(semanticCacheReturnTimer);
    semanticCacheReturnTimer = null;
  }
  if (semanticCacheUiTimer) {
    clearTimeout(semanticCacheUiTimer);
    semanticCacheUiTimer = null;
  }
  if (semanticGuardSettleTimer) {
    clearTimeout(semanticGuardSettleTimer);
    semanticGuardSettleTimer = null;
  }
  if (judgeSettleTimer) {
    clearTimeout(judgeSettleTimer);
    judgeSettleTimer = null;
  }
  if (judgeReturnTimer) {
    clearTimeout(judgeReturnTimer);
    judgeReturnTimer = null;
  }
  if (judgeUiTimer) {
    clearTimeout(judgeUiTimer);
    judgeUiTimer = null;
  }
  if (judgeCompleteTimer) {
    clearTimeout(judgeCompleteTimer);
    judgeCompleteTimer = null;
  }
  if (piiSanitizerHandoffTimer) {
    clearTimeout(piiSanitizerHandoffTimer);
    piiSanitizerHandoffTimer = null;
  }
  piiModelHandoffPending = false;
  semanticCacheMissReturnPending = false;
  semanticCacheProbeResolved = false;
  semanticCacheModelVisibleUntil = 0;
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
  semanticCacheProbeResolved = false;
  activeScenario = traceState.scenario;
  updateScenarioInfraVisibility(traceState.scenario);
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
    if (payload.type === "run_started" || payload.type === "run_completed") {
      void refreshRunHistory(selectedRunViewId || payload.run_id);
    }
    if (!selectedRunViewId || selectedRunViewId === payload.run_id) {
      handleTraceEvent(payload);
    }
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
      setObservabilityPath("active");
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
      if (traceState.scenario === "semantic_cache") {
        upsertSemanticCacheProbeNode(payload, "active");
        setFlowStage("Semantic cache probe", payload.message);
        hideTopologyActivity();
        clearOrchestratorLlmPath();
        activateActorPath("orchestrator", "active");
        activateRedisPath("active");
      } else if (traceState.scenario === "semantic_guard") {
        setFlowStage("Semantic guard probe", payload.message);
        hideTopologyActivity();
        clearOrchestratorLlmPath();
        activateActorPath("orchestrator", "active");
        activateRedisPath("active");
      } else if (traceState.scenario === "llm_as_judge") {
        setFlowStage("LLM accuracy probe", payload.message);
        hideTopologyActivity();
        activateActorPath("orchestrator", "active");
        markNode("kong", "active");
        markNode("openai", "complete");
        markLine("kong-openai", "complete");
      } else if (traceState.scenario === "pii_sanitizer") {
        setFlowStage("PII sanitization probe", payload.message);
        hideTopologyActivity();
        clearOrchestratorLlmPath();
        markNode("kong", "active");
        markNode("pii-service", "complete");
        markLine("kong-pii", "complete");
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
      } else {
        setFlowStage("Gathering account context", payload.message);
        setMcpPathState("active");
      }
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
      if (traceState.scenario === "semantic_guard") {
        hideTopologyActivity();
        activateActorPath("orchestrator", "active");
        activateRedisPath("active");
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
        markNode("gemini", "complete");
        markLine("kong-gemini", "complete");
        break;
      }
      if (traceState.scenario === "semantic_cache") {
        activateActorPath("orchestrator", "active");
        markNode("ui", "active");
        markLine("ui-kong", "active");
        if (!semanticCacheProbeResolved) {
          activateRedisPath("active");
        } else {
          completeRedisProbeKeepKongActive();
          setOpenAiNodeState("active");
          markLine("kong-openai", "active");
        }
        break;
      }
      if (traceState.scenario === "llm_as_judge") {
        activateActorPath("orchestrator", "active");
        markNode("kong", "active");
        markNode("openai", "active");
        markLine("kong-openai", "active");
        break;
      }
      if (traceState.scenario === "pii_sanitizer") {
        if (String(payload.stage || "").includes("block")) {
          piiModelHandoffPending = false;
          activatePiiRequestPath("active");
          setOpenAiNodeState("complete");
          markLine("kong-openai", "complete");
        } else {
          if (piiSanitizerHandoffTimer) {
            clearTimeout(piiSanitizerHandoffTimer);
            piiSanitizerHandoffTimer = null;
          }
          piiModelHandoffPending = true;
          activatePiiRequestPath("active");
          markLine("kong-openai", "complete");
          setOpenAiNodeState("complete");
          piiSanitizerHandoffTimer = window.setTimeout(() => {
            if (traceState.scenario === "pii_sanitizer" && piiModelHandoffPending) {
              markNode("pii-service", "complete");
              markLine("kong-pii", "complete");
              markNode("kong", "active");
              markLine("kong-openai", "active");
              setOpenAiNodeState("active");
            }
            piiSanitizerHandoffTimer = null;
          }, 450);
        }
        break;
      }
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
      if (traceState.scenario === "semantic_guard") {
        completeRedisPath();
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
        markNode("gemini", "complete");
        markLine("kong-gemini", "complete");
        break;
      }
      if (traceState.scenario === "semantic_cache") {
        completeRedisProbeKeepKongActive();
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
        if (semanticCacheMissReturnPending) {
          setFlowStage("Cache miss response returned", "The LLM response returned through Kong. The return path is settling back through the orchestrator and dashboard.");
          activateActorPath("orchestrator", "active");
          markNode("ui", "active");
          markLine("ui-kong", "active");
          markNode("kong", "active");
          const semanticCacheReturnDelay = Math.max(0, semanticCacheModelVisibleUntil - Date.now());
          scheduleSemanticCacheReturn(semanticCacheReturnDelay + 500);
          scheduleSemanticCacheUiComplete(semanticCacheReturnDelay + 1100);
        }
        break;
      }
      if (traceState.scenario === "llm_as_judge") {
        activateActorPath(payload.actor || "orchestrator", "active");
        markNode("openai", "complete");
        markLine("kong-openai", "complete");
        markNode("kong", "active");
        activateJudgePath("active");
        scheduleJudgeSettle();
        setFlowStage("Candidate response returned", "OpenAI returned the candidate response to Kong. Kong is about to invoke the judge model.");
        break;
      }
      if (traceState.scenario === "pii_sanitizer") {
        if (piiSanitizerHandoffTimer) {
          clearTimeout(piiSanitizerHandoffTimer);
          piiSanitizerHandoffTimer = null;
        }
        piiModelHandoffPending = false;
        activatePiiResponsePath("active");
        markLine("kong-openai", "complete");
        setOpenAiNodeState("complete");
        markNode("kong", "active");
        markLine("ui-kong", "active");
        markNode("ui", "active");
        break;
      }
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

    case "judge_started": {
      upsertJudgeNode(payload);
      setFlowStage("Judge model evaluating", "Kong is sending the candidate response to Gemini 2.5 Flash for scoring.");
      activateActorPath(payload.actor || "orchestrator", "active");
      markNode("openai", "complete");
      markLine("kong-openai", "complete");
      activateJudgePath("active");
      scheduleJudgeSettle();
      break;
    }

    case "judge_completed": {
      upsertJudgeNode(payload);
      setFlowStage("Judge completed", "Kong received the judge score and is returning the governed result to the orchestrator.");
      activateJudgePath("active");
      markNode("kong", "active");
      scheduleJudgeSettle(700);
      scheduleJudgeReturnSettle(700);
      break;
    }

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
        semantic_guard: "Kong semantic guard blocked request",
        semantic_cache_miss: "Semantic cache miss",
        semantic_cache_hit: "Semantic cache hit",
        pii_sanitizer: "PII sanitization policy applied",
        pii_sanitizer_request: "PII request sanitization applied",
        pii_sanitizer_response: "PII response sanitization applied",
        pii_sanitizer_blocked: "Kong PII sanitization blocked request",
        llm_as_judge: "LLM as Judge evaluation applied",
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
      if (payload.stage === "semantic_guard") {
        completeRedisPath();
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
        markNode("gemini", "complete");
        markLine("kong-gemini", "complete");
        markNode("orchestrator", "complete");
        markLine("kong-orchestrator", "complete");
        markNode("kong", "complete");
        markNode("redis", "complete");
        markLine("kong-redis", "complete");
        markNode("ui", "error");
        markLine("ui-kong", "error");
        if (semanticGuardSettleTimer) {
          clearTimeout(semanticGuardSettleTimer);
        }
        semanticGuardSettleTimer = window.setTimeout(() => {
          if (traceState.scenario === "semantic_guard") {
            settleSemanticGuardTopology();
          }
          semanticGuardSettleTimer = null;
        }, 1300);
      }
      if (payload.stage === "semantic_cache_miss") {
        semanticCacheProbeResolved = true;
        semanticCacheMissReturnPending = true;
        semanticCacheModelVisibleUntil = Date.now() + 1450;
        upsertSemanticCacheProbeNode(
          {
            ...payload,
            summary: payload.summary || "Redis did not contain a semantically similar cached response, so Kong is forwarding the request to the model.",
          },
          "complete",
        );
        activateActorPath("orchestrator", "active");
        markNode("ui", "active");
        markLine("ui-kong", "active");
        activateRedisPath("active");
        if (semanticRedisHandoffTimer) {
          clearTimeout(semanticRedisHandoffTimer);
        }
        if (semanticCacheOpenAiResetTimer) {
          clearTimeout(semanticCacheOpenAiResetTimer);
          semanticCacheOpenAiResetTimer = null;
        }
        semanticRedisHandoffTimer = window.setTimeout(() => {
          completeRedisProbeKeepKongActive();
          setOpenAiNodeState("active");
          markLine("kong-openai", "active");
          semanticCacheOpenAiResetTimer = window.setTimeout(() => {
            setOpenAiNodeState("complete");
            markLine("kong-openai", "complete");
            semanticCacheOpenAiResetTimer = null;
          }, 1100);
          semanticRedisHandoffTimer = null;
        }, 550);
      }
      if (payload.stage === "semantic_cache_hit") {
        semanticCacheProbeResolved = true;
        semanticCacheMissReturnPending = false;
        upsertSemanticCacheProbeNode(
          {
            ...payload,
            summary: payload.summary || "Redis contained a semantically similar cached response, so Kong returned it without invoking the model.",
          },
          "complete",
        );
        activateActorPath("orchestrator", "active");
        if (semanticRedisHandoffTimer) {
          clearTimeout(semanticRedisHandoffTimer);
          semanticRedisHandoffTimer = null;
        }
        if (semanticCacheOpenAiResetTimer) {
          clearTimeout(semanticCacheOpenAiResetTimer);
          semanticCacheOpenAiResetTimer = null;
        }
        completeRedisPath();
        setOpenAiNodeState("complete");
        markLine("kong-openai", "complete");
      }
      if (payload.stage === "llm_as_judge") {
        activateActorPath("orchestrator", "active");
        markNode("kong", "active");
        markNode("openai", "complete");
        markLine("kong-openai", "complete");
        activateJudgePath("active");
        scheduleJudgeSettle();
        setFlowStage("Judge model evaluating", payload.summary || "Kong is sending the candidate response to the judge model for scoring.");
      }
      if (payload.stage === "pii_sanitizer_request") {
        setFlowStage("PII request sanitization", payload.summary || "Kong is sanitizing the upstream request before the model call.");
      }
      if (payload.stage === "pii_sanitizer_response") {
        if (piiResponseCompleteTimer) {
          clearTimeout(piiResponseCompleteTimer);
          piiResponseCompleteTimer = null;
        }
        activatePiiPath("active");
        markNode("kong", "active");
        markNode("ui", "active");
        markLine("ui-kong", "active");
        setFlowStage("PII response sanitization", payload.summary || "Kong is sanitizing the downstream response before it returns to the UI.");
      }
      if (payload.stage === "pii_sanitizer") {
        activatePiiPath("active");
        markLine("kong-openai", "complete");
        setOpenAiNodeState("complete");
        if (piiSanitizerHandoffTimer) {
          clearTimeout(piiSanitizerHandoffTimer);
          piiSanitizerHandoffTimer = null;
        }
      }
      if (payload.stage === "pii_sanitizer_blocked") {
        if (piiSanitizerHandoffTimer) {
          clearTimeout(piiSanitizerHandoffTimer);
          piiSanitizerHandoffTimer = null;
        }
        piiModelHandoffPending = false;
        activatePiiPath("complete");
        markLine("kong-openai", "complete");
        setOpenAiNodeState("complete");
        markNode("ui", "error");
        markLine("ui-kong", "error");
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
      if (payload.output) {
        renderFinalOutput(payload.output);
      }
      selectedTraceId = "final-response";
      setFlowStage("Run complete", "The orchestrator completed synthesis and the final output is ready.");
      if (traceState.scenario === "llm_as_judge") {
        if (judgeSettleTimer) {
          clearTimeout(judgeSettleTimer);
          judgeSettleTimer = null;
        }
        activateJudgePath("active");
        markNode("kong", "active");
        scheduleJudgeUiReturn(1400);
      } else if (traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending) {
        activateActorPath("orchestrator", "active");
        markNode("ui", "active");
        markLine("ui-kong", "active");
        markNode("kong", "active");
      } else if (traceState.scenario !== "semantic_guard") {
        activateActorPath("orchestrator", "complete");
      }
      if (!(traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending)) {
        completeActorRoot("orchestrator", payload.timestamp);
      }
      if (traceState.scenario === "llm_as_judge") {
        // The judge scenario returns through Kong back to the orchestrator and UI.
      } else if (traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending) {
        // Cache miss return sequencing is driven from llm_completed.
      } else if (traceState.scenario !== "semantic_guard") {
        markNode("kong", "complete");
        markLine("ui-kong", "complete");
      }
      setObservabilityPath("complete");
      if (
        traceState.scenario === "llm_as_judge" ||
        traceState.scenario === "semantic_cache" ||
        traceState.scenario === "pii_sanitizer" ||
        traceState.scenario === "semantic_guard"
      ) {
        hideTopologyActivity();
        if (traceState.scenario === "llm_as_judge") {
          markNode("openai", "complete");
          markLine("kong-openai", "complete");
          if (!judgeReturnTimer && !judgeUiTimer) {
            markNode("kong", "complete");
            activateJudgePath("complete");
          }
        } else if (traceState.scenario === "semantic_cache") {
          activateRedisPath("complete");
          setOpenAiNodeState("complete");
          markLine("kong-openai", "complete");
          if (!semanticCacheMissReturnPending) {
            markNode("kong", "complete");
          }
        } else if (traceState.scenario === "semantic_guard") {
          // Let the semantic guard policy event own the visible block/reset sequence.
        } else {
          if (piiSanitizerHandoffTimer) {
            clearTimeout(piiSanitizerHandoffTimer);
            piiSanitizerHandoffTimer = null;
          }
          if (piiResponseCompleteTimer) {
            clearTimeout(piiResponseCompleteTimer);
            piiResponseCompleteTimer = null;
          }
          piiModelHandoffPending = false;
          if (payload.output?.policy_outcome === "blocked") {
            activatePiiPath("complete");
            markLine("kong-openai", "complete");
            setOpenAiNodeState("complete");
            markNode("ui", "error");
            markLine("ui-kong", "error");
          } else {
            activatePiiResponsePath("active");
            markLine("kong-openai", "complete");
            markNode("kong", "active");
            markNode("ui", "active");
            markLine("ui-kong", "active");
          }
          setOpenAiNodeState("complete");
        }
      }
      break;
    }

    case "run_completed": {
      const runNode = traceState.nodes.run;
      if (payload.output && !traceState.nodes["final-response"]) {
        renderFinalOutput(payload.output);
      }
      runNode.output =
        payload.output?.headline || payload.output?.policy_outcome
          ? {
              headline: payload.output?.headline,
              policy_outcome: payload.output?.policy_outcome || "completed",
            }
          : runNode.output;
      runNode.durationMs = payload.duration_ms;
      runNode.timestamp = payload.timestamp;
      if (payload.output?.policy_outcome === "blocked") {
        runNode.status = "error";
        setRunState("error");
      } else {
        runNode.status = "complete";
        setRunState("complete");
      }
      if (!(traceState.scenario === "semantic_cache" && semanticCacheMissReturnPending)) {
        completeActorRoot("orchestrator", payload.timestamp, payload.duration_ms);
      }
      if (
        traceState.scenario === "llm_as_judge" ||
        traceState.scenario === "semantic_cache" ||
        traceState.scenario === "pii_sanitizer" ||
        traceState.scenario === "semantic_guard"
      ) {
        hideTopologyActivity();
        setObservabilityPath("complete");
        if (traceState.scenario === "llm_as_judge") {
          markNode("openai", "complete");
          markLine("kong-openai", "complete");
          scheduleJudgeFlowComplete(2200);
        } else if (traceState.scenario === "semantic_cache") {
          activateRedisPath("complete");
          setOpenAiNodeState("complete");
          markLine("kong-openai", "complete");
          if (!semanticCacheMissReturnPending) {
            markNode("ui", "complete");
            markLine("ui-kong", "complete");
            markNode("kong", "complete");
          }
        } else if (traceState.scenario === "semantic_guard") {
          // Let the semantic guard policy event own the visible block/reset sequence.
        } else {
          if (piiSanitizerHandoffTimer) {
            clearTimeout(piiSanitizerHandoffTimer);
            piiSanitizerHandoffTimer = null;
          }
          if (piiResponseCompleteTimer) {
            clearTimeout(piiResponseCompleteTimer);
            piiResponseCompleteTimer = null;
          }
          piiModelHandoffPending = false;
          if (payload.output?.policy_outcome === "blocked") {
            activatePiiPath("complete");
            markLine("kong-openai", "complete");
            setOpenAiNodeState("complete");
            markNode("ui", "error");
            markLine("ui-kong", "error");
          } else {
            activatePiiResponsePath("active");
            markLine("kong-openai", "complete");
            markNode("kong", "active");
            markNode("ui", "active");
            markLine("ui-kong", "active");
            piiResponseCompleteTimer = window.setTimeout(() => {
              if (traceState.scenario === "pii_sanitizer") {
                activatePiiPath("complete");
                markNode("kong", "complete");
                markNode("ui", "complete");
                markLine("ui-kong", "complete");
              }
              piiResponseCompleteTimer = null;
            }, 900);
          }
          setOpenAiNodeState("complete");
        }
      }
      break;
    }

    default:
      break;
  }

  renderTraceTree();
  updateSelectedDetail();
}

async function play(overrides = {}) {
  const formData = new FormData(playForm);
  const payload = { ...Object.fromEntries(formData.entries()), ...overrides };
  if ((payload.governance_scenario || activeScenario) === "llm_as_judge") {
    payload.llm_judge_prompt_choice = selectedLlmJudgePromptChoice();
    payload.llm_judge_user_prompt = llmJudgePayloadPreview?.value?.trim() || llmJudgePayload().user_prompt;
  }
  payload.run_id = payload.run_id || createRunId();
  selectedRunViewId = payload.run_id;

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
        "x-demo-run-id": payload.run_id,
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

async function clearSemanticCache() {
  try {
    const response = await fetch(`${config.apiBaseUrl}/semantic-cache/clear`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: config.apiKey,
      },
    });
    if (!response.ok) {
      throw new Error(`Cache clear failed (${response.status})`);
    }
    const result = await response.json();
    setFlowStage("Semantic cache cleared", `Deleted ${result.deleted_keys ?? 0} cached semantic entries from Redis.`);
    if (activeScenario === "semantic_cache") {
      renderSemanticCachePayloads();
    }
    showNotice({
      kicker: "Semantic Cache",
      title: "Cache deleted successfully",
      message: `Deleted ${result.deleted_keys ?? 0} semantic cache entr${result.deleted_keys === 1 ? "y" : "ies"} from Redis.`,
    });
  } catch (error) {
    setFlowStage("Cache clear failed", error.message);
    showNotice({
      kicker: "Semantic Cache",
      title: "Cache delete failed",
      message: error.message,
    });
  }
}

async function resetObservability({ silent = false } = {}) {
  try {
    const response = await fetch(`${config.apiBaseUrl}/observability/reset`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: config.apiKey,
      },
    });
    if (!response.ok) {
      throw new Error(`Observability reset failed (${response.status})`);
    }
    const result = await response.json();
    setFlowStage("Observability reset", "Recreated Loki and restarted Grafana.");
    if (!silent) {
      showNotice({
        kicker: "Observability",
        title: "Observability reset complete",
        message: "Loki was recreated and Grafana was restarted. Refresh Grafana after a few seconds if panels still show old data.",
      });
    }
    return result;
  } catch (error) {
    setFlowStage("Observability reset failed", error.message);
    if (!silent) {
      showNotice({
        kicker: "Observability",
        title: "Observability reset failed",
        message: error.message,
      });
    }
    throw error;
  }
}

playButton.addEventListener("click", (event) => {
  event.preventDefault();
  sceneModal.close();
  play();
});

semanticCacheSeedButton?.addEventListener("click", (event) => {
  event.preventDefault();
  sceneModal.close();
  play({ governance_scenario: "semantic_cache", semantic_cache_step: "seed" });
});

semanticCacheHitButton?.addEventListener("click", (event) => {
  event.preventDefault();
  sceneModal.close();
  play({ governance_scenario: "semantic_cache", semantic_cache_step: "reuse" });
});

piiSendButton?.addEventListener("click", (event) => {
  event.preventDefault();
  const selectedMode =
    document.querySelector('input[name="pii_mode_choice"]:checked')?.value || "placeholder";
  sceneModal.close();
  play({ governance_scenario: "pii_sanitizer", pii_sanitizer_mode: selectedMode });
});

semanticCacheClearButton?.addEventListener("click", async (event) => {
  event.preventDefault();
  await clearSemanticCache();
});

presetOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "scene_preset") {
    return;
  }
  applyScenePreset(target.value);
  if (activeScenario === "semantic_cache") {
    renderSemanticCachePayloads();
  }
  if (activeScenario === "pii_sanitizer") {
    renderPiiSanitizerPayloads();
  }
});

scenarioOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "scenario_choice") {
    return;
  }
  applyScenarioChoice(target.value);
  if (policyModal?.open) {
    renderPolicyModal();
  }
});

piiModeOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "pii_mode_choice") {
    return;
  }
  renderPiiSanitizerPayloads();
  if (policyModal?.open && activeScenario === "pii_sanitizer") {
    renderPolicyModal();
  }
});

llmJudgePromptOptions?.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.name !== "llm_judge_prompt_choice") {
    return;
  }
  renderLlmJudgePayload();
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

resetObservabilityButton?.addEventListener("click", async () => {
  const confirmed = window.confirm(
    "This will delete all Loki log data and restart Grafana. Continue?"
  );
  if (!confirmed) {
    return;
  }
  await resetObservability();
});

playForm.addEventListener("input", () => {
  if (activeScenario === "semantic_cache") {
    renderSemanticCachePayloads();
  }
  if (activeScenario === "semantic_guard") {
    renderSemanticGuardPayload();
  }
  if (activeScenario === "pii_sanitizer") {
    renderPiiSanitizerPayloads();
  }
});

clearLogButton.addEventListener("click", () => {
  resetTraceState();
});

runHistorySelect?.addEventListener("change", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }
  try {
    await loadRunTrace(target.value);
  } catch (error) {
    setFlowStage("Run load failed", error.message);
    showNotice({
      kicker: "Run History",
      title: "Could not load run",
      message: error.message,
    });
  }
});

sceneButton.addEventListener("click", () => sceneModal.showModal());
graphButton.addEventListener("click", () => graphModal.showModal());
outputButton.addEventListener("click", () => outputModal.showModal());
kongPolicyButton?.addEventListener("click", () => {
  renderPolicyModal();
  policyModal?.showModal();
});

connectTraceSocket();
void refreshRunHistory(undefined, { autoLoad: true });
applyScenePreset("acme_default");
applyScenarioChoice("normal");
resetTraceState();
setRunState("idle");
setFlowStage("Waiting for a run", "Press Play to see Kong route the request across AI, sub-agent, and MCP paths.");
