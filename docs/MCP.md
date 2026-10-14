# Query Faultline's graph yourself (MCP)

Faultline exposes the read-only tools its agent uses (no write tools) as an MCP server. There are two ways in.

## 1. Local, over stdio (no key)
The checked-in `.mcp.json` registers two servers for Claude Code in this repo:
- `faultline`: our graph tools.
- `falkordb-readonly`: the official `@falkordb/mcpserver@1.3.0` with `FALKORDB_STRICT_READONLY=true`. Use it for raw, read-only access to the same graphs.

```bash
make up && make seed      # pinned FalkorDB + the acme tenant
claude                    # in the repo root; approve the project MCP servers when asked
```
Then ask, for example: *"Use causal_paths from payment to checkout, then impact_bound for D-pay-417."*

## 2. Remote, over Streamable HTTP (bearer key)
```bash
export FAULTLINE_MCP_KEYS="$(python -c 'import secrets;print(secrets.token_urlsafe(32))'):acme"   # or put it in .env
make mcp-http             # http://127.0.0.1:8401/mcp
claude mcp add --transport http faultline http://127.0.0.1:8401/mcp --header "Authorization: Bearer <key>"
```

**Guarantees:**
- **Key → tenant.** Each key maps to exactly one tenant (one graph). Tools never accept a graph name. Keys are compared in constant time.
- **Status codes.** A request without a key, or with a wrong one, gets `401`. Each key is limited to 30 calls per minute, and requests without a key to 30 per minute per client IP; over that you get `429`.
- **Sessions.** On the hosted server `session_history` returns only the caller's own sessions (user = the key id, `key-…`); visitors' brain questions are recorded in per-tenant brain scratch copies, never in the tenant graph the server reads.
- **Read-only, three ways.**
  - Every hosted tool reads with `GRAPH.RO_QUERY`, as the tenant's ACL user (`ro_<tenant>`) when ACL passwords are configured.
  - The hosted service is given no engine (write) credential.
  - Hosted tools carry `readOnlyHint: true`. Internal scratch-graph tools are marked `readOnlyHint: false` and are not hosted.
- **Provenance on every result:** the exact Cypher, params, timing, a sha256 row digest and `served_by` (engine version, graph, ACL user).

## Tools (read-only)
| group | tools |
|---|---|
| seeds and context | `find_entities`, `service_context`, `upstream_scope`, `column_lineage` |
| context for any agent | `context_pack(text, targets, at, budget_tokens, window_min)`: the graph's smallest provenance-carrying context for an alert or question, packed to a token budget (hybrid entry points by full-text and vector, then graph expansion: upstream changes by path distance, causal paths, owners, people, decisions, past incidents with their cause and fix). Also `POST /api/context_pack` |
| what breaks | `blast_radius`, `chokepoints` (betweenness), `upstream_suspects`, `window_changes` |
| proof | `causal_paths` (SPpaths, "no path, no claim"), `impact_bound` (maxFlow), `upstream_explained` (G4 upstream: strict lower bound for elimination, upper bound for the downgrade), `reachable_from_changes` (SSpaths), `alert_coverage` (which hops of a proven chain alerted), `residue_check` (anomalies the confirmed cause does not explain) |
| containment | `containment_cut` (maxFlow → min-cut), `connectivity_check` (WCC) |
| people | `owners_of`, `bus_factor`, `notify_set` (teams owning anything in the blast radius + who is on call now; distinct from who fixes it; optional `priority_ids` puts the owners of those nodes first) |
| obligations | `obligation_clock(target_id, now)`: every SLO on the failing component and its blast radius with its current error rate, burn rate and budget left (Q-OBL-SLO, from MetricWindow telemetry), the time to breach (code, `weights.yaml` `obligation`), the customers reached through the failure, each counted once with its nearest path, and the MRR at risk (Q-OBL-CUST); `urgent` when the soonest breach is under `page_within_min` |
| decisions | `trace_decision`, `decision_check` |
| change and code (specialists) | `change_details` (a change as recorded: kind, time, CHANGED target, asserted facts), `diff_summary` (commits it CONTAINS → files they TOUCH → component PART_OF, PRs, authors, diff facts; `code_on_target`; no function-level code) |
| memory | `similar_incidents` (vector index → shared Symptom), `incident_families` (labelPropagation), `runbook_for`, `session_history`, `remedy_stats` (Beta-smoothed success per action kind on incidents sharing a symptom) |
| company brain | `resolve_entity`, `people_who_worked_on`, `missing_guardrails`, `decisions_about` |
| company brain over time | `owner_at` (owner at a time or an incident's onset vs now, and who held the context), `beliefs_at` (owner, on-call, decisions in force, runbooks in effect as of a time), `component_timeline`, `topology_at` (what a component could break at a past time vs now, and which PR introduced each call since: versioned topology), `knowledge_health` (stale runbooks, handovers with no runbook since, decisions at risk, likely missing edges), `hidden_coupling` (co-failure in incident history with no failure path) |
| pre-deploy gate | `preflight_change` (BFS + betweenness + Q-DEC-1 + ownership → allow / require_review / block) |
| schema | `graph_schema`: the live labels (counts, property keys, indexes) and relationship types (counts, from → to label pairs) of your tenant's graph |
| last resort | `run_cypher_readonly`: guarded text2cypher (below) |

The agent also uses four internal tools: `rank_causes` (pageRank), `whatif` (BFS/WCC on a GRAPH.COPY branch), `who_fixes` (HarmonicCentrality) and `escalation_tree` (MSF). These build engine-written scratch graphs, so they are never hosted. The stdio server for this repo includes them, annotated as writing.

## Resources
Resources are bound to a tenant the same way tools are. Over HTTP the bearer key picks the tenant; over stdio it is the session's tenant. A URI never names a graph.

| URI | content |
|---|---|
| `faultline://schema` | The live schema of your tenant's graph (JSON). Same data as `graph_schema`, plus the tenant, graph and `served_by`. |
| `faultline://queries` | The template catalogue (JSON): every product read, with its id, purpose, parameters, `LIMIT` and file. Name one as `failed_template` when you fall back to `run_cypher_readonly`. |
| `faultline://weights` | `weights.yaml` verbatim: every gate threshold, score weight and preflight term the product computes in code. |

**How the schema is read** (templates Q-SCHEMA-1..4, all `GRAPH.RO_QUERY`):
- **Counts:** `db.meta.stats`, the engine's own statistics. They are O(1) and match a full count.
- **Endpoint pairs and property keys:** bounded scans of at most 100,000 edges and 20,000 nodes. `complete` says whether a scan covered the whole graph.
- **Indexes:** `db.indexes`.

`docs/GRAPH_SCHEMA.md` is generated from the same data by `scripts/gen_graph_schema.py`. `scripts/check_schema_drift.py` fails loudly when a graph holds a label or relationship type that `graph/schema_model.py` does not declare.

## Prompts
Each prompt steers you to the right tools and states the rule: **no path, no claim**.

| prompt | argument | steers to |
|---|---|---|
| `investigate_incident` | `symptom` | resolve → recall → upstream suspects → `causal_paths` + `impact_bound` per suspect → blast radius and min-cut → who fixes it |
| `preflight_pr` | `pr_id` | `preflight_change` (the verdict as returned, never re-scored) → `decision_check` / `trace_decision` → reviewers |
| `ask_brain` | `question` | resolve ids → the company-brain tools → schema and catalogue, then `run_cypher_readonly` only as a last resort; cite only ids a tool returned |

## The text2cypher guard (`backend/faultline/graph/guard.py`)
`run_cypher_readonly(query, failed_template, reason)` is the last resort, after the templates. You must name the template that could not answer. The query passes three layers:
1. **Guard**, on the query with its string literals masked:
   - single statement; no comments, no `GRAPH.*`;
   - no `CREATE`/`MERGE`/`SET`/`DELETE`/`DETACH`/`REMOVE`/`DROP`/`FOREACH`/`LOAD`/`UNION`;
   - `CALL` is allowed only for the resolved `algo.*` read procedures and the index queries;
   - variable-length paths must be bounded (≤ 8);
   - `LIMIT ≤ 100`, appended if missing.
2. **`GRAPH.EXPLAIN`**: rejects a plan with a Cartesian product over full scans.
3. **`GRAPH.RO_QUERY`** as the read-only ACL user, with a 3 s timeout.

The result is recorded like any template call, with `via: "text2cypher"` and template id `T2C`.
