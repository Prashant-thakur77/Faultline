/**
 * Which FalkorDB procedures a Cypher template calls, read from the template's own Cypher text (never a hand-kept
 * map: the names and casing live in the templates and in backend/faultline/graph/algo/registry.py).
 *
 *   algosOf("MATCH … CALL algo.BFS(s, 8, 'PROPAGATES_TO') YIELD nodes …")   → ["algo.BFS"]
 *   algosOf("CALL db.idx.vector.queryNodes(…)")                              → ["db.idx.vector.queryNodes"]
 *
 * Order of first appearance, de-duplicated. Comments (`//` lines) are ignored.
 */
const PROC = /\bCALL\s+((?:algo|db\.idx)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\s*\(/gi;

export function algosOf(cypher: string | null | undefined): string[] {
  if (!cypher) return [];
  const text = cypher
    .split("\n")
    .filter((l) => !l.trim().startsWith("//"))
    .join("\n");
  const out: string[] = [];
  for (const m of text.matchAll(PROC)) {
    if (!out.includes(m[1])) out.push(m[1]);
  }
  return out;
}

/** "Q-ORG-WHO+Q-ORG-KNOWS" → ["Q-ORG-WHO", "Q-ORG-KNOWS"]; blanks dropped. */
export function templateIds(template: string | null | undefined): string[] {
  return (template ?? "")
    .split("+")
    .map((s) => s.trim())
    .filter(Boolean);
}
