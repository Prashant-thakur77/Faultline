// id: Q-SESS-1
// purpose: persistent session history (T2): a user's recent turns across sessions, newest session first
// seen: session
MATCH (s:Session {user:$user})-[:HAS_TURN]->(t:Turn)
RETURN s.id AS session, t.seq AS seq, t.role AS role, t.text AS text, t.at AS at, t.refs AS refs
ORDER BY at DESC, session, seq DESC
LIMIT 40
