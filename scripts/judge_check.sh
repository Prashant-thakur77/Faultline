#!/usr/bin/env bash
# `make judge-check`: deterministic, keyless proof path for judges.
# Needs Docker + uv + Node. NO Anthropic key, NO GitHub token, no remote touched. Starts the pinned
# FalkorDB, runs the engine smoke suite, seeds the tenant graphs, runs unit + live graph tests and
# the data scenarios end to end with the deterministic investigator, then restores the incident fixture.
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=backend

pass=0; fail=0
declare -a LINES
step() { # step <label> <detail> <PASS|FAIL>
  if [ "$3" = "PASS" ]; then pass=$((pass+1)); else fail=$((fail+1)); fi
  LINES+=("$(printf '  %-30s %s  %s' "$1" "$3" "$2")")
}
junit() { # junit <file> → "<passed>/<total>"
  uv run python - "$1" <<'PY'
import sys, xml.etree.ElementTree as ET
r = ET.parse(sys.argv[1]).getroot(); s = r if r.tag == "testsuite" else r.find("testsuite")
t = int(s.get("tests", 0)); bad = int(s.get("failures", 0)) + int(s.get("errors", 0)); sk = int(s.get("skipped", 0))
print(f"{t - bad - sk}/{t}" + (f" ({sk} skipped)" if sk else ""))
PY
}
JC=$(mktemp -d)
echo "▸ Faultline judge check: deterministic, no API key required"

echo "① FalkorDB (pinned digest) …"
if make -s up >"$JC/up.log" 2>&1; then
  ENGINE=$(uv run python -c "import json;d=json.load(open('backend/faultline/graph/algo/resolved.json'));print(d['engine'],d['digest'][:19])")
  step "FalkorDB" "$ENGINE" PASS
else
  step "FalkorDB" "could not start (see $JC/up.log)" FAIL
fi

# a reused engine (after `make eval` / `make scale`) still holds the memory of deleted graphs; the live tests need room to
# copy graphs, so compact first (graphs persist through the AOF). A clean clone starts near 0 and skips this.
P=$(uv run python -c "from faultline.graph.engine_info import memory_pressure as m; f=m()['fraction']; print(round(100*(f or 0)))" 2>/dev/null || echo 0)
if [ "$P" -gt 35 ]; then
  echo "  engine at ${P}% of maxmemory: make compact …"
  make -s compact >"$JC/compact.log" 2>&1 || step "FalkorDB" "make compact failed (see $JC/compact.log)" FAIL
fi

echo "② engine smoke suite …"
if uv run pytest -q -m smoke backend/faultline/graph/smoke -p no:warnings --junitxml="$JC/smoke.xml" >/dev/null 2>&1; then
  step "smoke (critical items)" "$(uv run python -c "import json;r=json.load(open('docs/audit/smoke_pinned.json'))['results'];c=[x for x in r if x['critical']];print(f\"{sum(1 for x in c if x['ok'])}/{len(c)}\")")" PASS
else
  step "smoke (critical items)" "failed" FAIL
fi

echo "③ seed tenant graphs …"
if SEED=$(uv run python scripts/seed.py --tenant all --summary 2>"$JC/seed.log") \
   && uv run python scripts/seed.py --tenant acme --no-memory --summary >/dev/null 2>>"$JC/seed.log"; then
  step "seed" "$(echo "$SEED" | paste -sd ';' - | sed 's/;/; /g')" PASS
else
  step "seed" "failed (see $JC/seed.log)" FAIL
fi

# the pinned UDF library is loaded in the engine at its pinned sha (GRAPH.UDF LIST WITHCODE), not merely present on disk
if U=$(uv run python - 2>"$JC/udf.log" <<'PY'
import sys
from faultline.graph import client, udf
st = udf.udf_status(client.engine().connection)
print("; ".join(f"{k} {v['state']} at sha {v['loaded_sha'] or '-'} (pinned {v['pinned_sha']})" for k, v in st.items()))
sys.exit(0 if all(v["state"] == "loaded" for v in st.values()) else 1)
PY
); then
  step "UDF flex (GRAPH.UDF LIST)" "$U" PASS
else
  step "UDF flex (GRAPH.UDF LIST)" "${U:-error} (see $JC/udf.log)" FAIL
fi

echo "④ unit tests …"
if uv run pytest tests -q -m "not smoke and not live and not slow" -p no:warnings --junitxml="$JC/unit.xml" >/dev/null 2>&1; then
  step "unit tests" "$(junit "$JC/unit.xml")" PASS
else
  step "unit tests" "$(junit "$JC/unit.xml") — run: make test" FAIL
fi

echo "⑤ live graph, MCP, gate, scenario, isolation (S7) and concurrency (S13, reduced) tests (keyless) …"
if uv run pytest tests -q -m live -p no:warnings --junitxml="$JC/live.xml" >/dev/null 2>&1; then
  step "live graph tests" "$(junit "$JC/live.xml")" PASS
else
  step "live graph tests" "$(junit "$JC/live.xml")" FAIL
fi
echo "⑤b tenant isolation through the real ro_<tenant> ACL users (created for this run, random password, deleted after) …"
if uv run python scripts/acl_ephemeral.py tests/isolation --junitxml="$JC/acl.xml" >"$JC/acl.log" 2>&1; then
  step "ACL isolation (S7, ro users)" "$(junit "$JC/acl.xml")" PASS
else
  step "ACL isolation (S7, ro users)" "$(junit "$JC/acl.xml") (see $JC/acl.log)" FAIL
fi

echo "⑥ replay the committed examples' gate verdicts, re-read their write-back artefacts, gate bench (fast) …"
if R=$(uv run python evals/replay_examples.py 2>"$JC/replay.log"); then
  step "replay gate verdicts" "${R#replay gate verdicts }" PASS
else
  step "replay gate verdicts" "${R#replay gate verdicts } (see $JC/replay.log)" FAIL
fi
if W=$(uv run python scripts/run_artefacts.py --check 2>"$JC/artefacts.log"); then
  step "write-back re-read" "$W" PASS
else
  step "write-back re-read" "$W (see $JC/artefacts.log)" FAIL
fi
# 20 of the 100 generated gate cases; PASS = every verdict reproduces the recorded full bench (k/n is shown as is)
if B=$(uv run python evals/gate_bench.py --fast --quiet --check-recorded 2>"$JC/bench.log"); then
  step "gate bench (20 of 100)" "${B#gate verdicts }" PASS
else
  step "gate bench (20 of 100)" "${B#gate verdicts } (see $JC/bench.log)" FAIL
fi

# FalkorDB's own view after the tests: no product template above its slow-log budget (GRAPH.SLOWLOG, GRAPH.MEMORY)
if E=$(uv run python scripts/engine_check.py 2>"$JC/engine.log"); then
  step "engine slow log" "$E" PASS
else
  step "engine slow log" "$E (see $JC/engine.log)" FAIL
fi

echo "⑦ pipeline invariants on the healthy fixture …"
if uv run python pipeline/generate_sources.py --mode healthy >/dev/null 2>&1 && uv run python pipeline/run.py >/dev/null 2>&1 \
   && uv run pytest pipeline/invariants -q -p no:warnings --junitxml="$JC/inv.xml" >/dev/null 2>&1; then
  step "pipeline invariants" "$(junit "$JC/inv.xml")" PASS
else
  step "pipeline invariants" "failed" FAIL
fi

echo "⑧ lints, secret scan and .env …"
if L=$(uv run python scripts/lint_single_store.py 2>&1); then step "single-store lint" "${L#single-store lint }" PASS; else step "single-store lint" "$L" FAIL; fi
if N=$(uv run python scripts/lint_no_leaks.py 2>&1); then step "no-leaks lint" "${N#no-leaks lint }" PASS; else step "no-leaks lint" "$N" FAIL; fi
if C=$(uv run python scripts/check_claims.py 2>&1); then step "claims check" "${C#claims check }" PASS; else step "claims check" "$C" FAIL; fi
if S=$(bash scripts/secret_scan.sh 2>&1); then step "secret scan" "$S" PASS; else step "secret scan" "$S" FAIL; fi
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then  # .env must be untracked AND ignored
  if [ -z "$(git ls-files -- .env '*/.env')" ] && git check-ignore -q .env; then
    step ".env untracked" "not tracked, ignored by .gitignore" PASS
  else
    step ".env untracked" ".env is tracked or not ignored" FAIL
  fi
elif grep -qxF '.env' .gitignore; then
  step ".env untracked" "no git checkout; .env is listed in .gitignore" PASS
else
  step ".env untracked" ".env missing from .gitignore" FAIL
fi

echo "⑨ frontend lint + build …"
if [ ! -d frontend/node_modules ]; then (cd frontend && npm ci --no-audit --no-fund >/dev/null 2>&1); fi
if [ -d frontend/node_modules ]; then
  if (cd frontend && npm run -s lint >/dev/null 2>&1 && npm run -s build >/dev/null 2>&1); then
    step "frontend build" "clean" PASS
  else
    step "frontend build" "failed: cd frontend && npm run build" FAIL
  fi
else
  step "frontend build" "SKIPPED: run make setup" FAIL
fi

echo "⑩ restoring the incident fixture …"
uv run python pipeline/generate_sources.py --mode incident >/dev/null 2>&1
uv run python pipeline/run.py >/dev/null 2>&1

echo
echo "JUDGE CHECK"
printf '%s\n' "${LINES[@]}"
echo "  (no API key, no GitHub token, no remote touched)"
echo
if [ "$fail" -gt 0 ]; then echo "FAIL ($fail of $((pass+fail)) checks)"; exit 1; fi
echo "PASS"
