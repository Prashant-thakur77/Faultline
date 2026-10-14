# FalkorDB UDF libraries loaded by Faultline

| library | file | source | sha256 | license |
|---|---|---|---|---|
| `flex` | `flex-1.0.1.js` | FalkorDB FLEX release `1.0.1` (https://github.com/FalkorDB/flex/releases/tag/1.0.1, asset `flex.js`) | `e7e833ba87f88c1e31913b58bb9bdeab231714f8af4b43b437d84277ee653ece` | MIT, as declared by the upstream README (© FalkorDB Ltd.) |

`scripts/configure_falkordb.py` loads each library with `GRAPH.UDF LOAD REPLACE` (engine user) after verifying the
sha256 above, and fails loudly on a mismatch. Templates call FLEX functions inside `GRAPH.RO_QUERY`
(`flex.text.jaroWinkler`, `flex.sim.jaccard`); the bundle was inspected before vendoring (pure functions; no network,
`require`, `eval` or `Function`). It is unmodified.
