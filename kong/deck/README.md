# decK Notes

This folder contains the declarative Kong config for the demo.

## Intended use

- Konnect is the control plane.
- The local `kong-dp` container is a hybrid data plane.
- Sync this config to Konnect with `deck gateway sync`.

## What the config includes

- services and routes for the orchestrator, both sub-agents, the backing REST API, and the MCP route
- `key-auth` for agent-facing routes
- 3 Consumers and 3 Consumer Groups
- per-tool ACL intent for the `ai-mcp-proxy` plugin on `/mock-mcp`
- `ai-a2a-proxy` on the support and success agent services
- Kong `http-log` shaping for Loki so A2A, MCP, and LLM fields are queryable in Grafana and the custom trace explorer

## Current A2A shape

The A2A configuration is currently intended to work like this:

- `support-agent-service`
  - route prefix: `/support-agent`
  - `key-auth`
  - `ai-a2a-proxy`
- `success-agent-service`
  - route prefix: `/success-agent`
  - `key-auth`
  - `ai-a2a-proxy`

This means the same Kong service scope handles:

- discovery:
  - `GET /.well-known/agent-card.json`
- execution:
  - `POST /a2a`

The A2A plugin is expected to:

- detect `agent/getCard` on `/.well-known/agent-card.json`
- rewrite `url` and `additionalInterfaces[].url` to the gateway address
- detect A2A execution methods such as:
  - `message/send`
  - `message/stream`
  - `tasks/get`
- emit A2A log fields into the `ai.a2a` namespace consumed by Kong log plugins

Current application behavior:

- support-agent and success-agent are implemented with `a2a-sdk[http-server]==0.3.26`
- SDK agent cards report protocol version `0.3.0`
- first `message/send` or `message/stream` requests should not include `taskId`; the SDK creates the task id
- streamed responses are SDK SSE events:
  - `status-update`
  - `artifact-update`

## Sync workflow

Typical workflow:

1. Validate YAML locally
2. Sync `kong.yaml` to Konnect
3. Generate fresh traffic
4. Verify:
   - discovery works through Kong
   - A2A task execution works through Kong
   - Loki receives flattened A2A/MCP/LLM fields

Useful commands:

```bash
deck gateway sync \
  --konnect-token "$KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONNECT_CONTROL_PLANE_NAME" \
  kong/deck/kong.yaml
```

```bash
curl -sS \
  -H 'apikey: orchestrator-demo-key' \
  http://localhost:8000/support-agent/.well-known/agent-card.json | jq
```

```bash
curl -N \
  -H 'apikey: orchestrator-demo-key' \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  http://localhost:8000/support-agent/a2a \
  --data '{
    "jsonrpc": "2.0",
    "id": "deck-readme-stream-001",
    "method": "message/stream",
    "params": {
      "contextId": "ctx-deck-readme-001",
      "message": {
        "kind": "message",
        "messageId": "msg-deck-readme-001",
        "role": "user",
        "contextId": "ctx-deck-readme-001",
        "parts": [
          {
            "kind": "text",
            "text": "{\"run_id\":\"deck-readme-run-001\",\"context_id\":\"ctx-deck-readme-001\",\"customer_id\":\"cust_acme\",\"account_name\":\"Acme Health\",\"product_issue\":\"workflow agent sync delays\",\"incident_id\":\"INC-1007\",\"triage_brief\":\"Investigate the incident, verify impact, and provide next steps.\"}"
          }
        ]
      }
    }
  }'
```

## Important

Treat `kong.yaml` as a near-final starter config. Before sync:

- validate the exact `ai-mcp-proxy` field names against the latest Kong docs for your control plane version
- validate the exact `ai-a2a-proxy` field names and behavior against the installed 3.14 control plane version
- confirm the Consumer Group mapping syntax accepted by your installed decK version
- replace the demo keys with environment-backed secrets
- provide the real Konnect control plane details and run `deck gateway validate` or `deck gateway sync`
