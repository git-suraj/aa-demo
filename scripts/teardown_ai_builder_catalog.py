#!/usr/bin/env python3
"""Delete only the AI Builder Catalog records owned by AA-Demo-2."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LABELS = {"demo": "aa-demo-2", "managed_by": "repo_automation"}


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
BASE_URL = os.getenv("KONNECT_API_URL", "https://us.api.konghq.com").rstrip("/")
TOKEN = os.getenv("KONNECT_TOKEN", "").strip()


def request(method: str, path: str) -> dict[str, Any] | list[Any]:
    if not TOKEN:
        raise RuntimeError("KONNECT_TOKEN is required")
    req = urllib.request.Request(
        f"{BASE_URL}{path}", method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {exc.read().decode(errors='replace')}") from exc


def records(path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = request("GET", f"{path}?{urllib.parse.urlencode({'page[size]': '100', 'page[number]': page})}")
        if isinstance(payload, list):
            return payload
        values = payload.get("data") or payload.get("items") or payload.get("results") or []
        result.extend(values)
        metadata = (payload.get("meta") or {}).get("page") or {}
        if not values or metadata.get("next") is None:
            return result
        page += 1


def owned(item: dict[str, Any]) -> bool:
    labels = item.get("labels") or {}
    return all(labels.get(key) == value for key, value in LABELS.items())


def main() -> int:
    counts: dict[str, int] = {}
    for kind, path in (("models", "/v1/ai-models"), ("mcp_servers", "/v1/mcp-servers")):
        entries = [item for item in records(path) if owned(item)]
        for entry in entries:
            request("DELETE", f"{path}/{urllib.parse.quote(entry['id'], safe='')}")
        counts[kind] = len(entries)
    print(f"Deleted AA-Demo-2 AI Builder Catalog records: models={counts['models']} mcp_servers={counts['mcp_servers']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
