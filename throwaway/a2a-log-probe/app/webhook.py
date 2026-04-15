from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request


app = FastAPI(title="Probe Webhook", version="0.1.0")
LOG_PATH = Path("/data/http-log.ndjson")


@app.post("/logs")
async def ingest_log(request: Request) -> dict[str, bool]:
    raw = await request.body()
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("ab") as fh:
        fh.write(raw + b"\n")
    return {"ok": True}


@app.get("/logs")
async def get_logs() -> list[Any]:
    if not LOG_PATH.exists():
        return []
    rows = []
    for line in LOG_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"raw": line})
    return rows


@app.get("/summary")
async def get_summary() -> list[dict[str, Any]]:
    rows = await get_logs()
    summary: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        a2a_entries = (((row.get("ai") or {}).get("a2a") or {}).get("rpc") or [])
        entry = a2a_entries[0] if a2a_entries else {}
        payload = entry.get("payload") or {}
        response_text = payload.get("response") or ""
        summary.append(
            {
                "delivery_index": index,
                "service": (row.get("service") or {}).get("name") or row.get("service_name_extracted"),
                "route": (row.get("route") or {}).get("name") or row.get("route_name_extracted"),
                "request_uri": (row.get("request") or {}).get("uri") or row.get("request_uri"),
                "response_status": (row.get("response") or {}).get("status") or row.get("response_status"),
                "a2a_method": entry.get("method"),
                "a2a_binding": entry.get("binding"),
                "a2a_id": entry.get("id"),
                "a2a_task_id": entry.get("task_id"),
                "a2a_context_id": entry.get("context_id"),
                "a2a_task_state": entry.get("task_state"),
                "a2a_latency": entry.get("latency"),
                "a2a_streaming": entry.get("streaming"),
                "a2a_ttfb_latency": entry.get("ttfb_latency"),
                "a2a_sse_events_count": entry.get("sse_events_count"),
                "payload_request_preview": (payload.get("request") or "")[:300],
                "payload_response_preview": response_text[:500],
                "payload_response_contains_submitted": '"state": "submitted"' in response_text or '"state":"submitted"' in response_text,
                "payload_response_contains_working": '"state": "working"' in response_text or '"state":"working"' in response_text,
                "payload_response_contains_completed": '"state": "completed"' in response_text or '"state":"completed"' in response_text,
            }
        )
    return summary
