---
id: rb-recs-cache
kind: runbook
title: Recommendation cache stampede
source: human
reviewed_at: 2026-08-05
valid_from: 2026-05-12
services: [recommendation]
symptoms: [sym-latency-recommendation]
---
# Runbook: recommendation cache stampede

A recommendation release that changes cache keys or TTLs can empty the cache in one go. Every request
then misses at once and recomputes, which also floods product-catalog with lookups.

Turn on the recommendation cache-failure fallback flag to serve static picks, or roll back the release.
Re-enable gradually so the cache warms before full traffic returns. Recommendations are best-effort on
product pages, so contain quickly rather than debug under load.
