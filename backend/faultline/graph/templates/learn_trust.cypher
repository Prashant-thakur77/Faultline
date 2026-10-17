// id: Q-LEARN-TRUST
// purpose: learning trust (M21): whether an incident is trusted (page_external, set at run start: off the public demo, a keyed run or a keyed alert); an anonymous public-demo run is not, and nothing its holder does is learned
// returns: single-row
// seen: id
MATCH (i:Incident {id: $inc})
RETURN i.id AS id, coalesce(i.page_external, false) AS trusted, i.stage AS stage
LIMIT 1
