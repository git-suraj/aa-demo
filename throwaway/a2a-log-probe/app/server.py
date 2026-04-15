from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI(title="A2A Probe Server", version="0.1.0")


def build_task_event(
    request_id: str,
    task_id: str,
    context_id: str,
    state: str,
    *,
    include_result: bool = False,
) -> str:
    result: dict[str, Any] = {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": state},
        "messages": [],
        "artifacts": [],
        "history": [{"type": "state_changed", "state": state}],
        "metadata": {"agent_id": "probe-server"},
    }
    if include_result:
        result["artifacts"] = [
            {
                "artifactId": "probe-result",
                "name": "probe result",
                "parts": [{"kind": "text", "text": "{\"ok\":true}"}],
            }
        ]
    return "data: " + json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}) + "\n\n"


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    return {
        "name": "Probe A2A Server",
        "description": "Minimal streaming A2A server for Kong log verification.",
        "url": "http://a2a-server:8000/a2a",
        "version": "0.1.0",
        "capabilities": {"streaming": True},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [],
    }


@app.post("/a2a")
async def a2a(request: Request):
    payload = await request.json()
    method = payload.get("method")

    if method == "agent/getCard":
        return JSONResponse({"jsonrpc": "2.0", "id": payload.get("id"), "result": await agent_card()})

    if method != "message/stream":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {"code": -32601, "message": f"Unsupported method: {method}"},
            },
            status_code=400,
        )

    params = payload.get("params") or {}
    context_id = params.get("context_id") or params.get("contextId") or f"ctx-{uuid.uuid4()}"
    task_id = params.get("task_id") or params.get("taskId") or f"task-{uuid.uuid4()}"
    request_id = payload.get("id") or f"msg-{uuid.uuid4()}"

    async def event_stream():
        yield build_task_event(request_id, task_id, context_id, "submitted")
        await asyncio.sleep(0.2)
        yield build_task_event(request_id, task_id, context_id, "working")
        await asyncio.sleep(0.2)
        yield build_task_event(request_id, task_id, context_id, "completed", include_result=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
