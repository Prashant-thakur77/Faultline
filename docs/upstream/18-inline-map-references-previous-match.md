# A node's inline property map that references a variable from the previous MATCH: error with an index, empty without (6.0.2)

Found 2026-10-13 while writing the learned-edge approval (M15 #4). Verified on the pinned 6.0.2 digest only.

```cypher
CREATE (:Node {id:'a'}), (:P {id:'p1', src:'a'});

// A: expected [['a']]; got [] (no index on :Node(id)), silently
MATCH (p:P {id:'p1'}) MATCH (a:Node {id: p.src}) RETURN a.id;

// after CREATE INDEX FOR (n:Node) ON (n.id): the same query fails with "Variable p not found"

// B: correct in both cases
MATCH (p:P {id:'p1'}) MATCH (a:Node) WHERE a.id = p.src RETURN a.id;
// C: correct in both cases (a WITH between the clauses)
MATCH (p:P {id:'p1'}) WITH p MATCH (a:Node {id: p.src}) RETURN a.id;
```

**Impact for Faultline:** none shipped: the one query that had the shape (the learned-edge approval) was caught by its
first run and uses the WHERE form. A template-lint rule rejects an inline map that reads a variable's property when the
clause before it is a MATCH (`graph/templates/__init__.py`); the forms after WITH, UNWIND or inside CALL subqueries are
correct and allowed.
