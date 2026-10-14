import type { PreflightReversal, ProvenanceResponse } from "@/lib/types";

/** A real GET /api/incidents/{inc}/provenance payload (Q-PROV-1), unedited. */
export const PROVENANCE: ProvenanceResponse = {
  "incident": "inc-s1-363667c4",
  "template": "Q-PROV-1",
  "cypher": "MATCH (i:Incident {id: $inc})-[:HYPOTHESIZES]->(h:Hypothesis)-[:BLAMES]->(c)\nWHERE h.status = 'confirmed'\nMATCH (e:Evidence)-[:SUPPORTS]->(h)\nOPTIONAL MATCH (tc:ToolCall)-[:PRODUCED_EVIDENCE]->(e)\nOPTIONAL MATCH (t:Task)-[:MADE]->(tc)\nRETURN h.id AS hypothesis, c.id AS blames, e.id AS evidence, e.tool AS tool, e.template AS template, e.summary AS summary,\n       tc.id AS tool_call, tc.ms AS ms, t.id AS task, t.role AS role, t.kind AS task_kind, t.owner AS agent,\n       [(tc)-[:SAW]->(n) | n.id][0..6] AS saw\nORDER BY evidence, tool_call\nLIMIT 60",
  "params": {
    "inc": "inc-s1-363667c4"
  },
  "nodes": [
    {
      "id": "verdict:hyp-inc-s1-363667c4-D-pay-417",
      "kind": "verdict",
      "label": "D-pay-417 confirmed",
      "blames": "D-pay-417"
    },
    {
      "id": "ev_0d9b87053a",
      "kind": "evidence",
      "label": "upstream_explained",
      "template": "Q-GATE-UPSTREAM-UB",
      "summary": "bound: no anomalous component upstream accounts for payment"
    },
    {
      "id": "run-s1-363667c4-tc0042",
      "kind": "call",
      "label": "upstream_explained",
      "template": "Q-GATE-UPSTREAM-UB",
      "ms": 2.05
    },
    {
      "id": "agent:gate",
      "kind": "agent",
      "label": "gate (its own checks)",
      "task": null,
      "task_kind": "gate"
    },
    {
      "id": "ev_9dc2e8c800",
      "kind": "evidence",
      "label": "metric_window",
      "template": null,
      "summary": "checkout error rate 30.69% vs baseline 0.69% (\u00d744.5, band 1.5745)"
    },
    {
      "id": "run-s1-363667c4-tc0014",
      "kind": "call",
      "label": "metric_window",
      "template": null,
      "ms": 1.68
    },
    {
      "id": "agent:telemetry-specialist-eb3eaec3",
      "kind": "agent",
      "label": "telemetry",
      "task": "spec-run-s1-363667c4-telemetry-267e3600",
      "task_kind": "specialist"
    },
    {
      "id": "ev_d3ce0adb65",
      "kind": "evidence",
      "label": "metric_window",
      "template": null,
      "summary": "payment error rate 30.91% vs baseline 0.71% (\u00d743.6, band 1.4575)"
    },
    {
      "id": "run-s1-363667c4-tc0016",
      "kind": "call",
      "label": "metric_window",
      "template": null,
      "ms": 1.87
    },
    {
      "id": "ev_edbfd9c531",
      "kind": "evidence",
      "label": "impact_bound",
      "template": "Q-GATE-3+Q-GATE-MULT",
      "summary": "bound 1.0000 (max flow 1.0000, up to 1 path(s)) vs needed 0.2433 (sufficient)"
    },
    {
      "id": "run-s1-363667c4-tc0040",
      "kind": "call",
      "label": "impact_bound",
      "template": "Q-GATE-3+Q-GATE-MULT",
      "ms": 2.59
    },
    {
      "id": "node:payment",
      "kind": "seen",
      "label": "payment"
    },
    {
      "id": "run-s1-363667c4-tc0043",
      "kind": "call",
      "label": "impact_bound",
      "template": "Q-GATE-3+Q-GATE-MULT",
      "ms": 2.36
    }
  ],
  "edges": [
    {
      "source": "agent:gate",
      "target": "run-s1-363667c4-tc0040",
      "rel": "MADE"
    },
    {
      "source": "agent:gate",
      "target": "run-s1-363667c4-tc0042",
      "rel": "MADE"
    },
    {
      "source": "agent:gate",
      "target": "run-s1-363667c4-tc0043",
      "rel": "MADE"
    },
    {
      "source": "agent:telemetry-specialist-eb3eaec3",
      "target": "run-s1-363667c4-tc0014",
      "rel": "MADE"
    },
    {
      "source": "agent:telemetry-specialist-eb3eaec3",
      "target": "run-s1-363667c4-tc0016",
      "rel": "MADE"
    },
    {
      "source": "ev_0d9b87053a",
      "target": "verdict:hyp-inc-s1-363667c4-D-pay-417",
      "rel": "SUPPORTS"
    },
    {
      "source": "ev_9dc2e8c800",
      "target": "verdict:hyp-inc-s1-363667c4-D-pay-417",
      "rel": "SUPPORTS"
    },
    {
      "source": "ev_d3ce0adb65",
      "target": "verdict:hyp-inc-s1-363667c4-D-pay-417",
      "rel": "SUPPORTS"
    },
    {
      "source": "ev_edbfd9c531",
      "target": "verdict:hyp-inc-s1-363667c4-D-pay-417",
      "rel": "SUPPORTS"
    },
    {
      "source": "run-s1-363667c4-tc0014",
      "target": "ev_9dc2e8c800",
      "rel": "PRODUCED_EVIDENCE"
    },
    {
      "source": "run-s1-363667c4-tc0016",
      "target": "ev_d3ce0adb65",
      "rel": "PRODUCED_EVIDENCE"
    },
    {
      "source": "run-s1-363667c4-tc0040",
      "target": "ev_edbfd9c531",
      "rel": "PRODUCED_EVIDENCE"
    },
    {
      "source": "run-s1-363667c4-tc0040",
      "target": "node:payment",
      "rel": "SAW"
    },
    {
      "source": "run-s1-363667c4-tc0042",
      "target": "ev_0d9b87053a",
      "rel": "PRODUCED_EVIDENCE"
    },
    {
      "source": "run-s1-363667c4-tc0043",
      "target": "ev_edbfd9c531",
      "rel": "PRODUCED_EVIDENCE"
    },
    {
      "source": "run-s1-363667c4-tc0043",
      "target": "node:payment",
      "rel": "SAW"
    }
  ]
};

/** The `reversals` of a real POST /api/preflight response (PR #9, off-peak migrations again). */
export const REVERSALS: PreflightReversal[] = [
  {
    "reversed": "ADR-009",
    "reversed_title": "Catalog DB migrations run off-peak",
    "rule_key": "catalog.db.migration_window",
    "actual": "off_peak",
    "about": "product-catalog",
    "head": "ADR-021",
    "head_title": "Catalog DB schema changes use online migrations",
    "head_decided_at": 1780444800000,
    "head_url": "data/gen/docs/adr-021.md",
    "because": [
      {
        "id": "doc-chat-catalog-migrations",
        "title": "#catalog-db: off-peak migrations still lock the catalog"
      }
    ]
  }
];
