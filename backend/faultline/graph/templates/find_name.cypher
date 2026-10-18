// id: Q-FIND-NAME
// purpose: resolve a component from the words of its name or id ("shipping quote calculator" → quote, "valkey" → cache): every component scored by how many of the question's words ($words: word prefixes of at most 5 letters) begin a word of its name or id, in the engine; more words matched first, then the shorter name
// seen: id
MATCH (n:Node)
WHERE n:Service OR n:Datastore OR n:Table OR n:KPI OR n:Transform OR n:Dashboard
WITH n, [t IN split(replace(replace(replace(replace(replace(replace(toLower(coalesce(n.name, '') + ' ' + n.id), '-', ' '), '.', ' '), '_', ' '), '(', ' '), ')', ' '), '/', ' '), ' ') WHERE t <> ''] AS words
WITH n, words, size([w IN $words WHERE any(t IN words WHERE t STARTS WITH w)]) AS matched
WHERE matched > 0
RETURN n.id AS id, [x IN labels(n) WHERE x <> 'Node'][0] AS label, coalesce(n.name, n.id) AS name, matched,
       size(words) AS words, 'name' AS via
ORDER BY matched DESC, words, id
LIMIT 5
