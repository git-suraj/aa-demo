from __future__ import annotations

import json
import uuid
from typing import Any


def new_context_id() -> str:
    return f"ctx-{uuid.uuid4()}"


def new_task_id() -> str:
    return f"task-{uuid.uuid4()}"


def new_message_id() -> str:
    return f"msg-{uuid.uuid4()}"


def build_text_message(
    *,
    role: str,
    content: str,
    agent_id: str,
    context_id: str,
    task_id: str,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "message",
        "messageId": message_id or new_message_id(),
        "role": role,
        "parts": [{"kind": "text", "text": content}],
        "metadata": {
            "agent_id": agent_id,
            "context_id": context_id,
            "task_id": task_id,
            **(metadata or {}),
        },
    }


def build_message_send_request(
    *,
    context_id: str,
    task_id: str,
    message: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": new_message_id(),
        "method": "message/send",
        "params": {
            "context_id": context_id,
            "task_id": task_id,
            "message": message,
        },
    }
    if metadata:
        payload["params"]["metadata"] = metadata
    return payload


def build_message_stream_request(
    *,
    context_id: str,
    task_id: str,
    message: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_message_send_request(
        context_id=context_id,
        task_id=task_id,
        message=message,
        metadata=metadata,
    )
    payload["method"] = "message/stream"
    return payload


def build_tasks_get_request(*, task_id: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": new_message_id(),
        "method": "tasks/get",
        "params": {"id": task_id},
    }


def build_completed_task_result(
    *,
    agent_id: str,
    context_id: str,
    task_id: str,
    payload: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    response_message = build_text_message(
        role="agent",
        content=json.dumps(payload, ensure_ascii=False),
        agent_id=agent_id,
        context_id=context_id,
        task_id=task_id,
        metadata={"run_id": run_id} if run_id else None,
    )
    return {
        "id": task_id,
        "contextId": context_id,
        "status": {"state": "completed"},
        "artifacts": [
            {
                "artifactId": f"{agent_id}-result",
                "name": f"{agent_id} result",
                "parts": [{"kind": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                "metadata": {"agent_id": agent_id},
            }
        ],
        "messages": [response_message],
        "metadata": {"agent_id": agent_id, **({"run_id": run_id} if run_id else {})},
    }


def extract_task_payload(result: Any) -> Any:
    if not isinstance(result, dict):
        return result

    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            parts = artifact.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        return text

    messages = result.get("messages")
    if isinstance(messages, list):
        for message in messages:
            text = extract_message_text(message)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text

    return result


def extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        try:
            decoded = json.loads(message)
        except json.JSONDecodeError:
            return message
        return extract_message_text(decoded)

    if not isinstance(message, dict):
        return ""

    parts = message.get("parts") or []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("kind") == "text" and part.get("text"):
            texts.append(str(part["text"]))
    if texts:
        return "\n\n".join(texts)

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        nested: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                nested.append(str(item["text"]))
        return " ".join(nested)
    return ""
