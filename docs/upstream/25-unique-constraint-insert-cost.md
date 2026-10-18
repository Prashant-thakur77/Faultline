# Every insert under a UNIQUE constraint costs time proportional to the label's size (6.0.2): performance cliff

**Status:** known upstream as [FalkorDB#3330](https://github.com/FalkorDB/FalkorDB/issues/3330), fixed by #3334 after 6.0.2; not refiled.

Found building the engine-enforced invariants (2026-10-17): with a UNIQUE constraint on `:Node(id)` (a label every
node carries) the 1k-service scale world's seed timed out. Verified on the pinned 6.0.2 digest on a throwaway graph.

```cypher
// graph u: CREATE INDEX FOR (n:N) ON (n.id), then
//   GRAPH.CONSTRAINT CREATE u UNIQUE NODE N PROPERTIES 1 id     (wait for OPERATIONAL)
UNWIND range($lo, $lo + 999) AS i MERGE (n:N {id: i});        // run 20 times, $lo = 0, 1000, …, 19000
```

| Batch of 1,000 MERGEs | without the constraint | with UNIQUE (N) id |
|---|---|---|
| 1st (label empty) | about 0.007 s | about 0.13 s |
| 9th | about 0.003 s | about 1.6 s |
| 20th (19k nodes already) | about 0.005 s | about 5.2 s |

The cost per insert grows linearly with the label's size although the supporting exact-match range index exists (the
constraint refuses to be created without it). MANDATORY constraints cost nothing measurable in the same setup.

**Request.** Check uniqueness through the supporting index (one lookup per insert), or document the cost.

**Impact for Faultline:** UNIQUE is used only on small labels (`Run.id`, `Intent.idem`); `Node.id` is MANDATORY, not
UNIQUE. The constraint created by the first build of these invariants is retired and dropped automatically (`graph/constraints.py`
RETIRED); `tests/live/test_scale_smoke.py` seeds the 1k world with the final set.
