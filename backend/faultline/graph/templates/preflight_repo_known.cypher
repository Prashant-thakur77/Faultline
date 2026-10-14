// id: Q-PRE-REPO
// purpose: is this repository known to the tenant graph (a Repo node by id or url, or a PR already ingested from it)? An unkeyed preflight may fetch only such repos, so a visitor cannot make the server read arbitrary repos with the operator's GitHub auth
// returns: single-row
MATCH (n:Node)
WHERE (n:Repo AND (n.id = $repo OR n.url ENDS WITH $suffix)) OR (n:PR AND n.repo = $repo)
RETURN count(n) > 0 AS known
LIMIT 1
