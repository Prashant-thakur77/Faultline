# Remote `LOAD CSV` and read-only users (6.0.2): reported privately

Found in the M20 FalkorDB depth pass (2026-10-17) and verified on the pinned 6.0.2 digest. Because it concerns what a
read-only user can make the engine do, it went to FalkorDB through their private vulnerability reporting on 2026-10-17,
not as a public issue. The reproduction is withheld here until FalkorDB has responded.

**What Faultline does about it.** Production puts FalkorDB on an `internal: true` Docker network
(`deploy/docker-compose.prod.yml`), so the engine has no route to the internet; `scripts/egress_check.py --docker` and
`tests/live/test_egress.py` check that. Guarded text2cypher also refuses `LOAD`, and the read templates are linted.
