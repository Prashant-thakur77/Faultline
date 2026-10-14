---
id: ADR-024
kind: adr
title: Ledger database schema changes run online only
status: active
decided_at: 2026-05-18
reviewed_at: 2026-09-10
constrains: [ledger-db, ledger-service]
rule_key: ledger.db.migration_mode
rule_op: "=="
rule_value: online
---
# ADR-024: Ledger database schema changes run online only

Blocking DDL on ledger-db holds locks that stall postings, and every caller of ledger-service inherits the
latency. Schema and configuration changes use online, lock-free tooling and are rolled out one replica at a
time with the lock-wait metric watched.
