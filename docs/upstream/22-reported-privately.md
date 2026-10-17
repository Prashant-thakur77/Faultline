# Engine finding 22: reported privately to FalkorDB (2026-10-17)

Found in the M20 FalkorDB depth pass (2026-10-17) and verified on the pinned 6.0.2 digest. It went to FalkorDB through
their private vulnerability reporting on 2026-10-17, not as a public issue; details are withheld until they respond.

**Defence in depth in Faultline.** Production puts FalkorDB on an `internal: true` Docker network
(`deploy/docker-compose.prod.yml`), so the engine has no route to the internet; `scripts/egress_check.py --docker` and
`tests/live/test_egress.py` check that.
