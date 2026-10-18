# Temporal functions return silently wrong values (6.0.2): `{epochMillis}`, `{milliseconds}`, unknown map keys, Sunday's `dayOfWeek`

**Status:** known upstream ([FalkorDB#3295](https://github.com/FalkorDB/FalkorDB/issues/3295) and [FalkorDB#2936](https://github.com/FalkorDB/FalkorDB/issues/2936)); not refiled.

Found on 2026-10-17 while building change-freeze windows (Faultline's Q-PRE-FREEZE). Verified on the pinned 6.0.2
digest (smoke row 28, the "Engine depth" section of docs/FALKORDB_COMPAT.md).

```cypher
RETURN toString(localdatetime({epochMillis: 1792224000000}));   // got 1970-01-01T00:00:00 (expected 2026-10-18T…); also {epochSeconds: …}
RETURN toString(localdatetime({year: 2026, month: 10, day: 18, bogus: 1}));   // accepted; the unknown key is ignored
RETURN toString(duration({milliseconds: 90000}));              // got PT0S (expected PT1M30S)
WITH localdatetime('2026-10-18T12:00:00') AS t                   // 2026-10-18 is a Sunday
RETURN t.dayOfWeek, t.weekDay;                                    // got 0, 7 (openCypher dayOfWeek: Monday 1 … Sunday 7)
```

What works (and what we use): `localdatetime('1970-01-01T00:00:00') + duration({seconds: toInteger($ms / 1000) + offset})`,
then `.hour`, `.minute`, and `.dayOfWeek` read with `CASE WHEN d = 0 THEN 7 ELSE d END`.

**Missing** (each errors, which is fine, but worth listing in the docs): `datetime()`, `time()`, `datetime - datetime`,
`duration.between`, `duration.inSeconds`, `date.truncate`, `.epochMillis` / `.epochSeconds` accessors,
`toInteger(datetime)`, `date(localdatetime)`, `localtime(localdatetime)`, `duration * n`.

**Requests.**
1. `localdatetime({epochMillis | epochSeconds})` and `duration({milliseconds})` should compute the value (or error), never
   return a zero value.
2. An unknown key in a temporal map should be an error.
3. `.dayOfWeek` should follow openCypher (Sunday = 7), or the docs should say it is 0-based on Sunday.

**Impact for Faultline:** none shipped. Q-PRE-FREEZE uses only the working form above and normalises Sunday; epoch
milliseconds stay the stored truth everywhere; `tests/preflight/test_freeze.py` covers Friday, Saturday, Sunday and the
Monday 09:00 boundary.
