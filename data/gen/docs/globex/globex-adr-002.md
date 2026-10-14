---
id: ADR-002
kind: adr
title: Login sessions are pinned to the edge node that created them
status: superseded
decided_at: 2024-11-04
reviewed_at: 2025-05-20
constrains: [session-service]
rule_key: session.affinity
rule_op: "=="
rule_value: sticky
---
# ADR-002: Login sessions are pinned to the edge node that created them

Early globex ran one session table per edge node, so the gateway pinned every shopper to the node that
created their session. It was simple and fast, and a node restart logged its shoppers out.

This was always a stopgap until a shared session cache existed.
