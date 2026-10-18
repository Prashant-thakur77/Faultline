// id: Q-TOPO-EPOCHS
// purpose: versioned topology: every distinct time a call was introduced (valid_from), oldest first; the as-of reads that need a whole-graph algorithm (algo.maxFlow cannot filter edges by time) build one GRAPH.COPY branch per epoch between these
// seen: at
MATCH ()-[r:PROPAGATES_TO]->()
WHERE r.valid_from IS NOT NULL
RETURN DISTINCT r.valid_from AS at
ORDER BY at
LIMIT 100
