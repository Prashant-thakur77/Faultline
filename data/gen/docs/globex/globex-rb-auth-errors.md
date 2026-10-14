---
id: rb-gx-auth-errors
kind: runbook
title: Gateway authentication errors (401 spike)
source: human
reviewed_at: 2026-08-18
valid_from: 2026-02-14
services: [auth-service]
symptoms: [sym-error_rate-edge-gateway]
---
# Runbook: gateway authentication errors

A 401 spike at edge-gateway right after an auth-service release means token validation changed. Roll the
auth-service deploy back; there is no flag that bypasses authentication.
