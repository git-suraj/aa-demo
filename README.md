# Kong Agent + MCP Demo

This repo is a simple Konnect hybrid demo for showing how Kong governs both agent-to-agent traffic and MCP tool traffic.

## What the project does

This project demonstrates a small, visually clear agent system running behind Kong in Konnect hybrid mode.

The demo uses:

- 1 LangGraph orchestrator
- 2 LangGraph sub-agents
- an orchestrator LLM step for triage and executive synthesis
- LLM calls from the orchestrator and sub-agents routed through Kong AI Proxy Advanced
- separate Kong AI routes for orchestrator and sub-agents
- 1 backing REST API
- Kong's `ai-mcp-proxy` plugin to expose that API as MCP tools
- Consumers and Consumer Groups to control which agent can see which tools
- a lightweight UI that shows the flow in real time

The business scenario is a simple customer escalation:

- a customer is at risk of not renewing
- they report a billing problem
- they also report a product issue
- the system needs to produce an executive escalation brief quickly

The point of the demo is to show that Kong sits in the middle of every important hop:

- UI to orchestrator
- orchestrator to MCP tools
- orchestrator to sub-agents
- sub-agents to MCP tools

This makes Kong's role easy to explain:

- route control
- authentication
- tool exposure through MCP
- LLM routing through AI Proxy Advanced
- per-agent tool restrictions
- observability of agent traffic

## Current UI

The UI is now opinionated around Kong as the control plane.

Top-level controls:

- `Scenes`
- `View Diagrams`
- `Reset Scene`
- `Reset Observability`
- `View Run Output`
- `?` help modal for the demo scenario and agent roles

Main UI behaviors:

- the topology keeps Kong visually primary
- every topology node has a `+` button that opens contextual details
- Kong and MCP stay highlighted after reset / end-of-run so the gateway/tool-plane relationship stays visible
- the trace sidebar includes `Recent Runs`, backed by the in-memory `TraceBroker`
- `Reset Observability` clears Loki/Grafana state and also clears the recent-runs list in the UI

Diagram views:

- `View Diagrams` includes UML-style sequence flow for the normal scenario
- the same modal includes LangGraph state diagrams for:
  - orchestrator
  - support-agent
  - success-agent
- the sequence diagram has an `Open Full Width` action that opens the sequence in a separate popup for inspection

## What it will show

- 1 orchestrator agent
- 2 sub-agents
- 1 backing REST API exposed as MCP tools through Kong's `ai-mcp-proxy`
- per-agent tool visibility enforced with Consumers and Consumer Groups
- LangGraph-based deterministic agent workflows
- an orchestrator LLM call for planning and synthesis
- a lightweight UI that visualizes the request flow
- node-level detail popups explaining what each box does
- a sequence diagram for the normal end-to-end flow
- LangGraph workflow diagrams for all three agents

## Runtime shape

- `ui`: starts the demo and shows the trace
- `orchestrator`: receives the play request and coordinates the run
- `support-agent`: handles product and runbook investigation
- `success-agent`: handles customer follow-up and action items
- `mock-api`: backing REST API for the 7 tools
- `ai-llm-service`: LLM traffic routed through Kong AI Proxy Advanced
- `redis-stack`: vector database backing the semantic guard scenario
- `kong-dp`: Kong Gateway `3.13.0.1` in Konnect hybrid mode

## Routes

- `/orchestrator`
- `/support-agent`
- `/success-agent`
- `/api`
- `/mock-mcp`
- `/ai`
- `/ai/orchestrator/chat/completions`
- `/ai/subagent/chat/completions`

The UI is also intended to be hosted through Kong, so the full demo can be reached from the same gateway entrypoint instead of exposing the UI separately.

`/mock-mcp` is the important route for the demo. Kong fronts the REST API and exposes it as MCP tools using the `ai-mcp-proxy` plugin.
The AI routes are split by caller type:

- `/ai/orchestrator/chat/completions`
  - used only by the orchestrator
  - primary target: `gpt-4o-mini`
  - secondary failover target: `gemini-2.5-flash`
- `/ai/orchestrator-failover-demo/chat/completions`
  - used only for the orchestrator failover scenario
  - used for current failover experimentation with Kong `ai-proxy-advanced`
- `/ai/orchestrator-token-demo/chat/completions`
  - used only for the AI token limit scenario
  - protected by Kong `ai-rate-limiting-advanced`
- `/ai/orchestrator-prompt-enhance-demo/chat/completions`
  - used only for the prompt decorator scenario
  - applies a stronger prompt-decoration policy to shape a more structured executive output
- `/ai/orchestrator-semantic-guard-demo/chat/completions`
  - used only for the semantic guard scenario
  - protected by Kong `ai-semantic-prompt-guard` with Redis as the vector database
- `/ai/orchestrator-semantic-cache-demo/chat/completions`
  - used only for the semantic cache scenario
  - protected by Kong `ai-semantic-cache` with Redis as the vector database
- `/ai/orchestrator-pii-placeholder-demo/chat/completions`
  - used only for the PII Sanitization placeholder scenario
  - protected by Kong `ai-sanitizer` in `BOTH` mode with `redact_type: placeholder`
- `/ai/orchestrator-pii-synthetic-demo/chat/completions`
  - used only for the PII Sanitization synthetic scenario
  - protected by Kong `ai-sanitizer` in `BOTH` mode with `redact_type: synthetic`
- `/ai/subagent/chat/completions`
  - used by both sub-agents
  - target: `gemini-2.5-flash`

The services use OpenAI-compatible clients pointed at those Kong routes, and Kong forwards the requests using the AI Proxy Advanced plugin.

Prompt decoration is not applied on the standard orchestrator AI routes. It is used only in the dedicated `Prompt Decorator` scenario so the difference is easy to demonstrate.

## Governance scenarios

The UI includes a `Governance Scenario` selector. The customer escalation story stays the same, but the Kong-governed AI path changes depending on what is selected.

The route path is selected by the `governance_scenario` field sent in the `Play` request. In the orchestrator, `PlayRequest.governance_scenario` is mapped by `ai_route_for_scenario()` in [services/orchestrator/app.py](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py):

- `normal` -> `/ai/orchestrator/chat/completions`
- `llm_failover` -> `/ai/orchestrator-failover-demo/chat/completions`
- `token_limit` -> `/ai/orchestrator-token-demo/chat/completions`
- `prompt_enhancement` -> `/ai/orchestrator-prompt-enhance-demo/chat/completions`
- `semantic_guard` -> `/ai/orchestrator-semantic-guard-demo/chat/completions`
- `semantic_cache` -> `/ai/orchestrator-semantic-cache-demo/chat/completions`
- `pii_sanitizer` -> `/ai/orchestrator-pii-placeholder-demo/chat/completions` or `/ai/orchestrator-pii-synthetic-demo/chat/completions`

So the basis for route selection is simple: whichever governance scenario the user selected in the UI is included in the request payload, and the orchestrator picks the matching Kong AI route before it starts its own LLM steps.

### 1. Normal

This is the default run.

Behind the scenes:

- the orchestrator uses `/ai/orchestrator/chat/completions`
- the orchestrator planner, triage, and executive-summary LLM calls go through Kong on the standard orchestrator route
- the sub-agents use `/ai/subagent/chat/completions`
- MCP routing, ACL filtering, and agent-to-agent traffic still all flow through Kong exactly as in the base demo

This mode is meant to show the standard happy-path behavior.

### 2. LLM Failover

This scenario demonstrates what happens when the orchestrator's primary model path fails.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-failover-demo/chat/completions`
- the route is configured to experiment with Kong-managed failover behavior in `ai-proxy-advanced`
- the support and success sub-agents still use their normal Gemini sub-agent route

Important note:

- this scenario is currently a debugging path, not a proven deterministic demo
- multiple failover experiments were tested:
  - primary `401`
  - invalid model name
  - request-termination simulator route
  - unreachable upstream
- in this repo/runtime, the strongest finding is that target-specific `upstream_url` handling appears to interfere with failover target isolation
- specifically, when the primary target uses `upstream_url`, Kong may still log and fail the fallback target against that same effective upstream
- one experimental configuration only started working when the OpenAI target's `upstream_url` was pointed at a Gemini endpoint, which strongly suggests unexpected `upstream_url` behavior rather than correct target failover semantics
- current conclusion: this is likely an `ai-proxy-advanced` bug or limitation in per-target `upstream_url` handling during failover, and the failover scene should be treated as experimental unless verified again against a working Kong-supported provider-native failure

### 3. AI Token Limit

This scenario demonstrates Kong blocking the orchestrator with AI token governance.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-token-demo/chat/completions`
- that route uses `ai-rate-limiting-advanced`
- the current config in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml) is:
  - provider: `openai`
  - `limit: [1]`
  - `window_size: [300]`
- in plain terms, the demo route allows one counted OpenAI budget event in a 300-second window, and later orchestrator AI calls are blocked with `429`
- the orchestrator planner or later executive-summary calls hit Kong's AI policy and receive `429`
- instead of crashing the whole demo, the orchestrator converts that into a structured blocked result
- the trace shows that Kong policy blocked the orchestrator before the executive brief could be completed

This mode is useful for showing governance and protection, not a successful business outcome.

Important note:

- the current demo is not using a human-friendly fixed threshold like "block after 5,000 tokens"
- it is using the plugin configuration above on the scenario route
- in live logs, Kong reports `AI token rate limit exceeded for provider(s): openai`
- for demo purposes, the effect is deterministic: the scenario shows a policy block after the first counted orchestrator AI usage on that route
- the orchestrator now handles Kong `429` responses from the shared `httpx` LLM client correctly; earlier versions let those surface as `500`

### 4. Prompt Decorator

This scenario demonstrates how Kong prompt decoration can materially improve and govern the orchestrator output.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-prompt-enhance-demo/chat/completions`
- the normal orchestrator route does not decorate prompts
- this scenario route applies `ai-prompt-decorator`
- the application prompt stays the same, but Kong injects extra enterprise-governance instructions before the model sees it
- the trace shows policy events for:
  - the original prompt
  - the Kong-decorated prompt
  - the resulting LLM output
- the sub-agents still run through their normal sub-agent Gemini route

This mode is useful for showing that prompt shaping and output governance can happen in the gateway layer rather than inside application code.

The current prompt decorator policy configured in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml) prepends these instructions:

- `You are responding under AI governance enforced by Kong Gateway.`
- `Enhanced escalation policy for this demo:`
- `Respond in an executive escalation format with sections for Situation, Risk, Actions, and Next Checkpoint.`
- `State customer posture explicitly and keep the tone enterprise-safe.`
- `Mention regulatory or data residency considerations when they are relevant.`
- `End with a confidence score and a named owner.`

In the trace tree, this appears as a `Decorator policy applied` step nested under the relevant orchestrator LLM call. Clicking that row shows:

- the original prompt sent by the application
- the policy text Kong injected
- the decorated system and user prompts that Kong forwarded upstream

The prompt decorator scenario route uses this enhancement policy:

- `Respond in an executive escalation format with sections for Situation, Risk, Actions, and Next Checkpoint.`
- `State customer posture explicitly and keep the tone enterprise-safe.`
- `Mention regulatory or data residency considerations when they are relevant.`
- `End with a confidence score and a named owner.`

### 5. Semantic Guard

This scenario demonstrates Kong rejecting semantically unsafe prompts using `ai-semantic-prompt-guard` backed by Redis.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-semantic-guard-demo/chat/completions`
- that route applies `ai-semantic-prompt-guard`
- the plugin uses:
  - OpenAI `text-embedding-3-small` for embeddings
  - Redis as the vector database
- the current config in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml) uses:
  - `search.threshold: 0.7`
  - `vectordb.strategy: redis`
  - `vectordb.distance_metric: cosine`
  - `vectordb.threshold: 0.5`
  - `vectordb.dimensions: 1024`
  - `vectordb.redis.host: ${{ env "DECK_REDIS_HOST" }}`
- the deny topics currently configured are:
  - requests to reveal employee personal contact information or private customer data
  - requests to disclose internal credentials, access instructions, or confidential system details
  - requests to bypass security controls or reveal private infrastructure information
- for demo determinism, the orchestrator replaces its normal LLM user prompt with a denied sensitive-information request only in this scenario
- Kong compares that prompt semantically against the deny topics and blocks the LLM request before the model can answer
- the trace shows a `Kong semantic guard blocked request` event under the affected orchestrator LLM step

This mode is useful for showing semantic policy enforcement at the gateway layer instead of relying on exact keyword matches inside the application.

The `+` policy panel in the UI now shows the exact denied prompt families and explains the thresholds:

- `search.threshold`
  - broader candidate-search threshold for finding possible semantic matches
- `vectordb.threshold`
  - final similarity cutoff used for the block decision

### 6. Semantic Cache

This scenario demonstrates Kong serving a repeated orchestrator prompt from semantic cache backed by Redis.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-semantic-cache-demo/chat/completions`
- that route applies `ai-semantic-cache`
- the plugin uses:
  - OpenAI `text-embedding-3-small` for embeddings
  - Redis as the vector database
- the current config in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml) uses:
  - `vectordb.strategy: redis`
  - `vectordb.distance_metric: cosine`
  - `vectordb.dimensions: 1024`
  - `vectordb.threshold: 0.1`
  - `vectordb.redis.host: ${{ env "DECK_REDIS_HOST" }}`
- in this scenario, the orchestrator sends the same triage prompt twice through the semantic-cache route:
  - first call seeds the cache
  - second call reuses the cached answer
- Kong returns cache headers such as:
  - `X-Cache-Status`
  - `X-Cache-Key`
  - `X-Cache-Ttl`
  - `Age`
- the trace shows:
  - `Semantic cache miss`
  - `Semantic cache hit`
- the final output also includes a `Semantic Cache Probe` section with the cache headers from both calls
- topology behavior is now staged:
  - Redis activates first for both requests
  - OpenAI activates only on a cache miss
  - cache hits return from Redis through Kong back to the orchestrator/dashboard without activating the model path

This mode is useful for showing that Kong can speed up repeated or semantically similar orchestrator prompts without changing application code.

When `Semantic Cache` is selected in `View Scene`, the scene popup changes from a single `Play` action to three explicit semantic-cache controls:

- `Send First Request`
  - sends the semantic-cache seed request
  - the payload includes `governance_scenario: "semantic_cache"` and `semantic_cache_step: "seed"`
  - the orchestrator uses `/ai/orchestrator-semantic-cache-demo/chat/completions`
  - Kong calls the model normally, returns `X-Cache-Status: Miss`, and writes the semantic result into Redis
  - this run is a cache-probe flow only, so it does not invoke MCP tools or sub-agents

- `Send Second Request`
  - sends the semantic-cache reuse request
  - the payload includes `governance_scenario: "semantic_cache"` and `semantic_cache_step: "reuse"`
  - the payload is intentionally similar, not identical, to the first request so the cache behavior is semantic rather than exact-string matching
  - the orchestrator again uses `/ai/orchestrator-semantic-cache-demo/chat/completions`
  - Kong should return `X-Cache-Status: Hit` and serve the cached response from Redis instead of running the full downstream flow

- `Clear Semantic Cache`
  - calls the orchestrator cache-clear endpoint: `/orchestrator/semantic-cache/clear`
  - the orchestrator deletes all Redis keys matching `semantic_cache:*`
  - this button is independent of the send-request buttons and is intended to reset the semantic-cache demo back to a clean state before another first request

Important operational note:

- semantic cache state persists in Redis across runs
- because the cache is semantic, a later "first" request can still be a real cache hit if a sufficiently similar prompt already exists in Redis
- if you want a deterministic miss-then-hit demo sequence, clear semantic cache first, then run the seed request, then run the reuse request

### 7. PII Sanitization

This scenario demonstrates Kong anonymizing sensitive information in both the upstream request body and the downstream LLM response body.

Behind the scenes:

- the orchestrator switches to one of two dedicated routes:
  - `/ai/orchestrator-pii-placeholder-demo/chat/completions`
  - `/ai/orchestrator-pii-synthetic-demo/chat/completions`
- each route applies `ai-sanitizer` before `ai-proxy-advanced`
- the plugin is configured with:
  - `anonymize: [all_and_credentials]`
  - `sanitization_mode: BOTH`
  - `recover_redacted: false`
- the placeholder route uses `redact_type: placeholder`
- the synthetic route uses `redact_type: synthetic`
- both routes call the external Kong AI PII service at:
  - `docker.cloudsmith.io/kong/ai-pii/service:v0.1.4-en`
- the probe sends a prompt containing multiple categories of sensitive values and asks the model to restate them
- Kong sanitizes the request before it reaches the upstream model, and sanitizes the response before it is returned to the client

The demo intentionally uses the focused-probe pattern instead of the full MCP/sub-agent orchestration flow so the request/response anonymization is easy to see.

When `PII Sanitization` is selected in `View Scene`, the scene popup changes from a single `Play` action to two explicit PII-mode controls:

- `Send Placeholder Request`
  - sends `governance_scenario: "pii_sanitizer"` with `pii_sanitizer_mode: "placeholder"`
  - Kong replaces detected values with fixed placeholders in both request and response handling

- `Send Synthetic Request`
  - sends `governance_scenario: "pii_sanitizer"` with `pii_sanitizer_mode: "synthetic"`
  - Kong replaces detected values with synthetic category-matched values in both request and response handling

The final output shows:

- the selected anonymization mode
- the effective sanitization policy
- the original request prompt
- the sanitized response returned through Kong

Current topology behavior:

- placeholder and synthetic modes visibly traverse the PII service twice:
  - request-side sanitization before the model call
  - response-side sanitization after the model returns
- block mode now stays on the normal green lifecycle rather than turning red
- on blocked PII returns, the `pii-service`, `orchestrator`, `kong`, and `dashboard` highlights are intentionally held a bit longer so the return leg is visible before settling

Important setup note:

- the AI PII service image is hosted in Kong's private Cloudsmith registry
- you must authenticate with `docker login docker.cloudsmith.io`
- the docs show:
  - username: `kong/ai-pii`
  - password: your support-provided token

### 8. LLM as Judge

This scenario demonstrates Kong generating a candidate response with one model and then scoring that response with a separate judge model.

Behind the scenes:

- the orchestrator switches to `/ai/orchestrator-judge-demo/chat/completions`
- the route applies:
  - `ai-proxy-advanced` for the candidate response
  - `ai-llm-as-judge` for the scoring pass
- the current route shape is:
  - candidate model: `gpt-4o-mini`
  - judge model: `gemini-2.5-flash`
- the judge prompt is now generic rather than escalation-specific:
  - accuracy
  - relevance to the request
  - usefulness for the user's stated task
- the judge plugin is configured to emit payloads and statistics into Kong audit logs, which are then flattened into Loki by the global `http-log` transform

When `LLM as Judge` is selected in `View Scene`, the scene popup now includes:

- three radio presets:
  - `Escalation Triage`
  - `KongHQ Overview`
  - `Low Score Probe`
- an editable text box
  - selecting a radio preset preloads the text box
  - you can then edit the text directly
  - the edited text box value is the actual user prompt sent through Kong

Important implementation note:

- the judge-route candidate target is intentionally OpenAI only
- Gemini is reserved for the judge model
- earlier, the candidate target list also included Gemini, which caused intermittent failures because the candidate and judge paths could collide on the same model

Grafana support for this scenario now includes:

- `LLM as Judge Evaluations`
  - table showing:
    - input
    - output
    - inference model
    - LLM latency
    - judge model
    - judge latency
    - score
- `Kong Raw Log Stream`
  - full-width raw Kong logs for the selected run

The Kong log transform was also adjusted so the judge `Input` column reflects only the user message content from the request, not the hidden system prompt.

Current topology behavior:

- the OpenAI candidate leg completes before the judge leg is shown as settled
- the judge leg now uses a longer visible dwell in the UI so it better matches the multi-second judge latency seen in Grafana rather than flashing through on short synthetic timers
- the orchestrator/UI return begins only after that longer judge-visible window, so the topology is easier to correlate with observed Kong latency

## What happens when Play is pressed

When the user presses `Play` in the UI, the following flow happens:

1. The UI sends a single request to the orchestrator through Kong.
2. The UI-selected governance scenario is included in the request payload.
3. The orchestrator starts a LangGraph workflow and emits live trace events.
4. Based on the selected governance scenario, the orchestrator chooses the Kong AI route it will use for its own LLM calls.
5. The orchestrator calls Kong's MCP endpoint on `/mock-mcp`.
6. Through Kong, the orchestrator lists only the MCP tools it is allowed to access:
   - `get_customer_account`
   - `get_renewal_risk`
   - `get_open_tickets`
7. The orchestrator gathers account context using those tools:
   - customer account details
   - renewal risk
   - open support tickets
8. The orchestrator creates an executive triage brief using the scenario-specific orchestrator AI route in Kong.
9. The orchestrator sends that triage brief to both sub-agents as shared escalation context.
10. The orchestrator invokes the `support-agent` through Kong using explicit HTTP JSON-RPC.
11. The support agent starts its own LangGraph workflow and calls only its allowed MCP tools through Kong:
   - `get_incident_status`
   - `search_runbook`
12. The support agent also makes its own LLM call through the sub-agent AI route in Kong to turn the incident and runbook findings into a concise technical summary.
13. The support agent returns a structured technical response to the orchestrator through Kong.
14. The orchestrator uses that support output as context and then invokes the `success-agent` through Kong.
15. The success agent starts its own LangGraph workflow and calls only its allowed MCP tools through Kong:
   - `draft_customer_reply`
   - `create_followup_task`
16. The success agent also makes its own LLM call through the sub-agent AI route in Kong to turn the drafted reply and follow-up task into a concise customer-success summary.
17. The success agent returns a structured customer-success output to the orchestrator through Kong.
18. The orchestrator makes a second LLM call through the scenario-specific orchestrator AI route in Kong to turn the gathered context into an executive brief.
19. The orchestrator merges both tracks into one final recommendation.
20. The UI shows:
   - live node state changes
   - event log updates
   - the final coordinated response

In short: one button press creates a full end-to-end run where LangGraph controls the workflow and Kong controls the network path and tool visibility.

## Data flow

The data flow is explicit and easy to narrate.

### 1. Input data from the UI

The UI sends a single request to the orchestrator containing:

- `customer_id`
- `account_name`
- `issue_summary`
- `product_issue`
- `billing_issue`
- `incident_id`

This is the starting payload for the full run.

### 2. The orchestrator enriches that input with account context

The orchestrator uses its MCP tools through Kong to fetch structured records:

- `get_customer_account`
  - account metadata such as name, segment, ARR, renewal date, and health state
- `get_renewal_risk`
  - current renewal risk level and drivers
- `get_open_tickets`
  - currently open tickets tied to the customer

This turns the original UI request into a richer working context.

### 3. The orchestrator converts the raw context into a triage brief

The orchestrator sends the gathered context to Kong's orchestrator AI route and gets back a triage brief.

That brief is a concise narrative of:

- the current situation
- the likely next actions
- the customer communication posture

This triage brief is then passed to both sub-agents so they start from the same framing.

### 4. Data sent to the support sub-agent

The orchestrator sends the support sub-agent:

- `customer_id`
- `account_name`
- `product_issue`
- `incident_id`
- `triage_brief`

The support sub-agent uses:

- the operational identifiers to fetch technical evidence
- the triage brief to understand the escalation context

The support sub-agent then calls only:

- `get_incident_status`
- `search_runbook`

It also makes one LLM call through Kong's sub-agent AI route to convert the incident and runbook findings into a concise technical summary.

It returns:

- `triage_brief`
- `available_tools`
- `incident`
- `runbook`
- `technical_response`
- `recommended_actions`

### 5. Data sent to the success sub-agent

After support returns, the orchestrator sends the success sub-agent:

- `account_name`
- `csm`
- `issue_summary`
  - currently the triage brief summary
- `renewal_risk`
- `technical_summary`
  - derived from the support agent output
- `triage_brief`

The success sub-agent uses:

- the triage brief as shared executive framing
- the support technical summary as the technical basis for customer communication

The success sub-agent then calls only:

- `draft_customer_reply`
- `create_followup_task`

It also makes one LLM call through Kong's sub-agent AI route to turn those results into a concise customer-success summary.

It returns:

- `triage_brief`
- `available_tools`
- `customer_reply`
- `followup_task`
- `success_plan`

### 6. Final data assembly in the orchestrator

The orchestrator then holds:

- the original UI request
- the MCP-fetched account context
- the triage brief
- the support agent output
- the success agent output

It sends that combined package to Kong's orchestrator AI route one more time to produce the final executive brief.

That final payload is what the UI renders.

## Demo reference

### API keys used in the demo

These are the demo consumer keys currently configured in the repo:

- `ui-demo-key`
  - used by the hosted UI when it calls the orchestrator and subscribes to `/orchestrator/trace`
- `orchestrator-demo-key`
  - used by the orchestrator when it calls:
    - `/mock-mcp`
    - `/support-agent`
    - `/success-agent`
    - `/ai/orchestrator/chat/completions`
- `support-demo-key`
  - used by the support sub-agent when it calls:
    - `/mock-mcp`
    - `/ai/subagent/chat/completions`
- `success-demo-key`
  - used by the success sub-agent when it calls:
    - `/mock-mcp`
    - `/ai/subagent/chat/completions`

The Kong Consumers for these keys are defined in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml).

### Scene input values

The demo scene currently accepts these fields:

- `customer_id`
- `account_name`
- `issue_summary`
- `product_issue`
- `billing_issue`
- `incident_id`

The current default values in the UI are:

- `customer_id = cust_acme`
- `account_name = Acme Health`
- `issue_summary = Customer reports a billing dispute and workflow-agent sync delays.`
- `product_issue = workflow agent sync delays`
- `billing_issue = billing overcharge on enterprise add-ons`
- `incident_id = INC-1007`

These are defined in [ui/index.html](/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/index.html) and in the `PlayRequest` model in [services/orchestrator/app.py](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py).

### Final output

The final output is created by the orchestrator in the `finalize_response` step in [services/orchestrator/app.py](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py).

It is built from:

- the original UI request
- MCP-fetched account context
- the orchestrator triage brief
- the support sub-agent result
- the success sub-agent result
- the final orchestrator executive-summary LLM call

The final response object contains:

- `headline`
- `available_tools`
- `account_context`
- `renewal_risk`
- `open_tickets`
- `triage_brief`
- `support_track`
- `success_track`
- `executive_brief`
- `recommended_summary`

So the orchestrator is the component that creates the final answer, and it does so after it has gathered tool results and both sub-agent outputs through Kong.

## Agent responsibilities

### Orchestrator

The orchestrator is responsible for:

- receiving the request from the UI
- gathering account context from MCP tools through Kong
- creating the triage brief through the orchestrator AI route in Kong
- passing the triage brief to both sub-agents
- calling the support agent first
- calling the success agent with support output
- creating the final executive brief through the orchestrator AI route in Kong
- streaming live trace events

The orchestrator coordinates. It does not do deep technical investigation or customer action planning directly.

### Support sub-agent

The support sub-agent is responsible for:

- technical investigation of the escalation
- checking the incident status
- checking relevant runbook guidance
- creating an LLM-based technical summary through Kong's sub-agent AI route
- producing the technical response and recommended technical actions

It turns raw incident data into technical guidance for the orchestrator.

### Success sub-agent

The success sub-agent is responsible for:

- customer-facing follow-up planning
- drafting the customer reply
- creating the success-team follow-up task
- creating an LLM-based customer-success summary through Kong's sub-agent AI route
- keeping the customer response aligned with the technical response from support

It turns the technical findings plus the triage framing into a customer-ready action plan.

## Expected LLM Call Counts

In a normal full run, the expected Kong-routed LLM call counts are:

- orchestrator: `5`
  - `3` tool-selection planner calls
  - `1` triage brief call
  - `1` executive summary call
- support-agent: `3`
  - `2` tool-selection planner calls
  - `1` technical summary call
- success-agent: `3`
  - `2` tool-selection planner calls
  - `1` success summary call

So for a normal run:

- `gpt-4o-mini-2024-07-18` should appear as `5`
- `gemini-2.5-flash` should appear as `6`

If Grafana does not show those counts for a fresh normal run, the first thing to verify is whether the affected LLM log lines in Loki carry the correct `run_id`.

## Implemented services

- [UI](/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/index.html): static single-screen demo UI with `Play`, `Reset`, `Reset Observability`, live flow states, selected-step detail, and a `Recent Runs` dropdown that can replay the last 20 stored traces
- [orchestrator](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py): receives `POST /play`, exposes `WS /trace`, serves `GET /trace/runs` and `GET /trace/runs/{run_id}` for recent trace replay, calls MCP through Kong, invokes the support-agent first, then invokes the success-agent with support context
- [orchestrator LLM helper](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/llm.py): shared OpenAI-compatible client used by the orchestrator and sub-agents, pointed at Kong's `/ai` route
- [support-agent](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/support_agent/app.py): LangGraph sub-agent for technical investigation using `get_incident_status` and `search_runbook`
- [success-agent](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/success_agent/app.py): LangGraph sub-agent for customer-success actions using `draft_customer_reply` and `create_followup_task`
- [mock-api](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/mock_api/app.py): backing REST API for the 7 tool endpoints plus OpenAPI schema
- [shared MCP client](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/mcp_client.py): lightweight streamable HTTP MCP client for the agents

## Tool access model

- `orchestrator-agent`
  - `get_customer_account`
  - `get_renewal_risk`
  - `get_open_tickets`
- `support-agent`
  - `get_incident_status`
  - `search_runbook`
- `success-agent`
  - `draft_customer_reply`
  - `create_followup_task`

This tool split will be enforced by Kong with authenticated Consumers and Consumer Group based ACL rules inside the MCP proxy configuration.

## Backend API reference

The backing REST API lives in [services/mock_api/app.py](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/mock_api/app.py).
In the local demo, the intended host-facing access path is through Kong on `/api`, not by exposing the `mock-api` container directly on its own host port.

### Tool to endpoint mapping

- `get_customer_account` -> `GET /api/customers/{customer_id}`
- `get_renewal_risk` -> `GET /api/customers/{customer_id}/renewal-risk`
- `get_open_tickets` -> `GET /api/customers/{customer_id}/tickets`
- `get_incident_status` -> `GET /api/incidents/{incident_id}`
- `search_runbook` -> `GET /api/runbooks/search?q=...`
- `draft_customer_reply` -> `POST /api/drafts/customer-reply`
- `create_followup_task` -> `POST /api/tasks/followup`

Preview/helper endpoints also exist:

- `draft_customer_reply_preview` -> `GET /api/drafts/customer-reply/preview`
- `create_followup_task_preview` -> `GET /api/tasks/followup/preview`
- `get_demo_scene` -> `GET /api/demo-scene`
- `healthcheck` -> `GET /api/health`

### Direct curl examples through Kong

```bash
curl -s http://localhost:8000/api/health | jq
curl -s http://localhost:8000/api/customers/cust_acme | jq
curl -s http://localhost:8000/api/customers/cust_acme/renewal-risk | jq
curl -s http://localhost:8000/api/customers/cust_acme/tickets | jq
curl -s http://localhost:8000/api/incidents/INC-1007 | jq
curl -s "http://localhost:8000/api/runbooks/search?q=billing" | jq
curl -s http://localhost:8000/api/demo-scene | jq
```

```bash
curl -s http://localhost:8000/api/drafts/customer-reply \
  -H 'Content-Type: application/json' \
  -d '{
    "account_name": "Acme Health",
    "csm": "Maya Patel",
    "issue_summary": "Billing dispute and workflow delays",
    "renewal_risk": "high",
    "technical_summary": "Engineering is mitigating the incident and tracking the billing issue."
  }' | jq

curl -s http://localhost:8000/api/tasks/followup \
  -H 'Content-Type: application/json' \
  -d '{
    "account_name": "Acme Health",
    "owner": "Maya Patel",
    "due_date": "2026-04-02",
    "action_items": ["Send daily update", "Review renewal risk", "Confirm billing correction"]
  }' | jq
```

### Bypassing Kong for container-network debugging

The `mock-api` service is not published directly to the host in the default compose setup. If you want to hit it without Kong, call it from another container on the compose network, for example:

```bash
docker exec orchestrator curl -s http://mock-api:8000/customers/cust_acme
```

## Files added in this scaffold

- `docker-compose.yml`: local container topology
- `.env.example`: hybrid mode environment placeholders
- `.env`: local placeholder values so the compose file resolves
- `kong/deck/kong.yaml`: Konnect-managed services, routes, auth, Consumers, and MCP config skeleton
- `services/`: working FastAPI services and shared helper code
- `ui/`: static frontend assets and container

## Prerequisites

- Docker and Docker Compose
- `deck`
- a Konnect personal access token
- a Konnect control plane name
- Konnect hybrid data plane certificates
- an OpenAI API key
- a Gemini API key

## Quick Start

Run the following commands from the repo root.

### 1. Create the env file

```bash
cp .env.example .env
```

### 2. Edit `.env`

Set all required values in `.env`:

```bash
KONG_CLUSTER_CONTROL_PLANE=YOUR_KONNECT_CP_HOST:443
KONG_CLUSTER_SERVER_NAME=YOUR_KONNECT_CP_HOST
KONG_CLUSTER_TELEMETRY_ENDPOINT=YOUR_KONNECT_TELEMETRY_HOST:443
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
DECK_OPENAI_API_KEY=YOUR_OPENAI_API_KEY
DECK_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
DECK_OPENAI_MODEL=gpt-4o-mini
DECK_GEMINI_MODEL=gemini-2.5-flash
DECK_REDIS_HOST=redis-stack
KONNECT_TOKEN=YOUR_KONNECT_PAT
KONNECT_CONTROL_PLANE_NAME=YOUR_KONNECT_CONTROL_PLANE_NAME
```

### 3. Place the hybrid certs

```bash
mkdir -p kong/certs
```

Put your Konnect data plane cert and key here:

```text
kong/certs/tls.crt
kong/certs/tls.key
```

### 4. Export the env vars for decK

Load the values from `.env` into the current shell before running `deck`:

```bash
set -a
source .env
set +a
```

`set -a` tells the shell to automatically export variables that are defined or loaded after that point.
`set +a` turns that behavior back off.

### 5. Validate the Kong config

```bash
deck file validate kong/deck/kong.yaml
```

### 6. Sync the Kong config to Konnect

```bash
deck gateway sync \
  --konnect-token "$KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONNECT_CONTROL_PLANE_NAME" \
  kong/deck/kong.yaml
```

### 7. Start the stack

```bash
docker compose up --build -d
```

### 8. Verify the containers

```bash
docker compose ps
```

### 9. Open the hosted UI

After the hybrid data plane connects and the Kong config is synced, open:

```text
http://localhost:8000/
```

This is the intended demo entrypoint.

### 10. Open Grafana

The stack now includes Loki and Grafana for gateway log exploration:

```text
Grafana: http://localhost:3001/
Loki:    http://localhost:3100/
```

Grafana is pre-provisioned with:

- a Loki datasource
- a dashboard called `Kong Governance Overview`

The default Grafana credentials are:

```text
username: admin
password: admin
```

The UI is hosted through Kong and uses the same gateway for:

- `/orchestrator`
- `/orchestrator/trace`
- `/orchestrator/trace/runs`
- `/orchestrator/trace/runs/{run_id}`
- `/mock-mcp`
- `/ai/orchestrator/chat/completions`
- `/ai/subagent/chat/completions`

The trace sidebar also includes `Recent Runs`.

- it lists the last 20 runs currently held in orchestrator memory
- selecting one replays that run's stored trace events into the same execution tree and selected-step detail pane
- this is a UI replay of previously emitted trace events, not a second query path that rebuilds the tree differently
- because the history is in-memory, restarting or recreating the orchestrator clears the list

The top bar also includes `Reset Observability`, which triggers the orchestrator to:

- remove the `loki` container
- recreate `loki`
- restart `grafana`

This is intended as a demo-only reset path for clearing Loki log history between runs.

### Optional: direct UI container access for debugging

If you want to verify only the static UI container, you can open:

```text
http://localhost:3000/
```

That is only for debugging. The real demo path should be through Kong on port `8000`.

## Useful Commands

Validate Kong config:

```bash
deck file validate kong/deck/kong.yaml
```

Sync Kong config again:

```bash
deck gateway sync \
  --konnect-token "$KONNECT_TOKEN" \
  --konnect-control-plane-name "$KONNECT_CONTROL_PLANE_NAME" \
  kong/deck/kong.yaml
```

Start or rebuild the stack:

```bash
docker compose up --build -d
```

Check container status:

```bash
docker compose ps
```

Follow logs:

```bash
docker compose logs -f
```

Stop the stack:

```bash
docker compose down
```

## Observability

Kong now sends gateway logs to Loki through a global `http-log` plugin. The plugin reformats each gateway log line into Loki's `streams` payload and adds a small set of low-cardinality labels so Grafana queries stay useful.

### Loki labels

Each log line is labeled with:

- `gateway`
  - fixed as `kong-unified-governance`
- `component`
  - one of `llm`, `mcp`, `agent`, `backend`, `ui`, or `gateway`
- `service`
  - the Kong service name
- `route`
  - the Kong route name
- `consumer`
  - the consumer username, custom id, id, or `anonymous`
- `method`
  - the HTTP method
- `status`
  - the response status code
- `status_class`
  - the HTTP class such as `2xx`, `4xx`, or `5xx`
- `run_id`
  - extracted from the `x-demo-run-id` request header when it is present

### How component classification works

The global log plugin classifies traffic like this:

- `mock-mcp-route` => `mcp`
- services beginning with `ai-` => `llm`
- `orchestrator-service`, `support-agent-service`, `success-agent-service` => `agent`
- `mock-api-service` => `backend`
- `ui-service` => `ui`
- everything else => `gateway`

This makes it straightforward to build Grafana panels for:

- LLM request volume and failures
- MCP request volume and failures
- agent request volume and failures
- backend and UI traffic split by status

### How `run_id` correlates the system

The demo uses a single `run_id` to correlate one end-to-end execution across:

- the browser UI
- the orchestrator
- both sub-agents
- Kong gateway logs
- Loki log records
- Grafana dashboard filters

For a technical audience, the important point is that `run_id` is not only a UI concept. It is the correlation key that ties together both control-plane events and data-plane traffic.

#### 1. `run_id` creation

At the start of a run, the UI creates a `run_id` if one is not already present and sends it with the request body and request headers.

- request body field: `run_id`
- request header: `x-demo-run-id`

This means the same identifier is available to:

- the orchestrator application logic
- Kong request logging
- downstream agent and MCP calls that continue propagating the header

#### 2. Orchestrator scope

The orchestrator treats `run_id` as the execution identifier for the full workflow.

It uses that same value to:

- emit websocket trace events for the UI tree
- call LLM routes through Kong
- call MCP through Kong
- invoke the support-agent and success-agent
- construct the final response returned to the UI

In practice, this means all orchestration steps for a single execution are grouped under one `run_id`, even when the workflow fans out into multiple agent and tool calls.

#### 3. Propagation to sub-agents and tools

The orchestrator passes `run_id` into the sub-agent request payloads. Each sub-agent then reuses that same `run_id` when it:

- emits trace events back to the orchestrator
- calls MCP tools through `KongMCPClient`
- calls LLM routes through the shared LLM client

This matters because the workflow is distributed. Without explicit propagation, the support-agent and success-agent traffic would look like unrelated requests in Loki and Grafana.

#### 4. Header-level correlation in Kong

Kong extracts `run_id` from the `x-demo-run-id` header inside the logging plugin and writes it into the structured log payload.

That gives every logged request a stable correlation field alongside:

- `component`
- `service`
- `route`
- `consumer`
- `status`

So a single `run_id` can be used to join together:

- orchestrator LLM calls
- sub-agent LLM calls
- MCP tool calls
- agent-to-agent traffic
- any other gateway request that carried the same header

#### 5. Loki as the correlation store

Loki stores `run_id` as a structured field that the dashboard queries can filter on.

That is what enables questions like:

- "Show me only the LLM calls for this run"
- "What was the total cost for this run"
- "Which MCP tools were called during this run"
- "Why does this run have fewer support-agent LLM calls than expected"

Without `run_id`, Grafana could still show aggregate traffic, but it could not reliably isolate one workflow execution from another.

#### 6. Grafana usage

The governance dashboard exposes a `Run ID` variable.

- `All`
  - shows all labeled runs in the selected time range
- specific `run_id`
  - scopes queries to one execution

This is why the dashboard can act both as:

- an overall governance dashboard
- a per-run investigation view

#### 7. Failure mode to watch for

If any service makes downstream requests without propagating `run_id`, the workflow will fragment operationally:

- the run still executes
- Kong still logs the requests
- but those log lines will have blank or missing `run_id`
- Grafana run-scoped panels will undercount that run

That exact failure happened earlier with sub-agent planner LLM calls. The requests succeeded, but because `run_id` was not consistently propagated, the per-run LLM count panels showed `1` instead of `3` for support and success on affected historical runs.

So the technical rule in this repo is simple:

- every request that should belong to one business execution must carry the same `run_id`
- every internal service hop must preserve that value
- every observability query that claims to be "per run" depends on that propagation being correct

### Grafana dashboard

The dashboard `Kong Governance Overview` includes:

- requests by component
- errors by component
- LLM requests
- MCP requests
- agent requests
- semantic guard blocked requests
- semantic cache hits
- semantic cache misses
- LLM as Judge evaluations
- a raw log stream panel for inspection

The dashboard also includes a `Run ID` selector:

- `All`
  - shows all labeled runs in the selected time range
  - excludes traffic where `run_id` is blank
- a specific run id
  - scopes the dashboard to one run

The LLM cost panels and LLM call-count panels are intended to follow the active Grafana time range rather than a hardcoded lookback window.

The semantic-cache panels are driven by Kong AI semantic-cache audit log fields that are flattened into the Loki payload:

- `ai_cache_status`
- `ai_cache_fetch_latency`
- `ai_cache_embeddings_provider`
- `ai_cache_embeddings_model`
- `ai_cache_embeddings_latency`

The current cache counters use:

- `ai_cache_status = "hit"` for `Semantic Cache Hits`
- `ai_cache_status = "miss"` for `Semantic Cache Misses`

The semantic-guard counter uses the guarded route returning `400`:

- `Semantic Guard Blocked Requests`

The judge table is backed by Kong judge-route logs and expects the flattened fields:

- `judge_input`
- `judge_output`
- `judge_inference_model`
- `judge_model`
- `judge_latency_ms`
- `judge_accuracy`

Important judge-panel note:

- old Loki entries created before the recent Kong log-transform fixes may have blank `judge_input` or missing judge fields
- only fresh judge runs after the latest Kong sync should be used when validating the table

### Konnect dashboard imports

This repo also includes two Konnect Analytics dashboard JSON assets based on the exact exported dashboard definitions provided for this demo:

- [observability/konnect/dashboards/aa-demo-api-analytics.json](/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/konnect/dashboards/aa-demo-api-analytics.json)
- [observability/konnect/dashboards/aa-demo-ai-dashboard.json](/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/konnect/dashboards/aa-demo-ai-dashboard.json)

Notes:

- these are Konnect Analytics tile definitions, not Grafana dashboards
- these files should be treated as the authoritative exported dashboard definitions to import
- they already include a `control_plane` preset filter shape, and the uploader rewrites that filter to the supplied control plane id at upload time
- if a dashboard with the same name already exists in Konnect, the API uploader updates it in place
- if it does not exist, the uploader creates it

Uploader script:

- [scripts/upload_konnect_dashboards.py](/Users/surajpillai/Documents/work/demos/learn/aa-demo/scripts/upload_konnect_dashboards.py)

Recommended path:

- use the API uploader directly

Example:

```bash
python3 scripts/upload_konnect_dashboards.py \
  --control-plane-id "$KONNECT_CP_ID" \
  --pat "$KONNECT_TOKEN"
```

Dry run:

```bash
python3 scripts/upload_konnect_dashboards.py \
  --control-plane-id "$KONNECT_CP_ID" \
  --pat "$KONNECT_TOKEN" \
  --dry-run
```

Script behavior:

- loads the repo's two Konnect dashboard JSON files
- validates that `--control-plane-id` is a non-empty UUID before uploading
- preserves the exported dashboard definition and rewrites only the `control_plane` preset filter value
- lists existing Konnect dashboards
- updates matching dashboards by name, or creates them if they do not exist
- lets you override the default dashboard names with:
  - `--api-dashboard-name`
  - `--ai-dashboard-name`
- defaults to:
  - server: `https://us.api.konghq.com`
  - dashboards path: `/v2/dashboards`
- API schema reference:
  - rendered docs: `https://developer.konghq.com/api/konnect/analytics-dashboards/v2/#/`
- raw OpenAPI: `https://raw.githubusercontent.com/Kong/developer.konghq.com/main/api-specs/konnect/analytics-dashboards/v2/openapi.yaml`

Example with custom names:

```bash
python3 scripts/upload_konnect_dashboards.py \
  --control-plane-id "$KONNECT_CP_ID" \
  --pat "$KONNECT_TOKEN" \
  --api-dashboard-name "Customer API Analytics" \
  --ai-dashboard-name "Customer AI Analytics"
```

The UI-level `Reset Observability` button clears Loki history by recreating the Loki container and restarting Grafana. After using it, wait a few seconds and then refresh Grafana so the datasource reconnects and the dashboard reloads against the new empty Loki state.

The `Average Cost Per Run By Agent` panel means:

- first sum LLM cost per `(consumer, run_id)`
- then average those per-run totals by agent

Important note about historical data:

- older Loki entries created before the run-id propagation fix may show incorrect per-run sub-agent LLM counts
- those older runs cannot be corrected retroactively in Grafana because the blank `run_id` was already written into Loki
- fresh runs after restarting the updated services should show the expected counts listed above
- semantic-cache panels that rely on `ai_cache_status` only work for logs written after the Kong log transform started flattening those audit fields into the Loki payload

Important note about UI trace history:

- the `Recent Runs` dropdown is separate from Loki and Grafana
- it is backed by the orchestrator's in-memory trace store and is capped at the latest 20 runs
- restarting or rebuilding the orchestrator clears that history, so only runs created after the latest orchestrator start will appear

### Observability reset implementation

The reset flow is implemented through the orchestrator API rather than directly in the browser.

- UI calls `POST /orchestrator/observability/reset`
- orchestrator runs:
  - `docker-compose -p aa-demo -f docker-compose.yml rm -sf loki`
  - `docker-compose -p aa-demo -f docker-compose.yml up -d loki`
  - `docker-compose -p aa-demo -f docker-compose.yml restart grafana`

To make that work, the `orchestrator` service has:

- the Docker socket mounted
- the repo mounted read-only at its host-absolute path
- `docker-compose` installed in the service image

This is intentionally demo-oriented and should not be treated as a production pattern.

## Notes

- The demo is intentionally simple and deterministic.
- The backing API is the source of truth for tool definitions.
- Kong is the only public entry point for agent and MCP traffic.
- `docker compose config` now resolves locally with placeholder `.env` values.
- `deck file validate kong/deck/kong.yaml` passes offline validation.
- service dependencies now include `langgraph` and `openai`, but I did not run a live service boot locally because the workspace Python environment does not have the app dependencies installed outside Docker.
- live Konnect validation and sync still require your real Konnect control plane name, token, and hybrid certificates.
