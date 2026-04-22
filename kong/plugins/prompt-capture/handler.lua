local cjson = require("cjson.safe")

local PromptCaptureHandler = {
  VERSION = "0.1.0",
  PRIORITY = 1000000,
}

local function extract_request_text(messages)
  if type(messages) ~= "table" then
    return ""
  end

  local parts = {}

  for _, message in ipairs(messages) do
    local role = type(message) == "table" and tostring(message.role or "") or ""
    if role == "user" then
      local content = type(message) == "table" and message.content or nil
      if type(content) == "string" and content ~= "" then
        table.insert(parts, content)
      elseif type(content) == "table" then
        local nested = {}
        for _, item in ipairs(content) do
          if type(item) == "table" and item.type == "text" and item.text then
            table.insert(nested, tostring(item.text))
          end
        end
        if #nested > 0 then
          table.insert(parts, table.concat(nested, " "))
        end
      end
    end
  end

  return table.concat(parts, "\n\n")
end

local function decode_body(raw_body)
  if type(raw_body) ~= "string" or raw_body == "" then
    return nil
  end

  local decoded = cjson.decode(raw_body)
  if type(decoded) == "table" then
    return decoded
  end

  return nil
end

local function read_request_body()
  ngx.req.read_body()

  local raw_body = ngx.req.get_body_data()
  if raw_body and raw_body ~= "" then
    return raw_body
  end

  local body_file = ngx.req.get_body_file()
  if type(body_file) ~= "string" or body_file == "" then
    return nil
  end

  local file, err = io.open(body_file, "rb")
  if not file then
    kong.log.warn("prompt-capture: failed to open buffered body file: ", err)
    return nil
  end

  local file_body = file:read("*a")
  file:close()
  return file_body
end

function PromptCaptureHandler:access(conf)
  local raw_body = read_request_body()
  local decoded = decode_body(raw_body)
  if type(decoded) ~= "table" then
    return
  end

  local prompt = extract_request_text(decoded.messages or decoded)
  if prompt == "" then
    return
  end

  if conf.payload_max_len > 0 and #prompt > conf.payload_max_len then
    prompt = prompt:sub(1, conf.payload_max_len)
  end

  kong.ctx.shared.demo_input_prompt = prompt
end

return PromptCaptureHandler
