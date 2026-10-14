# Accessibility

Faultline's UI is audited with axe-core plus scripted keyboard checks. The audit is reproducible:

```bash
# backend on :8400, production UI on :3100 (npm run build && npx next start -p 3100),
# and the static Pages export built (npm run build:pages)
.venv/bin/python frontend/scripts/a11y_audit.py [--ui http://localhost:3100] [--api http://localhost:8400] \
    [--static-only | --live-only] [--chromium PATH]
```

The script writes `frontend/test-results/a11y/a11y.json` (every violation with its nodes and the keyboard results) and prints a table. It exits 1 if any serious or critical violation remains or a keyboard check fails, and 2 if the API or UI is unreachable. It fails loudly and never skips a page silently.

## Tool and rules

- **axe-core 4.14.0**: pinned as a devDependency in `frontend/package.json` and injected into each page from `node_modules/axe-core/axe.min.js`.
- **Rule tags:** `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` and `best-practice`. This includes WCAG 2.2 target size (2.5.8) and label-in-name (2.5.3). <!-- noclaim: WCAG version -->
- **Browser:** Playwright (Python, from `.venv`) driving Chromium headless shell 1243, with a 1440×900 viewport.
- **Colour modes:** the UI is dark-only (`<html class="dark">`; there is no light theme), so contrast was checked in dark mode only.

## Pages audited

The live UI was audited against the real backend, with no mocks.

| # | Page / state |
|---|---|
| 1 | `/`: home and scenario launcher |
| 2 | `/`: the "Reset demo data (all visitors)" confirm step (cancelled with Escape; nothing is reset) |
| 3 | `/incidents/<id>`: S1 started with `POST /api/scenarios/S1/run`, audited at AWAITING_APPROVAL |
| 4 | The same room in the plan/approval state: the first offered option chosen and the exact action rendered. It is never approved, so no PR is opened. |
| 5 | The Cypher panel (dialog) opened from a gate check |
| 6 | `/brain` after one question |
| 7 | `/brain` after a forget dry run (read-only; never executed by the audit) |
| 8 | `/preflight` after the S6 example |
| 9 | `/explore` |
| 10 | `/replay` (index) |
| 11 | `/replay/s1-hero`, played to the end at 8× |
| 12 | 404 page |

The static GitHub Pages export (`npm run build:pages`) was served locally under `/Faultline` with no backend:

| # | Page |
|---|---|
| 13 | landing |
| 14 | `/replay/` |
| 15 | `/replay/s1-hero/`, played to the end |
| 16 | `/replay/s2-data-incident/`, played to the end |

States 2 and 7 were added with the Reset-confirm and Forget features, so they have no "before" numbers.

## Results

Counts are axe nodes (elements) per impact, summed over all audited states. The "before" run had 14 states; the "after" run has 16.

| Impact | Before | After |
|---|---|---|
| critical | 0 | **0** |
| serious | 489 | **0** |
| moderate | 2 | **0** |
| minor | 0 | **0** |

The before counts by rule:

| Rule | Impact | Nodes before | Where |
|---|---|---|---|
| `target-size` (2.5.8) | serious | 341 | small inline buttons: template chips (`Q-…`), evidence ids, evidence chips, mechanism-chain chips. They appear in the incident room, replay (live and Pages) and preflight. |
| `label-content-name-mismatch` (2.5.3) | serious | 116 | gate-check rows, "Rejected by …" buttons, the G8 decision card, Explore's "Focus" buttons, the replay "Play again" button |
| `color-contrast` (1.4.3) | serious | 31 | the white-on-red-500 "CAUSE" badge (3.8:1); the white-on-emerald-600 Approve button (3.65:1); zinc-500 tier text in Explore (3.67:1) |
| `scrollable-region-focusable` | serious | 1 | the scrollable Cypher `<pre>` in the Cypher panel |
| `landmark-no-duplicate-banner`, `landmark-unique` | moderate | 1 + 1 | the Cypher dialog's `<header>` became a second page banner |

The keyboard checks ran on the incident room in the plan state.

| Check | Before | After |
|---|---|---|
| Tab from the top of the incident room reaches "Approve this exact action" | pass | **pass** (157 Tab stops) |
| Every Tab stop shows a visible focus indicator | **fail**: graph nodes had no focus outline | **pass** |
| Enter on a gate check opens the Cypher panel, focus moves inside | pass | **pass** |
| Tab stays inside the Cypher panel, with visible focus | fail as measured; see note | **pass** |
| Escape closes the panel and returns focus to the trigger | pass | **pass** |

Note on the focus-trap row. Base UI's dialog did trap focus before the fix. The first version of the check read `document.activeElement` before Base UI's focus guard had moved focus back into the dialog, so it reported a false failure. The script now waits 150 ms after each Tab. It also measures focus rings strictly: a box-shadow layer only counts if it is non-transparent and non-zero, and the check waits for the 150 ms ring transition. That stricter check is what found the real graph-node problem.

## M13 re-audit: reject, tenant switch, naive vs Faultline, Memory tab, Brain widgets (2026-10-13)

The new UI was audited with the same script against the real backend (no mocks): a production build of the UI and a backend run from the same tree. Six new states were added to the audit:

| # | Page / state |
|---|---|
| 13 | The incident room with the suspects card switched to the **Naive recency** lens |
| 14 | The plan card with the **Reject** form open and a reason typed |
| 15 | The plan card **after the rejection** (the option disabled, who and why shown). Only this S1 run's own graph copy changes; nothing is approved |
| 16 | `/memory?incident=<the S1 incident>`: recall, families, derived runbooks, cold vs warm |
| 17 | `/brain?tenant=globex`: the Brain widgets on the other tenant's graph (the top-bar tenant switch and isolation badge are on every live page) |
| 18 | `/memory/` on the static Pages export (cold vs warm only, from the eval summary) |

**axe-core 4.14.0, 22 states (17 live + 5 static): 0 critical, 0 serious, 0 moderate, 0 minor.** All five keyboard checks pass; Tab now reaches "Approve this exact action" after 225 stops (the suspects lens and the reject control add stops before it).

Accessibility choices in the new parts:

- **Reject.** "Reject…" sits next to "Approve this exact action" and is a disclosure button (`aria-expanded`, `aria-controls`). Opening it moves focus into a labelled reason field (required, `aria-invalid` under 3 characters, with a hint saying what is recorded). Escape or Cancel closes it and returns focus to "Reject…". "Confirm reject" stays disabled until there is a reason and an approver. Errors (409 stale plan, 422 reason or approver, 403) are `role="alert"` with the cause in words. Success is a `role="status"` line. A rejected option shows a thumbs-down icon and the text "rejected by <person>", plus the reason, so status is not colour-only.
- **Naive vs Faultline.** Two toggle buttons (`aria-pressed`) in a labelled group. The comparison is a captioned table (change, what it changed, time before onset, pageRank, gate verdict with icon and text), and the agree/disagree line is a `role="status"`.
- **Tenant switch.** A labelled `<select>` filled from `GET /api/tenants`. The isolation badge has an icon and the text "graph: tenant_<t> · isolated"; its tooltip text (S7 test counts) is also in visually hidden text.
- **Memory tab and Brain widgets.** Every section is a labelled region with an `h2`. Tables have captions. Each bar in the cold-vs-warm chart is `aria-hidden` and has its value printed next to it. Component and incident chips are toggle buttons (`aria-pressed`) with 24 px targets. Expandable groups use `aria-expanded`. Results that load after a choice land in polite live regions.

### Lighthouse

Lighthouse 12.8.2 (pinned with `npx -y lighthouse@12.8.2`; Lighthouse 13 needs Node ≥ 22.19 and this machine has Node 20.19) ran headless against Playwright's Chromium 1243, accessibility category only, on the same production UI and backend: <!-- noclaim: tool and Node versions -->

| Page | Accessibility score |
|---|---|
| `/incidents/<S1 incident>` at AWAITING_APPROVAL (the incident room) | **100** |
| `/` (home) | **100** |
| `/memory?incident=<S1 incident>` | **100** |
| `/brain` (acme) | **100** |
| `/brain?tenant=globex` | **100** |
| `/preflight` | **100** |
| `/explore` | **100** |
| `/replay/s1-hero` | **100** |

No binary accessibility audit failed on any page. This meets our accessibility bar for the incident room. These are UI audit results from the runs described here, not eval results. Command (one page):

```bash
CHROME_PATH=~/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome npx -y lighthouse@12.8.2 \
  "http://localhost:3100/incidents/<id>?tenant=acme" --only-categories=accessibility \
  --chrome-flags="--headless=new --no-sandbox" --output=json --output-path=lh.json
```

Lighthouse's accessibility score is a weighted subset of axe rules, so it adds little beyond the axe audit above. It is recorded because the plan asks for it.

### Component tests

`npm test` (vitest 4.1.11 with happy-dom 21.0.1 and Testing Library; pinned exact in `package.json`; vitest 5 needs Node 22) renders the real components with only `fetch` stubbed. 30 tests in 7 files cover:

- the reject flow: the reason is required, the exact plan hash is posted, 409 is an alert, Escape returns focus, and a rejected option shows who and why;
- the naive contrast: disagree, agree, tie and "nothing recorded";
- the decision tracer chain and head, the ownership history, and the guardrails grouping with a loud 503;
- the recall columns, derived runbooks with support, and cold vs warm copied verbatim (or "not in this eval");
- the tenant switch: list, navigation, failure; the isolation badge: isolated, switching, failing; tenant store precedence;
- the "G7 correlation" order and the neutral "not evaluable" state;
- the obligations card (urgent, unknown, not recorded).

## What was fixed

- **Target size.** Every small inline button now has a hit area at least 24 px tall (`inline-flex min-h-6 items-center`). This covers:
  - template chips in the timeline, hypotheses, containment, brain steps and preflight;
  - evidence-id buttons in the timeline, evidence and blast tables;
  - `EvidenceChip`;
  - mechanism-chain chips;
  - the Explore table's Cypher and Focus buttons.
- **Label in name (2.5.3).** Complex buttons no longer override their visible text with an `aria-label`. Their accessible name now comes from their content, plus visually hidden text:
  - gate rows read "G2 path: pass. Q-GATE-1 … Open the Cypher panel for Q-GATE-1.";
  - rejected-suspect buttons end with "Open the Cypher panel for G2 path.";
  - the G8 card reads "Decision ADR-012 violated …";
  - Explore buttons read "Focus the view on X" and "Cypher for X (Q-BLAST-1)";
  - the replay play button's name is its visible text.
- **Contrast.**
  - The CAUSE badge in the graph and its legend: red-500 became red-700 (white text, about 6.4:1).
  - The Approve button: emerald-600 became emerald-700.
  - Explore tier text: zinc-500 became zinc-400.
  - Diff line numbers: zinc-500 became zinc-400 (found once the plan state rendered a rollback diff).
  - The new gate legend separators use zinc-400.
- **Scrollable regions.** Every scrollable `<pre>` is focusable (`tabIndex=0`, `role="region"`, a label and a focus ring) so keyboard users can scroll it. This covers the Cypher text, the PROFILE output, the issue body and the PR description.
- **Landmarks.** The Cypher dialog's header is a `<div>`, not a second `<header>` banner.
- **Graph focus.** `@xyflow/react` ships `.react-flow__node.selectable:focus-visible { outline: none }` after our stylesheet. The node focus outline now uses a more specific selector (`.react-flow .react-flow__node.selectable:focus-visible`), so Tab-focused graph nodes show a sky-300 outline.
- **Reset confirm.** "Reset demo data (all visitors)":
  - asks before acting;
  - focuses "Reset now";
  - Escape or Cancel returns focus to the control;
  - focus also returns there after the reset finishes.
- **Announcements.** Stage announcements say stages in words ("Stage awaiting approval: …"), not raw ids.

## Keyboard and screen-reader notes

- **Skip link.** "Skip to content" is the first Tab stop and jumps to `<main id="main">`.
- **Live stage updates.**
  - The run timeline has a polite live region (`aria-live="polite" aria-atomic="true"`). It announces each new stage, gate run (passed or rejected, with its origin) and the run's end, from SSE.
  - In replay it announces each event as it plays.
  - After approval, the action path (execute → verify → write-back → final) is summarised in a second polite region.
  - The fix verdict and the final result use `role="status"`, or `role="alert"` for failures.
  - The API/FalkorDB failure banner is `role="alert"`.
- **Status is never colour-only.** Every status has colour, an icon and text:
  - gate checks show ✓ pass / ✗ fail / ! downgrade / – not evaluable (neutral; e.g. "G7 correlation" when it cannot be evaluated);
  - verdicts show APPLIED / NOT_APPLIED / UNKNOWN with distinct icons;
  - verification channels show ok / failed / unknown.
  - The header separates "Cause confirmed" from the fix verdict chip. The cause chip drops its green once the fix did not verify.
- **Text alternatives for the graphs.**
  - The proof path is listed in the "Causal chains (text alternative of the graph)" section (`ChainTable`). It has one captioned table per chain: the proof path, plus each rejected suspect's chain. Rows run change → hops → symptom, and each hop opens its Cypher.
  - The ripple view has the blast-radius table (`BlastTable`).
  - Each graph node has an accessible name (id, kind, role on the path, betweenness) and opens the Cypher panel with Enter.
  - The graph view announces mode changes and the path animation politely.
  - `/explore` renders the canvas graph (`@falkordb/canvas`) next to a full node table with Cypher and Focus buttons per node. The canvas itself is not accessible; the table is its text alternative.
- **Cypher panel.**
  - It is a modal dialog with a title and description.
  - Focus moves into it and is trapped there.
  - Escape closes it and returns focus to the opener.
  - Re-run and PROFILE results land in polite live regions.
- **Reduced motion.** With `prefers-reduced-motion: reduce`:
  - the path and ripple animations show their final, complete state;
  - replay playback is manual (step buttons and the slider), and the page says so.

## Known remaining issues

- **Automated coverage is partial.** axe finds only a subset of WCAG failures. No manual pass was done with a real screen reader (NVDA, JAWS, VoiceOver or Orca). The accessible names and live regions are verified only through Playwright's accessibility tree and axe.
- **Long Tab path.** Reaching "Approve this exact action" takes about 225 Tab stops, because every evidence and template chip is a stop. The only skip link goes to main content; there are no in-page skip links to the plan or gate sections. Screen-reader users can jump by heading or landmark, because every section is a labelled region with an `h2`.
- **The Explore canvas** (`@falkordb/canvas`, a `<canvas>`) cannot be inspected by axe or read by assistive technology. The node table next to it carries the same data.
- **Single theme.** The UI is dark-only, so a light theme was neither built nor audited.
- **Exempt low-contrast text.** Disabled or `aria-disabled` controls (e.g. "Anthropic (not configured)") keep low-contrast zinc-500 text. WCAG exempts inactive components; it is still not ideal.
- **The approver field** uses a `<datalist>` of the ranked Who-fixes-it people. Screen-reader support for `datalist` varies by browser; the free-text input still works on its own.
- **Audit side effects.** The live audit starts a real S1 run (a new clean-room graph and incident in the audit index) each time it runs. It rejects one option of that run, in that run's own graph copy. It never approves an action, executes a forget or resets the demo data.
- **Screenshots.** `frontend/scripts/screenshots.py` regenerates `docs/screenshots/` from the live UI (same backend, no mocks). It also starts an S1 run and rejects one option in that run's copy.
