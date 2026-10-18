# A MATCH whose WHERE holds a pattern comprehension, followed by another MATCH, drops the row (6.0.2): silent wrong result

**Status:** posted [as new evidence on FalkorDB#2502](https://github.com/FalkorDB/FalkorDB/issues/2502#issuecomment-6237945777).

Found writing the on-call escalation write (`W_PAGE_ESCALATE`): it returned nothing while every part of it, run
alone, returned the expected rows. Verified on the pinned 6.0.2 digest only (docs/FALKORDB_COMPAT.md).

```cypher
CREATE (:N {id:'a'}), (:P {id:'p'});

// A: expected [['a', 'p']]; got []
MATCH (n:N {id:'a'}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0 MATCH (p:P {id:'p'}) RETURN n.id, p.id;

// correct variants
MATCH (n:N {id:'a'}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0 RETURN n.id;                 // B: [['a']] (no second MATCH)
MATCH (p:P {id:'p'}) MATCH (n:N {id:'a'}) WHERE size([(n)<-[:R]-(x:X) | x]) = 0
RETURN n.id, p.id;                                                                       // C: the other MATCH first
MATCH (n:N {id:'a'}) WITH n, size([(n)<-[:R]-(x:X) | x]) AS k WHERE k = 0
MATCH (p:P {id:'p'}) RETURN n.id, p.id;                                                  // E: the comprehension in a WITH
MATCH (n:N {id:'a'}) WHERE n.id = 'a' MATCH (p:P {id:'p'}) RETURN n.id, p.id;            // D: no comprehension
```

Plan of A: `Project ← Node By Label Scan (p:P) ← Apply(Filter ← Label Scan (n:N), Filter ← Aggregate ← Conditional
Traverse ← Argument)`: the second MATCH's scan is placed above the Apply with no Cartesian Product, and the row is lost.

**Impact for Faultline:** none shipped. `W_PAGE_ESCALATE` uses form C (both MATCHes first, the comprehensions in a
WITH), with a comment. The template lint now refuses the pattern in any read template (a MATCH clause whose WHERE holds a
pattern comprehension, directly followed by another MATCH).
