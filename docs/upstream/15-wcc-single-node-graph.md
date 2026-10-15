# algo.WCC fails on a graph with exactly one node (6.0.2)

**Filed as [FalkorDB#3349](https://github.com/FalkorDB/FalkorDB/issues/3349)** (re-verified on 6.0.2 before filing; `algo.pageRank` fails the same way). Found building alert-storm grouping (2026-10-13): a window with a single alert projects
a one-node scratch graph.

**Engine:** `falkordb/falkordb:6.0.2` @ `sha256:107455e8…` (module 60002)

```
GRAPH.QUERY g "CREATE (:Node {id:'a'})"
GRAPH.RO_QUERY g "CALL algo.WCC({nodeLabels:['Node'], relationshipTypes:['PROPAGATES_TO']}) YIELD node, componentId RETURN node.id, componentId"
GRAPH.RO_QUERY g "CALL algo.WCC({nodeLabels:['Node']}) YIELD node, componentId RETURN node.id, componentId"
```
**Expected:** one row, `a` in its own component.
**Actual:** `LAGr_ConnectedComponents failed: -1000` for both forms. With two nodes and no relationship at all, or with
a relationship type that has no edges, WCC answers correctly (each node its own component).

**Workaround in Faultline:** `group_alerts` (mcp_server/tools.py) adds one isolated anchor node without alerts to every
alert projection, so the graph has at least two nodes; `Q-STORM-WCC` returns only components that hold alerts.
