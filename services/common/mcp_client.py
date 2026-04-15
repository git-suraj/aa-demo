from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from services.common.trace_context import current_trace_headers


class MCPError(RuntimeError):
    pass


class KongMCPClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        client_name: str,
        timeout: float = 20.0,
        run_id: str | None = None,
        context_id: str | None = None,
        task_id: str | None = None,
        message_id: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_name = client_name
        self.timeout = timeout
        self.run_id = run_id
        self.context_id = context_id
        self.task_id = task_id
        self.message_id = message_id
        self.session_id: str | None = None
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self.api_key,
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            **current_trace_headers(),
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.run_id:
            headers["x-demo-run-id"] = self.run_id
        if self.context_id:
            headers["x-demo-context-id"] = self.context_id
        if self.task_id:
            headers["x-demo-task-id"] = self.task_id
        if self.message_id:
            headers["x-demo-message-id"] = self.message_id
        return headers

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse_payload(response.text)
        if not response.text.strip():
            return {}
        return response.json()

    def _parse_sse_payload(self, text: str) -> dict[str, Any]:
        data_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if not data_lines:
            raise MCPError("Unable to parse MCP SSE payload")
        payload = "\n".join(data_lines).strip()
        return json.loads(payload)

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.base_url, headers=self._headers(), json=payload)
            response.raise_for_status()
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                self.session_id = session_id
            data = self._parse_response(response)
        if "error" in data:
            error = data["error"]
            raise MCPError(f'{error.get("code")}: {error.get("message")}')
        return data

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params:
            payload["params"] = params
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.base_url, headers=self._headers(), json=payload)
            response.raise_for_status()

    async def initialize(self) -> None:
        if self._initialized:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": self.client_name, "version": "1.0.0"},
            },
        }
        await self._request(payload)
        await self._notify("notifications/initialized")
        self._initialized = True

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/list",
            "params": {},
        }
        data = await self._request(payload)
        return data.get("result", {}).get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.initialize()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        data = await self._request(payload)
        return data.get("result", {})
