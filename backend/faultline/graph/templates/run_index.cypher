// id: Q-RUNS-1
// purpose: recent runs from the audit graph index (which graph holds which incident)
MATCH (x:RunIndex)
RETURN x.id AS run, x.incident AS incident, x.graph AS graph, x.scenario AS scenario, x.investigator AS investigator,
       x.outcome AS outcome, x.cause AS cause, x.started_at AS started_at, x.updated_at AS updated_at
ORDER BY started_at DESC, run
LIMIT 50
