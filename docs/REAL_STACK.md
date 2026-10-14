# Pointing this at a real stack

| Seam | Demo source | Real source | File |
|---|---|---|---|
| Topology | OTel-Demo-shaped YAML | service graph or traces (CALLS + rps) | `ingest/otel_topology.py` |
| Data lineage | fixture export | lineage export in the same JSON shape (an OpenLineage / dbt `manifest.json` importer is not built) | `ingest/lineage_to_graph.py` |
| Telemetry | simulator → `MetricWindow` | metrics backend → the same nodes | `sim/telemetry.py`, `agent/datatools.py` |
| Changes | scenario injection | deploy events + PR webhooks | `graph/writes.py::inject_change`, `preflight/engine.py` |
| People | synthetic org | directory + on-call schedule + git history | `ingest/org_gen.py` |
| Decisions and runbooks | markdown with front matter | ADR repo, wiki, chats, tickets | `ingest/docs.py` |
| Actions | simulated GitHub | GitHub REST (`gh api`) | `actions/github.py` |

