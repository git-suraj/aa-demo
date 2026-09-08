#!/usr/bin/env python3
"""Register AA-Demo-2 native AI Gateway Models and MCP Servers in Catalog.

Catalog is an inventory layer. Each record created here links to a native
AI Gateway 2.0 entity, but the link is a snapshot rather than a live sync.
Run this after synchronising the native AI Gateway configuration.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.getenv("KONNECT_API_URL", "https://us.api.konghq.com").rstrip("/")
TOKEN = os.getenv("KONNECT_TOKEN", "").strip()
GATEWAY_ID = os.getenv("AIGW_GATEWAY_ID", "47e9610a-2ad8-4b19-98d3-2b5364a7f38f").strip()
# AI Builder validates remotes as URLs and rejects ``localhost``. This Docker
# host alias reaches the published native AI Gateway port from local clients.
MCP_REMOTE_URL = os.getenv("AIGW_CATALOG_MCP_REMOTE_URL", "http://host.docker.internal:8002/mock-mcp").strip()
LABELS = {"demo": "aa-demo-2", "managed_by": "repo_automation"}
VERSION = "1.0.0"


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
BASE_URL = os.getenv("KONNECT_API_URL", BASE_URL).rstrip("/")
TOKEN = os.getenv("KONNECT_TOKEN", TOKEN).strip()
GATEWAY_ID = os.getenv("AIGW_GATEWAY_ID", GATEWAY_ID).strip()
MCP_REMOTE_URL = os.getenv("AIGW_CATALOG_MCP_REMOTE_URL", MCP_REMOTE_URL).strip()


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    if not TOKEN:
        raise RuntimeError("KONNECT_TOKEN is required")
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
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


def records(path: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        payload = request("GET", f"{path}{separator}{urllib.parse.urlencode({'page[size]': '100', 'page[number]': page})}")
        if isinstance(payload, list):
            return payload
        values = payload.get("data") or payload.get("items") or payload.get("results") or []
        result.extend(values)
        metadata = (payload.get("meta") or {}).get("page") or {}
        # AI Builder uses ``meta.page.next``. Unlike OpenMeter collections it
        # does not include a total, so a missing next link means this is the
        # final page even when it contains values.
        if not values or metadata.get("next") is None:
            return result
        page += 1


def catalog_name(native_name: str) -> str:
    return f"aa-demo-2-{native_name}"


def owned_labels(source_id: str) -> dict[str, str]:
    return {**LABELS, "source_ai_gateway_id": GATEWAY_ID, "source_entity_id": source_id}


def ensure_catalog_item(kind: str, native: dict[str, Any]) -> dict[str, Any]:
    collection = "/v1/ai-models" if kind == "model" else "/v1/mcp-servers"
    wanted_name = catalog_name(native["name"])
    existing = next((item for item in records(collection) if item.get("name") == wanted_name), None)
    if existing:
        labels = existing.get("labels") or {}
        if labels.get("managed_by") != LABELS["managed_by"] or labels.get("demo") != LABELS["demo"]:
            raise RuntimeError(f"Catalog {kind} {wanted_name!r} already exists but is not managed by this demo")
        return existing
    payload = {
        "name": wanted_name,
        "display_name": f"AA-Demo-2: {native.get('display_name') or native['name']}",
        "description": f"Catalog snapshot of AA-Demo-2 AI Gateway {kind} {native['name']}.",
        "labels": owned_labels(native["id"]),
    }
    try:
        created = request("POST", collection, payload)
    except RuntimeError as exc:
        # A previous interrupted run can create the record after this worker's
        # inventory read. Re-read on the API's explicit duplicate-name signal.
        if "_name_conflict" not in str(exc):
            raise
        created = next((item for item in records(collection) if item.get("name") == wanted_name), None)
        if not created:
            raise
    if not isinstance(created, dict) or not created.get("id"):
        raise RuntimeError(f"Catalog {kind} creation returned no id for {wanted_name}")
    print(f"Created Catalog {kind}: {wanted_name}")
    return created


def target_models(native: dict[str, Any]) -> list[dict[str, str]]:
    targets = []
    for target in native.get("targets") or []:
        provider, name = target.get("provider"), target.get("name")
        if provider and name:
            targets.append({"provider": provider, "name": name})
    if not targets:
        raise RuntimeError(f"Native Model {native['name']} has no Catalog-compatible targets")
    return targets


def tool_input_schema(tool: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in tool.get("parameters") or []:
        name = parameter.get("name")
        if not name:
            continue
        properties[name] = {**(parameter.get("schema") or {"type": "string"})}
        if parameter.get("description"):
            properties[name]["description"] = parameter["description"]
        if parameter.get("required"):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def catalog_tools(native: dict[str, Any]) -> list[dict[str, Any]]:
    tools = []
    for tool in native.get("tools") or []:
        item: dict[str, Any] = {
            "name": tool["name"],
            "input_schema": tool_input_schema(tool),
        }
        if tool.get("description"):
            item["description"] = tool["description"]
        if tool.get("annotations"):
            item["annotations"] = tool["annotations"]
        tools.append(item)
    return tools


def ensure_version(kind: str, catalog: dict[str, Any], native: dict[str, Any]) -> None:
    base = "/v1/ai-models" if kind == "model" else "/v1/mcp-servers"
    versions = records(f"{base}/{catalog['id']}/versions")
    if any(version.get("version") == VERSION for version in versions):
        return
    payload: dict[str, Any] = {"version": VERSION}
    if kind == "model":
        payload["target_models"] = target_models(native)
    else:
        payload["tools"] = catalog_tools(native)
        payload["resources"] = []
        payload["prompts"] = []
        payload["packages"] = []
        payload["remotes"] = [{"type": "streamable-http", "url": MCP_REMOTE_URL}]
    request("POST", f"{base}/{catalog['id']}/versions", payload)
    print(f"Added Catalog {kind} version {VERSION}: {catalog['name']}")


def ensure_implementation(kind: str, catalog: dict[str, Any], native: dict[str, Any]) -> None:
    base = "/v1/ai-models" if kind == "model" else "/v1/mcp-servers"
    implementations = records(f"{base}/{catalog['id']}/implementations")
    for implementation in implementations:
        config = implementation.get("config") or implementation.get("implementation", {}).get("config") or {}
        source_id = config.get("gateway_model_id") if kind == "model" else config.get("gateway_mcp_server_id")
        if config.get("gateway_control_plane_id") == GATEWAY_ID and source_id == native["id"]:
            return
    if kind == "model":
        payload = {"gateway_control_plane_id": GATEWAY_ID, "gateway_model_id": native["id"]}
    else:
        payload = {
            "implementation": {
                "type": "ai-gateway",
                "config": {"gateway_control_plane_id": GATEWAY_ID, "gateway_mcp_server_id": native["id"]},
            }
        }
    try:
        request("POST", f"{base}/{catalog['id']}/implementations", payload)
    except RuntimeError as exc:
        # AI Builder currently returns an empty implementation collection for
        # some linked records, while rejecting a duplicate POST with this
        # explicit conflict. That conflict proves the desired one-to-one link
        # already exists and keeps this startup step idempotent.
        if "implementation_already_exists" not in str(exc):
            raise
        return
    print(f"Linked Catalog {kind} to native AI Gateway entity: {catalog['name']}")


def register(kind: str) -> int:
    native_base = f"/v1/ai-gateways/{urllib.parse.quote(GATEWAY_ID, safe='')}"
    native_path = f"{native_base}/models" if kind == "model" else f"{native_base}/mcp-servers"

    def register_one(summary: dict[str, Any]) -> None:
        native = request("GET", f"{native_path}/{urllib.parse.quote(summary['id'], safe='')}")
        if not isinstance(native, dict):
            raise RuntimeError(f"Could not retrieve native {kind} {summary['id']}")
        catalog = ensure_catalog_item(kind, native)
        ensure_version(kind, catalog, native)
        ensure_implementation(kind, catalog, native)

    summaries = records(native_path)
    # Catalog records are independent by native entity. A small pool keeps the
    # startup step practical while avoiding a burst of requests to Konnect.
    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(register_one, summaries))
    return len(summaries)


def main() -> int:
    if not TOKEN:
        raise RuntimeError("KONNECT_TOKEN is required")
    if not GATEWAY_ID:
        raise RuntimeError("AIGW_GATEWAY_ID is required")
    models = register("model")
    mcp_servers = register("mcp-server")
    print(f"AI Builder Catalog registration complete: models={models} mcp_servers={mcp_servers}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
