// id: Q-RUNS-2
// purpose: find the run/graph that holds an incident (audit graph index)
// home: audit
// returns: single-row
MATCH (x:RunIndex {incident:$inc})
RETURN x.id AS run, x.graph AS graph, x.scenario AS scenario, x.outcome AS outcome, x.cause AS cause, x.investigator AS investigator
LIMIT 1
