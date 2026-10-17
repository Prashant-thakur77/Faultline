// id: Q-LLM-SPEND
// purpose: live-LLM spend in the last hour on the global ledger (LlmSpend rows: settled cost, or the reserved estimate while a run or question is in flight); the demo turns replay-only past the budget
// home: audit
// returns: single-row
MATCH (x:LlmSpend)
WHERE coalesce(x.spent_at, x.reserved_at) >= $since
RETURN coalesce(sum(CASE WHEN x.usd IS NULL THEN x.reserved_usd ELSE x.usd END), 0.0) AS usd,
       coalesce(sum(CASE WHEN x.usd IS NULL THEN x.reserved_usd ELSE 0.0 END), 0.0) AS reserved,
       count(x) AS runs
LIMIT 1
