---
id: rb-gx-event-bus-lag
kind: runbook
title: Event bus consumer lag
source: human
reviewed_at: 2026-08-05
valid_from: 2026-04-11
services: [inventory-sync, report-builder]
symptoms: [sym-lag-event-bus]
---
# Runbook: event bus consumer lag

Lag that grows steadily after an event-bus configuration change points at partition throughput or
rebalancing. Restore the previous broker settings and watch the lag drain; open an issue to size the
partitions before trying again.
