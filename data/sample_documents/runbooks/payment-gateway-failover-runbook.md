---
document_id: "ab74db88-eebb-527b-8601-1d884bbcaf09"
title: "HorizonPay Gateway Failover Runbook"
source: "lhcb-synthetic-knowledge-base"
department: "payments"
document_type: "runbook"
access_level: "internal"
allowed_roles:
  - "viewer"
  - "analyst"
  - "administrator"
created_date: "2025-01-10"
updated_date: "2026-06-10"
version: "1.3"
owner: "Technology Operations"
status: "active"
tags:
  - "operations"
  - "payments"
related_document_ids:
  - "45bef0d5-b559-55d9-b192-d867d99628be"
  - "829bf020-40a2-56e4-8426-a37c68ae736e"
---
# HorizonPay Gateway Failover Runbook

> Authority: **active runbook**. This synthetic document belongs to Lanka Horizon Commercial Bank, a fictional Sri Lankan commercial bank used only for technical evaluation. It concerns payments operations and the services the relevant controlled services. All identifiers, people, metrics, controls, and events are invented. The content establishes consistent terminology for retrieval tests and is not guidance for any real institution.

## Purpose and preconditions

Use this synthetic runbook only after an incident commander confirms scope, access, and change authority. Operators must work from an approved console, preserve correlation IDs, and maintain a timestamped action log. Example commands are non-executable pseudocommands and contain no hosts, credentials, or destructive operations.

## Symptoms and severity

Signals may include elevated error rate, pending transactions, queue age, connection wait time, certificate alerts, authentication latency, or missing notifications. Declare SEV-1 for broad inability to complete critical journeys, SEV-2 for material degradation with workaround, and SEV-3 for limited impact. Confirm customer impact independently of a single dashboard because monitoring gaps have occurred.

## Diagnostics

1. Query OpsPulse for the service, correlation window, deployment version, dependency latency, and saturation indicators.
2. Compare incoming rate, successful completions, retry volume, queue depth, and oldest-message age.
3. Use safe pseudocommand `observe service=<fictional-service> window=<utc-range>` to capture read-only evidence.
4. Check recent configuration, certificate, DNS, capacity, and deployment changes. Do not print secrets or raw customer payloads.
5. Determine whether payment state is known, pending, or ambiguous before any replay.

## Decision and recovery

Stop automatic retries when they amplify load. Fail over only when the standby is healthy and reconciliation ownership is assigned. Drain backlog in controlled batches with idempotency verification. Increase capacity only within pre-approved bounds. For ambiguous payments, quarantine records for reconciliation rather than resubmitting them. Record every decision and obtain incident-command approval at defined gates.

## Validation and rollback

Validate error rate, latency, queue age, transaction-state agreement, notification delivery, and synthetic customer journeys for two observation intervals. Roll back the most recent reversible change if recovery indicators worsen. If failover was used, keep traffic stable until data comparison completes; do not immediately fail back.

## Escalation and evidence

Escalate to the owning platform, infrastructure, cybersecurity, risk, and customer-service roles according to severity. Preserve dashboards, trace identifiers, configuration versions, decision timestamps, and reconciliation totals. Never attach credentials, tokens, or full customer records. Open corrective actions for missing alerting, unsafe defaults, capacity assumptions, and incomplete prior remediation.

## Related documents

- `45bef0d5-b559-55d9-b192-d867d99628be` — Digital Banking Platform Overview
- `829bf020-40a2-56e4-8426-a37c68ae736e` — Incident Management Policy
