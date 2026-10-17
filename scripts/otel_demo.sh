#!/usr/bin/env bash
# FaultBench-OTel: bring the trimmed, pinned OpenTelemetry Demo up or down (evals/faultbench_otel.py drives it).
#   scripts/otel_demo.sh up | down | status | config
# Clones open-telemetry/opentelemetry-demo at the pinned release into tmp/otel-demo/src (git-ignored) on first use.
# Never `docker system prune`; `down` removes only this project's containers and network.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="3.1.0"
DIR="$ROOT/tmp/otel-demo/src"
SERVICES=(ad cart checkout currency email frontend frontend-proxy image-provider load-generator payment product-catalog
          quote recommendation shipping flagd astronomy-db valkey-cart otel-collector prometheus)
if [ ! -d "$DIR/.git" ]; then
  mkdir -p "$ROOT/tmp/otel-demo"
  git clone -q --depth 1 --branch "$TAG" https://github.com/open-telemetry/opentelemetry-demo.git "$DIR"
fi
have="$(git -C "$DIR" describe --tags --exact-match 2>/dev/null || true)"
[ "$have" = "$TAG" ] || { echo "otel_demo: $DIR is at '${have:-?}', expected tag $TAG" >&2; exit 1; }
export DEMO_VERSION="$TAG" FAULTBENCH_DIR="$ROOT/deploy/otel-demo"
dc() { docker compose -p otel-demo --project-directory "$DIR" -f "$DIR/compose.yaml" -f "$ROOT/deploy/otel-demo/faultbench.compose.yaml" "$@"; }
case "${1:-status}" in
  up)     dc up -d --no-build "${SERVICES[@]}" ;;
  down)   dc down --remove-orphans; git -C "$DIR" checkout -- src/flagd/demo.flagd.json ;;
  status) dc ps --format '{{.Name}} {{.Status}}' ;;
  config) dc config --images | sort -u ;;
  *) echo "usage: $0 up|down|status|config" >&2; exit 2 ;;
esac
