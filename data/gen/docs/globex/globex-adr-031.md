---
id: ADR-031
kind: adr
title: Sessions resume from session-store; legacy-cache is read-only until decommission
status: active
decided_at: 2026-07-21
reviewed_at: 2026-09-15
constrains: [session-service, legacy-cache, session-store]
rule_key: session.cache.backend
rule_op: "=="
rule_value: session-store
supersedes: [ADR-007]
cites: [doc-globex-adr-007]
---
# ADR-031: Sessions resume from session-store; legacy-cache is read-only until decommission

After repeated session errors caused by legacy-cache evictions, session-service writes sessions only to
session-store (redis with persistence). legacy-cache stays read-only behind the legacyCacheBypass flag
so old sessions can still resume, and is decommissioned once its hit rate falls below one percent.

No new component may depend on legacy-cache.
