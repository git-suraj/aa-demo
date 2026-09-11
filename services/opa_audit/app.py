from __future__ import annotations

import gzip
import json
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response

app = FastAPI(title="OPA Decision Audit Receiver")
LOKI_PUSH_URL = "http://loki:3100/loki/api/v1/push"


def safe_event(event: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(event))
    headers = copied.get("input", {}).get("request", {}).get("http", {}).get("headers", {})
    for key in list(headers):
        if key.lower() in {"apikey", "authorization", "cookie"}:
            headers[key] = "[redacted]"
    return copied


@app.post("/logs")
async def receive_decisions(request: Request) -> Response:
    raw = await request.body()
    if request.headers.get("content-encoding", "").lower() == "gzip":
        raw = gzip.decompress(raw)
    values_by_run: dict[str, list[list[str]]] = {}
    for item in json.loads(raw):
        event = safe_event(item)
        headers = event.get("input", {}).get("request", {}).get("http", {}).get("headers", {})
        run_id = headers.get("x-demo-run-id", "unknown")
        values_by_run.setdefault(run_id, []).append([str(time.time_ns()), json.dumps(event, separators=(",", ":"))])
    if values_by_run:
        payload = {"streams": [{"stream": {"component": "opa", "run_id": run_id}, "values": values} for run_id, values in values_by_run.items()]}
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(LOKI_PUSH_URL, json=payload)
            response.raise_for_status()
    return Response(status_code=204)
