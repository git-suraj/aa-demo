from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from typing import Any

from services.common.a2a import build_text_message


TERMINAL_TASK_STATES = {"completed", "failed", "canceled", "rejected", "auth-required"}


class A2ATaskStore:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self._tasks: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    def _snapshot(self, task: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(task)

    async def _publish_locked(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        snapshot = self._snapshot(task)
        for queue in self._subscribers.get(task_id, []):
            await queue.put(snapshot)

    async def upsert_inbound_message(
        self,
        *,
        task_id: str,
        context_id: str,
        run_id: str | None,
        message: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                now = time.time()
                task = {
                    "id": task_id,
                    "contextId": context_id,
                    "status": {"state": "submitted"},
                    "messages": [],
                    "artifacts": [],
                    "history": [],
                    "metadata": {"agent_id": self.agent_id, **({"run_id": run_id} if run_id else {}), **(metadata or {})},
                    "created_at": now,
                    "updated_at": now,
                    "result_payload": None,
                    "error": None,
                }
                self._tasks[task_id] = task
                self._subscribers.setdefault(task_id, [])
            task["contextId"] = context_id or task.get("contextId")
            task["updated_at"] = time.time()
            task["messages"].append(message)
            task["history"].append(
                {
                    "ts": task["updated_at"],
                    "type": "message_received",
                    "message_id": message.get("messageId"),
                    "state": task["status"]["state"],
                }
            )
            await self._publish_locked(task_id)
            return self._snapshot(task)

    async def mark_working(self, task_id: str, stage: str = "working") -> None:
        await self.update_state(task_id, "working", detail=stage)

    async def update_state(self, task_id: str, state: str, *, detail: str | None = None, error: str | None = None) -> None:
        async with self._lock:
            task = self._tasks[task_id]
            task["status"] = {"state": state}
            task["updated_at"] = time.time()
            if error:
                task["error"] = error
            task["history"].append(
                {
                    "ts": task["updated_at"],
                    "type": "state_changed",
                    "state": state,
                    **({"detail": detail} if detail else {}),
                    **({"error": error} if error else {}),
                }
            )
            await self._publish_locked(task_id)

    async def append_history(self, task_id: str, entry_type: str, **payload: Any) -> None:
        async with self._lock:
            task = self._tasks[task_id]
            task["updated_at"] = time.time()
            task["history"].append({"ts": task["updated_at"], "type": entry_type, **payload})
            await self._publish_locked(task_id)

    async def complete(self, task_id: str, *, payload: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        async with self._lock:
            task = self._tasks[task_id]
            task["result_payload"] = payload
            task["status"] = {"state": "completed"}
            task["updated_at"] = time.time()
            response_message = build_text_message(
                role="agent",
                content=__import__("json").dumps(payload, ensure_ascii=False),
                agent_id=self.agent_id,
                context_id=task["contextId"],
                task_id=task_id,
                metadata={"run_id": run_id} if run_id else None,
            )
            task["messages"].append(response_message)
            task["artifacts"] = [
                {
                    "artifactId": f"{self.agent_id}-result",
                    "name": f"{self.agent_id} result",
                    "parts": [{"kind": "text", "text": __import__("json").dumps(payload, ensure_ascii=False)}],
                    "metadata": {"agent_id": self.agent_id},
                }
            ]
            task["history"].append({"ts": task["updated_at"], "type": "state_changed", "state": "completed"})
            await self._publish_locked(task_id)
            return self._snapshot(task)

    async def fail(self, task_id: str, error: str) -> dict[str, Any]:
        async with self._lock:
            task = self._tasks[task_id]
            task["status"] = {"state": "failed"}
            task["updated_at"] = time.time()
            task["error"] = error
            task["history"].append({"ts": task["updated_at"], "type": "state_changed", "state": "failed", "error": error})
            await self._publish_locked(task_id)
            return self._snapshot(task)

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            task = self._tasks.get(task_id)
            return self._snapshot(task) if task else None

    async def is_terminal(self, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return True
            return task.get("status", {}).get("state") in TERMINAL_TASK_STATES

    async def subscribe(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        async with self._lock:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self._subscribers.setdefault(task_id, []).append(queue)
            task = self._tasks.get(task_id)
            if task:
                await queue.put(self._snapshot(task))
            return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(task_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)
