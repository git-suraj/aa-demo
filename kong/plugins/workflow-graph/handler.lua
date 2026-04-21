local http = require "resty.http"
local cjson = require "cjson.safe"

local WorkflowGraph = {
  VERSION = "0.2.0",
  PRIORITY = 101,
}

local RELATION_CACHE = ngx.shared.workflow_graph

local function truncate(value, max_len)
  if value == nil then
    return nil
  end

  local str = tostring(value)
  if max_len <= 0 or #str <= max_len then
    return str
  end

  return string.sub(str, 1, max_len) .. "...(truncated)"
end

local function set_attributes(span, attributes)
  if not span then
    return
  end

  for key, value in pairs(attributes) do
    if value ~= nil and value ~= "" then
      span:set_attribute(key, tostring(value))
    end
  end
end

local function relation_key(run_id, branch_id)
  if not run_id or run_id == "" or not branch_id or branch_id == "" then
    return nil
  end

  return "workflow:" .. tostring(run_id) .. ":" .. tostring(branch_id)
end

local function encode_json(value)
  if value == nil then
    return nil
  end

  local encoded = cjson.encode(value)
  if encoded == nil then
    kong.log.err("workflow-graph: failed to encode JSON payload")
  end

  return encoded
end

local function decode_json(value)
  if type(value) == "table" then
    return value
  end
  if type(value) ~= "string" or value == "" then
    return nil
  end

  return cjson.decode(value)
end

local function store_relation(run_id, branch_id, relation_value, ttl)
  if not RELATION_CACHE then
    return
  end

  local key = relation_key(run_id, branch_id)
  local encoded = encode_json(relation_value)
  if not key or not encoded then
    return
  end

  RELATION_CACHE:set(key, encoded, ttl)
end

local function load_relation(run_id, branch_id)
  if not RELATION_CACHE then
    return nil
  end

  local key = relation_key(run_id, branch_id)
  if not key then
    return nil
  end

  return decode_json(RELATION_CACHE:get(key))
end

local function format_uuid_from_hex(hex)
  if not hex or #hex ~= 32 then
    return nil
  end

  local versioned = table.concat({
    string.sub(hex, 1, 12),
    "7",
    string.sub(hex, 14, 16),
    "8",
    string.sub(hex, 18, 32),
  })

  return string.format(
    "%s-%s-%s-%s-%s",
    string.sub(versioned, 1, 8),
    string.sub(versioned, 9, 12),
    string.sub(versioned, 13, 16),
    string.sub(versioned, 17, 20),
    string.sub(versioned, 21, 32)
  )
end

local function deterministic_uuid(value)
  if not value or value == "" then
    return nil
  end

  if tostring(value):match("^[0-9a-fA-F]{8}%-%x%x%x%x%-7%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$") then
    return string.lower(value)
  end

  local normalized = tostring(value):gsub("-", "")
  if normalized:match("^[0-9a-fA-F]{32}$") then
    return string.lower(format_uuid_from_hex(normalized))
  end

  return string.lower(format_uuid_from_hex(ngx.md5(tostring(value))))
end

local function iso8601(epoch_seconds)
  local safe_value = tonumber(epoch_seconds) or ngx.now()
  local seconds = math.floor(safe_value)
  local millis = math.floor((safe_value - seconds) * 1000)
  return os.date("!%Y-%m-%dT%H:%M:%S", seconds) .. string.format(".%03dZ", millis)
end

local function workflow_root_node_id(run_id)
  if not run_id or run_id == "" then
    return nil
  end

  return "workflow." .. tostring(run_id)
end

local function workflow_root_span_id(run_id)
  return deterministic_uuid("root:" .. tostring(run_id or ""))
end

local function agent_node_id(actor, branch_id)
  if not actor or actor == "" or not branch_id or branch_id == "" then
    return nil
  end

  return tostring(actor) .. ".agent." .. tostring(branch_id)
end

local function agent_span_id(actor, branch_id)
  local node_id = agent_node_id(actor, branch_id)
  if not node_id then
    return nil
  end

  return deterministic_uuid(node_id)
end

local function semantic_span_name(attributes)
  local kind = attributes["workflow.kind"]
  local actor = attributes["workflow.actor"]
  local label = attributes["workflow.label"]

  if kind == "workflow" then
    return label or "workflow run"
  end

  if kind == "handoff" then
    if actor and actor ~= "" then
      return actor .. " handoff"
    end
    return label or "handoff"
  end

  if kind == "tool" then
    local tool_name = attributes["mcp.tool_name"] or label or "tool"
    if actor and actor ~= "" then
      return actor .. " tool: " .. tostring(tool_name)
    end
    return "tool: " .. tostring(tool_name)
  end

  if kind == "llm" then
    local model = attributes["llm.response_model"] or attributes["llm.request_model"] or label or "llm"
    if actor and actor ~= "" then
      return actor .. " llm: " .. tostring(model)
    end
    return "llm: " .. tostring(model)
  end

  return label or kind or "workflow-node"
end

local function create_semantic_span(parent_span, attributes)
  if not kong.tracing or not kong.tracing.start_span then
    return nil
  end

  local previous_active = kong.tracing.active_span and kong.tracing.active_span() or nil

  if parent_span and kong.tracing.set_active_span then
    kong.tracing.set_active_span(parent_span)
  end

  local span = kong.tracing.start_span(semantic_span_name(attributes))

  if previous_active and kong.tracing.set_active_span then
    kong.tracing.set_active_span(previous_active)
  end

  if not span then
    return nil
  end

  set_attributes(span, attributes)
  span:finish()

  return span
end

local function derive_actor(request_headers, service_name, route_name, run_id, branch_id)
  local actor = request_headers["x-demo-actor"] or request_headers["X-Demo-Actor"]
  if actor and actor ~= "" then
    return actor
  end

  if service_name == "support-agent-service" then
    return "support-agent"
  end
  if service_name == "success-agent-service" then
    return "success-agent"
  end
  if service_name == "orchestrator-service" or string.sub(service_name or "", 1, 16) == "ai-orchestrator-" then
    return "orchestrator"
  end

  if (service_name == "ai-subagent-service" or route_name == "mock-mcp-route") and branch_id and branch_id ~= "" then
    local relation = load_relation(run_id, branch_id)
    if relation and relation["actor"] and relation["actor"] ~= "" then
      return relation["actor"]
    end
  end

  if service_name == "ai-subagent-service" then
    return "subagent"
  end
  if route_name == "mock-mcp-route" then
    return branch_id and branch_id ~= "" and "subagent" or "orchestrator"
  end

  return nil
end

local function hydrate_common_attributes(request_headers)
  return {
    ["demo.run_id"] = request_headers["x-demo-run-id"] or request_headers["X-Demo-Run-Id"],
    ["demo.context_id"] = request_headers["x-demo-context-id"] or request_headers["X-Demo-Context-Id"],
    ["a2a.task_id"] = request_headers["x-demo-task-id"] or request_headers["X-Demo-Task-Id"],
    ["a2a.message_id"] = request_headers["x-demo-message-id"] or request_headers["X-Demo-Message-Id"],
  }
end

local function enrich_mcp(attributes, ai, conf)
  local mcp = ai["mcp"] or {}
  local rpc_entries = mcp["rpc"] or {}
  local entry = rpc_entries[1] or {}
  local payload = entry["payload"] or {}

  if next(mcp) == nil and next(entry) == nil then
    return false
  end

  attributes["mcp.session_id"] = mcp["mcp_session_id"]
  attributes["mcp.request.id"] = entry["id"]
  attributes["mcp.method"] = entry["method"]
  attributes["mcp.tool_name"] = entry["tool_name"]
  attributes["mcp.error"] = entry["error"]
  attributes["mcp.latency_ms"] = entry["latency"]
  attributes["mcp.response_body_size"] = entry["response_body_size"]
  if conf.include_payloads then
    attributes["mcp.request.payload"] = truncate(payload["request"], conf.payload_max_len)
    attributes["mcp.response.payload"] = truncate(payload["response"], conf.payload_max_len)
  end

  return true
end

local function enrich_a2a(attributes, ai, conf)
  local a2a = ai["a2a"] or {}
  local rpc_entries = a2a["rpc"] or {}
  local entry = rpc_entries[1] or {}
  local payload = entry["payload"] or {}

  if next(a2a) == nil and next(entry) == nil then
    return false
  end

  attributes["a2a.method"] = entry["method"]
  attributes["a2a.request.id"] = entry["id"]
  attributes["a2a.error"] = entry["error"]
  attributes["a2a.latency_ms"] = entry["latency"]
  attributes["a2a.response_body_size"] = entry["response_body_size"]
  if conf.include_payloads then
    attributes["a2a.request.payload"] = truncate(payload["request"], conf.payload_max_len)
    attributes["a2a.response.payload"] = truncate(payload["response"], conf.payload_max_len)
  end

  return true
end

local function enrich_llm(attributes, ai, conf)
  local proxy = ai["proxy"] or {}
  local meta = proxy["meta"] or {}
  local usage = proxy["usage"] or {}
  local payload = proxy["payload"] or {}

  if next(proxy) == nil and next(meta) == nil then
    return false
  end

  attributes["llm.provider"] = meta["provider_name"]
  attributes["llm.request_model"] = meta["request_model"]
  attributes["llm.response_model"] = meta["response_model"]
  attributes["llm.latency_ms"] = meta["llm_latency"]
  attributes["llm.prompt_tokens"] = usage["prompt_tokens"] or usage["input_tokens"]
  attributes["llm.completion_tokens"] = usage["completion_tokens"] or usage["output_tokens"]
  attributes["llm.total_tokens"] = usage["total_tokens"]
  attributes["llm.cost"] = usage["cost"]
  if conf.include_payloads then
    attributes["llm.request.payload"] = truncate(payload["request"], conf.payload_max_len)
    attributes["llm.response.payload"] = truncate(payload["response"], conf.payload_max_len)
  end

  return true
end

local function apply_workflow_attributes(attributes, request, request_headers, log_payload, has_mcp, has_a2a, has_llm, conf)
  local service = log_payload["service"] or {}
  local route = log_payload["route"] or {}
  local service_name = service["name"] or ""
  local route_name = route["name"] or ""
  local run_id = attributes["demo.run_id"]
  local task_id = attributes["a2a.task_id"]
  local message_id = attributes["a2a.message_id"]
  local request_id = request["id"] or ""
  local root_id = workflow_root_node_id(run_id)
  local root_span_id = workflow_root_span_id(run_id)

  if not run_id or run_id == "" then
    return false
  end

  if service_name == "orchestrator-service" and (request["uri"] == "/play" or request["uri"] == "/orchestrator/play") then
    attributes["workflow.run_id"] = run_id
    attributes["workflow.kind"] = "workflow"
    attributes["workflow.actor"] = "orchestrator"
    attributes["workflow.label"] = "Workflow run"
    attributes["workflow.node_id"] = root_id
    attributes["workflow.span_id"] = root_span_id
    return true
  end

  local branch_id = task_id
  if not branch_id or branch_id == "" then
    branch_id = message_id
  end

  local actor = derive_actor(request_headers, service_name, route_name, run_id, branch_id)

  if has_a2a then
    local handoff_branch = branch_id
    if not handoff_branch or handoff_branch == "" then
      handoff_branch = attributes["a2a.request.id"] or request_id
    end

    local agent_node = agent_node_id(actor or "agent", handoff_branch)
    local agent_span = agent_span_id(actor or "agent", handoff_branch)
    local node_id = tostring(actor or "agent") .. ".handoff." .. tostring(handoff_branch) .. "." .. tostring(attributes["a2a.method"] or request_id)
    local span_id = deterministic_uuid(node_id)
    local relation = {
      actor = actor,
      branch_id = handoff_branch,
      node_id = agent_node,
      span_id = agent_span,
      handoff_node_id = node_id,
      handoff_span_id = span_id,
    }

    attributes["workflow.run_id"] = run_id
    attributes["workflow.kind"] = "handoff"
    attributes["workflow.actor"] = actor
    attributes["workflow.label"] = tostring(actor or "agent") .. " handoff"
    attributes["workflow.branch_id"] = handoff_branch
    attributes["workflow.agent_node_id"] = agent_node
    attributes["workflow.agent_span_id"] = agent_span
    attributes["workflow.node_id"] = node_id
    attributes["workflow.span_id"] = span_id
    attributes["workflow.parent_node_id"] = agent_node
    attributes["workflow.parent_span_id"] = agent_span
    store_relation(run_id, handoff_branch, relation, conf.relation_ttl_seconds)
    if message_id and message_id ~= "" and message_id ~= handoff_branch then
      store_relation(run_id, message_id, relation, conf.relation_ttl_seconds)
    end
    return true
  end

  if has_mcp or has_llm then
    local parent_relation = load_relation(run_id, branch_id)
    local parent_node_id = parent_relation and parent_relation["node_id"] or root_id
    local parent_span_id = parent_relation and parent_relation["span_id"] or root_span_id
    local span_name_key = nil
    local span_label = nil
    local kind = nil

    if has_mcp then
      kind = "tool"
      span_label = attributes["mcp.tool_name"] or attributes["mcp.method"] or "tool"
      span_name_key = tostring(actor or "agent") .. ".tool." .. tostring(span_label) .. "." .. tostring(request_id)
    else
      kind = "llm"
      span_label = route_name ~= "" and route_name or "chat-completions"
      span_name_key = tostring(actor or "agent") .. ".llm." .. tostring(span_label) .. "." .. tostring(request_id)
    end

    attributes["workflow.run_id"] = run_id
    attributes["workflow.kind"] = kind
    attributes["workflow.actor"] = actor
    attributes["workflow.label"] = span_label
    attributes["workflow.branch_id"] = branch_id
    attributes["workflow.agent_node_id"] = parent_relation and parent_relation["node_id"] or nil
    attributes["workflow.agent_span_id"] = parent_relation and parent_relation["span_id"] or nil
    attributes["workflow.node_id"] = span_name_key
    attributes["workflow.span_id"] = deterministic_uuid(span_name_key)
    attributes["workflow.parent_node_id"] = parent_node_id
    attributes["workflow.parent_span_id"] = parent_span_id
    return true
  end

  return false
end

local function request_start_end_times(attributes)
  local now_seconds = ngx.now()
  local latency_ms = tonumber(attributes["mcp.latency_ms"] or attributes["a2a.latency_ms"] or attributes["llm.latency_ms"] or 0) or 0
  local start_seconds = now_seconds - (latency_ms / 1000)
  return iso8601(start_seconds), iso8601(now_seconds)
end

local function request_input_output(attributes)
  if attributes["workflow.kind"] == "tool" then
    return attributes["mcp.request.payload"], attributes["mcp.response.payload"]
  end
  if attributes["workflow.kind"] == "agent" then
    return nil, nil
  end
  if attributes["workflow.kind"] == "handoff" then
    return attributes["a2a.request.payload"], attributes["a2a.response.payload"]
  end
  if attributes["workflow.kind"] == "llm" then
    return attributes["llm.request.payload"], attributes["llm.response.payload"]
  end
  return nil, nil
end

local function usage_payload(attributes)
  if attributes["workflow.kind"] ~= "llm" then
    return nil
  end

  local usage = {}
  local prompt_tokens = tonumber(attributes["llm.prompt_tokens"])
  local completion_tokens = tonumber(attributes["llm.completion_tokens"])
  local total_tokens = tonumber(attributes["llm.total_tokens"])

  if prompt_tokens then
    usage["prompt_tokens"] = prompt_tokens
  end
  if completion_tokens then
    usage["completion_tokens"] = completion_tokens
  end
  if total_tokens then
    usage["total_tokens"] = total_tokens
  end

  return next(usage) and usage or nil
end

local function filtered_metadata(attributes)
  local metadata = {}
  for key, value in pairs(attributes) do
    if value ~= nil and value ~= "" then
      metadata[key] = value
    end
  end
  return metadata
end

local function span_type(kind)
  if kind == "tool" then
    return "tool"
  end
  if kind == "llm" then
    return "llm"
  end
  return "general"
end

local function opik_request(conf, method, path, payload)
  local client = http.new()
  client:set_timeout(conf.timeout_ms)

  local res, err = client:request_uri(conf.opik_api_base_url .. path, {
    method = method,
    body = encode_json(payload),
    headers = {
      ["Content-Type"] = "application/json",
    },
    keepalive = false,
  })

  if not res then
    kong.log.err("workflow-graph: Opik request failed: ", tostring(err))
    return nil, err
  end

  if res.status >= 200 and res.status < 300 then
    return res, nil
  end

  if res.status == 409 then
    return res, "conflict"
  end

  kong.log.err("workflow-graph: Opik request returned ", tostring(res.status), ": ", tostring(res.body))
  return res, tostring(res.status)
end

local function upsert_trace(conf, trace_id, payload)
  local res, err = opik_request(conf, "POST", "/traces", payload)
  if err ~= "conflict" then
    return res, err
  end

  local patch_payload = {
    project_name = payload.project_name,
    name = payload.name,
    end_time = payload.end_time,
    input = payload.input,
    output = payload.output,
    metadata = payload.metadata,
    tags = payload.tags,
    thread_id = payload.thread_id,
  }
  return opik_request(conf, "PATCH", "/traces/" .. trace_id, patch_payload)
end

local function upsert_span(conf, span_id, payload)
  local res, err = opik_request(conf, "POST", "/spans", payload)
  if err ~= "conflict" then
    return res, err
  end

  local patch_payload = {
    trace_id = payload.trace_id,
    project_name = payload.project_name,
    parent_span_id = payload.parent_span_id,
    name = payload.name,
    type = payload.type,
    end_time = payload.end_time,
    input = payload.input,
    output = payload.output,
    metadata = payload.metadata,
    model = payload.model,
    provider = payload.provider,
    tags = payload.tags,
    usage = payload.usage,
    total_estimated_cost = payload.total_estimated_cost,
    ttft = payload.ttft,
  }
  return opik_request(conf, "PATCH", "/spans/" .. span_id, patch_payload)
end

local function export_to_opik(conf, attributes)
  if not conf.export_directly then
    return
  end

  local run_id = attributes["workflow.run_id"]
  local trace_id = deterministic_uuid(run_id)
  local root_span_id = workflow_root_span_id(run_id)
  local context_id = attributes["demo.context_id"]
  local start_time, end_time = request_start_end_times(attributes)
  local input_payload, output_payload = request_input_output(attributes)
  local semantic_span_id = attributes["workflow.span_id"]
  local semantic_kind = attributes["workflow.kind"]
  local semantic_name = semantic_span_name(attributes)
  local metadata = filtered_metadata(attributes)

  if not trace_id or not root_span_id or not semantic_span_id then
    return
  end

  upsert_trace(conf, trace_id, {
    id = trace_id,
    project_name = conf.project_name,
    name = "Workflow run",
    start_time = start_time,
    end_time = end_time,
    input = {
      run_id = run_id,
      context_id = context_id,
    },
    metadata = {
      ["workflow.run_id"] = run_id,
      ["demo.context_id"] = context_id,
    },
    tags = { "workflow", "kong" },
    thread_id = context_id,
  })

  upsert_span(conf, root_span_id, {
    id = root_span_id,
    trace_id = trace_id,
    project_name = conf.project_name,
    name = "workflow run",
    type = "general",
    start_time = start_time,
    end_time = end_time,
    input = {
      run_id = run_id,
      context_id = context_id,
    },
    metadata = {
      ["workflow.kind"] = "workflow",
      ["workflow.node_id"] = workflow_root_node_id(run_id),
      ["workflow.run_id"] = run_id,
      ["demo.context_id"] = context_id,
    },
    tags = { "workflow", "kong", "root" },
  })

  local branch_agent_span_id = attributes["workflow.agent_span_id"]
  local branch_agent_node_id = attributes["workflow.agent_node_id"]
  local branch_id = attributes["workflow.branch_id"]
  local actor = attributes["workflow.actor"]

  if branch_agent_span_id and branch_agent_node_id and branch_id and actor and actor ~= "" then
    upsert_span(conf, branch_agent_span_id, {
      id = branch_agent_span_id,
      trace_id = trace_id,
      parent_span_id = root_span_id,
      project_name = conf.project_name,
      name = tostring(actor) .. " agent",
      type = "general",
      start_time = start_time,
      end_time = end_time,
      metadata = {
        ["workflow.kind"] = "agent",
        ["workflow.run_id"] = run_id,
        ["workflow.actor"] = actor,
        ["workflow.branch_id"] = branch_id,
        ["workflow.node_id"] = branch_agent_node_id,
        ["workflow.parent_node_id"] = workflow_root_node_id(run_id),
      },
      tags = { "kong", "agent", tostring(actor) },
    })
  end

  if semantic_kind == "workflow" then
    return
  end

  upsert_span(conf, semantic_span_id, {
    id = semantic_span_id,
    trace_id = trace_id,
    parent_span_id = attributes["workflow.parent_span_id"] or root_span_id,
    project_name = conf.project_name,
    name = semantic_name,
    type = span_type(semantic_kind),
    start_time = start_time,
    end_time = end_time,
    input = input_payload,
    output = output_payload,
    metadata = metadata,
    model = attributes["llm.response_model"] or attributes["llm.request_model"],
    provider = attributes["llm.provider"],
    tags = {
      "kong",
      tostring(semantic_kind),
      tostring(attributes["workflow.actor"] or "unknown"),
    },
    usage = usage_payload(attributes),
    total_estimated_cost = tonumber(attributes["llm.cost"]),
    ttft = tonumber(attributes["llm.latency_ms"]),
  })
end

local function schedule_export(conf, attributes)
  if not conf.export_directly or not ngx.timer or not ngx.timer.at then
    return
  end

  local conf_copy = {
    export_directly = conf.export_directly,
    opik_api_base_url = conf.opik_api_base_url,
    project_name = conf.project_name,
    timeout_ms = conf.timeout_ms,
  }

  local attrs_copy = {}
  for key, value in pairs(attributes) do
    attrs_copy[key] = value
  end

  local ok, err = ngx.timer.at(0, function(premature, timer_conf, timer_attributes)
    if premature then
      return
    end
    export_to_opik(timer_conf, timer_attributes)
  end, conf_copy, attrs_copy)

  if not ok then
    kong.log.err("workflow-graph: failed to schedule Opik export: ", tostring(err))
  end
end

function WorkflowGraph:log(conf)
  local log_payload = kong.log.serialize() or {}
  local request = log_payload["request"] or {}
  local request_headers = request["headers"] or {}
  local ai = log_payload["ai"] or {}

  local attributes = hydrate_common_attributes(request_headers)
  local has_mcp = enrich_mcp(attributes, ai, conf)
  local has_a2a = enrich_a2a(attributes, ai, conf)
  local has_llm = enrich_llm(attributes, ai, conf)
  local has_workflow = apply_workflow_attributes(attributes, request, request_headers, log_payload, has_mcp, has_a2a, has_llm, conf)

  if not has_workflow then
    return
  end

  local root_span = kong.tracing.get_root_span and kong.tracing.get_root_span() or nil
  local active_span = kong.tracing.active_span and kong.tracing.active_span() or nil

  set_attributes(root_span, attributes)
  set_attributes(active_span, attributes)
  create_semantic_span(root_span or active_span, attributes)
  schedule_export(conf, attributes)
end

return WorkflowGraph
