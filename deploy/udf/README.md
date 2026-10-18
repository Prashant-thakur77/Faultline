# FalkorDB UDF libraries loaded by Faultline

| library | file | source | sha256 | license |
|---|---|---|---|---|
| `faultline` | `faultline-1.0.0.js` | ours (this repo) | `55cd126a097dbea6e402b297c3ace79f827cb68a9455784c5bdbf09a0354ee7f` | Apache-2.0, as the rest of this repo |
| `flex` | `flex-1.0.1.js` | FalkorDB FLEX release `1.0.1` (https://github.com/FalkorDB/flex/releases/tag/1.0.1, asset `flex.js`) | `e7e833ba87f88c1e31913b58bb9bdeab231714f8af4b43b437d84277ee653ece` | MIT, as declared by the upstream README (© FalkorDB Ltd.) |

`scripts/configure_falkordb.py` loads each library with `GRAPH.UDF LOAD REPLACE` (engine user) after verifying the
sha256 above, and fails loudly on a mismatch. Templates call FLEX functions inside `GRAPH.RO_QUERY`
(`flex.text.jaroWinkler`, `flex.sim.jaccard`); the bundle was inspected before vendoring (pure functions; no network,
`require`, `eval` or `Function`). It is unmodified.

`faultline` is our own library: the arithmetic that turns graph facts into a ranking (`faultline.tierWeight`,
`faultline.impact`, `faultline.capImpact`, `faultline.noteScore`, `faultline.round4`). `blast_radius` (`Q-BLAST-3`),
`notify_set` (`Q-NOTIFY-2`) and `recall_notes` (`Q-NOTE-RECALL`) return rows scored and ordered by FalkorDB with it;
`find_entities` (`Q-FIND-HYBRID`) and `search_knowledge` (`Q-KNOW-1`) use `faultline.round4` for their scores. It holds
pure functions over numbers (no graph access, network, `require`, `eval` or `Function`; `tests/graph/test_udf_status.py`
checks), and the weights arrive as query parameters from `backend/faultline/agent/weights.yaml`. When the file changes,
its sha256 in `backend/faultline/graph/udf.py` and in the table above must change with it, or loading fails loudly.
