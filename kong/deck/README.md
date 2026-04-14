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
- `ai-a2a-proxy` on the agent-to-agent routes for support and success handoffs

## Important

Treat `kong.yaml` as a near-final starter config. Before sync:

- validate the exact `ai-mcp-proxy` field names against the latest Kong docs for your control plane version
- confirm the Consumer Group mapping syntax accepted by your installed decK version
- replace the demo keys with environment-backed secrets
- provide the real Konnect control plane details and run `deck gateway validate` or `deck gateway sync`
