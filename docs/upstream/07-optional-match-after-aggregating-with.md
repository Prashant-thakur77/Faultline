# OPTIONAL MATCH after an aggregating WITH returns no rows (6.0.2)

**Status:** related to [FalkorDB#3037](https://github.com/FalkorDB/FalkorDB/issues/3037); comment prepared, not posted.

**Image:** falkordb/falkordb@sha256:107455e8… (6.0.2)
```
CREATE (r:Run {id:'r'})-[:HAS_TOOL_CALL]->(t:ToolCall {id:'t'})-[:PRODUCED_EVIDENCE]->(e:Evidence {id:'e1'}), (t)-[:SAW]->(:N {id:'n1'})

MATCH (run:Run {id:'r'})
OPTIONAL MATCH (run)-[:HAS_TOOL_CALL]->(:ToolCall)-[:SAW]->(n) WHERE n.id IN $ids
WITH run, collect(DISTINCT n.id) AS seen
OPTIONAL MATCH (run)-[:HAS_TOOL_CALL]->(:ToolCall)-[:PRODUCED_EVIDENCE]->(e:Evidence) WHERE e.id IN $ev
RETURN seen, collect(DISTINCT e.id)
```
With `$ev = ['e1']`, the result is `[[], []]` for `$ids` in `[]`, `['zz']` and even `['n1']` (where `seen = ['n1']`, and evidence is still `[]`).
**Expected:** evidence = `['e1']`. The second OPTIONAL MATCH alone returns `['e1']`, and so does the same query with pattern comprehensions.
Simple single-hop variants do not reproduce it; the multi-hop pattern through an anonymous intermediate node after the aggregating WITH does.
