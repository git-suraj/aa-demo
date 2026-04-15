# Context

## Project Summary

This repo is a Kong-governed multi-agent demo for a customer escalation workflow.

Core flow:
- UI sends a `Play` request through Kong to the orchestrator.
- Orchestrator gathers account context through MCP tools exposed by Kong.
- Orchestrator discovers two sub-agents through Kong using `GET /.well-known/agent-card.json`.
- Kong rewrites the discovered agent card URLs to the gateway address.
- Orchestrator calls two sub-agents through Kong using A2A-native `message/stream` handoffs:
  - `support-agent`
  - `success-agent`
- Orchestrator produces a final executive brief through Kong-routed LLM endpoints.

Main code locations:
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/support_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/success_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/llm.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/mcp_client.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/a2a_sdk_server.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/grafana/dashboards/kong-governance-overview.json`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/konnect/dashboards/aa-demo-api-analytics.json`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/konnect/dashboards/aa-demo-ai-dashboard.json`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/scripts/upload_konnect_dashboards.py`

## Runtime Shape

Relevant services in `docker-compose.yml`:
- `orchestrator`
- `support-agent`
- `success-agent`
- `mock-api`
- `kong-dp`
- `loki`
- `grafana`
- `redis-stack`
- `ui`

## Current UI State

Important current UI behaviors:

- header actions are:
  - `Scenes`
  - `View Diagrams`
  - `Reset Scene`
  - `Reset Observability`
  - `View Run Output`
  - `?` help modal for the scenario and agent-role explainer
- topology nodes all expose a `+` detail button
- Kong is the primary highlighted node
- `MCP Tools` is intentionally highlighted at lower intensity than Kong
- `Recent Runs` in the sidebar is populated from `TraceBroker`
- `Reset Observability` also clears the recent-runs UI state
- `Trace Explorer` opens a custom trace UI backed by normalized Loki events

Diagram modal state:

- `View Diagrams` contains:
  - a normal-scenario UML-style sequence diagram
  - LangGraph state diagrams for orchestrator, support-agent, and success-agent
- `Open Full Width` opens the sequence diagram in a separate top-level dialog

Current UI files to inspect for this behavior:
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/index.html`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/styles.css`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/ui/app.js`

Important environment wiring:
- orchestrator uses `AGENT_API_KEY=orchestrator-demo-key`
- support-agent uses `AGENT_API_KEY=support-demo-key`
- success-agent uses `AGENT_API_KEY=success-demo-key`
- orchestrator LLM base URL: `http://kong-dp:8000/ai/orchestrator`
- sub-agent LLM base URL: `http://kong-dp:8000/ai/subagent`
- agent-to-agent tracing now uses a shared `context_id` per escalation run alongside the existing `run_id`
- `context_id` is the primary conversation key
- `run_id` is the demo execution key
- `task_id` is the A2A task key
- `message_id` is the A2A message key
- orchestrator now also has Docker access for the demo-only observability reset flow:
  - Docker socket mounted
  - repo mounted read-only at the host-absolute path
  - `docker-compose` installed in the service image

## Current A2A Shape

Important current A2A behavior:

- Kong Gateway is `3.14.0.1`
- support-agent and success-agent are now served by `a2a-sdk[http-server]==0.3.26`
- SDK-generated agent cards report A2A protocol version `0.3.0`
- `ai-a2a-proxy` is applied at service scope for:
  - `support-agent-service`
  - `success-agent-service`
- discovery is through Kong on:
  - `/support-agent/.well-known/agent-card.json`
  - `/success-agent/.well-known/agent-card.json`
- execution is through Kong on:
  - `/support-agent/a2a`
  - `/success-agent/a2a`
- the orchestrator uses SDK-compatible `message/stream` instead of polling `tasks/get`
- the orchestrator does not send `taskId` on the first message; the SDK creates the task and returns the task id in streamed events
- sub-agents expose `tasks/get` through the SDK task store as a protocol-compatible inspection endpoint

Task lifecycle model:

- one `context_id` can contain multiple A2A tasks
- one `task_id` can contain multiple `message_id`s
- sub-agent task state is emitted by the A2A SDK over SSE with:
  - `submitted`
  - `working`
  - `completed`
  - `failed`
- `message/stream` emits SDK event objects:
  - `status-update` for task state changes
  - `artifact-update` for result artifacts
- the orchestrator folds those SDK stream events back into the task/result shape used by the rest of the demo

Current implementation files:

- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/a2a.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/a2a_tasks.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/a2a_sdk_server.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/support_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/success_agent/app.py`

## Trace Surfaces

There are now four trace surfaces:

- `TraceBroker`
  - recent runs and live run updates for the main UI
- Grafana + Loki
  - operational dashboarding and context trace tables
- Jaeger
  - local OpenTelemetry trace UI for Kong spans, GenAI spans, and A2A spans
- custom `Trace Explorer`
  - a UI for loading normalized events for a `context_id`

The custom trace explorer endpoint is:

- `/orchestrator/trace/context/{context_id}/events`

It queries Loki and normalizes:

- A2A discovery
- A2A execution
- MCP `initialize`
- MCP `notifications/initialized`
- MCP `tools/list`
- MCP `tools/call`
- LLM planning and synthesis calls

## Expected LLM Call Counts Per Normal Run

For a normal run:
- orchestrator should produce `5` LLM calls
  - 3 tool-selection/planner calls
  - 1 triage brief call
  - 1 executive summary call
- support-agent should produce `3` LLM calls
  - 2 tool-selection/planner calls
  - 1 technical summary call
- success-agent should produce `3` LLM calls
  - 2 tool-selection/planner calls
  - 1 success summary call

Expected per-model totals for a normal run:
- `gpt-4o-mini-2024-07-18` = `5`
- `gemini-2.5-flash` = `6`

## Grafana / Loki Findings

### Current Table Semantics

Important interpretation notes for the A2A context table:

- `tasks/get`
  - protocol-compatible task inspection endpoint exposed through the A2A SDK task store
  - no longer the orchestrator's main execution path
- `message/stream`
  - current orchestrator-to-subagent execution path through the A2A SDK
- `task_state`
  - request-level final state extracted by Kong from the streamed A2A response
  - not a separate row per SSE event in the Kong http-log record
- `notifications/initialized`
  - MCP lifecycle handshake noise after `initialize`
- `task_stage = planning`
  - synthetic label for orchestrator or sub-agent LLM planner calls before tool execution

The Grafana A2A table was simplified to remove:

- `TTFB`
- `Stage Detail`
- `Subject`
- `SSE Events`
- `A2A Binding`
- `A2A Task ID`

### Dashboard Consolidation

User wanted one dashboard instead of separate governance and run dashboards.

Current direction:
- governance dashboard now has a `Run ID` variable
- `Run ID = All` should show all labeled runs
- selecting a concrete run id should scope the governance dashboard to that run

### Cost Mismatch Root Cause

Original issue:
- governance dashboard cost panels used hardcoded `[1h]`

That caused mismatches because Grafana time range and query window did not match.

Fix applied:
- changed cost panels to use `[$__range]`

### "All Runs" Mismatch Root Cause

Another issue:
- governance dashboard originally used `run_id=~"$run_id"`
- when `Run ID = All`, Grafana expands to `.*`
- that matched blank `run_id` too

Effect:
- unlabeled traffic was included in the "All" view

Fix applied:
- added `run_id!=""` to run-scoped dashboard queries

### Average Cost Meaning

Original panel:
- `Average Cost By Agent`
- query used `avg_over_time(...)`

That was actually average cost per LLM call, not average total cost per run.

User intent:
- average agent cost across runs

Fix applied:
- panel now computes:
  - per `(consumer, run_id)` total cost
  - then average of those per-run totals by `consumer`
- title changed to `Average Cost Per Run By Agent`

## Key LLM Logging Bug We Found

This was the important debugging thread.

Observed symptom:
- `LLM Calls By Model`
- `LLM Calls By Agent And Model`
- support and success were showing `1` instead of expected `3`

Initial suspicion:
- dashboard query issue

What Loki proved:
- the missing planner calls existed
- but for earlier runs they were logged with `run=""`
- only the final sub-agent summary call had the real `run_id`

Important evidence:
- for historical run `3d4f8dd5-c303-48bf-9d03-f32c047ad507`, Loki showed:
  - `orchestrator-agent = 5`
  - `support-agent = 1`
  - `success-agent = 1`
- inspecting nearby sub-agent LLM logs showed the missing planner calls existed with blank run id

## Code Fixes Applied

### 1. Pass `run_id` into sub-agent planner calls

Fixed in:
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/support_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/success_agent/app.py`

Change:
- `llm.choose_next_tool(...)` now receives `run_id=params["run_id"]`

### 2. Replace `AsyncOpenAI` path in shared LLM client

Critical fix in:
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/llm.py`

What changed:
- `OrchestratorLLM.generate(...)` no longer uses `AsyncOpenAI`
- it now uses explicit `httpx.AsyncClient.post(...)`
- headers are set directly:
  - `apikey`
  - `content-type`
  - `x-demo-run-id`

Reason:
- planner calls were still arriving in Kong/Loki with blank `run_id`
- switching to explicit HTTP requests removed ambiguity in header propagation

### 3. Dashboard count windows

Updated:
- governance dashboard LLM count panels use `[$__range]`

## Verified Fresh Run After Fix

After rebuilding and restarting:
- `orchestrator`
- `support-agent`
- `success-agent`

I triggered a fresh run:
- `6890278c-9815-4015-ac87-eadf224c6834`

Verified in Loki:
- `orchestrator-agent -> gpt-4o-mini-2024-07-18 = 5`
- `support-agent -> gemini-2.5-flash = 3`
- `success-agent -> gemini-2.5-flash = 3`

Also verified raw sub-agent LLM log lines for that run:
- support-agent had 3 `/ai/subagent/chat/completions` entries with the correct run id
- success-agent had 3 `/ai/subagent/chat/completions` entries with the correct run id

Conclusion:
- fix is live for new runs
- old Loki data remains historically incorrect

## Historical Runs

Important note for future debugging:
- previously generated runs will still show wrong counts if their planner calls were logged without `run_id`
- Grafana cannot retroactively fix old Loki entries
- only fresh runs after the service rebuild reflect the corrected behavior

## Current Dashboard State

Governance dashboard changes currently include:
- optional `Run ID` selector
- `All` mode excludes blank `run_id`
- cost panels respect `[$__range]`
- LLM count panels respect `[$__range]`
- average cost panel means average per-run cost by agent
- ambiguous single-series tiles now force label rendering and clearer titles

Additional dashboard cleanup:
- token panels now exclude blank `llm_usage_model`, which removed phantom `0` rows
- model-grouped cost panels also exclude blank `llm_usage_model`
- agent/model label shortening is done at the display layer, not by hardcoding agent or model names in the Loki queries
- governance dashboard now also includes:
  - `Semantic Guard Blocked Requests`
  - `Semantic Cache Hits`
  - `Semantic Cache Misses`
- `Context Trace Table` is present on the governance dashboard
- A2A log/table queries now include SDK execution traffic on `/a2a` as well as legacy `/v1/jsonrpc`
- the metering/billing dashboard agent latency and agent log-stream panels also include `/a2a`

## Jaeger OpenTelemetry State

Current implementation:
- `jaeger` runs as part of the normal Docker Compose stack
- Kong tracing is enabled with:
  - `KONG_TRACING_INSTRUMENTATIONS=all`
  - `KONG_TRACING_SAMPLING_RATE=1.0`
- Kong has a global `opentelemetry` plugin exporting traces to:
  - `http://jaeger:4318/v1/traces`
- Kong post-function tagging adds searchable trace attributes:
  - `demo.run_id`
  - `demo.context_id`
  - `a2a.task_id`
  - `a2a.message_id`

Latest SDK validation run:
- run id: `f34eb1d2-899f-4727-bb32-ae23a3788985`
- context id: `ctx-7dfe3072-a372-4c6f-a2b4-d5a648bfeea8`
- Jaeger trace id: `64f9561a571b467430bf2d0c6987354d`
- span count observed: `268`
- Jaeger includes:
  - `kong.a2a`
  - `kong.access.plugin.ai-a2a-proxy`
  - `kong.access.plugin.ai-proxy-advanced`
  - GenAI span tags
  - A2A span tags including `kong.a2a.task.state`, `kong.a2a.task.id`, `kong.a2a.sse_events_count`, and `kong.a2a.streaming`

Interpretation:
- Jaeger is good for one end-to-end trace tree when trace context is propagated.
- Grafana/Loki remains better for tabular A2A/MCP/LLM event inspection.
- Jaeger is not intended to replace Grafana for metric-style dashboard panels.

Konnect dashboard assets:
- two Konnect Analytics tile-definition JSONs were added under `observability/konnect/dashboards`
- these should now be treated as the exact exported dashboard definitions to import
- `scripts/upload_konnect_dashboards.py` is now the only intended provisioning path
- the stored exports already include a `control_plane` preset filter shape
- the uploader validates that the supplied control plane id is a non-empty UUID
- it preserves the exported dashboard definition and rewrites only the `control_plane` preset filter value at upload time
- it also allows dashboard-name overrides via `--api-dashboard-name` and `--ai-dashboard-name`
- it uses the Konnect Dashboards API to overwrite by name when the dashboard already exists or create it when absent

## UI Trace History

New UI capability:
- the trace sidebar now includes a `Recent Runs` dropdown

Behavior:
- the orchestrator stores the most recent 20 runs in memory inside `TraceBroker`
- each stored run includes summary metadata plus the ordered list of emitted trace events
- UI calls:
  - `GET /orchestrator/trace/runs`
  - `GET /orchestrator/trace/runs/{run_id}`
- when a run is selected, the UI replays the stored event stream through the existing `handleTraceEvent(...)` path
- this means the execution tree and selected-step detail pane update exactly as if that run were streaming live

Implementation details:
- backend persistence is intentionally lightweight and bounded:
  - `services/common/trace.py`
  - uses an `OrderedDict`
  - keeps only the latest 20 runs
- replay uses the existing frontend reducer rather than a second tree-building code path:
  - `ui/app.js`
- sidebar markup and styling were updated in:
  - `ui/index.html`
  - `ui/styles.css`

Additional current behavior:
- `Reset Observability` now clears the recent-runs dropdown and selected replay state in the frontend after the backend reset succeeds

Operational caveats:
- run history is not persisted to Redis, Loki, or disk
- restarting or recreating the orchestrator clears all saved runs
- after the orchestrator rebuild/restart done for this feature, only new runs created afterward will appear in the dropdown
- the selected historical run now also updates the `View Run Output` pane, not just the tree trace

Related runtime issue we hit:
- after rebuilding `ui` and `orchestrator`, Kong temporarily served `502` for `http://localhost:8000`
- root cause was stale upstream container IPs inside Kong after container recreation
- restarting `kong-dp` fixed upstream resolution

## Semantic Cache / Guard Metrics

User asked for:

## Recent Governance / UI Fixes

### LLM as Judge UI and Grafana

Fixes applied:
- the `LLM as Judge` scene now has three prompt presets:
  - `Escalation Triage`
  - `KongHQ Overview`
  - `Low Score Probe`
- the prompt text area is now editable
- selecting a radio preset preloads the text area, but the edited text box value is what gets sent on play

Important bug that was fixed:
- the radio buttons live outside `#play-form`
- `FormData(playForm)` was therefore not carrying `llm_judge_prompt_choice`
- `ui/app.js` now injects the selected preset explicitly when playing the judge scenario

Grafana / Kong logging fixes:
- `LLM as Judge Evaluations` was initially empty even though the route was being called
- root causes included:
  - Kong Lua transform using the wrong JSON path for judge fields
  - request/response payload decoding bugs
  - Grafana table transformations that were too fragile
- current state:
  - judge route logs are present in Loki
  - the table renders from the raw judge-route logs
  - the raw judge-only log panel was replaced with a full-width `Kong Raw Log Stream`

Judge input logging fix:
- the Kong log transform originally concatenated all request messages, including the hidden system prompt
- that made Grafana's `Input` column look like the preset text had been sent even when the text area had been edited
- the transform now records only `user`-role content for `judge_input`

Judge route stability fix:
- the judge demo route originally allowed Gemini as both a candidate target and the judge model
- that caused intermittent failures when the candidate path selected Gemini
- the route was corrected so the candidate model is OpenAI only and the judge model is Gemini only

Judge topology timing refinement:
- the UI originally used short synthetic judge timers, which made OpenAI appear to linger too long and the judge appear to complete too quickly compared with Grafana latency
- `ui/app.js` was adjusted so the judge model gets a longer minimum visible dwell of about 4 seconds and the orchestrator/UI return starts later
- this is still a visualization aid, but it now tracks the real multi-second judge latency much more closely

### Token-limit scenario

Observed issue:
- Kong correctly returned `429` on `/ai/orchestrator-token-demo/chat/completions`
- orchestrator still surfaced `500`

Root cause:
- token-limit handling still assumed OpenAI SDK exceptions
- shared LLM client now uses `httpx`, so Kong policy failures arrived as `httpx.HTTPStatusError`

Fix applied:
- `services/orchestrator/app.py`
- token-limit `429` and semantic-guard `400` are now handled correctly for the `httpx` path
- governed blocked responses now return as structured policy results instead of `500`

### PII sanitizer request/response trace

Observed issue:
- placeholder and synthetic modes visibly passed through the PII service twice
- the tree trace only showed one generic sanitizer step

Fix applied:
- `services/orchestrator/app.py` now emits:
  - `pii_sanitizer_request`
  - `pii_sanitizer_response`
- `ui/app.js` renders these as separate trace nodes

Additional UI fix:
- the response-side PII box on the topology return path was not visibly highlighted because the return completed too quickly
- a dedicated dwell timer was added so the response-side PII highlight is now visible before settling

Later refinements:
- the block mode topology was changed to stay green rather than turning red
- the blocked return leg now deliberately holds `pii-service`, `orchestrator`, `kong`, and `dashboard` active a bit longer so the return path is visible before settling

## Failover Findings

This became a separate debugging thread.

What was tested:
- invalid OpenAI auth returning `401`
- invalid model name returning provider-native `404`
- request-termination simulator route returning `503`
- unreachable upstream URL returning transport timeout/error
- Kong `3.13.0.1`
- Kong `3.12.0.0`

What was learned:
- `401` is not usable because this Kong version does not support `http_401` in `failover_criteria`
- invalid-model `404` was not usable in practice because the Kong AI route surfaced it as `400`
- request-termination and unreachable-upstream simulations both showed the same problem:
  - Kong logically considered fallback targets
  - but the effective upstream in logs still reflected the primary target's `upstream_url`
  - fallback targets were then marked failed without clear evidence of a real provider call

Most important conclusion:
- there is strong evidence of an `ai-proxy-advanced` bug or limitation in per-target `upstream_url` handling during failover
- the clearest clue was that one failover experiment only started working when the OpenAI target's `upstream_url` was pointed at a Gemini endpoint
- that suggests `upstream_url` is influencing transport beyond the primary target in ways that are not expected

Version comparison:
- reproduces on Kong Enterprise `3.13.0.1`
- also reproduces on Kong Enterprise `3.12.0.0`
- therefore this does not look like a 3.13-only regression

Current practical state:
- local `docker-compose.yml` is on Kong Gateway `3.14.0.1`
- failover scenario should be treated as experimental in this repo unless re-validated with a proven provider-native failover condition that Kong surfaces as a supported criterion
- semantic guard blocked requests
- semantic cache hits
- semantic cache misses

Current implementation:
- `Semantic Guard Blocked Requests`
  - counts `status="400"` on `ai-orchestrator-semantic-guard-demo-chat-route`
- `Semantic Cache Hits`
  - counts `ai_cache_status = "hit"` on `ai-orchestrator-semantic-cache-demo-chat-route`
- `Semantic Cache Misses`
  - counts `ai_cache_status = "miss"` on `ai-orchestrator-semantic-cache-demo-chat-route`

Important correction:
- initial cache hit/miss implementation inferred hits from missing `llm_usage_model`
- user correctly pointed out Kong documents first-class semantic-cache audit fields
- implementation was changed to use Kong audit-log-derived cache status instead

Kong log transform change:
- `kong/deck/kong.yaml` now flattens semantic-cache audit fields into the Loki payload:
  - `ai_cache_status`
  - `ai_cache_fetch_latency`
  - `ai_cache_embeddings_provider`
  - `ai_cache_embeddings_model`
  - `ai_cache_embeddings_latency`

Observed live-data nuance:
- Kong logs `ai_cache_status` in lowercase:
  - `hit`
  - `miss`
- dashboard initially queried `Hit` / `Miss`
- that caused `No data`
- fixed by changing the Grafana queries to lowercase values

Observed demo-state nuance:
- a semantic-cache "first" request can still show as a hit if Redis already contains a semantically similar entry
- after live inspection, two recent semantic-cache route requests both logged as `hit`
- this was not a panel bug; it was existing cache state
- for deterministic demo validation:
  - clear semantic cache
  - run seed
  - run reuse

## Reset Observability Flow

New UI capability:
- topbar now includes `Reset Observability`

Behavior:
- UI calls `POST /orchestrator/observability/reset`
- orchestrator runs:
  - `docker-compose -p aa-demo -f docker-compose.yml rm -sf loki`
  - `docker-compose -p aa-demo -f docker-compose.yml up -d loki`
  - `docker-compose -p aa-demo -f docker-compose.yml restart grafana`

Why this shape:
- deleting Loki data via browser alone is not practical
- recreating the local Loki container is simpler than wiring a true Loki delete API
- Grafana is restarted so provisioned dashboards/datasource reconnect cleanly after Loki reset

Important implementation details:
- backend needed `docker-compose` available inside `orchestrator`
- backend needed access to `/var/run/docker.sock`
- backend needed the repo mounted at the host-absolute path, not `/workspace`, because Docker Desktop volume resolution on macOS needs real host paths for bind mounts like `observability/loki/loki-config.yaml`
- backend subprocess environment needed `PWD` set explicitly so `docker-compose.yml` variable interpolation would resolve `${PWD}` correctly

Verified behavior:
- reset endpoint returns `200`
- Loki is removed and recreated
- Grafana is restarted
- Loki comes back healthy after reset

Operational caveat:
- this is a demo-only control surface with host Docker access
- after clicking the button, wait a few seconds and refresh Grafana

## Recommended Next Checks If Work Resumes

If the next session continues from here, useful next checks are:
- confirm Grafana UI reflects the latest dashboard JSON after reload
- convert remaining token panels from fixed windows like `[1h]` or `[5m]` if exact dashboard-range parity is required everywhere
- if semantic-cache counters look wrong, inspect fresh Loki entries on `ai-orchestrator-semantic-cache-demo-chat-route` and verify actual `ai_cache_status` values before changing panel queries
