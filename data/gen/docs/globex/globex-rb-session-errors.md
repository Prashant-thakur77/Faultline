---
id: rb-gx-session-errors
kind: runbook
title: Session resume errors and unexpected logouts
source: human
reviewed_at: 2026-09-03
valid_from: 2026-07-25
services: [session-service]
symptoms: [sym-error_rate-session-service]
---
# Runbook: session resume errors and unexpected logouts

Session errors usually come from legacy-cache evictions after a config or capacity change. Switch the
legacyCacheBypass flag off so sessions resume from session-store only, then revert the legacy-cache change.
ADR-031 forbids new dependencies on legacy-cache.
