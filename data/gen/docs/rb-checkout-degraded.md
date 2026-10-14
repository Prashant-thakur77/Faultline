---
id: rb-checkout-degraded
kind: runbook
title: Checkout degraded
source: human
reviewed_at: 2026-07-30
valid_from: 2026-03-01
services: [checkout]
symptoms: [sym-error_rate-checkout]
---
# Runbook: checkout degraded

Checkout depends synchronously on payment, cart, currency, shipping and product-catalog. Email and the
order queue are best-effort, so their failures should not fail orders (ADR-004). Walk the synchronous
dependencies first and look for the one whose errors started before checkout's.

If no dependency changed, check checkout's own recent deploys and its connection pools. Escalate to the
owning team of whichever dependency explains the error share; do not page everyone at once.
