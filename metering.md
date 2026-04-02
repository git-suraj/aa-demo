# Kong Metering And Billing Plan

This document is a planning note for implementing Kong Metering & Billing in this demo. It does not describe implemented behavior yet.

## Goal

Add Kong Metering & Billing so this demo can attribute:

- LLM token usage
- backend API usage

Both should be attributable by Consumer.

The business entities for this demo are:

- `mock-api` backend
- `orchestrator`
- `support-agent`
- `success-agent`

## Confirmed implementation decisions

- authentication for setup/teardown scripts:
  - personal access token from `.env`
- target Konnect control plane:
  - `KONNECT_CP_ID` from `.env`
  - confirmed value for current environment:
    - `73d2189b-8711-47c2-a11e-7e122eabd1d7`
- implementation language:
  - Python
- automation model:
  - one setup script provisions all demo-managed Metering & Billing entities
  - one teardown script removes only demo-managed Metering & Billing entities
- safety boundary:
  - it is safe for the scripts to create and delete demo-specific Metering & Billing entities in this Konnect environment
- naming convention:
  - use a repo-specific prefix such as `aa-demo-` for all script-managed entities
- Consumer/customer mapping:
  - create billing/customer mappings for:
    - `orchestrator-agent`
    - `support-agent`
    - `success-agent`
  - do not include `ui-client`
  - Kong Consumers themselves already exist as part of the main demo setup
- teardown scope:
  - remove only Metering & Billing entities created by the demo automation
  - do not delete the existing control-plane Consumers
- validation approach:
  - no separate validation script
  - validation will happen through the normal demo flow

## What Kong supports

Kong Metering & Billing supports:

- API Gateway request metering
- AI Gateway token metering
- customer mapping based on Consumer attribution
- product catalog features, plans, rate cards, and subscriptions

Official docs:

- https://developer.konghq.com/metering-and-billing/
- https://developer.konghq.com/metering-and-billing/get-started/

Important documented model:

- Kong Gateway usage is attributed to a Consumer
- Metering & Billing customers can include usage from that Consumer
- billable features are created by filtering raw meter data, for example by `service_name`

## Current repo shape

Current Consumers in [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml):

- `orchestrator-agent`
- `support-agent`
- `success-agent`
- `ui-client`

Current traffic surfaces relevant to billing:

- AI routes:
  - orchestrator AI routes
  - sub-agent AI route
  - scenario-specific AI routes
- backend/API routes:
  - `/api`
  - `/mock-mcp`
  - upstream service: `mock-api-service`

Important implication:

- the intended billable entities are the backend plus the three agents
- this aligns well with the current technical Consumer model for the agents
- backend usage should be billed at the MCP tool invocation level, with attribution following the calling Consumer

## Implementation plan

### 1. Use the agent/backend entity model

The implementation should treat these as the billable entities:

- `orchestrator`
- `support-agent`
- `success-agent`
- `mock-api`

This means:

- token billing should be separated by the three agent Consumers
- backend API billing should be tracked for the `mock-api` surface
- `ui-client` should not be a billable entity unless explicitly added later

### 2. Enable Metering & Billing for this Konnect control plane

Enable the built-in Kong meters for:

- API Gateway requests
- AI Gateway token usage

This should be done for the control plane used by this repo so Kong starts feeding the right usage streams into Metering & Billing.

### 3. Define the billable surfaces

Map the demo’s runtime traffic to billable product surfaces.

Initial billable surfaces:

- MCP tool invocation usage
- orchestrator LLM token usage
- support-agent LLM token usage
- success-agent LLM token usage

Optional expanded surfaces:

- deeper provider/model reporting
- additional endpoint-level breakdowns if needed later

### 4. Create features for backend API usage

Use API Gateway request metering to define one or more features for backend traffic.

Chosen backend billing model:

- bill every MCP tool invocation

Planned first feature set:

- `get_customer_account-invocations`
- `get_renewal_risk-invocations`
- `get_open_tickets-invocations`
- `get_incident_status-invocations`
- `search_runbook-invocations`
- `draft_customer_reply-invocations`
- `create_followup_task-invocations`

Pricing assumption:

- each MCP tool invocation feature should have its own distinct rate card

Likely first filter shape:

- meter: `API Gateway Requests`
- group/filter by route/service dimensions plus the MCP/backend path shape needed to isolate each tool invocation

Optional later refinement:

- regroup only if the seven-feature model becomes too noisy for reporting, not for initial pricing

### 5. Create features for AI token usage

Use AI Gateway metering to define token-related features.

Chosen token billing model:

- separate input vs output token features
- preserve separate provider/model visibility for reporting and showback

Planned first feature set:

- `orchestrator-input-tokens`
- `orchestrator-output-tokens`
- `support-agent-input-tokens`
- `support-agent-output-tokens`
- `success-agent-input-tokens`
- `success-agent-output-tokens`

Planned reporting breakdown:

- consumer/entity
- provider
- model

### 6. Map Consumers to Metering & Billing customers

Create Metering & Billing customers and map them to the Consumers that should pay for the usage.

Expected first customer/entity mapping:

- customer/entity for `orchestrator-agent`
- customer/entity for `support-agent`
- customer/entity for `success-agent`

Optional later mapping:

- a reporting construct for `mock-api` usage if you want the backend surface called out separately in billing or analytics

The customer mapping should use Kong’s Consumer-based usage attribution model.

### 7. Create plans and rate cards

Define separate plans for API and LLM usage, and use tiered pricing so the demo can show pricing bands instead of only flat per-unit usage.

Required plan shape:

- one API plan for backend request usage
- one LLM plan for token usage

Recommended first catalog shape:

- `API Plan`
  - features:
    - one rate card per MCP tool invocation feature
  - pricing model: tiered
- `LLM Plan`
  - features:
    - input/output token features for orchestrator
    - input/output token features for support-agent
    - input/output token features for success-agent
  - pricing model: tiered

Example demo-friendly tiering approach:

- API Plan
  - tier 1: low-volume MCP tool usage band
  - tier 2: mid-volume MCP tool usage band
  - tier 3: high-volume MCP tool usage band
- LLM Plan
  - tier 1: lower token price up to a threshold
  - tier 2: different token price above that threshold
  - tier 3: highest-volume usage band
  - thresholds should differ from API thresholds

Likely first pricing model:

- tiered pricing for each plan’s rate cards

Why this shape:

- it clearly separates API showback from LLM showback
- it lets the demo show two distinct cost products
- tiering is easier to explain visually in invoices and plan setup than a single flat rate
- API and LLM can use different thresholds because their consumption patterns differ

### 8. Align gateway auth and attribution

Review the auth flow on all billable routes to ensure Kong resolves the intended Consumer for:

- AI routes
- MCP route
- backend API route

This is critical because Metering & Billing attribution is only correct if Kong identifies the right Consumer on the request path.

Validation points:

- orchestrator AI traffic resolves `orchestrator-agent`
- support-agent AI traffic resolves `support-agent`
- success-agent AI traffic resolves `success-agent`
- MCP/backend traffic resolves the correct calling Consumer
- each MCP tool invocation can be isolated cleanly as a billable feature

### 9. Update repo configuration and documentation

When implementation starts, update these areas:

- [kong/deck/kong.yaml](/Users/surajpillai/Documents/work/demos/learn/aa-demo/kong/deck/kong.yaml)
  - any Consumer/auth changes needed for attribution
  - any route/service naming cleanup needed to make feature filters easier
- [README.md](/Users/surajpillai/Documents/work/demos/learn/aa-demo/README.md)
  - explain what is billed
  - explain how attribution works
  - explain which Consumers map to which customers
- required helper scripts
  - one setup script that provisions all Metering & Billing entities
  - one teardown script that removes the provisioned Metering & Billing entities
  - optional validation script for sample traffic and verification

Planned operator experience:

- one command to set everything up
- one command to tear everything down
- no manual Konnect UI setup required for the normal workflow

Likely implementation shape:

- `scripts/setup_metering_billing.*`
- `scripts/teardown_metering_billing.*`
- likely shared Python helpers if Konnect API orchestration becomes large

Expected setup responsibilities:

- create or update the required meters
- create features for MCP tool invocations
- create features for agent input/output token usage
- create customers mapped to the intended Consumers
- create the API and LLM plans
- create all tiered rate cards
- start the required subscriptions

Script/runtime assumptions:

- scripts read credentials and control-plane configuration from `.env`
- scripts target the control plane defined by `KONNECT_CP_ID`
- scripts should be safe to re-run without creating duplicate demo entities

Expected teardown responsibilities:

- remove subscriptions created for the demo
- remove plans and rate cards created for the demo
- remove features created for the demo
- remove customers created for the demo if they are demo-specific
- remove or disable meters created specifically for the demo if safe to do so

Important implementation principle:

- setup and teardown should be idempotent
- setup should be safe to re-run
- teardown should remove only the entities managed by the demo automation

### 10. Validate in stages

Validation should happen in three passes.

#### Pass 1: backend-only validation

Generate backend/API traffic and confirm:

- request usage appears in Metering & Billing
- usage is attributed to the intended Consumer/customer
- feature filters isolate only the backend usage you want billed

#### Pass 2: AI-only validation

Generate orchestrator and sub-agent LLM traffic and confirm:

- token usage appears in Metering & Billing
- usage is attributed to the intended Consumer/customer
- token features separate the traffic the way you expect

#### Pass 3: end-to-end validation

Run the normal demo flow and confirm:

- backend request usage is visible
- token usage is visible
- both are attributed to the expected Consumer/customer
- invoice preview or cost view shows:
  - MCP tool usage under the API plan
  - token usage under the LLM plan
  - input/output token attribution by agent
  - provider/model visibility for token showback
  - tier transitions or tiered totals matching the expected usage story

### 11. Optional second phase

After the basic rollout works, possible follow-up improvements:

- per-tool billing for MCP tools
- per-model billing for OpenAI vs Gemini
- internal showback vs external billing split
- stronger linkage between Metering & Billing and existing Grafana/Loki dashboards
- declarative or scripted provisioning for more of the Metering & Billing setup

## Key design warning

The current repo already uses Consumers, and in this clarified plan that is acceptable because the intended billable entities are system actors plus the backend surface.

That means:

- agent token usage can be billed directly with the existing Consumer model
- MCP tool usage can be billed directly with attribution following the calling Consumer
- this fits the internal cost attribution/showback goal

## Open questions

No major product-shape questions remain based on the current decisions.

Implementation-time questions may still arise around exact Konnect API behavior, entity lifecycles, and naming/idempotency strategy, but the billing model itself is now defined.
