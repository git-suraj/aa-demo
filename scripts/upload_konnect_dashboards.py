#!/usr/bin/env python3
"""
Upload the repo's Konnect Analytics dashboard JSON definitions to Konnect and
scope them to a specific control plane.

What it does:
- loads dashboard JSON files from observability/konnect/dashboards
- rewrites preset_filters so they target the supplied control plane id
- lets callers override the dashboard names instead of forcing the repo defaults
- creates dashboards when absent
- overwrites dashboards in place when a dashboard with the same name already exists

Notes:
- these JSON files are Konnect Analytics dashboard definitions, not Grafana dashboards
- control-plane scoping is done through the dashboard preset filter:
    {"field":"control_plane","operator":"in","value":[<cpid>]}
- the Konnect Dashboards API is documented under the official Kong docs:
  https://developer.konghq.com/api/konnect/analytics-dashboards/v2/
- raw OpenAPI source:
  https://raw.githubusercontent.com/Kong/developer.konghq.com/main/api-specs/konnect/analytics-dashboards/v2/openapi.yaml

Example:
  python3 scripts/upload_konnect_dashboards.py \
    --control-plane-id <cpid> \
    --pat <kpat_...>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = REPO_ROOT / "observability" / "konnect" / "dashboards"
DEFAULT_SERVER_URL = "https://us.api.konghq.com"
DEFAULT_DASHBOARDS_PATH = "/v2/dashboards"

class KonnectApiError(RuntimeError):
    pass


def default_dashboard_name(path: Path) -> str:
    stem = path.stem.strip().replace("_", " ").replace("-", " ")
    words = [word for word in stem.split() if word]
    return " ".join(word.upper() if word.lower() == "aa" else word.capitalize() for word in words)


def default_dashboard_description(path: Path) -> str:
    return f"Konnect analytics dashboard for {default_dashboard_name(path)}."


def discover_dashboard_specs(dashboard_dir: Path) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for file_path in sorted(dashboard_dir.glob("*.json")):
        specs.append(
            {
                "file": file_path,
                "name": default_dashboard_name(file_path),
                "description": default_dashboard_description(file_path),
            }
        )
    return specs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload aa-demo Konnect dashboards and scope them to a control plane.")
    parser.add_argument("--control-plane-id", "--cpid", required=True, help="Konnect control plane id to scope dashboard data to.")
    parser.add_argument("--pat", required=True, help="Konnect personal access token.")
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"Konnect API base URL. Default: {DEFAULT_SERVER_URL}",
    )
    parser.add_argument(
        "--dashboards-path",
        default=DEFAULT_DASHBOARDS_PATH,
        help=f"Dashboards API path. Default: {DEFAULT_DASHBOARDS_PATH}",
    )
    parser.add_argument(
        "--dashboard-dir",
        default=str(DASHBOARD_DIR),
        help=f"Directory containing dashboard JSON files. Default: {DASHBOARD_DIR}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rewritten payloads and planned API operations without calling Konnect.",
    )
    return parser.parse_args()


def request_json(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
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
        raise KonnectApiError(f"{method} {url} failed with {exc.code}: {payload}") from exc
    except urllib.error.URLError as exc:
        raise KonnectApiError(f"{method} {url} failed: {exc}") from exc


def validate_control_plane_id(control_plane_id: str) -> str:
    value = control_plane_id.strip()
    if not value:
        raise KonnectApiError("control plane id is empty. Pass --control-plane-id with a valid UUID.")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise KonnectApiError(
            f"invalid control plane id: {control_plane_id!r}. Pass a valid UUID."
        ) from exc


def rewrite_preset_filters(source_filters: list[dict[str, Any]], control_plane_id: str) -> list[dict[str, Any]]:
    rewritten: list[dict[str, Any]] = []
    replaced = False
    for item in source_filters:
        if item.get("field") == "control_plane":
            next_item = dict(item)
            next_item["operator"] = "in"
            next_item["value"] = [control_plane_id]
            rewritten.append(next_item)
            replaced = True
        else:
            rewritten.append(item)
    if not replaced:
        rewritten.append(
            {
                "field": "control_plane",
                "operator": "in",
                "value": [control_plane_id],
            }
        )
    return rewritten


def dashboard_payload_from_file(path: Path, control_plane_id: str, name: str, description: str) -> dict[str, Any]:
    source = json.loads(path.read_text())
    control_plane_id = validate_control_plane_id(control_plane_id)
    return {
        "name": name,
        "definition": {
            "tiles": source.get("tiles", []),
            "preset_filters": rewrite_preset_filters(source.get("preset_filters", []), control_plane_id),
        },
    }


def list_dashboards(base_url: str, dashboards_path: str, token: str) -> list[dict[str, Any]]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", dashboards_path.lstrip("/"))
    response = request_json("GET", url, token)
    if isinstance(response, dict):
        for key in ("data", "items", "results"):
            if isinstance(response.get(key), list):
                return response[key]
    if isinstance(response, list):
        return response
    return []


def find_dashboard_id(existing: list[dict[str, Any]], name: str) -> str | None:
    for item in existing:
        if item.get("name") == name or item.get("title") == name:
            return item.get("id")
    return None


def build_dashboard_url(base_url: str, dashboards_path: str, dashboard_id: str | None = None) -> str:
    base = urllib.parse.urljoin(base_url.rstrip("/") + "/", dashboards_path.lstrip("/"))
    return f"{base}/{dashboard_id}" if dashboard_id else base


def upsert_dashboard(
    payload: dict[str, Any],
    *,
    base_url: str,
    dashboards_path: str,
    token: str,
    existing: list[dict[str, Any]],
    dry_run: bool,
) -> None:
    dashboard_id = find_dashboard_id(existing, payload["name"])
    method = "PUT" if dashboard_id else "POST"
    url = build_dashboard_url(base_url, dashboards_path, dashboard_id)

    if dry_run:
        print(f"[dry-run] {method} {url}")
        print(json.dumps(payload, indent=2))
        return

    result = request_json(method, url, token, payload)
    resolved_id = result.get("id") or dashboard_id or "<unknown>"
    print(f"{method} {payload['name']} -> {resolved_id}")


def main() -> int:
    args = parse_args()
    dashboard_dir = Path(args.dashboard_dir).resolve()
    if not dashboard_dir.exists():
        print(f"Dashboard directory not found: {dashboard_dir}", file=sys.stderr)
        return 1

    specs = discover_dashboard_specs(dashboard_dir)
    if not specs:
        print(f"No dashboard JSON files found in: {dashboard_dir}", file=sys.stderr)
        return 1

    try:
        existing = [] if args.dry_run else list_dashboards(args.server_url, args.dashboards_path, args.pat)
        for spec in specs:
            payload = dashboard_payload_from_file(
                spec["file"],
                args.control_plane_id,
                spec["name"],
                spec["description"],
            )
            upsert_dashboard(
                payload,
                base_url=args.server_url,
                dashboards_path=args.dashboards_path,
                token=args.pat,
                existing=existing,
                dry_run=args.dry_run,
            )
    except KonnectApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
