// id: Q-FUNCS
// purpose: the engine function catalogue (dbms.functions), split into built-ins and UDFs; guarded text2cypher builds its function allow-list from it (graph/guard.py)
// returns: single-row
CALL dbms.functions() YIELD name, udf
WITH collect(CASE WHEN udf THEN null ELSE name END) AS builtin, collect(CASE WHEN udf THEN name END) AS udfs
RETURN builtin, udfs, size(builtin) + size(udfs) AS total
LIMIT 1
