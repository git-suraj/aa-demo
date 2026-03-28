# Context

## Project Summary

This repo is a Kong-governed multi-agent demo for a customer escalation workflow.

Core flow:
- UI sends a `Play` request through Kong to the orchestrator.
- Orchestrator gathers account context through MCP tools exposed by Kong.
- Orchestrator calls two sub-agents through Kong:
  - `support-agent`
  - `success-agent`
- Orchestrator produces a final executive brief through Kong-routed LLM endpoints.

Main code locations:
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/orchestrator/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/support_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/success_agent/app.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/llm.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/services/common/mcp_client.py`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml`
- `/Users/surajpillai/Documents/work/demos/learn/aa-demo/observability/grafana/dashboards/kong-governance-overview.json`

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

Important environment wiring:
- orchestrator uses `AGENT_API_KEY=orchestrator-demo-key`
- support-agent uses `AGENT_API_KEY=support-demo-key`
- success-agent uses `AGENT_API_KEY=success-demo-key`
- orchestrator LLM base URL: `http://kong-dp:8000/ai/orchestrator`
- sub-agent LLM base URL: `http://kong-dp:8000/ai/subagent`
- orchestrator now also has Docker access for the demo-only observability reset flow:
  - Docker socket mounted
  - repo mounted read-only at the host-absolute path
  - `docker-compose` installed in the service image

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

Operational caveats:
- run history is not persisted to Redis, Loki, or disk
- restarting or recreating the orchestrator clears all saved runs
- after the orchestrator rebuild/restart done for this feature, only new runs created afterward will appear in the dropdown

Related runtime issue we hit:
- after rebuilding `ui` and `orchestrator`, Kong temporarily served `502` for `http://localhost:8000`
- root cause was stale upstream container IPs inside Kong after container recreation
- restarting `kong-dp` fixed upstream resolution

## Semantic Cache / Guard Metrics

User asked for:
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
