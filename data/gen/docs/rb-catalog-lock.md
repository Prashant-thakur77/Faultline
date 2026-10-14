---
id: rb-catalog-lock
kind: runbook
title: Product catalog lock contention
source: human
reviewed_at: 2026-09-10
valid_from: 2026-06-05
services: [product-catalog]
symptoms: [sym-latency-product-catalog]
---
# Runbook: product catalog lock contention

Slow catalog lookups with normal CPU usually mean queries are waiting on database locks. Check the
astronomy-db lock-wait metrics and recent configuration or schema changes on the database.

Roll back the offending config change or cancel the running migration. Schema changes must use the
online migration mode (ADR-021); a plain blocking migration is a finding for the postmortem.
