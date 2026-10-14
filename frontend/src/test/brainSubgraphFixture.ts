import type { BrainAnswer, BrainSubgraph } from "@/lib/types";

/** GET /api/brain/subgraph for the answer below, as the live API returned it (acme demo tenant). */
export const BRAIN_SUBGRAPH: BrainSubgraph = {
  "template": "Q-BRAIN-SUB",
  "cypher": "MATCH (a:Node) WHERE a.id IN $ids\nMATCH (b:Node) WHERE b.id IN $ids AND a.id < b.id\nMATCH p = (a)-[*1..2]-(b)\nWHERE none(n IN nodes(p) WHERE n:ToolCall OR n:Evidence OR n:Run OR n:Turn OR n:Session OR n:StageEvent OR n:Task OR n:Agent)\nRETURN [n IN nodes(p) | {id: n.id, label: labels(n)[1], name: coalesce(n.name, n.title, n.id)}] AS nodes,\n       [r IN relationships(p) | {rel: type(r), source: startNode(r).id, target: endNode(r).id}] AS rels,\n       length(p) AS hops, a.id AS from, b.id AS to\nORDER BY hops, from, to\nLIMIT 60",
  "params": {
    "ids": [
      "ADR-012",
      "ADR-013",
      "payment",
      "p-004",
      "p-022"
    ]
  },
  "truncated": false,
  "nodes": [
    {
      "id": "ADR-012",
      "label": "Decision",
      "name": "Payment client timeout must stay ≤ 2000 ms",
      "cited": true
    },
    {
      "id": "p-004",
      "label": "Person",
      "name": "Dorian Marrowby",
      "cited": true
    },
    {
      "id": "p-022",
      "label": "Person",
      "name": "Vesna Hollowell",
      "cited": true
    },
    {
      "id": "payment",
      "label": "Service",
      "name": "payment charge processing",
      "cited": true
    },
    {
      "id": "ADR-013",
      "label": "Decision",
      "name": "Payment client keeps ≥ 2 retries",
      "cited": true
    },
    {
      "id": "doc-chat-payment-timeouts",
      "label": "Doc",
      "name": "#inc-checkout-pool: payment timeouts exhausting checkout connections",
      "cited": false
    },
    {
      "id": "inc-h028",
      "label": "Incident",
      "name": "Checkout errors after payment deploy",
      "cited": false
    },
    {
      "id": "p-017",
      "label": "Person",
      "name": "Quinn Lindqvane",
      "cited": false
    },
    {
      "id": "p-030",
      "label": "Person",
      "name": "Desmond Brackwater",
      "cited": false
    },
    {
      "id": "p-034",
      "label": "Person",
      "name": "Hester Hawksmere",
      "cited": false
    },
    {
      "id": "p-036",
      "label": "Person",
      "name": "Juno Pellucid",
      "cited": false
    },
    {
      "id": "team-payments",
      "label": "Team",
      "name": "Payments",
      "cited": false
    },
    {
      "id": "checkout",
      "label": "Service",
      "name": "checkout order placement",
      "cited": false
    }
  ],
  "edges": [
    {
      "rel": "DECIDED",
      "source": "p-004",
      "target": "ADR-012"
    },
    {
      "rel": "DECIDED",
      "source": "p-022",
      "target": "ADR-012"
    },
    {
      "rel": "CONSTRAINS",
      "source": "ADR-012",
      "target": "payment"
    },
    {
      "rel": "DECIDED",
      "source": "p-004",
      "target": "ADR-013"
    },
    {
      "rel": "DECIDED",
      "source": "p-022",
      "target": "ADR-013"
    },
    {
      "rel": "CONSTRAINS",
      "source": "ADR-013",
      "target": "payment"
    },
    {
      "rel": "COMMITTED",
      "source": "p-004",
      "target": "payment"
    },
    {
      "rel": "CITES",
      "source": "ADR-012",
      "target": "doc-chat-payment-timeouts"
    },
    {
      "rel": "CITES",
      "source": "ADR-013",
      "target": "doc-chat-payment-timeouts"
    },
    {
      "rel": "ABOUT",
      "source": "doc-chat-payment-timeouts",
      "target": "payment"
    },
    {
      "rel": "RESOLVED",
      "source": "p-004",
      "target": "inc-h028"
    },
    {
      "rel": "AFFECTED",
      "source": "inc-h028",
      "target": "payment"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-004",
      "target": "p-017"
    },
    {
      "rel": "COMMITTED",
      "source": "p-017",
      "target": "payment"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-017",
      "target": "p-004"
    },
    {
      "rel": "REPORTS_TO",
      "source": "p-017",
      "target": "p-004"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-004",
      "target": "p-030"
    },
    {
      "rel": "COMMITTED",
      "source": "p-030",
      "target": "payment"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-030",
      "target": "p-004"
    },
    {
      "rel": "REPORTS_TO",
      "source": "p-030",
      "target": "p-004"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-004",
      "target": "p-034"
    },
    {
      "rel": "COMMITTED",
      "source": "p-034",
      "target": "payment"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-034",
      "target": "p-004"
    },
    {
      "rel": "REPORTS_TO",
      "source": "p-034",
      "target": "p-004"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-004",
      "target": "p-036"
    },
    {
      "rel": "COMMITTED",
      "source": "p-036",
      "target": "payment"
    },
    {
      "rel": "COLLABORATES",
      "source": "p-036",
      "target": "p-004"
    },
    {
      "rel": "REPORTS_TO",
      "source": "p-036",
      "target": "p-004"
    },
    {
      "rel": "MEMBER_OF",
      "source": "p-004",
      "target": "team-payments"
    },
    {
      "rel": "OWNED_AT",
      "source": "team-payments",
      "target": "payment"
    },
    {
      "rel": "OWNS",
      "source": "team-payments",
      "target": "payment"
    },
    {
      "rel": "ON_CALL",
      "source": "p-004",
      "target": "team-payments"
    },
    {
      "rel": "COMMITTED",
      "source": "p-022",
      "target": "checkout"
    },
    {
      "rel": "CALLS",
      "source": "checkout",
      "target": "payment"
    },
    {
      "rel": "DEPENDS_ON",
      "source": "checkout",
      "target": "payment"
    },
    {
      "rel": "PROPAGATES_TO",
      "source": "payment",
      "target": "checkout"
    }
  ]
};

/** POST /api/brain/ask for "who decided the payment timeout" (steps trimmed: the graph does not read them). */
export const BRAIN_ANSWER: BrainAnswer = {
  "question": "Who decided the payment timeout, and are they still here?",
  "tenant": "acme",
  "run_id": "brain-680304d11e",
  "intent": "decision",
  "tier": 2,
  "answer": "Decisions about [payment]:\n- [ADR-012] Payment client timeout must stay ≤ 2000 ms: active, and still current (nothing supersedes it). Decided by [p-004] Dorian Marrowby (still on the owning team), [p-022] Vesna Hollowell (still here, another team).\n- [ADR-013] Payment client keeps ≥ 2 retries: active, and still current (nothing supersedes it). Decided by [p-004] Dorian Marrowby (still on the owning team), [p-022] Vesna Hollowell (still here, another team).",
  "citations": [
    "ADR-012",
    "ADR-013",
    "p-004",
    "p-022",
    "payment"
  ],
  "sources": [
    "data/gen/docs/adr-012.md",
    "data/gen/docs/adr-013.md",
    "data/gen/docs/chat-payment-timeouts.md"
  ],
  "guard": {
    "ok": true,
    "cited": [
      "ADR-012",
      "ADR-013",
      "p-004",
      "p-022",
      "payment"
    ],
    "unseen": [],
    "reason": ""
  },
  "answered_by": "baseline-brain (deterministic router, no LLM)",
  "ms": 43.5,
  "steps": []
};
