# Live deployment runbook

**Deployed:** [https://13-203-185-119.sslip.io](https://13-203-185-119.sslip.io) (MCP at `/mcp`). One EC2 `t3.medium` (2 vCPU, 4 GB, 30 GB gp3, encrypted) in `ap-south-1`, an Elastic IP, a security group with 80/443 open and SSH from the owner's address only. The hostname is the free `sslip.io` name for the IP; Caddy gets a real certificate for it. <!-- noclaim: instance size and disk -->

**Two lessons from the first deploy:**
- A new AWS account may not be allowed Lightsail's 4 GB plan ("can not create an instance using this Lightsail plan size"); a `t3.medium` is the same size on EC2.
- `docker compose exec` reads standard input: in a script piped over `ssh … 'bash -s'`, give every `exec` `</dev/null`, or it swallows the rest of the script.


**Shape.** One small VM runs Docker Compose with:
- FalkorDB, pinned by digest and never published;
- the API;
- MCP over HTTP;
- the UI;
- Caddy, which handles TLS.

**Cost and safety defaults:**
- **Keyless.** The investigator is deterministic and GitHub is simulated, so a public visitor can never spend money or touch a real repo.
- **Real GitHub** needs both `FAULTLINE_GITHUB=real` and `FAULTLINE_APPROVER_KEY`. Without the key, approve returns 503/403.
- **Public mode** (`FAULTLINE_PUBLIC=true` in the prod compose): run tokens on choose/approve; forget and preflight run on clean-room copies; no anonymous LLM. See [SECURITY.md](../SECURITY.md).
- **Rate limits** are per visitor (the API trusts Caddy's `X-Forwarded-For`) plus global caps. MCP allows 30 calls per minute per key.
- **No LLM spend.** The live LLM is off unless `ANTHROPIC_API_KEY` is set, and the public demo leaves it unset.

**Steps:**
1. Create the VM (2 vCPU, 4 GB RAM is enough; add a 4 GB swap file so the UI image builds next to the engine). Open ports 80/443; SSH from your address only. Set `FALKORDB_MAXMEMORY=2000mb` and `FALKORDB_MEM_LIMIT=2560m` on a 4 GB host (the seeded tenants use well under 100 MB).
2. Point a DNS A record at the VM and set `FAULTLINE_DOMAIN`.
3. On the VM, put the secrets in `.env` (never committed):
   - `FALKORDB_ENGINE_PASSWORD` and `FALKORDB_RO_PASSWORD`;
   - `FAULTLINE_MCP_KEYS` (one judge key → acme);
   - optionally `FAULTLINE_PREFLIGHT_KEY`.
4. Render the ACL: `python scripts/render_acl.py > deploy/users.acl`.
5. Start the stack: `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build`.
6. Seed: `docker compose … exec api /app/.venv/bin/python scripts/seed.py --tenant all`. Seed `--no-memory` as well if evals will run there.
7. Smoke from outside:
   - `curl https://$FAULTLINE_DOMAIN/api/status`;
   - the UI loads and shows the engine tag;
   - run S1 → approve → RESOLVED;
   - Re-arm works.
8. MCP check: `claude mcp add --transport http faultline https://$FAULTLINE_DOMAIN/mcp --header "Authorization: Bearer <key>"`.

**Base images** are pinned by digest: python:3.12-slim, node:20-slim and caddy:2.8.4, resolved with `docker buildx imagetools inspect` on 2026-10-13. Re-resolve them when bumping a tag.
