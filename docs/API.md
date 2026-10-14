# Faultline API v2 contract (backend/faultline/api.py)

Base `http://localhost:8400`. Every read goes through FalkorDB read-only templates (`graph/ro.py`). Writes (run state, approvals, write-back) go through `graph/writes.py`. The warehouse KPI comes from the system under observation.

**Errors fail loudly:**
- `503 {detail}`: FalkorDB unavailable, graph not ready, or live LLM not configured.
- `429`: rate limited (per visitor, plus global caps in public mode).
- `404`: unknown incident, template, scenario, document or preflight.
- `409`: stale plan hash, wrong stage, option not available, or a stale dry-run token.
- `422`: invalid input (tenant, ids, params, approver not in the graph).
- `401`/`403`: missing or wrong key: preflight key, approver key (real GitHub), run token (public mode), LLM key (public mode).
- `502`: GitHub error while rendering an action.

The UI must show a banner with `detail` and never fabricate data.

## Endpoints
| Method | Path | Returns |
|---|---|---|
| GET | `/api/status?tenant=acme` | `{status:'ok'\|'unavailable', reason?, engine:{engine,digest}, tenant, graph, acl:'ro_user'\|'default_user', graph_disabled, models:{orchestrator,specialists}, llm_configured, templates, ready:{ready,data_hash,seeded_at,engine}, counts:{nodes,edges}, llm_budget:{usd_last_hour,reserved_usd,runs_last_hour,usd_per_hour_limit,scope:'global',replay_only}, udf:{flex:'loaded'\|'missing'}, udf_detail}`. `udf` comes from `GRAPH.UDF LIST WITHCODE` on the engine connection ("missing" also covers a library loaded at another sha); the UI shows a missing library in the red banner. `llm_budget` is ONE ledger for all tenants (settled cost plus in-flight reservations) |
| GET | `/api/tenants` | `[{tenant, graph, ready}]`: the seeded tenants, read from the FalkorDB graph list |
| GET | `/api/scenarios` | `[{id,name,tenant,report}]` |
| POST | `/api/scenarios/{id}/run` body `{llm:'baseline'\|'anthropic'}` | `{job,state,scenario,incident,run,graph,run_token}`; the incident exists as soon as this returns. `run_token` is the capability for choose/approve on this run (required as `X-Faultline-Run-Token` in public mode). When INTAKE splits the alerts into several incidents (S14: an alert storm plus a concurrent fault), the job investigates every one in turn (then the later intake rounds) and adds `incidents: [{incident, run, symptoms, intake_round, outcome}]`; each has its own RunIndex row (listed by `GET /api/incidents`, addressable by every incident route) and the same `run_token` is valid for all of them; `incident`/`run` stay the first one. At most 4 runs at once (429). 429 also when FalkorDB has too many queries waiting or is above `engine.max_memory_fraction` of maxmemory, and on the public demo when a data scenario needs a warehouse mode other than the one an active run holds. |
| GET | `/api/jobs/{job}?tenant=acme` | A run job's handle: `{job,state,scenario,tenant,incident,run,graph,incidents,outcome,error,token_valid}`, including incidents a later intake round opened after the run response. Tenant-bound (404 for another tenant). `run_token` is echoed back only when the caller presents the job's own token as `X-Faultline-Run-Token` (`token_valid: true`); the UI keys its token by job and uses this to learn the late incidents. Handles live in the API process (404 after a restart). |
| GET | `/api/incidents?tenant=acme` | `[{run,incident,graph,scenario,investigator,outcome,cause,started_at,updated_at}]` (newest first) |
| GET | `/api/incidents/{inc}` | `IncidentView` (below) |
| GET | `/api/incidents/{inc}/events` | SSE (below) |
| GET | `/api/graph?tenant=acme[&incident=…][&focus=<node>]` | `{graph, focus, truncated, nodes:[{id,label,tier,betweenness}], edges:[{source,target,cap,domain}]}`: the failure-flow graph (PROPAGATES_TO; service + data lineage; Transforms hidden). Large tenants (globex) should pass `focus`, which scopes the view to that node's upstream (≤ 3 hops) and blast radius. `truncated:true` means the unscoped view hit the template LIMIT. |
| GET | `/api/templates/{tid}` | `{id,purpose,cypher,file,limit}` |
| POST | `/api/templates/{tid}/profile` body `{params, incident?, tenant}` | `{id, plan:[…], engine_ms, graph}` (GRAPH.PROFILE; 30/min per visitor, 60/min global) |
| POST | `/api/templates/{tid}/run` body `{params, incident?, tenant}` | `{rows, ms, digest, truncated, served_by, cypher}` (read-only re-run; 30/min) |
| POST | `/api/demo/rearm?tenant=acme` | `{src,dst,ms,indexes}` (the UI's "Reset demo data (all visitors)"; 1/min per visitor, 20/h global; audit graph kept; resets only the tenant graph's simulated GitHub) |
| GET | `/api/metrics/snapshot` | warehouse KPI `{kpi_day,revenue,expected_revenue,anomaly_ratio,status,daily[]}` |

### Action path (two-step approval)
| Method | Path | Returns |
|---|---|---|
| GET | `/api/incidents/{inc}/blast` | `{graph, blast:{<symptom>:{rows:[{id,label,tier,revenue,hops,max_cap,impact}],template,via}}}` |
| GET | `/api/incidents/{inc}/plan` | `{stage, containment_cut, whatif, who_fixes, bus_factor, escalation_tree, notify_set, owner_at, options, memory}` (see below) |
| POST | `/api/incidents/{inc}/choose` body `{action_id}` | the **exact action**: `{kind,incident,args,branch,idem,file?,before?,after?,commit?,pr_body?,rollback?,title?,body?,plan_hash}`. 409 if not available or not awaiting approval; 403 without the run token (public mode); 20/min |
| POST | `/api/incidents/{inc}/approve` body `{action_id, plan_hash, approver}` | `{approved:true,state,mine,idem,approval_id,approver:{id,name,owner_team,committed}}`, then EXECUTE → VERIFY → WRITEBACK run in the background (see the stage sequence). 409 if the plan hash is stale or the incident is not awaiting approval. 422 if the approver is not an active person in the tenant graph. 403 without the run token (public mode) or the approver key (real GitHub). 10/min |
| POST | `/api/incidents/{inc}/reject` body `{action_id, plan_hash, approver, reason}` | `{rejected:true, action_id, status:'rejected', rejected_at, stage:'AWAITING_APPROVAL', reason, approver:{id,name,owner_team,committed}}`. Rejects the **exact** chosen action (the plan hash the human saw). One atomic query (`writes.W_REJECT`): the action becomes `status:'rejected'`, `enabled:false`, with `rejected_by`, `reject_reason` and `rejected_at` (the option's own `reason` is kept), and a stage event records it on the run; the incident stays `AWAITING_APPROVAL` so another option can be chosen. When no enabled option is left, a second conditional query moves it to `UNKNOWN_ESCALATED` with the reason, and the response carries `stage:'UNKNOWN_ESCALATED', escalated:true`. A rejected option can be neither re-chosen nor approved (409). Same guards as approve: 409 if the hash is stale, the action is not the current choice or the incident is not awaiting approval; 422 if the approver is not an active person or `reason` is shorter than 3 characters (after trimming); 403 without the run token (public mode) or the approver key (real GitHub). Nothing outside the graph is touched (no intent exists before approval). 10/min |
| GET | `/api/incidents/{inc}/contrast` | Naive recency vs the gate, from what the run recorded (nothing recomputed): `{graph, onset_at, confirmed, outcome, naive:[deploy], changes:[{deploy,kind,target,at,before_onset_ms,pagerank,gate_status,gate_reason,confirmed}], window_changes:{template,evidence_id,params,summary}, rank_causes:{…}\|null, unavailable}`. `changes` is the run's recorded `window_changes` result (Q-SUS-2, newest first); `naive` is its first row plus any change at the same instant (a tie); `pagerank` is the run's recorded `rank_causes` score of the changed node; `gate_status`/`gate_reason` come from the hypotheses (Q-HYP-1). `unavailable` says why when the run recorded no `window_changes` result. |

**Plan fields:**
- `containment_cut`, `whatif`, `who_fixes`, `bus_factor`, `escalation_tree`, `notify_set`, `owner_at` are each `{id, evidence_id, summary, template, params, payload, at}` or null.
- `payload.rows` is the tool's result rows:
  - cut: `[{u,v,cut_cost,domain}]` and `max_flow`;
  - whatif: `[{removed_edges,reach_before,reach_after,no_longer_reached,protected_still_reached,still_connected}]` and `verdict`;
  - who_fixes: `[{person,name,score,teams,reasons[]}]`;
  - bus_factor: `bus_factor`, `top_contributor_inactive`;
  - escalation_tree: `[{from,to,w}]`, `managers`;
  - notify_set (who to notify, not who fixes it): `[{team,name,owns_impacted,oncall,impact,nearest_hops}]`;
  - owner_at (owner when the change shipped): `[{team,name,since,until,covers_at,current}]`, `owner_then`, `owner_now`, `changed_hands`, `knew_it_then`, `at`.
- `options` are `[{id,kind,option,enabled,reason,target,status:'option'|'chosen'|'approved'|'executed'|'failed'|'rejected',preview,spec,plan_hash,idem,external_ref,verdict:'APPLIED'|'NOT_APPLIED'|'UNKNOWN'|null,explanation,channels,approval_id,rejected_by,reject_reason,rejected_at}]`. Disabled options carry the reason they are not offered ("not simulated").

**data_repair** (data incidents): offered disabled until a transform patch is proposed (`act.propose_data_repair`; in live mode, by the specialist). Only allowlisted `pipeline/transforms/*.sql` files can be patched, and the diff is computed server-side. Verification:
- channel 1 re-reads the file;
- channel 2 rebuilds the warehouse, runs the invariant suite and recomputes the KPI (anomaly ratio 0.8–1.3). <!-- noclaim: configured band -->

A repair that fails verification is reverted (`NOT_APPLIED`).

**Reconciler** (`actions/reconcile.py`): runs at API start and before every execute. It looks at intents still `PENDING` after 2 minutes and checks GitHub with the idempotency key:

| What it finds | Result |
|---|---|
| The change is at main HEAD | Re-verify through both channels, then write back |
| The change is absent | `NOT_APPLIED`; the intent becomes `FAILED` and needs a new approval |
| GitHub is unreadable | `UNKNOWN`; the intent stays `PENDING` and the incident is escalated |

**Stage sequence after the gate:**
1. `GATE`, then `CONTRADICTION` (only if a decision is violated). Abstention (no change explains it): `GATE` with an "inferred origin, NOT confirmed" note; outcome `NOT_CONFIDENT`.
2. `CONTAIN` → `ROUTE` → `PLAN` → `AWAITING_APPROVAL`.
3. After approval: `EXECUTE` → `VERIFY` → `WRITEBACK`. The WRITEBACK note carries the verdict and its explanation.
4. Then:
   - **APPLIED**, re-read n/n: `LEARN` → `RESOLVED` (note `write-back verified n/m`).
   - **NOT_APPLIED**: back to `AWAITING_APPROVAL`; the failed option is disabled (`status:'failed'`).
   - **UNKNOWN**, an incomplete re-read, or a failure after execute: `UNKNOWN_ESCALATED`.
   - **open_issue**: `UNKNOWN_ESCALATED` ("tracked in issue"; not resolved).
   - **A failure before anything external changed**: `FAILED`.

**Plan memory fields** (`memory`, read from the graph):
- `recalled`: `[{id,title,similarity,recency,salience,shared[],actions:[{kind,verdict,target}],cause_targets[]}]` (Q-MEM-4). These are the RECALLED edges written at RECALL: vector seed from `db.idx.vector.queryNodes(Incident.embedding)`, kept only when the past incident shares a `(:Symptom)` node with this one.
- `fix_history`: `[{kind,verdict,n,incidents[]}]` (Q-MEM-5), which tells how each fix kind fared on the recalled precedents.

The stage sequence starts `INTAKE → RECALL → LOCALIZE …`. At write-back, recalled incidents whose cause changed the same component become `PRECEDENT_FOR` the new incident (Q-MEM-2). An APPLIED `flip_flag` also sets the `FeatureFlag` node's state in the same query.

### M15: break the graph, decision overrides, learned links
| Method | Path | Returns |
|---|---|---|
| GET | `/api/playground` | `{scenario, perturbations:[{id,label,what,expect,algorithm}]}` (menu: `data/scenarios/playground.yaml`) |
| POST | `/api/playground/{id}` | `{scenario, perturbation, applied, before, after, diff:[{decision,before,after,changed,templates[]}], changed[], seconds, cached}`; recorded as a `PlaygroundRun` in `audit_<t>`; the public demo serves the recorded diff (`cached: true`). One at a time; 429 when busy or the engine sheds load |
| POST | `/api/decisions/{decision}/override?tenant=` body `{change, verdict: intentional\|accidental\|discuss, why, incident?, plan_hash?, approver?}` | step 1 (no plan_hash): the contradiction as the graph holds it and the plan hash; step 2 (plan_hash + approver): `{…, step:"recorded", override}`. 404 no such contradiction, 409 stale hash, 422 approver not an active person, 403 on the public demo without the approver key |
| POST | `/api/incidents/{inc}/human-fix?tenant=` body `{change, by, why}` | an enabled rollback option of a change a human names (only when the gate did not confirm one, only a change in the incident's 30-minute window, `by` an active person); 409 otherwise |
| GET | `/api/incidents/{inc}/edge-proposals?tenant=` | `{incident, proposals:[{id,src,dst,cap,why,status,plan_hash,action,change,approved_by}]}`, read-only (proposals are made by the execute job after an APPLIED rollback) |
| POST | `/api/incidents/{inc}/edge-proposals/{pid}/approve?tenant=` body `{plan_hash, approver}` | `{approved, by}`; 409 when the hash is stale, the proposal was already approved, its fix is no longer APPLIED, the approver is not an active person, or the graph has a path now |

### Company brain, memory and preflight
| Method | Path | Returns |
|---|---|---|
| POST | `/api/brain/ask?tenant=` body `{question, llm, user?, session?}` | `{question, tenant, run_id, intent, tier:1\|2\|3, answer, citations[], steps:[{tool,args,params,template,cypher,rows,evidence_id,via,ms,error}], sources[], guard:{ok,cited[],unseen[],reason}, answered_by, ms, session}` |
| GET | `/api/preflight?pr=<id>&tenant=` | the latest recorded preflight of that PR: same fields as the POST plus `{run_id, at, recorded:true}`; 404 if none (unkeyed public preflights are never recorded) |
| GET | `/api/brain/history?user=&tenant=` | `{user, turns:[{session,seq,role,text,at,refs[]}]}` (Q-SESS-1) |
| POST | `/api/memory/forget?tenant=` body `{doc_id}` | dry run: `{dry_run:true, doc, owned:[{id,label,rels,has_vector}], nodes, relationships, vectors, kept[], token}` |
| POST | `/api/memory/forget?tenant=` body `{doc_id, token, approver}` | `{dry_run:false, clean_room, graph, nodes, relationships, vectors, vectors_still_found, forgotten_ids[], kept_ids[], proof}`. In public mode without the admin key, `clean_room:true` and `graph` is a temporary `eval_<t>_forget_*` copy, deleted afterwards; the live tenant graph is unchanged. The receipt goes to `audit_<tenant>`. 409 if the token no longer matches. |
| GET | `/api/memory/overview?tenant=&incident=` | Memory tab. `{graph, incident, families, runbooks, recall?, recalled?}`: `families` = the `incident_families` tool (algo.labelPropagation, Q-MEM-6; the incident's family first, `mine:true`); `runbooks` = every runbook in effect, derived first by support, with `for_ids[]` and `derived_from[]` postmortems (Q-MEM-RB). With `incident`: `recall` = the `similar_incidents` tool (Q-MEM-1: `similarity`, `recency`, `salience` as separate columns, `now` = the incident's onset) and `recalled` = the RECALLED edges its run wrote (Q-MEM-4). An agent-run incident is read from its run's graph, a seeded one from `tenant_<t>`; 404 if unknown. |
| GET | `/api/brain/decisions?tenant=` | Decision tracer picker: `{rows:[{id,title,status,decided_at,url,constrains[],superseded_by[]}], template:'Q-DEC-LIST', params, ms, truncated}` |
| GET | `/api/brain/decisions/{id}?tenant=` | `{trace, chain}`: `trace` = the `trace_decision` tool (head through SUPERSEDES, Q-DEC-2, plus the head's sources, Q-DEC-3); `chain` = the whole SUPERSEDES chain the decision belongs to, oldest first, each with `supersedes[]` and `superseded_by[]` (Q-DEC-CHAIN). 404 for an unknown decision. |
| GET | `/api/brain/ownership?tenant=` | Ownership map: `{rows:[{team,name,owns[],n_owned,active_members}], template:'Q-OWN-MAP', …}` |
| GET | `/api/brain/ownership/{component}?tenant=&at=` | the `owner_at` tool at `at` (default now): OWNED_AT periods, `owner_then`, `owner_now`, `changed_hands`, `knew_it_then` |
| GET | `/api/brain/guardrails?tenant=` | `{missing_guardrails, knowledge_health}`: the two tools as of now (Q-GAP-1; Q-KH-1/2/3 + Q-COUPLE-1) |
| POST | `/api/preflight?tenant=` body `{repo, number, title, author, head_sha, files:[{path,before,after}]}`, or `{repo, number}` alone to fetch the PR (only a repo the tenant graph knows, Q-PRE-REPO, unless the preflight key is presented: 403 otherwise) | `{pr, run_id, verdict, risk, thresholds, terms{…:{value,weighted,why}}, would_change_if[], reviewers[], decision_links[], assessment, facts[], notes[], unknown_files[], evidence, comment, ms}` |

**Read-only view endpoints** (`incidents/{inc}/contrast`, `memory/overview`, `brain/decisions*`, `brain/ownership*`, `brain/guardrails`): tenant-bound GETs that call existing MCP tools bound with `record=False` (no ToolCall/Evidence is written) or catalogue templates through the RO wrapper. Tool results keep the tool envelope (`rows, via, template, cypher, params, ms, digest, truncated, evidence_id`) and template results are `{rows, template, params, ms, truncated, digest}`, so the UI's Cypher panel can re-run each one read-only. A tool error is returned in its section as `{error}` (never empty rows); FalkorDB down is a 503.

**Brain citations.**
- Every `[id]` in a brain answer was SEEN by a tool call of that question's own Run (Q-CITE-1 decides). Otherwise the answer is withheld.
- With `user`, turns persist as `(:Session)-[:HAS_TURN]->(:Turn)`. A follow-up with no named entity resolves to the subject of the user's previous answer.

**Preflight.**
- Quiet on `allow` (`comment` is null).
- `block` fails the GitHub status check (`deploy/github-action/faultline-preflight.yml`).
- A contradicted active decision is never `allow`.
- If `FAULTLINE_PREFLIGHT_KEY` is set, the endpoint requires `Authorization: Bearer <key>`.

## IncidentView
```jsonc
{
  "incident": {"id","title","stage","onset_at","opened_at","confident","targets":[…],"kinds":[…]},
  "run": {"run","graph","scenario","outcome","cause","investigator"},
  "stages": [{"id","stage","ord","at","note"}],
  "tool_calls": [{"id","tool","template","ms","rows","at","evidence_id","kind","summary"}],
  "hypotheses": [{"id","cause","status":"open|eliminated|confirmed|unresolved","score","reason","origin":"code|sweep|investigator|gate","supports":[…],"refutes":[…]}],
  "gate_runs": [{"id","cause","passed","confident","origin":"sweep|confirm|no_incident","attempt","at",
                 "checks":[{"name","passed":true|false|null,"detail","template","params","evidence_ids":[…],"downgrade_only"}]}],
  "report": {"incident_id","outcome","confident","cause_id","mechanism":[ids],"proven":[{"claim","evidence_ids","check"}],
             "inferred":[{"claim","basis"}],"contradictions":[…],
             "why_alerts_missed_it":{"summary","hops":[{"hop","id","label","alerted","first_alert_lag_s","has_telemetry"}]},
             "ownership":{"component","at","owner_then","owner_now","changed_hands","summary"},
             "residue":{"advisory","k","n","explained":[…],"unexplained":[…],"summary"},
             "remedy":{"applied","lines":[…],"note"},
             "rejected":[{"cause","origin","gate_run","failed":[…]}],
             "evidence":[{"id","kind","source","tool","template","cypher","summary","digest","value","baseline","anomalous","about":[…]}]}
}
```
`report` is present once the run has an outcome. `why_alerts_missed_it`, `ownership`, `residue` and `remedy` are `{}` when they do not apply (no proven chain, no confirmed change, no plan); the residue check and the remedy ordering are advisory and never change the verdict. Check names:
- G1 grounded
- G2 path
- G3 time
- G3 earlier upstream
- G4 quantitative
- G5 sufficiency
- G6 competitors
- G6 unresolved
- G7 agreement
- G7 correlation
- G8 contradiction
- N1/N2 (no-incident)

## SSE `/api/incidents/{inc}/events`
| event | data |
|---|---|
| `hello` | `{incident}`, first event; sets `retry: 5000` |
| `stage` | a `stages[]` row |
| `tool_call` | a `tool_calls[]` row |
| `gate_run` | a `gate_runs[]` row (checks parsed) |
| `paused` | `{stage:'AWAITING_APPROVAL'}`: waiting for a human; the stream stays open |
| `done` | `{stage}`, sent once the run reaches NO_INCIDENT, UNKNOWN_ESCALATED, FAILED or RESOLVED |
| `idle` | `{reason}`, sent before closing after 120 s without new events (reconnect to resume) |
| `collected` | `{reason}`, the run's graph was garbage-collected (or no longer holds the incident); the stream closes and must not be reopened: every route for this incident now answers 410 |

Events are graph-derived: the server polls the run's StageEvents, ToolCalls and GateRuns every 0.5 s and emits rows it has not sent yet, ordered by `at`. Streams are capped at 3 per visitor and 50 in total (429). <!-- noclaim: configured poll interval -->

**410 Gone.** The live demo collects old run graphs (`api.gc_run_graphs`: beyond the `engine.keep_recent_runs` most recent runs, a graph is deleted only when nothing holds it: no PENDING intent, no live lease, no execute job or reconciler working on it, nothing recorded within `engine.gc_touched_ttl_min`, and no non-terminal incident idle less than `engine.gc_open_max_idle_h`). Any incident route on a collected run (view, plan, choose, approve, events…) answers 410 with a message saying so; the UI shows "This run was collected" and stops polling.

## Outcomes
| outcome | meaning |
|---|---|
| `CONFIRMED` | gate passed and confident |
| `NOT_CONFIDENT` | gate passed, but a downgrade check failed (G3 earlier, G6 unresolved, G7 agreement or correlation) |
| `NO_INCIDENT` | negative proof accepted |
| `UNKNOWN_ESCALATED` | no cause accepted; handed to a human |
| `FAILED` | error, with its reason |
