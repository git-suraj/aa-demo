# AtlasFlow Cloud Escalation Policy

This policy defines when AtlasFlow Support must escalate Vector Sync incidents to Success Engineering.

## Escalate to Success Engineering when any of the following are true

- A Vector Sync job remains in `SYNCING` for more than 30 minutes after one approved connector restart.
- The backlog remains above 500 records for more than 20 minutes.
- The last sync error code is `VS-503`.
- More than three customer-facing sync jobs are affected in the same tenant.
- The affected tenant is on the Enterprise Critical support tier and customer operations are blocked.

## Escalation handoff requirements

Support must include all of the following in the escalation note:

- tenant name
- impacted job ids
- job age in minutes
- backlog size
- connector restart timestamp
- last sync error code
- exact customer-facing impact statement

## When not to escalate yet

- job age under 30 minutes after the first connector restart
- backlog under 500 records and trending down
- only a single low-volume sandbox job is affected

## Response time target after escalation

Success Engineering should acknowledge the escalation within 15 minutes during business hours.
