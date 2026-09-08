# AA-Demo-2 agent cost attribution

Each LLM request is authenticated through one of these stable native AI Gateway
Consumer identifiers. Their display names and billing customer keys use the
requested `aa-demo-2-*` naming:

| Agent | Billing customer |
| --- | --- |
| `orchestrator-agent` → `aa-demo-2-orchestrator` | AA-Demo-2 Orchestrator |
| `support-agent` → `aa-demo-2-support-agent` | AA-Demo-2 Support Agent |
| `success-agent` → `aa-demo-2-success-agent` | AA-Demo-2 Success Agent |

The `metering-and-billing` policy is attached to those Consumers. It meters AI
input and output tokens, using the authenticated Consumer as the event subject.
The model-based DataKit router forwards the original key to its internal calls,
so selector and final-model usage stays attributed to the initiating agent.

## Setup

Add a Konnect system-account token with Metering & Billing and AI Gateway read
access to `.env` (a personal access token is not sufficient for event ingest):

```dotenv
KONNECT_SYSTEM_TOKEN=spat_...
KONNECT_METERING_INGEST_ENDPOINT=https://us.api.konghq.com/v3/openmeter/events
```

`start_rag_demo.sh` runs the following automatically. They are also useful for
an isolated manual retry:

```sh
set -a && source .env && set +a
kongctl diff -f kongctl/ai-gateway
kongctl apply -f kongctl/ai-gateway
python3 scripts/setup_ai_gateway_metering_billing.py
```

The bootstrap script creates an LLM-token meter (`kong.llm_request` events,
grouped by model and request/response token type), six rate-card features, a monthly plan, three
billing customers, and their subscriptions. Each customer invoice shows:

```text
AA-Demo-2 Support Agent
├── OpenAI GPT-4o mini input cost
├── OpenAI GPT-4o mini output cost
├── Gemini 2.5 Flash input cost
├── Gemini 2.5 Flash output cost
└── Total cost
```

The same breakdown is created for `o3-mini`. The deliberately inflated
per-1,000-token demo rates make each model and token direction visible in Konnect:

| Model | Input | Output |
| --- | ---: | ---: |
| OpenAI GPT-4o mini | $1.00/1K tokens | $3.00/1K tokens |
| Gemini 2.5 Flash | $0.80/1K tokens | $2.50/1K tokens |
| OpenAI o3-mini | $2.00/1K tokens | $6.00/1K tokens |

The per-model cost and rolled-up agent total are therefore visible even for a
short demo request.

`stop_rag_demo.sh` tears down the billing catalog before deleting the managed
AI Gateway child entities. It intentionally retains the pre-created
`AA-Demo-2` gateway and its data-plane attachment, so a later start can
recreate the demo from the same `.env`.
