# A2A Log Probe

Throwaway setup to verify what Kong exports for A2A `message/stream` traffic.

Observed result with Kong Gateway `3.14`:
- Kong/http-log emits one request-level log record for the streamed `message/stream` request.
- `ai.a2a.rpc[0].task_state` resolves to the final task state when Kong can parse the streamed response.
- `ai.a2a.rpc[0].sse_events_count` records the number of SSE events.
- `ai.a2a.rpc[0].payload.response`, when payload logging is enabled, can contain the raw SSE response body with intermediate states such as `submitted`, `working`, and `completed`.
- The http-log plugin does not deliver one separate webhook call per SSE event.

Services:
- `kong`: DB-less Kong with `ai-a2a-proxy` and `http-log`
- `a2a-server`: minimal A2A server that streams `submitted -> working -> completed`
- `webhook`: receives `http-log` POSTs and stores raw JSON lines

## Start

```bash
cd throwaway/a2a-log-probe
export KONG_LICENSE_DATA='...'
docker compose up --build -d
```

## Run the client

```bash
docker compose run --rm client
```

This sends:
- `agent/getCard`
- `message/stream`

through Kong at `http://kong:8000/probe-server/a2a`.

## Inspect logs

Raw webhook payloads:

```bash
curl -s http://localhost:18081/logs | jq
```

Raw NDJSON file on disk:

```bash
cat logs/http-log.ndjson
```

Flattened A2A summary:

```bash
curl -s http://localhost:18081/summary | jq
```

Useful filters:

```bash
curl -s http://localhost:18081/logs | jq '.[] | {method: .ai.a2a.rpc[0].method, task_state: .ai.a2a.rpc[0].task_state, streaming: .ai.a2a.rpc[0].streaming, sse_events_count: .ai.a2a.rpc[0].sse_events_count}'
```

## Tear down

```bash
docker compose down -v
```
