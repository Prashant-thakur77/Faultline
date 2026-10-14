---
id: rb-gx-card-errors
kind: runbook
title: Checkout failures from card gateway errors
source: human
reviewed_at: 2026-08-22
valid_from: 2026-03-10
services: [card-gateway]
symptoms: [sym-error_rate-order-orchestrator]
---
# Runbook: checkout failures from card gateway errors

When order-orchestrator errors climb, check card-gateway first: a deploy, a config change or a flag. If both
error rates moved together right after a card-gateway change, that change is the prime suspect.

Contain with the deferredCapture flag (orders are accepted and captured later) or roll back the
card-gateway deploy, then confirm the order-orchestrator error rate is back in band.
