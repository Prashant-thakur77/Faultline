---
id: rb-payment-errors
kind: runbook
title: Payment charge errors at checkout
source: human
reviewed_at: 2026-08-20
valid_from: 2026-04-02
services: [payment]
symptoms: [sym-error_rate-checkout]
---
# Runbook: payment charge errors at checkout

When the checkout error rate rises, first check whether payment changed recently: a deploy, a config
change or a flag. Compare the payment charge error rate with checkout's; if both moved together right
after a payment change, that change is the prime suspect.

Contain first: degrade checkout's payment path with the payment gate flag, or roll back the payment
deploy. Then confirm through a second channel that the checkout error rate is back inside its baseline
band before closing.
