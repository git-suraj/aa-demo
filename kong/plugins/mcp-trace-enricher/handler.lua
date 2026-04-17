local McpTraceEnricher = {
  VERSION = "0.1.0",
  PRIORITY = 100,
}

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

function McpTraceEnricher:log(conf)
  local log_payload = kong.log.serialize() or {}
  local request = log_payload["request"] or {}
  local request_headers = request["headers"] or {}
  local ai = log_payload["ai"] or {}
  local mcp = ai["mcp"] or {}
  local rpc_entries = mcp["rpc"] or {}
  local mcp_entry = rpc_entries[1] or {}
  local mcp_payload = mcp_entry["payload"] or {}

  if next(mcp) == nil and next(mcp_entry) == nil then
    return
  end

  local attributes = {
    ["demo.run_id"] = request_headers["x-demo-run-id"] or request_headers["X-Demo-Run-Id"],
    ["demo.context_id"] = request_headers["x-demo-context-id"] or request_headers["X-Demo-Context-Id"],
    ["a2a.task_id"] = request_headers["x-demo-task-id"] or request_headers["X-Demo-Task-Id"],
    ["a2a.message_id"] = request_headers["x-demo-message-id"] or request_headers["X-Demo-Message-Id"],
    ["mcp.session_id"] = mcp["mcp_session_id"],
    ["mcp.request.id"] = mcp_entry["id"],
    ["mcp.method"] = mcp_entry["method"],
    ["mcp.tool_name"] = mcp_entry["tool_name"],
    ["mcp.error"] = mcp_entry["error"],
    ["mcp.latency_ms"] = mcp_entry["latency"],
    ["mcp.response_body_size"] = mcp_entry["response_body_size"],
  }

  if conf.include_payloads then
    attributes["mcp.request.payload"] = truncate(mcp_payload["request"], conf.payload_max_len)
    attributes["mcp.response.payload"] = truncate(mcp_payload["response"], conf.payload_max_len)
  end

  local root_span = kong.tracing.get_root_span and kong.tracing.get_root_span() or nil
  set_attributes(root_span, attributes)
  set_attributes(kong.tracing.active_span(), attributes)
end

return McpTraceEnricher
