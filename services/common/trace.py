from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from fastapi import WebSocket


class TraceBroker:
    def __init__(self, max_runs: int = 20) -> None:
        self._clients: set[WebSocket] = set()
        self._max_runs = max_runs
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        async with self._lock:
            self._record_event(event)
            clients: Iterable[WebSocket] = tuple(self._clients)
        dead: list[WebSocket] = []
        for websocket in clients:
            try:
                await websocket.send_json(event)
            except Exception:
                dead.append(websocket)
        if dead:
            async with self._lock:
                for websocket in dead:
                    self._clients.discard(websocket)

    async def list_runs(self) -> list[dict[str, Any]]:
        async with self._lock:
            runs = [self._summary(run) for run in self._runs.values()]
        runs.reverse()
        return deepcopy(runs)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        async with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None
            payload = {
                **self._summary(run),
                "events": run["events"],
            }
        return deepcopy(payload)

    def _record_event(self, event: dict[str, Any]) -> None:
        run_id = event.get("run_id")
        if not run_id:
            return
        run = self._runs.get(run_id)
        if not run:
            run = {
                "run_id": run_id,
                "governance_scenario": "normal",
                "summary": None,
                "started_at": None,
                "updated_at": None,
                "status": "running",
                "headline": None,
                "events": [],
            }
            self._runs[run_id] = run

        run["events"].append(deepcopy(event))
        run["updated_at"] = event.get("timestamp") or run["updated_at"]

        event_type = event.get("type")
        if event_type == "run_started":
            run["started_at"] = event.get("timestamp") or run["started_at"]
            run["governance_scenario"] = event.get("governance_scenario") or run["governance_scenario"]
            run["summary"] = event.get("summary") or run["summary"]
            run["status"] = "running"
        elif event_type == "final_response":
            output = event.get("output") or {}
            run["headline"] = output.get("headline") or event.get("headline") or run["headline"]
        elif event_type == "run_completed":
            output = event.get("output") or {}
            run["headline"] = output.get("headline") or run["headline"]
            run["status"] = "blocked" if output.get("policy_outcome") == "blocked" else "complete"

        self._runs.move_to_end(run_id)
        while len(self._runs) > self._max_runs:
            self._runs.popitem(last=False)

    @staticmethod
    def _summary(run: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run["run_id"],
            "governance_scenario": run["governance_scenario"],
            "summary": run["summary"],
            "started_at": run["started_at"],
            "updated_at": run["updated_at"],
            "status": run["status"],
            "headline": run["headline"],
        }
