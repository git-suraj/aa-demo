#!/usr/bin/env python3
"""
Create or reuse a Konnect MCP Registry and publish an MCP server entry to it.

Defaults are geared toward this repo's local demo setup:
- registry name: aa-demo-mcp-registry
- display name: AA Demo MCP Registry
- remote URL: http://localhost:8000/mock-mcp
- remote transport: streamable-http

This targets the Konnect Labs MCP Registry API documented here:
https://developer.konghq.com/catalog/mcp-registry/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_SERVER_URL = "https://klabs.us.api.konghq.com"
DEFAULT_REGISTRIES_PATH = "/v0/mcp-registries"
DEFAULT_REGISTRY_NAME = "aa-demo-mcp-registry"
DEFAULT_REGISTRY_DISPLAY_NAME = "AA Demo MCP Registry"
DEFAULT_REGISTRY_DESCRIPTION = "Registry for internal AA demo MCP servers routed through Kong."
DEFAULT_MCP_NAME = "com.aa-demo/mock-mcp"
DEFAULT_MCP_DESCRIPTION = "AA Demo MCP server exposed through Kong AI MCP Proxy."
DEFAULT_MCP_VERSION = "1.0.0"
DEFAULT_REMOTE_URL = "http://localhost:8000/mock-mcp"
DEFAULT_REMOTE_TYPE = "streamable-http"


class KonnectApiError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/publish a Konnect MCP Registry entry for the AA demo MCP server.")
    parser.add_argument("--pat", default=os.getenv("KONNECT_TOKEN"), help="Konnect personal access token. Defaults to KONNECT_TOKEN.")
    parser.add_argument("--server-url", default=os.getenv("KONNECT_KLABS_API_URL", DEFAULT_SERVER_URL), help=f"Konnect Labs API base URL. Default: {DEFAULT_SERVER_URL}")
    parser.add_argument("--registries-path", default=DEFAULT_REGISTRIES_PATH, help=f"Registry API path. Default: {DEFAULT_REGISTRIES_PATH}")
    parser.add_argument("--registry-name", default=DEFAULT_REGISTRY_NAME, help=f"Registry name. Default: {DEFAULT_REGISTRY_NAME}")
    parser.add_argument("--registry-display-name", default=DEFAULT_REGISTRY_DISPLAY_NAME, help=f"Registry display name. Default: {DEFAULT_REGISTRY_DISPLAY_NAME}")
    parser.add_argument("--registry-description", default=DEFAULT_REGISTRY_DESCRIPTION, help="Registry description.")
    parser.add_argument("--mcp-name", default=DEFAULT_MCP_NAME, help=f"MCP server name. Default: {DEFAULT_MCP_NAME}")
    parser.add_argument("--mcp-description", default=DEFAULT_MCP_DESCRIPTION, help="MCP server description.")
    parser.add_argument("--mcp-version", default=DEFAULT_MCP_VERSION, help=f"MCP server version. Default: {DEFAULT_MCP_VERSION}")
    parser.add_argument("--remote-url", default=DEFAULT_REMOTE_URL, help=f"Remote MCP URL to publish. Default: {DEFAULT_REMOTE_URL}")
    parser.add_argument("--remote-type", default=DEFAULT_REMOTE_TYPE, choices=["streamable-http", "sse"], help=f"Remote MCP transport type. Default: {DEFAULT_REMOTE_TYPE}")
    parser.add_argument("--dry-run", action="store_true", help="Print planned requests without calling Konnect.")
    return parser.parse_args()


def request_json(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    *,
    treat_409_as_success: bool = False,
) -> dict[str, Any]:
    data = None
    headers = {
        "Accept": "application/json, application/problem+json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        if treat_409_as_success and exc.code == 409:
            return {"conflict": True, "status": exc.code, "payload": payload}
        raise KonnectApiError(f"{method} {url} failed with {exc.code}: {payload}") from exc
    except urllib.error.URLError as exc:
        raise KonnectApiError(f"{method} {url} failed: {exc}") from exc


def build_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def list_registries(base_url: str, registries_path: str, token: str) -> list[dict[str, Any]]:
    response = request_json("GET", build_url(base_url, registries_path), token)
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in ("data", "items", "results"):
            if isinstance(response.get(key), list):
                return response[key]
    return []


def list_servers(base_url: str, registries_path: str, token: str, registry_name: str) -> list[dict[str, Any]]:
    response = request_json(
        "GET",
        build_url(base_url, f"{registries_path.rstrip('/')}/{registry_name}/v0.1/servers"),
        token,
    )
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in ("data", "items", "results", "servers"):
            if isinstance(response.get(key), list):
                return response[key]
    return []


def registry_exists(base_url: str, registries_path: str, token: str, registry_name: str) -> bool:
    registries = list_registries(base_url, registries_path, token)
    for item in registries:
        if item.get("name") == registry_name or item.get("id") == registry_name:
            return True
    return False


def ensure_registry(args: argparse.Namespace) -> None:
    payload = {
        "name": args.registry_name,
        "display_name": args.registry_display_name,
        "description": args.registry_description,
    }
    url = build_url(args.server_url, args.registries_path)
    if args.dry_run:
        print(f"[dry-run] ensure registry: {args.registry_name}")
        print(json.dumps(payload, indent=2))
        return

    if registry_exists(args.server_url, args.registries_path, args.pat, args.registry_name):
        print(f"Registry already exists: {args.registry_name}")
        return

    request_json("POST", url, args.pat, payload, treat_409_as_success=True)
    print(f"Created registry: {args.registry_name}")


def find_existing_server(base_url: str, registries_path: str, token: str, registry_name: str, mcp_name: str) -> dict[str, Any] | None:
    servers = list_servers(base_url, registries_path, token, registry_name)
    for item in servers:
        if item.get("name") == mcp_name or item.get("id") == mcp_name:
            return item
    return None


def delete_server(args: argparse.Namespace, server_identifier: str) -> None:
    delete_path = f"{args.registries_path.rstrip('/')}/{args.registry_name}/v0.1/servers/{urllib.parse.quote(server_identifier, safe='')}"
    url = build_url(args.server_url, delete_path)
    request_json("DELETE", url, args.pat)
    print(f"Deleted existing MCP server entry: {server_identifier}")


def publish_server(args: argparse.Namespace) -> None:
    payload = {
        "name": args.mcp_name,
        "description": args.mcp_description,
        "version": args.mcp_version,
        "remotes": [
            {
                "type": args.remote_type,
                "url": args.remote_url,
            }
        ],
    }
    publish_path = f"{args.registries_path.rstrip('/')}/{args.registry_name}/v0.1/publish"
    url = build_url(args.server_url, publish_path)
    if args.dry_run:
        print(f"[dry-run] publish MCP server to {args.registry_name}")
        print(json.dumps(payload, indent=2))
        return

    existing = find_existing_server(args.server_url, args.registries_path, args.pat, args.registry_name, args.mcp_name)
    if existing:
        delete_server(args, str(existing.get("id") or existing.get("name") or args.mcp_name))

    result = request_json("POST", url, args.pat, payload)
    identifier = result.get("id") or result.get("name") or args.mcp_name
    print(f"Published MCP server: {identifier}")


def main() -> int:
    args = parse_args()
    if not args.pat:
        print("Missing Konnect token. Pass --pat or set KONNECT_TOKEN.", file=sys.stderr)
        return 1

    try:
        ensure_registry(args)
        publish_server(args)
    except KonnectApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
