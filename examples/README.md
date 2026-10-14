# Recorded runs: what to read, in order

Each folder is one run recorded through the API, keyless (the deterministic investigator, simulated GitHub), and
exported **from the graph** (`scripts/record_demo.py`, `scripts/export_run.py`). The graph is the record; these files
are views of it. `make judge-check` re-checks them: the gate verdicts are replayed (`evals/replay_examples.py`) and the
write-back is re-read (`scripts/run_artefacts.py --check`).

| Folder | What it shows | Read first |
|---|---|---|
| [`s1-hero/`](s1-hero/) | The hero incident: two same-minute look-alikes rejected (one by G2 "no path", one by G5 max flow), the proof path, the min-cut, who fixes it, two-step approval, a PR verified APPLIED, write-back 7/7 | `report.md`, then `gate_runs.json`, `plan.json`, `verify.txt`, `pr.md` |
| [`s2-data-incident/`](s2-data-incident/) | A data incident: the proof path crosses from a service into the warehouse lineage to the revenue KPI; the FX look-alike rejected by max flow over row shares; the service flag shown disabled because no failure path to the KPI crosses it | `report.md`, `gate_runs.json`, `plan.json` |
| [`s4-no-incident/`](s4-no-incident/) | A control: a deploy and a noisy metric, but no anomaly any change can reach (negative proof, `algo.SSpaths`): NO_INCIDENT, nobody blamed | `report.md`, `gate_runs.json` |
| [`s5-bad-fix/`](s5-bad-fix/) | Wrong fixes caught: a rollback of the wrong deploy and a data patch that does not fix the rows both verify NOT_APPLIED; nothing is written as success | `verify.txt`, `remediation_rejected.json`, `data_bad_fix_rejected.json` |
| [`s6-preflight-block/`](s6-preflight-block/) | The pre-deploy gate blocking a PR before it ships: what it reaches, the decisions it contradicts, who owns it | `report.md`, `preflight.json` |

## The files

| File | What it is |
|---|---|
| `report.md` / `report.json` | the root-cause report: proven claims (each with its gate check), the inferred, contradictions, futures, obligations, evidence |
| `gate_runs.json` | every gate run with every check (G1–G8), its Cypher template and parameters |
| `hypotheses.json` | every suspect with its HYPOTHESIZE score and the gate's status |
| `plan.json` | the options, each with its predicted future and why it is enabled or not; the chosen one's exact action and plan hash |
| `verify.txt` | the three-valued verdict per channel (GitHub main re-read, telemetry) and the write-back `verified n/m` |
| `pr.md` | the exact approved change (branch, commit, diff) |
| `events.jsonl` / `transcript.jsonl` | the run in order: stages, tool calls with their results, gate verdicts |
| `tool_calls.json` | every tool call with its template id, parameters, rows and engine time |
| `graph.json`, `blast.json`, `incident.json` | what the incident room draws |
| `cost.json` | model ids, tokens, US$ (keyless: 0) |

The static replay site (`frontend/public/replay/`, `npm run replay:export`) plays `s1-hero` and `s2-data-incident`
with the backend off.
