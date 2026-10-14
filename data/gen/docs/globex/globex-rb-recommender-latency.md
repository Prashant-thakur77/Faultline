---
id: rb-gx-recommender-latency
kind: runbook
title: Recommender latency after a deploy (cache stampede)
source: human
reviewed_at: 2026-08-14
valid_from: 2026-05-02
services: [recommender]
symptoms: [sym-latency-recommender]
---
# Runbook: recommender latency after a deploy

A latency jump on recommender right after one of its deploys is almost always a cache stampede: the new
build changed cache keys and every request recomputes.

Contain first: switch the recommenderRail flag off so product pages stop calling recommender, then roll the
deploy back or let the cache warm with recommenderCacheWarmup on. Confirm recommender latency is back
inside its band before turning the rail on again.
