"""The contract between ingest producers and the seeder.

A producer returns a `Bundle`: node rows grouped by label and edge rows grouped by
(type, src_label, dst_label). Labels and relationship types must be in `graph.schema_model`
(whitelists), because the seeder formats them into Cypher from code, never from input.
Every node row has a string `id`; every edge row has `src`, `dst` and optional `props`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Bundle:
    nodes: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    edges: dict[tuple[str, str, str], list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))

    def node(self, label: str, id: str, **props: Any) -> None:
        self.nodes[label].append({"id": id, **props})

    def edge(self, rel: str, src_label: str, src: str, dst_label: str, dst: str, **props: Any) -> None:
        self.edges[(rel, src_label, dst_label)].append({"src": src, "dst": dst, "props": props})

    def merge(self, other: "Bundle") -> "Bundle":
        for k, v in other.nodes.items():
            self.nodes[k].extend(v)
        for k, v in other.edges.items():
            self.edges[k].extend(v)
        return self

    def counts(self) -> dict[str, int]:
        out = {f"node:{k}": len(v) for k, v in self.nodes.items()}
        out.update({f"edge:{k[0]}({k[1]}->{k[2]})": len(v) for k, v in self.edges.items()})
        return dict(sorted(out.items()))
