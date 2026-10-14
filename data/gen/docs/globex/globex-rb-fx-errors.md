---
id: rb-gx-fx-errors
kind: runbook
title: Pricing errors from foreign exchange conversion
source: human
reviewed_at: 2026-09-08
valid_from: 2026-06-01
services: [fx-converter]
symptoms: [sym-error_rate-pricing]
---
# Runbook: pricing errors from foreign exchange conversion

If pricing errors are limited to foreign-currency baskets, check fx-converter and the external rates
provider. Switch fxStaticRates off to serve the last published daily rates, then roll back any fx-converter
change.
