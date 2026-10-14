# Faultline UI

Next.js 16 + React 19 + Tailwind 4 + `@xyflow/react` 12. It renders only what the Faultline API v2
returns (contract: `../docs/API.md`). There is no sample data: when the API or FalkorDB is unavailable,
a red banner says so.

```bash
npm install
npm run dev            # http://localhost:3000, API at http://localhost:8400
npm run lint && npm run build
npm test               # component tests (vitest + happy-dom + Testing Library; only fetch is stubbed)
npm run evals:summary  # copy the eval numbers the UI quotes into public/evals/summary.json (after make results)
```

| Env var | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_FAULTLINE_API_URL` | `http://localhost:8400` | API base URL |
| `NEXT_PUBLIC_FAULTLINE_TENANT` | `acme` | default tenant; the top-bar switch (or `?tenant=`) changes it for every call |

## Screens
- Top bar: a tenant switch (`GET /api/tenants`) with an isolation badge ("graph: tenant_<t> · isolated", with the
  last eval's S7 isolation counts). Every page and API call follows the chosen tenant (`src/lib/tenant.ts`).
- `/`: scenario launcher (`GET /api/scenarios`, `POST /api/scenarios/{id}/run`) and recent incidents.
- `/incidents/[id]`: incident room. The left column is the stage timeline (SSE). The centre is the graph
  view plus a text alternative of the chains. The right column holds suspects, the gate checklist G1–G8
  (rejections first), the root cause (proven solid, inferred dashed) and the evidence table. Suspects have a
  "Faultline (gate) / Naive recency" toggle (`GET /incidents/{id}/contrast`). The plan card has Approve and
  Reject (with a reason; `POST /incidents/{id}/reject`), and an "Obligations at risk" card shows the obligation clock.
- `/memory`: recall (similarity, recency, salience), incident families, derived runbooks with support and
  DERIVED_FROM postmortems, and cold vs warm from the last eval (`GET /api/memory/overview`).
- `/brain`: ask box plus the decision tracer, ownership map and guardrails widgets (`GET /api/brain/*`).
- Cypher panel (dialog): opened from any gate check, evidence id, tool call template or graph node. It
  shows the template, the exact Cypher, params (marked recorded / derived / missing), PROFILE and a
  read-only re-run.

## Layout
`src/lib/layout.ts` is a deterministic layered layout computed from `/api/graph` edges. It has no
randomness or force simulation, so every load looks identical. Changes sit in a left lane next to the
node they changed. The service band is drawn above the data band.

## Static replay site (GitHub Pages)
`npm run build:pages` exports a backend-free site into `out-pages/`: a landing page (`/`), `/replay/`
and one page per recording in `public/replay/` (`/replay/s1-hero/`, `/replay/s2-data-incident/`). It
calls no API: the top bar says "Static replay site", the Cypher panel shows the recorded query and
params with PROFILE and Re-run switched off, and `/brain`, `/explore`, `/preflight` and the incident
room render a "needs the live backend" page (unknown deep links get a 404 that says the same).

| Env var | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_BASE_PATH` | `/Faultline` | project-site prefix; `""` for a user site or custom domain |
| `NEXT_PUBLIC_FAULTLINE_REPO_URL` | unset | optional source link on the landing page |

```bash
npm run build:pages
# preview under the same sub-path GitHub Pages uses
mkdir -p ../tmp/pages && ln -sfn "$PWD/out-pages" ../tmp/pages/Faultline
python3 -m http.server 8765 --directory ../tmp/pages   # open http://127.0.0.1:8765/Faultline/
```

`next build` always writes scratch files to `<project>/.next/`, so the script builds from a staging
project dir `.pages-build/` (src and public symlinked, configs copied) and never touches the live
build's `.next/`. It fails if a bundle or page is missing, if a page loads assets outside the base
path or if any page references the API. `.github/workflows/pages.yml` runs it on push to `main` with
`NEXT_PUBLIC_BASE_PATH=/<repo>` and deploys with `actions/deploy-pages` (Settings → Pages → Source:
GitHub Actions). Refresh the bundles with `npm run replay:export` before building.
