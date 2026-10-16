import { describe, expect, it } from "vitest";
import { algosOf, templateIds } from "./templateAlgo";

describe("algosOf", () => {
  it("reads the procedures a template calls, in order, once each", () => {
    const q = `MATCH (s:Node {id:$id})
CALL algo.BFS(s, 8, 'PROPAGATES_TO') YIELD nodes
CALL algo.maxFlow({sourceNodes: [s]}) YIELD maxFlow
CALL algo.BFS(s, 2, 'X') YIELD nodes AS n2
RETURN nodes`;
    expect(algosOf(q)).toEqual(["algo.BFS", "algo.maxFlow"]);
  });

  it("keeps the template's own casing and reads index procedures", () => {
    expect(algosOf("CALL algo.HarmonicCentrality({}) YIELD node")).toEqual(["algo.HarmonicCentrality"]);
    expect(algosOf("call db.idx.vector.queryNodes('Incident', 'emb', 5, vecf32($v))")).toEqual([
      "db.idx.vector.queryNodes",
    ]);
  });

  it("returns nothing for plain Cypher, comments or no text", () => {
    expect(algosOf("MATCH (n) RETURN n LIMIT 5")).toEqual([]);
    expect(algosOf("// CALL algo.WCC(x)\nMATCH (n) RETURN n")).toEqual([]);
    expect(algosOf(null)).toEqual([]);
  });
});

describe("templateIds", () => {
  it("splits combined template ids", () => {
    expect(templateIds("Q-ORG-WHO+Q-ORG-KNOWS + Q-ORG-HARM")).toEqual(["Q-ORG-WHO", "Q-ORG-KNOWS", "Q-ORG-HARM"]);
    expect(templateIds(null)).toEqual([]);
  });
});
