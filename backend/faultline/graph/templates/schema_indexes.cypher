// id: Q-SCHEMA-4
// purpose: schema introspection: the indexes on each label (range / full-text / vector per property) and their status (db.indexes)
CALL db.indexes() YIELD label, properties, types, entitytype, status
RETURN label, properties, types, entitytype, status
ORDER BY entitytype, label
LIMIT 100
