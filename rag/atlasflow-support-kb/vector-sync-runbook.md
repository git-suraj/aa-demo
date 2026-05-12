# AtlasFlow Cloud Runbook: Vector Sync Delay

Applies to AtlasFlow Cloud tenants using the Vector Sync pipeline.

## Trigger

Use this runbook when a customer reports one or more Vector Sync jobs stuck in `SYNCING` for more than 15 minutes.

## Approved support steps

1. Confirm the job age in the AtlasFlow support console.
   - If the job has been in `SYNCING` for fewer than 15 minutes, do not escalate yet.
   - If the job has been in `SYNCING` for more than 15 minutes, continue the runbook.

2. Check the connector heartbeat.
   - If the connector heartbeat is stale by more than 5 minutes, restart the connector once.
   - Record the connector restart time in the support ticket.

3. Check the sync backlog.
   - If backlog is under 500 records, wait 10 minutes after the connector restart and recheck.
   - If backlog is 500 records or higher, mark the case as high-priority and continue.

4. Review the last sync error code.
   - `VS-429`: advise the customer that rate limiting is slowing sync and continue monitoring.
   - `VS-503`: treat as platform degradation and escalate using the escalation policy.
   - `VS-SCHEMA`: collect the schema mismatch details before escalation.

5. Approved customer-facing message.
   - Tell the customer support is validating connector health, backlog, and last sync status.
   - Do not promise a root cause until the backlog and error-code checks are complete.

## What support must not do

- Do not trigger more than one connector restart in the first 30 minutes.
- Do not ask Success Engineering to engage before the escalation conditions are met.
- Do not tell the customer to recreate production sync jobs unless Success Engineering approves it.
