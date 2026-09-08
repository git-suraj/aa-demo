# AI Gateway 2.0 migration decisions

## Target

- AI Gateway control plane: `AA-Demo-2`
- Control plane ID: `47e9610a-2ad8-4b19-98d3-2b5364a7f38f`
- Management surface: AI Gateway 2.0 entities managed with `kongctl`

The native runtime inventory, including Model names, provider targets, and
policy attachments, is maintained in
[AI Gateway Models and policies](ai-gateway-models-and-policies.md).

## Gateway-layer prompt logging

Prompt logging remains a gateway responsibility. The AI Gateway 2.0 models and
logging policies must be configured to retain the request payloads required by
the demo, including requests evaluated by supported guard policies. Do not move
this responsibility into application-level audit logging for the initial
migration.

Validate this behavior for successful and blocked requests before cutover.

## Deferred custom-plugin parity

AI Gateway 2.0 custom-plugin support is not currently assumed. The following
main-branch custom plugins are deliberately out of the initial migration and
must be implemented when that capability becomes available:

| Main-branch plugin | Current purpose | Deferred v2 outcome |
| --- | --- | --- |
| `prompt-capture` | Captures a bounded inbound user prompt before AI policies run, so blocked semantic-guard requests can be logged with their input. | Restore the exact pre-policy prompt-capture fallback. |
| `trace-enricher` | Enriches Kong-side traces and logs with AI, MCP, A2A, and demo correlation data. | Restore enriched trace/log fields and the Loki trace-explorer data shape. |
| `workflow-graph` | Builds a synthetic workflow tree and exports it to Opik. | Restore workflow-graph export and the Opik workflow view. |

The initial v2 implementation must use only supported native AI Gateway
entities and policies. Native observability and gateway-level prompt payload
logging are required; custom-plugin-dependent enhancements are deferred rather
than reimplemented in application code.


## Konnect Observability

Konnect Observability for AI Gateway 2.0 is not yet functional, with a target to fix this by end of September 2026.


## Register MCP servers

Register MCP servers in the catalog and link to MCP server in the gateway

## Register agents

Register agents in the catalog and link to agents in the gateway
