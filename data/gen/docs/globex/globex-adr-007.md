---
id: ADR-007
kind: adr
title: legacy-cache is the session cache of record
status: superseded
decided_at: 2025-05-14
reviewed_at: 2026-03-02
constrains: [session-service, legacy-cache]
rule_key: session.cache.backend
rule_op: "=="
rule_value: legacy-cache
supersedes: [ADR-002]
---
# ADR-007: legacy-cache is the session cache of record

Sessions move off the edge nodes into a shared memcached cluster (legacy-cache), so any gateway node can
resume any session. session-service reads and writes sessions there; nothing else may.

memcached has no persistence and evicts under memory pressure, so a resize or config change can log users
out. Accepted for now; revisit when a persistent store is available.
