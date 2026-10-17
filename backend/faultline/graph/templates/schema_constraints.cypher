// id: Q-SCHEMA-5
// purpose: schema introspection: the engine-enforced constraints on the graph (db.constraints: UNIQUE and MANDATORY per label or relationship type, their properties and status, OPERATIONAL once built), the invariants FalkorDB itself refuses to break (graph/constraints.py)
CALL db.constraints() YIELD type, label, properties, entitytype, status
RETURN type, label, properties, entitytype, status
ORDER BY entitytype, label, type
LIMIT 100
