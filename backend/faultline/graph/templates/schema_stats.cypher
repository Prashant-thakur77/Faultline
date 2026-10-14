// id: Q-SCHEMA-1
// purpose: schema introspection: node counts per label, edge counts per relationship type and totals, from the engine's own statistics (db.meta.stats, O(1); a 0 count = a type registered by an index or a deleted edge)
// returns: single-row
CALL db.meta.stats() YIELD labels, relTypes, nodeCount, relCount, propertyKeyCount
RETURN labels, relTypes, nodeCount, relCount, propertyKeyCount
LIMIT 1
