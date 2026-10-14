# Preflight pr:Prashant-thakur77/faultline-demo-app#9900: **block** (risk 0.8)

S6 Mode B. Exported from the graph (the preflight Run's `preflight_change` evidence); clean room of golden_acme.

## Decisions this change contradicts

| decision | title |
|---|---|
| ADR-012 | Payment client timeout must stay ≤ 2000 ms |
| ADR-013 | Payment client keeps ≥ 2 retries |

## Required reviewers

- p-004
- p-017
- p-030
- p-034
- p-036

## Would change if

- {'term': 'blast', 'verdict': 'require_review', 'if': 'blast were not a factor (a failure reaches 12 components: agent, chatbot, checkout, dash.exec_morning, frontend, frontend-proxy)'}
- {'term': 'revenue', 'verdict': 'require_review', 'if': 'revenue were not a factor (reaches revenue path: checkout, frontend, frontend-proxy)'}
- {'term': 'decision', 'verdict': 'require_review', 'if': 'decision were not a factor (violates ADR-012 (payment.client.timeout_ms <= 2000, PR sets 5000); violates ADR-013 (payment.client.retries >= 2, PR sets 0))'}

Evidence `ev_a960834a70` · template `Q-PRE-1` · FalkorDB 6.0.2 · eval_acme_preflight_ef6833a5 · GRAPH.RO_QUERY as default-user

Mode A (the same contradiction found during an incident): G8 attaches ADR-012 to the S1 cause, see `examples/s1-hero/gate_runs.json` (check `G8 contradiction`).
