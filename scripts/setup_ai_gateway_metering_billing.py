#!/usr/bin/env python3
"""Create the AA-Demo-2 LLM-token meter, billing customers, and subscriptions.

The Metering & Billing policy emits ``kong.llm_request`` events for request and
response tokens. Kong uses the authenticated native AI Gateway Consumer as the
event subject; this script maps those consumer IDs to billing customers.
"""

from __future__ import annotations

import json
import os
import sys
import time
from decimal import Decimal
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
KONNECT_SERVER_URL = os.getenv("KONNECT_SERVER_URL", "https://us.api.konghq.com").rstrip("/")
SYSTEM_TOKEN = os.getenv("KONNECT_SYSTEM_TOKEN", "").strip()
KONNECT_PAT = os.getenv("KONGCTL_DEFAULT_KONNECT_PAT", os.getenv("KONNECT_TOKEN", "")).strip()
GATEWAY_ID = os.getenv("AIGW_GATEWAY_ID", "47e9610a-2ad8-4b19-98d3-2b5364a7f38f").strip()

LABELS = {"demo": "aa-demo-2", "managed_by": "repo_automation"}
METER = {
    "key": "aa_demo_2_llm_tokens",
    "name": "AA-Demo-2 LLM Tokens",
    "description": "Input and output LLM tokens attributed to AA-Demo-2 agents",
    "aggregation": "sum",
    "event_type": "kong.llm_request",
    "value_property": "$.tokens",
    "dimensions": {"model": "$.model", "type": "$.type"},
    "labels": LABELS,
}
# These are intentionally illustrative, inflated per-token prices. They make
# the model/input/output breakdown obvious in a short live demo.
MODEL_PRICING = (
    # AI Gateway reports the selected request model and the provider's response
    # model separately. Map both values into one customer-facing model label.
    ("gpt-4o-mini", "gpt-4o-mini-2024-07-18", "OpenAI GPT-4o mini", "0.001", "0.003"),
    ("gemini-2.5-flash", "gemini-2.5-flash", "Gemini 2.5 Flash", "0.0008", "0.0025"),
    ("o3-mini", "o3-mini", "OpenAI o3-mini", "0.002", "0.006"),
)
PLAN = {
    "key": "aa_demo_2_agent_llm_plan",
    "name": "AA-Demo-2 Agent LLM Plan",
    "currency": "USD",
    "billing_cadence": "P1M",
}
AGENTS = (
    ("orchestrator-agent", "aa-demo-2-orchestrator", "AA-Demo-2 Orchestrator"),
    ("support-agent", "aa-demo-2-support-agent", "AA-Demo-2 Support Agent"),
    ("success-agent", "aa-demo-2-success-agent", "AA-Demo-2 Success Agent"),
)


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()
KONNECT_SERVER_URL = os.getenv("KONNECT_SERVER_URL", KONNECT_SERVER_URL).rstrip("/")
SYSTEM_TOKEN = os.getenv("KONNECT_SYSTEM_TOKEN", SYSTEM_TOKEN).strip()
KONNECT_PAT = os.getenv("KONGCTL_DEFAULT_KONNECT_PAT", os.getenv("KONNECT_TOKEN", KONNECT_PAT)).strip()
GATEWAY_ID = os.getenv("AIGW_GATEWAY_ID", GATEWAY_ID).strip()


def require(value: str, name: str) -> str:
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def request(method: str, path: str, payload: dict | None = None, *, token: str | None = None) -> dict | list:
    token = token or require(SYSTEM_TOKEN, "KONNECT_SYSTEM_TOKEN")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{KONNECT_SERVER_URL}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def items(path: str, *, token: str | None = None) -> list[dict]:
    """Return every page from an OpenMeter collection.

    Subscription lists are shared across the Konnect organization. The default
    page is small enough that an existing AA-Demo-2 subscription can be absent
    from it, which would make the bootstrap try to create a duplicate active
    subscription.
    """
    records: list[dict] = []
    page_number = 1
    separator = "&" if "?" in path else "?"
    while True:
        page_path = (
            f"{path}{separator}{urllib.parse.urlencode({
                'page[size]': '100',
                'page[number]': str(page_number),
            })}"
        )
        payload = request("GET", page_path, token=token)
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return records

        page_records = payload.get("data") or payload.get("items") or payload.get("results") or []
        records.extend(page_records)
        page = ((payload.get("meta") or {}).get("page") or {})
        total = page.get("total")
        if not page_records or (isinstance(total, int) and len(records) >= total):
            return records
        page_number += 1


def by_key(path: str, key: str) -> dict | None:
    return next((item for item in items(path) if item.get("key") == key), None)


def ensure_meter() -> dict:
    existing = by_key("/v3/openmeter/meters", METER["key"])
    if existing:
        return existing
    return request("POST", "/v3/openmeter/meters", METER)  # type: ignore[return-value]


def feature_key(model: str, token_type: str) -> str:
    return f"aa_demo_2_{model.replace('-', '_').replace('.', '_')}_{token_type}_tokens"


def per_thousand_label(price_per_token: str) -> str:
    """Format a unit rate for the human-facing 1K-token rate-card label."""
    amount = Decimal(price_per_token) * Decimal("1000")
    return format(amount.normalize(), "f")


def ensure_feature(
    meter_id: str, feature_model: str, event_model: str, model_label: str, token_type: str,
) -> dict:
    logical_type = "input" if token_type == "request" else "output"
    key = feature_key(feature_model, logical_type)
    existing = by_key("/v3/openmeter/features", key)
    if existing:
        return existing
    payload = {
        "key": key,
        "name": f"{model_label} {logical_type.title()} Tokens",
        "description": f"{logical_type.title()} tokens for {model_label}",
        "labels": LABELS,
        "meter": {
            "id": meter_id,
            "filters": {"model": {"eq": event_model}, "type": {"eq": token_type}},
        },
    }
    return request("POST", "/v3/openmeter/features", payload)  # type: ignore[return-value]


def ensure_plan(features: dict[str, dict]) -> dict:
    plans = [plan for plan in items("/v3/openmeter/plans") if plan.get("key") == PLAN["key"]]
    active = next((plan for plan in reversed(plans) if plan.get("status") == "active"), None)
    if active:
        return active
    rate_cards = []
    for request_model, response_model, model_label, input_price, output_price in MODEL_PRICING:
        for event_type, price in (("request", input_price), ("response", output_price)):
            logical_type = "input" if event_type == "request" else "output"
            key = feature_key(request_model, logical_type)
            rate_cards.append({
                "key": key,
                "name": f"{model_label} {logical_type.title()} at ${per_thousand_label(price)}/1K tokens (demo pricing)",
                "feature": {"id": features[key]["id"]},
                "billing_cadence": "P1M",
                "payment_term": "in_arrears",
                "price": {"type": "unit", "amount": price},
            })
    payload = {
        "key": PLAN["key"],
        "name": PLAN["name"],
        "currency": PLAN["currency"],
        "billing_cadence": PLAN["billing_cadence"],
        "labels": LABELS,
        "pro_rating_enabled": True,
        "phases": [{
            "key": "default",
            "name": "Default",
            "rate_cards": rate_cards,
        }],
    }
    draft = request("POST", "/v3/openmeter/plans", payload)
    return request("POST", f"/v3/openmeter/plans/{draft['id']}/publish")  # type: ignore[index,return-value]


def native_consumers() -> dict[str, str]:
    # This AI Gateway endpoint currently requires a PAT. Metering & Billing
    # operations above use the system-account token instead.
    payload = request(
        "GET",
        f"/v1/ai-gateways/{urllib.parse.quote(GATEWAY_ID, safe='')}/consumers",
        token=require(KONNECT_PAT, "KONGCTL_DEFAULT_KONNECT_PAT or KONNECT_TOKEN"),
    )
    records = payload if isinstance(payload, list) else (
        payload.get("data") or payload.get("items") or payload.get("results") or []
    )
    found = {record.get("name"): record.get("id") for record in records}
    missing = [native_name for native_name, _, _ in AGENTS if not found.get(native_name)]
    if missing:
        raise RuntimeError(f"AA-Demo-2 Consumers not found: {', '.join(missing)}")
    return {native_name: found[native_name] for native_name, _, _ in AGENTS}


def ensure_customer(agent_name: str, display_name: str, consumer_id: str) -> dict:
    existing = by_key("/v3/openmeter/customers", agent_name)
    payload = {
        "key": agent_name,
        "name": display_name,
        "labels": LABELS,
        "usage_attribution": {"subject_keys": [f"consumer:{consumer_id}"]},
    }
    if existing:
        current = existing.get("usage_attribution", existing.get("usageAttribution", {}))
        subjects = current.get("subject_keys", current.get("subjectKeys", []))
        if existing.get("name") == display_name and subjects == payload["usage_attribution"]["subject_keys"]:
            return existing
        return request("PUT", f"/v3/openmeter/customers/{existing['id']}", payload)  # type: ignore[index,return-value]
    return request("POST", "/v3/openmeter/customers", payload)  # type: ignore[return-value]


def ensure_subscription(customer: dict, plan: dict) -> None:
    def current() -> list[dict]:
        return [
            item for item in items("/v3/openmeter/subscriptions")
            if item.get("customer_id") == customer["id"]
            and item.get("status") in {"active", "scheduled", "pending"}
        ]

    subscriptions = current()
    if any(item.get("plan_id") == plan["id"] for item in subscriptions):
        return

    # Each AA-Demo-2 customer is dedicated to one agent. If a previous run
    # left it on an older plan version, replace that subscription before adding
    # the new plan. OpenMeter permits only one active subscription at a time.
    for subscription in subscriptions:
        request("POST", f"/v3/openmeter/subscriptions/{subscription['id']}/cancel", {"timing": "immediate"})

    for _ in range(15):
        if not current():
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"Timed out cancelling the previous subscription for {customer['key']}")

    payload = {
        "customer": {"id": customer["id"]},
        "plan": {"id": plan["id"]},
        "labels": LABELS,
    }
    for attempt in range(15):
        try:
            request("POST", "/v3/openmeter/subscriptions", payload)
            return
        except RuntimeError as exc:
            if "only_single_subscription_allowed_per_customer_at_a_time" not in str(exc) or attempt == 14:
                raise
            time.sleep(1)
            if any(item.get("plan_id") == plan["id"] for item in current()):
                return


def main() -> int:
    require(GATEWAY_ID, "AIGW_GATEWAY_ID")
    meter = ensure_meter()
    features = {}
    for request_model, response_model, model_label, _, _ in MODEL_PRICING:
        for event_type, event_model in (("request", request_model), ("response", response_model)):
            feature = ensure_feature(meter["id"], request_model, event_model, model_label, event_type)
            features[feature["key"]] = feature
    plan = ensure_plan(features)
    consumers = native_consumers()
    for native_name, customer_key, display_name in AGENTS:
        customer = ensure_customer(customer_key, display_name, consumers[native_name])
        ensure_subscription(customer, plan)
        print(f"{customer_key}: customer={customer['id']} subject=consumer:{consumers[native_name]}")
    print(f"meter={meter['id']} features={len(features)} plan={plan['id']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
