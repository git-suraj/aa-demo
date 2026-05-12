# AtlasFlow Cloud Ownership Matrix

## Support owns

- validating job age
- checking connector heartbeat
- performing the first connector restart
- documenting backlog size
- sending the first customer-facing status message

## Success Engineering owns

- repeated connector interventions after the first approved restart
- schema-repair guidance for `VS-SCHEMA`
- platform degradation response for `VS-503`
- production job recreation approval
- final remediation plan for enterprise critical tenants

## Support-to-Success escalation wording

Use the phrase:

"Escalating AtlasFlow Vector Sync delay per policy after approved support runbook steps were completed."

Include:

- connector restart timestamp
- backlog size
- whether the tenant is Enterprise Critical
- whether more than three jobs are affected
