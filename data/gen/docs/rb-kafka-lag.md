---
id: rb-kafka-lag
kind: runbook
title: Order queue consumer lag
source: human
reviewed_at: 2026-07-14
valid_from: 2026-02-20
services: [accounting]
symptoms: [sym-lag-queue]
---
# Runbook: order queue consumer lag

Consumer lag on the order topic delays accounting and fraud detection; it does not block order
placement, because checkout publishes asynchronously. Check recent queue configuration changes
(partition counts, retention, consumer-group settings) and consumer restarts.

Restore the previous queue settings if a change lines up with the lag, then let consumers catch up.
Open a follow-up issue if the backlog keeps growing at normal traffic.
