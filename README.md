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

## What it will show

- 1 orchestrator agent
- 2 sub-agents
- 1 backing REST API exposed as MCP tools through Kong's `ai-mcp-proxy`
- per-agent tool visibility enforced with Consumers and Consumer Groups
- LangGraph-based deterministic agent workflows
- an orchestrator LLM call for planning and synthesis
- a lightweight UI that visualizes the request flow

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
  - intentionally starts with a broken OpenAI primary path so the demo can show fallback behavior
- `/ai/orchestrator-token-demo/chat/completions`
  - used only for the AI token limit scenario
  - protected by Kong `ai-rate-limiting-advanced`
- `/ai/orchestrator-prompt-enhance-demo/chat/completions`
  - used only for the prompt decorator scenario
  - applies a stronger prompt-decoration policy to shape a more structured executive output
- `/ai/orchestrator-semantic-guard-demo/chat/completions`
  - used only for the semantic guard scenario
  - protected by Kong `ai-semantic-prompt-guard` with Redis as the vector database
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
- that route is configured so the OpenAI primary path fails deterministically
- the run emits explicit policy events showing:
  - the primary OpenAI path was attempted
  - the primary path failed
  - Gemini was selected as the fallback model
- the orchestrator then continues the rest of the run using Gemini
- the support and success sub-agents still use their normal Gemini sub-agent route

Important note:

- in the current implementation, the demo shows the failover outcome through Kong-routed calls and orchestrator policy handling after the primary path returns `401`
- the visible result is still the intended demo story: OpenAI fails, Gemini completes the run

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

## Implemented services

- [UI](/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/index.html): static single-screen demo UI with `Play`, `Reset`, live flow states, and event log
- [orchestrator](/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py): receives `POST /play`, exposes `WS /trace`, calls MCP through Kong, invokes the support-agent first, then invokes the success-agent with support context
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

The UI is hosted through Kong and uses the same gateway for:

- `/orchestrator`
- `/orchestrator/trace`
- `/mock-mcp`
- `/ai/orchestrator/chat/completions`
- `/ai/subagent/chat/completions`

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

## Notes

- The demo is intentionally simple and deterministic.
- The backing API is the source of truth for tool definitions.
- Kong is the only public entry point for agent and MCP traffic.
- `docker compose config` now resolves locally with placeholder `.env` values.
- `deck file validate kong/deck/kong.yaml` passes offline validation.
- service dependencies now include `langgraph` and `openai`, but I did not run a live service boot locally because the workspace Python environment does not have the app dependencies installed outside Docker.
- live Konnect validation and sync still require your real Konnect control plane name, token, and hybrid certificates.
