---
id: ADR-018
kind: adr
title: Recommender deploys must pre-warm the cache
status: active
decided_at: 2026-04-27
reviewed_at: 2026-09-01
constrains: [recommender]
rule_key: recommender.cache.prewarm
rule_op: required
rule_value: true
---
# ADR-018: Recommender deploys must pre-warm the cache

Every recommender release that changes cache keys has caused a stampede: the cache empties at once and every
request recomputes against catalog-service. Releases must run with recommenderCacheWarmup on and roll out
in waves. The storefront can hide the rail with the recommenderRail flag while the cache fills.
