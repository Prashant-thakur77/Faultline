# Faultline: no path, no claim. FalkorDB is the only store (see docs/ARCHITECTURE.md).
UV := uv run
PY := PYTHONPATH=backend $(UV) python
# heavy targets run under a hard memory ceiling (MB) so they can never exhaust the host (scripts/memguard.sh)
GUARD := scripts/memguard.sh
TENANT ?= acme

.PHONY: fixture gc graphrag-sdk-venv graphrag-sdk-dry mcp-http eval results claims bench chaos oncall-night learning-night t2-gonogo replay concurrency scale tenants-bench algo10k setup up down smoke smoke-both seed test invariants judge-check demo api frontend mcp run export \
        demo-reset demo-healthy build baselines doctor eval results claims

setup:
	uv sync
	cd frontend && npm install

## -- FalkorDB (pinned by digest in deploy/docker-compose.yml; docs/FALKORDB_COMPAT.md) ----------
up:
	docker compose -f deploy/docker-compose.yml up -d falkordb
	$(PY) scripts/wait_healthy.py
	$(PY) scripts/configure_falkordb.py

compact:  ## give FalkorDB back the memory of deleted graphs (rewrite the AOF, restart the pinned engine; graphs are kept)
	$(PY) -c "from faultline.graph import client; print('BGREWRITEAOF', client.engine().connection.execute_command('BGREWRITEAOF'))"
	$(PY) scripts/wait_aof.py
	docker compose -f deploy/docker-compose.yml restart falkordb
	$(PY) scripts/wait_healthy.py
	$(PY) scripts/configure_falkordb.py

down:
	docker compose -f deploy/docker-compose.yml down

smoke:
	PYTHONPATH=backend $(UV) pytest -q -m smoke backend/faultline/graph/smoke

# Full compat comparison on both candidate engines; regenerates docs/FALKORDB_COMPAT.md + resolved.json.
smoke-both:
	bash scripts/smoke_both.sh

# Idempotent: golden_<t> from deterministic producers, then tenant_<t> = GRAPH.COPY golden_<t>.
seed:
	$(PY) scripts/seed.py --tenant $(TENANT)

gc:  ## drop leftover eval/whatif/scratch graphs (keeps those recent runs point at)
	$(PY) scripts/gc_graphs.py --tenant $(TENANT)

## -- tests ---------------------------------------------------------------------------------------
test: fixture
	PYTHONPATH=backend $(UV) pytest tests -m "not smoke and not live and not slow"

# The demo warehouse the SQL-tool tests open read-only: built once if a fresh clone has none (incident mode, as
# judge-check leaves it). `make demo-healthy` / the scenarios switch modes themselves.
fixture:
	@test -f data/warehouse/faultline.duckdb -a -f data/sources/raw_orders.csv || \
	  ($(UV) python pipeline/generate_sources.py --mode incident && $(UV) python pipeline/run.py)

# Fixture-dependent pipeline invariants: build the HEALTHY fixture first (32/32 expected).
invariants: demo-healthy
	$(UV) pytest pipeline/invariants -q

# Deterministic, keyless proof path for judges (no API key, no remote).
judge-check:
	$(GUARD) 3000 bash scripts/judge_check.sh

eval:  ## eval arms (keyless: N,A2,A3,A4; LLM arms need a key + approved budget) → evals/results/, evals/RESULTS.md
	$(GUARD) 5000 $(PY) evals/harness.py --arms $${ARMS:-N,V,T,A2,A3,A3-noG5,A4} --n $${N:-3}

ui-check:  ## optional browser checks of the UI (needs Playwright Chromium and `make demo` running): overflow, collapsed sections, axe
	$(UV) python scripts/ui_check.py

retag:  ## after `make eval`: regenerate the query catalogue, retag timing/count claims; fail if a real result drifted
	$(PY) scripts/gen_query_catalogue.py
	$(PY) scripts/retag_timings.py

results:  ## regenerate evals/RESULTS.md + latest.json from the newest run (never hand-edit RESULTS.md)
	$(PY) evals/regen.py

mutants:  ## break each safety invariant in a scratch copy; prove a test notices → docs/audit/mutation.json
	$(GUARD) 3000 $(UV) python scripts/mutation_check.py

claims:  ## every tagged number in README/docs equals evals/results/latest.json
	$(UV) python scripts/check_claims.py

bench:  ## gate bench: 100 generated gate cases on clean rooms → "gate verdicts k/k" (evals/results/gate_bench.json)
	$(GUARD) 3000 $(PY) evals/gate_bench.py --quiet --out evals/results/gate_bench.json

oncall-night:  ## scripted on-call night: page → escalate → ack → APPLIED → contract → same fault under contract + 5 negatives → evals/results/oncall_night.json
	$(GUARD) 2500 $(PY) evals/oncall_night.py

graphrag-sdk-venv:  ## eval only: isolated venv for FalkorDB's GraphRAG-SDK under tmp/ (+ the 6.0.x full-text DDL patch, GLiNER model)
	bash scripts/graphrag_sdk_venv.sh

graphrag-sdk-dry:  ## eval only: brain vs GraphRAG-SDK corpus + cost estimate (no API call); the paid run is evals/graphrag_sdk_arm.py --run
	$(PY) evals/graphrag_sdk_arm.py --dry-run

learning-night:  ## learning night: choices cold vs warm, guidelines, who responds (MTTA), forget, gaps, recency recall → evals/results/learning_night.json
	$(GUARD) 3000 $(PY) evals/learning_night.py

t2-gonogo:  ## the memory and coordination checklist (track T2): cold vs warm, work claims under contention, cross-tenant isolation, forget with a receipt (incl. the live URL's read-only dry run), session history → evals/results/t2_gonogo.json
	$(GUARD) 3000 $(PY) evals/t2_gonogo.py

chaos:  ## kill -9 the API between execute and verify; the reconciler must settle the intent exactly once
	$(GUARD) 2000 $(PY) evals/chaos.py

replay:  ## replay every examples/<run> gate verdict on a clean room + re-read the committed write-back artefacts
	$(PY) evals/replay_examples.py
	$(PY) scripts/run_artefacts.py --check

scale:  ## scale benchmark: synthetic 1k/10k-service tenants by default (SIZES=… for more, e.g. 1k,3k,5k,10k; MERGE=1 folds one size into scale.json; memory-guarded; minutes) → evals/results/scale.json
	$(GUARD) 3000 $(PY) evals/scale.py --sizes $${SIZES:-1k,10k} $${MERGE:+--merge} --reason "$${REASON:-make scale}"
	@echo "scale: FalkorDB keeps the memory of the deleted scale graphs until restart; run 'make compact' before 'make eval'"

tenants-bench:  ## N tenant graphs on one engine (MB/tenant, copy ms, ACL isolation 0/K leaks, p50/p95/p99 at 1/8/32/64 investigators) → evals/results/tenants_bench.json
	$(GUARD) 3000 $(PY) evals/tenants_bench.py

algo10k:  ## all 10 algo.* at 10k services + an eval-only NetworkX comparator (same answers, time, memory) → evals/results/algo10k.json
	$(GUARD) 3000 env PYTHONPATH=backend $(UV) --group comparator python evals/algo10k.py

concurrency:  ## work claims under contention: 16 workers x 100 rounds
	$(PY) evals/concurrency.py --out evals/results/concurrency.json

doctor:
	$(PY) scripts/doctor.py

## -- run -----------------------------------------------------------------------------------------
# Run a scenario end to end in a GRAPH.COPY clean room (keyless deterministic investigator by default).
run:
	$(PY) -m faultline.cli run --scenario $${SCENARIO:-S2} --llm $${LLM:-baseline} $${EXPORT:+--export $$EXPORT}

mcp:
	$(PY) -m faultline.mcp_server.server --stdio

mcp-http:  ## MCP over Streamable HTTP at :8401/mcp (bearer keys from FAULTLINE_MCP_KEYS)
	$(PY) -m faultline.mcp_server.http --host 127.0.0.1 --port 8401

api:
	PYTHONPATH=backend $(UV) uvicorn faultline.api:app --port 8400 --app-dir backend

frontend:
	cd frontend && npm run dev

demo:
	@trap 'kill 0' INT TERM; \
	PYTHONPATH=backend $(UV) uvicorn faultline.api:app --port 8400 --app-dir backend & \
	(cd frontend && npm run dev) & \
	wait

## -- the existing data fixture (system under observation) ---------------------------------------
demo-reset:
	git checkout -- pipeline/transforms/ 2>/dev/null || true
	rm -f pipeline/transforms/*.sql.orig
	$(UV) python pipeline/generate_sources.py --mode incident
	$(UV) python pipeline/run.py

demo-healthy:
	git checkout -- pipeline/transforms/ 2>/dev/null || true
	rm -f pipeline/transforms/*.sql.orig
	$(UV) python pipeline/generate_sources.py --mode healthy
	$(UV) python pipeline/run.py

build:
	$(UV) python pipeline/run.py

baselines:
	$(UV) python pipeline/make_baselines.py
