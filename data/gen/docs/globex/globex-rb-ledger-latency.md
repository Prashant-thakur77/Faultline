---
id: rb-gx-ledger-latency
kind: runbook
title: Ledger posting latency and lock waits
source: human
reviewed_at: 2026-07-30
valid_from: 2026-05-20
services: [ledger-service]
symptoms: [sym-latency-ledger-service]
---
# Runbook: ledger posting latency and lock waits

Check ledger-db lock waits and any recent ledger-db configuration change. Revert the change, kill
long-running blocking statements, and open a follow-up to redo the change online (ADR-024).
