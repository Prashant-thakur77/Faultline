import type { Crew, GateRun } from "@/lib/types";

/**
 * Trimmed from a real GET /api/incidents/{inc} payload (crew + gate_runs): calls cut to two per step,
 * the confirmation run cut to four checks, crew steps stored in REVERSE so order must come from `after`.
 */
export const CREW: Crew = {
  "roster": [
    {
      "key": "triage",
      "id": "crew-triage",
      "name": "Triage",
      "job": "groups the alert storm into independent incidents (algo.WCC)",
      "stages": [
        "INTAKE"
      ],
      "tools": [
        "context_pack",
        "find_entities",
        "finish"
      ],
      "writes": "opens incidents and attaches alerts (intake writes)",
      "model": "none"
    },
    {
      "key": "historian",
      "id": "crew-historian",
      "name": "Historian",
      "job": "recalls past incidents and runbooks that share the symptoms",
      "stages": [
        "RECALL"
      ],
      "tools": [
        "finish",
        "incident_families",
        "runbook_for"
      ],
      "writes": "records what was recalled (W-RECALL)",
      "model": "none"
    },
    {
      "key": "cartographer",
      "id": "crew-cartographer",
      "name": "Cartographer",
      "job": "maps the symptoms' upstream scope, context and blast radius",
      "stages": [
        "LOCALIZE",
        "BLAST"
      ],
      "tools": [
        "blast_radius",
        "chokepoints",
        "column_lineage"
      ],
      "writes": "none (read-only)",
      "model": "none"
    },
    {
      "key": "profiler",
      "id": "crew-profiler",
      "name": "Profiler",
      "job": "lists the changes upstream of the symptoms in the window and ranks them in code",
      "stages": [
        "HYPOTHESIZE"
      ],
      "tools": [
        "finish",
        "rank_causes",
        "record_hypothesis"
      ],
      "writes": "open hypotheses (W-HYP)",
      "model": "none"
    },
    {
      "key": "lead",
      "id": "crew-lead",
      "name": "Lead investigator",
      "job": "dispatches the five specialists and proposes a cause to the gate",
      "stages": [
        "INVESTIGATE"
      ],
      "tools": [
        "anomalous_row_share",
        "baseline_columns",
        "causal_paths"
      ],
      "writes": "hypothesis status, through the gate only",
      "model": "optional"
    },
    {
      "key": "gatekeeper",
      "id": "crew-gatekeeper",
      "name": "Gatekeeper",
      "job": "decides: path, flow, time, origin, rivals, agreement, contradictions (G1–G8)",
      "stages": [
        "GATE",
        "CONTRADICTION"
      ],
      "tools": [
        "alert_coverage",
        "confirm_root_cause",
        "decision_check"
      ],
      "writes": "gate runs (W-GATE)",
      "model": "none"
    },
    {
      "key": "containment",
      "id": "crew-containment",
      "name": "Containment",
      "job": "finds the smallest cut (algo.maxFlow) and tries each option on a GRAPH.COPY",
      "stages": [
        "CONTAIN"
      ],
      "tools": [
        "blast_radius",
        "connectivity_check",
        "containment_cut"
      ],
      "writes": "none (clean rooms are scratch graphs)",
      "model": "none"
    },
    {
      "key": "dispatcher",
      "id": "crew-dispatcher",
      "name": "Dispatcher",
      "job": "finds who fixes it, the escalation path, obligations and who to notify",
      "stages": [
        "ROUTE"
      ],
      "tools": [
        "bus_factor",
        "escalation_tree",
        "finish"
      ],
      "writes": "none (read-only)",
      "model": "none"
    },
    {
      "key": "planner",
      "id": "crew-planner",
      "name": "Planner",
      "job": "turns the cut into options from the fixed action enum, each with a plan hash",
      "stages": [
        "PLAN"
      ],
      "tools": [
        "finish",
        "propose_plan",
        "remedy_stats"
      ],
      "writes": "plan and options (W-PLAN)",
      "model": "none"
    }
  ],
  "steps": [
    {
      "task": "crew-run-s1-64064d24-planner-plan",
      "kind": "crew",
      "role": "planner",
      "stage": "PLAN",
      "agent": "crew-planner",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987192055,
      "done_at": 1791987192073,
      "summary": "4 option(s), 3 enabled; awaiting two-step approval",
      "after": [
        "crew-run-s1-64064d24-dispatcher-route"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0059",
          "tool": "remedy_stats",
          "template": "Q-REM-1",
          "ms": 2.26,
          "rows": 3,
          "at": 1791987192062
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-dispatcher-route",
      "kind": "crew",
      "role": "dispatcher",
      "stage": "ROUTE",
      "agent": "crew-dispatcher",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191994,
      "done_at": 1791987192052,
      "summary": "fixer p-017; bus factor 2; 4 to notify; urgent (obligations at risk)",
      "after": [
        "crew-run-s1-64064d24-containment-contain"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0053",
          "tool": "who_fixes",
          "template": "Q-ORG-WHO+Q-ORG-KNOWS+Q-ORG-HARM",
          "ms": 7.14,
          "rows": 6,
          "at": 1791987192011
        },
        {
          "id": "run-s1-64064d24-tc0054",
          "tool": "bus_factor",
          "template": "Q-ORG-BUS",
          "ms": 1.27,
          "rows": 1,
          "at": 1791987192017
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-containment-contain",
      "kind": "crew",
      "role": "containment",
      "stage": "CONTAIN",
      "agent": "crew-containment",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191485,
      "done_at": 1791987191992,
      "summary": "min-cut of 2 edge(s) between payment and 2 protected node(s); 5 option(s) tried on clean rooms",
      "after": [
        "crew-run-s1-64064d24-gatekeeper-gate"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0049",
          "tool": "connectivity_check",
          "template": "Q-CONN-2",
          "ms": 0.62,
          "rows": 1,
          "at": 1791987191487
        },
        {
          "id": "run-s1-64064d24-tc0050",
          "tool": "containment_cut",
          "template": "Q-CUT-1",
          "ms": 3.14,
          "rows": 2,
          "at": 1791987191493
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-gatekeeper-gate",
      "kind": "crew",
      "role": "gatekeeper",
      "stage": "GATE",
      "agent": "crew-gatekeeper",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191467,
      "done_at": 1791987191483,
      "summary": "accepted D-pay-417 (confident)",
      "after": [
        "crew-run-s1-64064d24-lead-investigate"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0046",
          "tool": "alert_coverage",
          "template": "Q-CHAIN-MON",
          "ms": 0.96,
          "rows": 3,
          "at": 1791987191470
        },
        {
          "id": "run-s1-64064d24-tc0047",
          "tool": "residue_check",
          "template": "Q-RESIDUE-1",
          "ms": 1.61,
          "rows": 4,
          "at": 1791987191475
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "spec-run-s1-64064d24-code-267e3600",
      "kind": "specialist",
      "role": "code",
      "stage": null,
      "agent": "code-specialist-4de244a8",
      "state": "done",
      "status": "complete",
      "claimed_at": 1791987191351,
      "done_at": 1791987191381,
      "summary": null,
      "after": [],
      "names": [
        "D-pay-417"
      ],
      "cites": 3,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0020",
          "tool": "diff_summary",
          "template": "Q-CODE-1",
          "ms": 5.26,
          "rows": 1,
          "at": 1791987191361
        },
        {
          "id": "run-s1-64064d24-tc0023",
          "tool": "diff_summary",
          "template": "Q-CODE-1",
          "ms": 3.19,
          "rows": 1,
          "at": 1791987191369
        }
      ],
      "unknowns": [
        "D-email-88: no commits, PR or diff facts in the graph; its code cannot be inspected",
        "D-rec-12: no commits, PR or diff facts in the graph; its code cannot be inspected"
      ],
      "limits": [
        "no function-level code graph: a file path is the finest grain, and the paths are synthetic"
      ],
      "reaps": 0
    },
    {
      "task": "spec-run-s1-64064d24-change-267e3600",
      "kind": "specialist",
      "role": "change",
      "stage": null,
      "agent": "change-specialist-4de244a8",
      "state": "done",
      "status": "complete",
      "claimed_at": 1791987191349,
      "done_at": 1791987191398,
      "summary": null,
      "after": [],
      "names": [
        "D-pay-417",
        "D-email-88",
        "D-rec-12"
      ],
      "cites": 6,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0021",
          "tool": "change_details",
          "template": "Q-CHANGE-2",
          "ms": 5.36,
          "rows": 1,
          "at": 1791987191362
        },
        {
          "id": "run-s1-64064d24-tc0025",
          "tool": "decision_check",
          "template": "Q-DEC-1",
          "ms": 1.23,
          "rows": 2,
          "at": 1791987191372
        }
      ],
      "unknowns": [],
      "limits": [
        "change records only (kind, time, actor, title, CHANGED target, asserted facts); no rollout progress or canary data"
      ],
      "reaps": 0
    },
    {
      "task": "spec-run-s1-64064d24-data-267e3600",
      "kind": "specialist",
      "role": "data",
      "stage": null,
      "agent": "data-specialist-4de244a8",
      "state": "done",
      "status": "insufficient",
      "claimed_at": 1791987191345,
      "done_at": 1791987191347,
      "summary": null,
      "after": [],
      "names": [],
      "cites": 0,
      "calls": [],
      "unknowns": [
        "no KPI symptom: the data channel has nothing to measure for this incident"
      ],
      "limits": [
        "warehouse measurements only: daily KPI and per-column baseline ranges; no row-level lineage of a change"
      ],
      "reaps": 0
    },
    {
      "task": "spec-run-s1-64064d24-telemetry-267e3600",
      "kind": "specialist",
      "role": "telemetry",
      "stage": null,
      "agent": "telemetry-specialist-4de244a8",
      "state": "done",
      "status": "complete",
      "claimed_at": 1791987191320,
      "done_at": 1791987191343,
      "summary": null,
      "after": [],
      "names": [
        "D-pay-417",
        "D-rec-12"
      ],
      "cites": 5,
      "calls": [],
      "unknowns": [],
      "limits": [
        "error rate only (no latency, saturation or traces); telemetry is simulated per scenario"
      ],
      "reaps": 0
    },
    {
      "task": "spec-run-s1-64064d24-topology-267e3600",
      "kind": "specialist",
      "role": "topology",
      "stage": null,
      "agent": "topology-specialist-4de244a8",
      "state": "done",
      "status": "complete",
      "claimed_at": 1791987191317,
      "done_at": 1791987191395,
      "summary": null,
      "after": [],
      "names": [
        "D-pay-417",
        "D-email-88",
        "D-rec-12"
      ],
      "cites": 6,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0019",
          "tool": "causal_paths",
          "template": "Q-GATE-1",
          "ms": 0.92,
          "rows": 1,
          "at": 1791987191356
        },
        {
          "id": "run-s1-64064d24-tc0022",
          "tool": "causal_paths",
          "template": "Q-GATE-1",
          "ms": 0.9,
          "rows": 1,
          "at": 1791987191364
        }
      ],
      "unknowns": [
        "no path D-rec-12 → checkout"
      ],
      "limits": [
        "reachability only: a path is necessary for a claim, never sufficient (flow and timing are gate checks)"
      ],
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-lead-investigate",
      "kind": "crew",
      "role": "lead",
      "stage": "INVESTIGATE",
      "agent": "crew-lead",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191316,
      "done_at": 1791987191466,
      "summary": "baseline-policy (deterministic, no LLM): 5 specialist(s) dispatched, 4 complete; 1 cause(s) put to the gate",
      "after": [
        "crew-run-s1-64064d24-profiler-hypothesize"
      ],
      "names": [],
      "cites": 0,
      "calls": [],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-profiler-hypothesize",
      "kind": "crew",
      "role": "profiler",
      "stage": "HYPOTHESIZE",
      "agent": "crew-profiler",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191283,
      "done_at": 1791987191313,
      "summary": "3 suspect change(s) ranked in code: D-pay-417, D-email-88, D-rec-12",
      "after": [
        "crew-run-s1-64064d24-cartographer-localize"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0010",
          "tool": "upstream_suspects",
          "template": "Q-SUS-1",
          "ms": 1.23,
          "rows": 2,
          "at": 1791987191286
        },
        {
          "id": "run-s1-64064d24-tc0011",
          "tool": "upstream_suspects",
          "template": "Q-SUS-1",
          "ms": 0.88,
          "rows": 3,
          "at": 1791987191290
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-cartographer-localize",
      "kind": "crew",
      "role": "cartographer",
      "stage": "LOCALIZE",
      "agent": "crew-cartographer",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191247,
      "done_at": 1791987191281,
      "summary": "27 upstream node(s) in scope; blast radius of 2 symptom(s): 9 node(s); top chokepoint frontend",
      "after": [
        "crew-run-s1-64064d24-historian-recall"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0003",
          "tool": "service_context",
          "template": "Q-CTX-1",
          "ms": 0.93,
          "rows": 1,
          "at": 1791987191250
        },
        {
          "id": "run-s1-64064d24-tc0004",
          "tool": "upstream_scope",
          "template": "Q-LIN-1",
          "ms": 1.04,
          "rows": 12,
          "at": 1791987191254
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-historian-recall",
      "kind": "crew",
      "role": "historian",
      "stage": "RECALL",
      "agent": "crew-historian",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191183,
      "done_at": 1791987191245,
      "summary": "5 precedent(s), 3 runbook(s) recalled; prior on payment",
      "after": [
        "crew-run-s1-64064d24-triage-intake"
      ],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-tc0001",
          "tool": "similar_incidents",
          "template": "Q-MEM-1",
          "ms": 4.9,
          "rows": 5,
          "at": 1791987191192
        },
        {
          "id": "run-s1-64064d24-tc0002",
          "tool": "runbook_for",
          "template": "Q-MEM-3",
          "ms": 1.35,
          "rows": 3,
          "at": 1791987191240
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    },
    {
      "task": "crew-run-s1-64064d24-triage-intake",
      "kind": "crew",
      "role": "triage",
      "stage": "INTAKE",
      "agent": "crew-triage",
      "state": "done",
      "status": "done",
      "claimed_at": 1791987191101,
      "done_at": 1791987191103,
      "summary": "opened inc-s1-64064d24 from 2 alert(s) on checkout, frontend",
      "after": [],
      "names": [],
      "cites": 0,
      "calls": [
        {
          "id": "run-s1-64064d24-intake-tc0001",
          "tool": "group_alerts",
          "template": "Q-ALERT-1+Q-STORM-EDGES+Q-STORM-ORIGINS+Q-STORM-WCC+Q-STORM-ATTACH",
          "ms": 11.37,
          "rows": 1,
          "at": 1791987191089
        }
      ],
      "unknowns": null,
      "limits": null,
      "reaps": 0
    }
  ],
  "template": "Q-CREW-1"
};

export const GATE_RUNS: GateRun[] = [
  {
    "id": "gr-inc-s1-64064d24-f2863684",
    "cause": "D-email-88",
    "passed": false,
    "confident": false,
    "checks": [
      {
        "detail": "D-email-88 → email → checkout",
        "downgrade_only": false,
        "evidence_ids": [
          "ev_1a986a73de",
          "ev_03b4535c58",
          "ev_d3ce0adb65"
        ],
        "name": "G2 path",
        "params": {
          "cause": "D-email-88",
          "symptom": "checkout"
        },
        "passed": true,
        "template": "Q-GATE-1"
      },
      {
        "detail": "G5: max flow 0.0200 < needed 0.2433 (observed 0.3041 × 0.8); another suspect alone can carry 1.0000",
        "downgrade_only": false,
        "evidence_ids": [],
        "name": "G5 sufficiency",
        "params": null,
        "passed": false,
        "template": "Q-GATE-3"
      }
    ],
    "attempt": 0,
    "origin": "sweep",
    "at": 1791987191431
  },
  {
    "id": "gr-inc-s1-64064d24-3dbafb38",
    "cause": "D-pay-417",
    "passed": true,
    "confident": false,
    "checks": [
      {
        "detail": "D-pay-417 → payment → checkout",
        "downgrade_only": false,
        "evidence_ids": [
          "ev_d9c05ffae8",
          "ev_edbfd9c531",
          "ev_d3ce0adb65"
        ],
        "name": "G2 path",
        "params": {
          "cause": "D-pay-417",
          "symptom": "checkout"
        },
        "passed": true,
        "template": "Q-GATE-1"
      },
      {
        "detail": "G5: max flow 1.0000 ≥ needed 0.2433 (observed 0.3041 × 0.8)",
        "downgrade_only": false,
        "evidence_ids": [],
        "name": "G5 sufficiency",
        "params": null,
        "passed": true,
        "template": "Q-GATE-3"
      }
    ],
    "attempt": 0,
    "origin": "sweep",
    "at": 1791987191433
  },
  {
    "id": "gr-inc-s1-64064d24-382c4c3a",
    "cause": "D-rec-12",
    "passed": false,
    "confident": false,
    "checks": [
      {
        "detail": "G2: no path to any primary symptom (no path, no claim)",
        "downgrade_only": false,
        "evidence_ids": [
          "ev_5b8e92d948"
        ],
        "name": "G2 path",
        "params": {
          "cause": "D-rec-12",
          "symptom": "checkout"
        },
        "passed": false,
        "template": "Q-GATE-1"
      }
    ],
    "attempt": 0,
    "origin": "sweep",
    "at": 1791987191434
  },
  {
    "id": "gr-inc-s1-64064d24-6262cdb8",
    "cause": "D-pay-417",
    "passed": true,
    "confident": true,
    "checks": [
      {
        "detail": "D-pay-417 → payment → checkout",
        "downgrade_only": false,
        "evidence_ids": [],
        "name": "G2 path",
        "params": {
          "cause": "D-pay-417",
          "symptom": "checkout"
        },
        "passed": true,
        "template": "Q-GATE-1"
      },
      {
        "detail": "checkout: max flow 1.0000 ≥ needed 0.2433",
        "downgrade_only": false,
        "evidence_ids": [
          "ev_d3ce0adb65",
          "ev_edbfd9c531"
        ],
        "name": "G5 sufficiency",
        "params": null,
        "passed": true,
        "template": "Q-GATE-3"
      },
      {
        "detail": "independent channels on the chain: ['falkordb', 'simulator']",
        "downgrade_only": true,
        "evidence_ids": [],
        "name": "G7 agreement",
        "params": null,
        "passed": true,
        "template": "Q-GATE-7"
      },
      {
        "detail": "violates ADR-012: payment.client.timeout_ms <= 2000 (actual 5000); violates ADR-013: payment.client.retries >= 2 (actual 0)",
        "downgrade_only": true,
        "evidence_ids": [],
        "name": "G8 contradiction",
        "params": null,
        "passed": false,
        "template": "Q-DEC-1"
      }
    ],
    "attempt": 1,
    "origin": "confirm",
    "at": 1791987191463
  }
];
