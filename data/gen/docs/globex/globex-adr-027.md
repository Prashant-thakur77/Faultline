---
id: ADR-027
kind: adr
title: Pricing rule changes ship behind the pricingRulesV2 flag
status: active
decided_at: 2026-06-30
reviewed_at: 2026-09-12
constrains: [pricing]
rule_key: pricing.rules.flagged
rule_op: required
rule_value: true
---
# ADR-027: Pricing rule changes ship behind the pricingRulesV2 flag

A pricing rule error blanks prices on every product page. New rules ship dark behind pricingRulesV2 and are
enabled per market, so a bad rule is switched off without a redeploy.
