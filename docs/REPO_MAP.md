# Repo map

`backend/faultline/` contains:
- `graph/`: RO wrapper, writes, templates, `algo/`, guard, tenancy;
- `agent/`: loop, gate, score, phases;
- `mcp_server/`;
- `actions/`: act, github, reconcile;
- `memory/`, `brain/`, `preflight/`, `sim/`, `ingest/`;
- `api.py`.

The rest of the repo:
- `frontend/`: Next.js incident room, brain, preflight and replay.
- `data/`: fixtures, topology, scenarios plus truth files (read only by `evals/` and `tests/`), generated docs and embeddings.
- `evals/`: harness, report, concurrency.
- `tests/`: unit and live.
- `docs/`: decisions, API, MCP, query catalogue, FalkorDB compatibility, upstream drafts, explainer.

