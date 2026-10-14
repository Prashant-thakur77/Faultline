#!/usr/bin/env bash
# Run a heavy command under a hard memory ceiling so it cannot exhaust the host (the dev laptop has ~14 GB and also
# runs the editor, browser and Claude). On Linux with systemd user scopes the command runs with MemoryMax and no swap:
# if it overruns, only the command is killed (exit 137). Anywhere else (macOS, containers without systemd) it runs
# uncapped with a warning: the guard must never stop a judge from running `make judge-check`.
#
#   scripts/memguard.sh <cap-MB> <command> [args…]       e.g. scripts/memguard.sh 3000 make eval
#   MEMGUARD=off                 run uncapped, no checks
#   MEMGUARD_STRICT=1            refuse to start when free memory is below cap + headroom (default: warn only)
#   MEMGUARD_HEADROOM_MB=1500    memory that should stay free for everything else
set -uo pipefail
cap="${1:?cap in MB}"; shift
if [ "${MEMGUARD:-on}" = "off" ]; then exec env "$@"; fi
headroom="${MEMGUARD_HEADROOM_MB:-1500}"
avail=""
if [ -r /proc/meminfo ]; then
  avail=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || true)
fi
if [ -n "$avail" ] && [ "$avail" -lt $((cap + headroom)) ]; then
  msg="memguard: only ${avail} MB available (cap ${cap} + headroom ${headroom} MB); stop other heavy jobs if this fails"
  if [ "${MEMGUARD_STRICT:-0}" = "1" ]; then echo "$msg; refusing (MEMGUARD_STRICT=1): $*" >&2; exit 75; fi
  echo "$msg" >&2
fi
if command -v systemd-run >/dev/null 2>&1 && systemd-run --user --scope --quiet true 2>/dev/null; then
  exec systemd-run --user --scope --quiet -p MemoryMax="${cap}M" -p MemorySwapMax=0 -- env "$@"
fi
echo "memguard: no systemd user scopes here; running uncapped: $*" >&2
exec env "$@"
