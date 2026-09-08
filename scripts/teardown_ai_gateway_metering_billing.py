#!/usr/bin/env python3
"""Delete only the Metering & Billing resources created for AA-Demo-2."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LABELS = {"demo": "aa-demo-2", "managed_by": "repo_automation"}
PLAN_KEY = "aa_demo_2_agent_llm_plan"
RETRIES = 20


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()
BASE_URL = os.getenv("KONNECT_SERVER_URL", "https://us.api.konghq.com").rstrip("/")
TOKEN = os.getenv("KONNECT_SYSTEM_TOKEN", "").strip()


def api(method: str, path: str, payload: dict | None = None) -> dict | list:
    if not TOKEN:
        raise RuntimeError("KONNECT_SYSTEM_TOKEN is required")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {exc.read().decode(errors='replace')}") from exc


def list_items(path: str) -> list[dict]:
    result: list[dict] = []
    next_path: str | None = f"{path}?{urllib.parse.urlencode({'page[size]': '100'})}"
    while next_path:
        payload = api("GET", next_path)
        if isinstance(payload, list):
            result.extend(payload)
            break
        result.extend(payload.get("data") or payload.get("items") or payload.get("results") or [])
        next_path = ((payload.get("meta") or {}).get("page") or {}).get("next")
    return result


def owned(resource: dict) -> bool:
    return all((resource.get("labels") or {}).get(key) == value for key, value in LABELS.items())


def delete(path: str) -> None:
    # Plan deletion is asynchronous. A feature can remain temporarily marked
    # as referenced after the plan and every subscription are already gone.
    # Wait for OpenMeter's reference index to converge instead of leaving a
    # half-deleted demo catalog behind.
    for attempt in range(RETRIES):
        try:
            api("DELETE", path)
            return
        except RuntimeError as exc:
            if "failed with 403" not in str(exc) or attempt == RETRIES - 1:
                raise
            time.sleep(2)


def cancel_subscriptions(customer_ids: set[str], plan_ids: set[str]) -> None:
    subscriptions = [
        item for item in list_items("/v3/openmeter/subscriptions")
        if item.get("customer_id") in customer_ids or item.get("plan_id") in plan_ids
    ]
    for subscription in subscriptions:
        if subscription.get("status") in {"active", "scheduled", "pending"}:
            api("POST", f"/v3/openmeter/subscriptions/{subscription['id']}/cancel", {"timing": "immediate"})

    for _ in range(RETRIES):
        pending = [
            item for item in list_items("/v3/openmeter/subscriptions")
            if (item.get("customer_id") in customer_ids or item.get("plan_id") in plan_ids)
            and item.get("status") in {"active", "scheduled", "pending"}
        ]
        if not pending:
            return
        time.sleep(2)
    raise RuntimeError("Timed out waiting for Metering & Billing subscriptions to cancel")


def delete_draft_invoices(customer_ids: set[str]) -> None:
    """Draft invoices block customer deletion after a demo request."""
    invoices = list_items("/v3/openmeter/billing/invoices")
    for invoice in invoices:
        customer_id = (invoice.get("customer") or {}).get("id")
        if customer_id not in customer_ids:
            continue
        status = invoice.get("status")
        if status == "draft":
            delete(f"/v3/openmeter/billing/invoices/{invoice['id']}")
        elif status not in {"deleted", "void", "paid"}:
            raise RuntimeError(
                f"AA-Demo-2 invoice {invoice['id']} is {status!r}; it must be finalized before customer cleanup."
            )


def main() -> int:
    customers = [item for item in list_items("/v3/openmeter/customers") if owned(item)]
    # OpenMeter's plan-list endpoint currently omits plan labels, even though
    # the plan was created with them. This key is unique to the demo and is
    # needed to remove the active plan before its features can be deleted.
    plans = [
        item for item in list_items("/v3/openmeter/plans")
        if owned(item) or item.get("key") == PLAN_KEY
    ]
    features = [item for item in list_items("/v3/openmeter/features") if owned(item)]
    meters = [item for item in list_items("/v3/openmeter/meters") if owned(item)]
    cancel_subscriptions({item["id"] for item in customers}, {item["id"] for item in plans})
    delete_draft_invoices({item["id"] for item in customers})

    for plan in plans:
        if plan.get("status") == "active":
            api("POST", f"/v3/openmeter/plans/{plan['id']}/archive")
        delete(f"/v3/openmeter/plans/{plan['id']}")
    for feature in features:
        delete(f"/v3/openmeter/features/{feature['id']}")
    for meter in meters:
        delete(f"/v3/openmeter/meters/{meter['id']}")
    for customer in customers:
        delete(f"/v3/openmeter/customers/{customer['id']}")
    print(f"Deleted AA-Demo-2 billing resources: customers={len(customers)} plans={len(plans)} features={len(features)} meters={len(meters)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
