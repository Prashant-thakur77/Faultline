---
id: ADR-015
kind: adr
title: Card gateway authorisation timeout must stay ≤ 1500 ms
status: active
decided_at: 2026-02-09
reviewed_at: 2026-08-30
constrains: [card-gateway]
rule_key: card-gateway.client.timeout_ms
rule_op: "<="
rule_value: 1500
---
# ADR-015: Card gateway authorisation timeout must stay at or below 1500 ms

order-orchestrator holds a saga slot for every in-flight authorisation, so a long card-network timeout
turns a slow acquirer into exhausted saga slots and failed checkouts everywhere. Fail fast and let the
deferredCapture flag accept the order and capture the card later.
