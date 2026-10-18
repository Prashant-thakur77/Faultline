# Unanchored pattern comprehension returns [] (6.0.2): compat note

**Status:** withdrawn: not reproduced on a fresh 6.0.2 graph. Kept as a compatibility note.

`MATCH (inc:Incident) RETURN [(it:Intent)-[:EXECUTED]->(a:Action {id:$aid}) | it.state]` returns `[]` for every row, even though the pattern exists. That is, a comprehension whose pattern does not reference any variable bound outside it. Neo4j evaluates such comprehensions against the whole graph. Either behaviour is defensible, but the docs should say which, and ideally it should be an error rather than a silent empty list. Faultline only uses comprehensions anchored on an outer variable.
