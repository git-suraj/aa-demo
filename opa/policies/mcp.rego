package aa_demo.mcp

default decision := {
  "allow": false,
  "status": 403,
  "message": "OPA denied this MCP request"
}

# The focused route is used by the success agent. The MCP protocol handshake
# and tool discovery remain available; OPA decides only the actual tool call.
decision := {"allow": true} if {
  input.consumer.username == "success-agent"
  input.request.http.parsed_body.method in {"initialize", "notifications/initialized", "tools/list"}
}

decision := {"allow": true} if {
  input.consumer.username == "success-agent"
  input.request.http.parsed_body.method == "tools/call"
  input.request.http.parsed_body.params.name == "draft_customer_reply"
}

# The second visible tool is intentionally denied. Kong returns this result
# directly, so the MCP upstream never receives the request.
decision := {
  "allow": false,
  "status": 403,
  "message": "OPA policy denies follow-up task creation for this agent"
} if {
  input.consumer.username == "success-agent"
  input.request.http.parsed_body.method == "tools/call"
  input.request.http.parsed_body.params.name == "create_followup_task"
}
