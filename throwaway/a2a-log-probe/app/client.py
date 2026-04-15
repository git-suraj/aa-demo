from __future__ import annotations

import json
import time
import uuid

import httpx


BASE_URL = "http://kong:8000/probe-server/a2a"
API_KEY = "probe-demo-key"


def print_header(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> None:
    context_id = f"ctx-{uuid.uuid4()}"
    task_id = f"task-{uuid.uuid4()}"
    message_id = f"msg-{uuid.uuid4()}"
    headers = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "apikey": API_KEY,
        "x-demo-context-id": context_id,
        "x-demo-task-id": task_id,
        "x-demo-message-id": message_id,
        "x-demo-run-id": "throwaway-a2a-log-probe",
    }

    with httpx.Client(timeout=30.0) as client:
        for _ in range(30):
            try:
                ready = client.get("http://kong:8001/status", headers={"apikey": API_KEY})
                if ready.status_code < 500:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)

        print_header("agent/getCard")
        card_payload = {"jsonrpc": "2.0", "id": f"card-{uuid.uuid4()}", "method": "agent/getCard", "params": {}}
        card_response = client.post(BASE_URL, headers=headers, json=card_payload)
        print(card_response.status_code)
        print(card_response.text)

        print_header("message/stream")
        stream_payload = {
            "jsonrpc": "2.0",
            "id": message_id,
            "method": "message/stream",
            "params": {
                "context_id": context_id,
                "task_id": task_id,
                "message": {
                    "kind": "message",
                    "messageId": message_id,
                    "role": "user",
                    "parts": [{"kind": "text", "text": "{\"probe\":true}"}],
                },
            },
        }
        with client.stream("POST", BASE_URL, headers=headers, json=stream_payload) as response:
            print(response.status_code)
            for line in response.iter_lines():
                if line:
                    print(line)


if __name__ == "__main__":
    main()
