#!/usr/bin/env bash
# Run the engine smoke suite against both candidate engines (by digest) and regenerate
# docs/FALKORDB_COMPAT.md + backend/faultline/graph/algo/resolved.json (refuses to pin on a critical failure).
set -euo pipefail
cd "$(dirname "$0")/.."
declare -A IMG=(
  [6.0.2]="falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6"
  [v4.22.0]="falkordb/falkordb@sha256:4ac83f55062d364dcf151692635138b0bd2e12578019a56eb86ef53d067b116b"
)
declare -A PORT=([6.0.2]=6391 [v4.22.0]=6392)
cleanup() { for tag in "${!IMG[@]}"; do docker rm -f "fl-smoke-$tag" >/dev/null 2>&1 || true; done; }
trap cleanup EXIT
for tag in 6.0.2 v4.22.0; do
  docker rm -f "fl-smoke-$tag" >/dev/null 2>&1 || true
  docker run -d --name "fl-smoke-$tag" -p "127.0.0.1:${PORT[$tag]}:6379" "${IMG[$tag]}" >/dev/null
done
for tag in 6.0.2 v4.22.0; do
  FALKORDB_PORT="${PORT[$tag]}" PYTHONPATH=backend uv run python scripts/wait_healthy.py --timeout 60
done
rc=0
for tag in 6.0.2 v4.22.0; do
  PYTHONPATH=backend uv run python -m faultline.graph.smoke.runner --port "${PORT[$tag]}" --tag "$tag" \
    --digest "${IMG[$tag]#*@}" --out "docs/audit/smoke_$tag.json" || [ "$tag" != "6.0.2" ] || rc=1
done
PYTHONPATH=backend uv run python scripts/render_compat.py docs/audit/smoke_6.0.2.json docs/audit/smoke_v4.22.0.json --pin 6.0.2 || rc=1
exit $rc
