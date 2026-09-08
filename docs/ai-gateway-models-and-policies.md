# AI Gateway Models and policies

This is the runtime reference for the native AI Gateway 2.0 configuration in
`kongctl/ai-gateway`. An AI Gateway Model owns the route, accepted request
format, provider targets, balancer, payload logging, and access policy. A
policy is attached to a Model only when that route needs additional behavior.

All Models use the `demo-key-auth` identity provider. The three agent
Consumers also have the `aa-demo-2-agent-llm-metering` Metering and Billing
policy attached, so usage is attributed to `aa-demo-2-orchestrator`,
`aa-demo-2-support-agent`, or `aa-demo-2-success-agent`.

## Provider targets

| Provider | Target model |
| --- | --- |
| OpenAI | `gpt-4o-mini` |
| OpenAI | `o3-mini` |
| Gemini | `gemini-2.5-flash` |

## Models and attached policies

| Route path | AI Gateway Model | Provider targets | Attached policy |
| --- | --- | --- | --- |
| `/ai/orchestrator` | `ai-orchestrator-chat-route` | `gpt-4o-mini`, `gemini-2.5-flash` | None |
| `/ai/subagent` | `ai-subagent-chat-route` | `gemini-2.5-flash` | None |
| `/ai/orchestrator-failover-demo` | `ai-orchestrator-failover-demo-chat-route` | `gpt-4o-mini`, `gemini-2.5-flash` | None |
| `/llm-failure-simulator` | `ai-orchestrator-failover-simulator-route` | `gpt-4o-mini`, `gemini-2.5-flash` | `request-termination` |
| `/ai/orchestrator-semantic-load-balance-demo` | `ai-orchestrator-semantic-load-balance-demo-chat-route` | `gpt-4o-mini`, `gemini-2.5-flash` | None. The Model uses its native semantic balancer with Redis and `text-embedding-3-small`. |
| `/ai/orchestrator-model-based-demo` | `model-based-router` | `gpt-4o-mini` | `datakit` |
| `/ai/orchestrator-model-selector` | `ai-orchestrator-model-selector-chat-route` | `o3-mini` | `ai-prompt-decorator` |
| `/ai/orchestrator-model-based-complex` | `complex` | `gpt-4o-mini` | None |
| `/ai/orchestrator-model-based-simple` | `simple` | `gemini-2.5-flash` | None |
| `/ai/orchestrator-token-demo` | `ai-orchestrator-token-demo-chat-route` | `gpt-4o-mini` | `ai-rate-limiting-advanced-3` |
| `/ai/orchestrator-consumer-cost-demo` | `ai-orchestrator-consumer-cost-demo-chat-route` | `gpt-4o-mini` | `ai-rate-limiting-advanced` or `ai-rate-limiting-advanced-2`, attached through the selected Consumer |
| `/ai/orchestrator-prompt-enhance-demo` | `ai-orchestrator-prompt-enhance-demo-chat-route` | `gpt-4o-mini` | `ai-prompt-decorator-2` |
| `/ai/orchestrator-prompt-enhance-plain-demo` | `ai-orchestrator-prompt-enhance-plain-demo-chat-route` | `gpt-4o-mini` | None |
| `/ai/orchestrator-prompt-compress-ratio-demo` | `ai-orchestrator-prompt-compress-ratio-demo-chat-route` | `gpt-4o-mini` | `ai-prompt-compressor` |
| `/ai/orchestrator-prompt-compress-token-demo` | `ai-orchestrator-prompt-compress-token-demo-chat-route` | `gpt-4o-mini` | `ai-prompt-compressor-2` |
| `/ai/orchestrator-semantic-guard-demo` | `ai-orchestrator-semantic-guard-demo-chat-route` | `gpt-4o-mini` | `ai-semantic-prompt-guard` |
| `/ai/orchestrator-semantic-cache-demo` | `ai-orchestrator-semantic-cache-demo-chat-route` | `gpt-4o-mini` | `ai-semantic-cache` |
| `/ai/orchestrator-rag-before-demo` | `ai-orchestrator-rag-before-demo-chat-route` | `gpt-4o-mini` | None |
| `/ai/orchestrator-rag-after-demo` | `ai-orchestrator-rag-after-demo-chat-route` | `gpt-4o-mini` | `ai-rag-injector` |
| `/ai/orchestrator-pii-block-demo` | `ai-orchestrator-pii-block-demo-chat-route` | `gpt-4o-mini` | `ai-sanitizer` |
| `/ai/orchestrator-pii-placeholder-demo` | `ai-orchestrator-pii-placeholder-demo-chat-route` | `gpt-4o-mini` | `ai-sanitizer-2` |
| `/ai/orchestrator-pii-synthetic-demo` | `ai-orchestrator-pii-synthetic-demo-chat-route` | `gpt-4o-mini` | `ai-sanitizer-3` |
| `/ai/orchestrator-judge-demo` | `ai-orchestrator-judge-demo-chat-route` | `gpt-4o-mini` | `ai-llm-as-judge`, which uses `gemini-2.5-flash` as the judge |
| `/ai/orchestrator-lakera-demo` | `ai-orchestrator-lakera-demo-chat-route` | `gpt-4o-mini` | `ai-lakera-guard` |

The Model-based Routing flow makes two native AI Gateway calls. `datakit` calls
the selector Model, which returns `simple` or `complex`, then calls the
corresponding final Model. It forwards the original API key on both calls so
Metering and Billing preserves the initiating agent identity.

## Policy catalog

| Policy | Purpose |
| --- | --- |
| `aa-demo-2-agent-llm-metering` | Emits `kong.llm_request` token events by Consumer, model, and request or response token type. |
| `ai-rate-limiting-advanced`, `ai-rate-limiting-advanced-2`, `ai-rate-limiting-advanced-3` | Enforce the consumer-cost and token-limit demonstrations. |
| `datakit` | Runs the selector and final-model calls for model-based routing. |
| `ai-prompt-decorator`, `ai-prompt-decorator-2` | Adds selector or executive-output instructions. |
| `ai-prompt-compressor`, `ai-prompt-compressor-2` | Compresses prompts by ratio or target token count. |
| `ai-semantic-prompt-guard`, `ai-semantic-cache`, `ai-rag-injector` | Apply the Redis-backed semantic guard, cache, and RAG scenarios. |
| `ai-sanitizer`, `ai-sanitizer-2`, `ai-sanitizer-3` | Demonstrate blocking, placeholder, and synthetic PII handling. |
| `ai-llm-as-judge` | Scores the candidate response with Gemini. |
| `ai-lakera-guard` | Sends prompts to Lakera for allow-or-block inspection. |
| `request-termination` | Simulates an upstream failure for the failover scenario. |
