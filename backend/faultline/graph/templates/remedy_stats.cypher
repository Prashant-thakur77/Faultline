// id: Q-REM-1
// purpose: learned remediation ordering: past incidents that share a Symptom with $inc (or are listed in $incidents), and how each fix kind fared on them: successes (RESOLVED_BY an APPLIED action), failures (a NOT_APPLIED action), Beta(1,1)-smoothed success rate (s+1)/(s+f+2). Per kind (target '*') and per flag for flip_flag; UNKNOWN verdicts count as neither
// seen: incidents
MATCH (p:Incident)
WHERE p.id <> $inc AND (p.id IN $incidents OR size([(p)-[:HAS_SYMPTOM]->(y:Symptom) WHERE y.id IN $symptoms | y.id]) > 0)
MATCH (p)-[r:RESOLVED_BY|ATTEMPTED]->(a:Action)
WHERE (type(r) = 'RESOLVED_BY' AND a.verdict = 'APPLIED') OR a.verdict = 'NOT_APPLIED'
WITH p, a, CASE WHEN type(r) = 'RESOLVED_BY' AND a.verdict = 'APPLIED' THEN 1 ELSE 0 END AS ok
UNWIND (CASE WHEN a.kind = 'flip_flag' THEN ['*', a.target_id] ELSE ['*'] END) AS target
WITH a.kind AS kind, target, toInteger(sum(ok)) AS successes, toInteger(sum(1 - ok)) AS failures, collect(DISTINCT p.id) AS incidents
RETURN kind, target, successes, failures, successes + failures AS n,
       (toFloat(successes) + 1.0) / (toFloat(successes + failures) + 2.0) AS rate,
       size(incidents) AS incident_count, incidents[0..20] AS incidents
ORDER BY rate DESC, n DESC, kind, target
LIMIT 50
