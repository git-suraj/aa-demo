# A2A Log Probe

Throwaway setup to verify what Kong exports for A2A `message/stream` traffic.

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
