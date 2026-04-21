local TraceEnricher = {
  VERSION = "0.2.0",
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


local function enrich_mcp(attributes, ai, conf)
  local mcp = ai["mcp"] or {}
  local rpc_entries = mcp["rpc"] or {}
  local mcp_entry = rpc_entries[1] or {}
  local mcp_payload = mcp_entry["payload"] or {}

  if next(mcp) == nil and next(mcp_entry) == nil then
    return false
  end

  attributes["mcp.session_id"] = mcp["mcp_session_id"]
  attributes["mcp.request.id"] = mcp_entry["id"]
  attributes["mcp.method"] = mcp_entry["method"]
  attributes["mcp.tool_name"] = mcp_entry["tool_name"]
  attributes["mcp.error"] = mcp_entry["error"]
  attributes["mcp.latency_ms"] = mcp_entry["latency"]
  attributes["mcp.response_body_size"] = mcp_entry["response_body_size"]

  if conf.include_payloads then
    attributes["mcp.request.payload"] = truncate(mcp_payload["request"], conf.payload_max_len)
    attributes["mcp.response.payload"] = truncate(mcp_payload["response"], conf.payload_max_len)
  end

  return true
end

local function enrich_a2a(attributes, ai, conf)
  local a2a = ai["a2a"] or {}
  local rpc_entries = a2a["rpc"] or {}
  local a2a_entry = rpc_entries[1] or {}
  local a2a_payload = a2a_entry["payload"] or {}

  if next(a2a) == nil and next(a2a_entry) == nil then
    return false
  end

  attributes["a2a.method"] = a2a_entry["method"]
  attributes["a2a.request.id"] = a2a_entry["id"]
  attributes["a2a.error"] = a2a_entry["error"]
  attributes["a2a.latency_ms"] = a2a_entry["latency"]
  attributes["a2a.response_body_size"] = a2a_entry["response_body_size"]

  if conf.include_payloads then
    attributes["a2a.request.payload"] = truncate(a2a_payload["request"], conf.payload_max_len)
    attributes["a2a.response.payload"] = truncate(a2a_payload["response"], conf.payload_max_len)
  end

  return true
end

local function enrich_llm(attributes, ai, conf)
  if not conf.include_llm then
    return false
  end

  local proxy = ai["proxy"] or {}
  local proxy_meta = proxy["meta"] or {}
  local proxy_usage = proxy["usage"] or {}
  local proxy_payload = proxy["payload"] or {}

  if next(proxy) == nil and next(proxy_meta) == nil then
    return false
  end

  attributes["llm.provider"] = proxy_meta["provider_name"]
  attributes["llm.request_model"] = proxy_meta["request_model"]
  attributes["llm.response_model"] = proxy_meta["response_model"]
  attributes["llm.latency_ms"] = proxy_meta["llm_latency"]
  attributes["llm.prompt_tokens"] = proxy_usage["prompt_tokens"] or proxy_usage["input_tokens"]
  attributes["llm.completion_tokens"] = proxy_usage["completion_tokens"] or proxy_usage["output_tokens"]
  attributes["llm.total_tokens"] = proxy_usage["total_tokens"]
  attributes["llm.cost"] = proxy_usage["cost"]

  if conf.include_payloads then
    attributes["llm.request.payload"] = truncate(proxy_payload["request"], conf.payload_max_len)
    attributes["llm.response.payload"] = truncate(proxy_payload["response"], conf.payload_max_len)
  end

  return true
end

function TraceEnricher:log(conf)
  local log_payload = kong.log.serialize() or {}
  local ai = log_payload["ai"] or {}

  local attributes = {}

  local has_mcp = enrich_mcp(attributes, ai, conf)
  local has_a2a = enrich_a2a(attributes, ai, conf)
  local has_llm = enrich_llm(attributes, ai, conf)

  if not has_mcp and not has_a2a and not has_llm then
    return
  end

  local root_span = kong.tracing.get_root_span and kong.tracing.get_root_span() or nil
  set_attributes(root_span, attributes)
  set_attributes(kong.tracing.active_span(), attributes)
end

return TraceEnricher
