#!/usr/bin/env bash
# Scan every file that would be published (tracked + untracked-not-ignored) for credential-shaped
# strings. Prints path:line only, NEVER the matched value. Fails loudly if files cannot be listed or
# if grep itself errors.
set -uo pipefail
cd "$(dirname "$0")/.."
# generic (review round 4, m11): a value that looks generated (12+ key-like characters with at least two digits)
# given, as a quoted literal, to something named like a password/secret, or env-style (NAME=value, unquoted) to a
# *PASSWORD*/*SECRET*/*TOKEN*/*_KEY(S)* variable, including every FAULTLINE_*_KEY. Placeholders (<…>, ${…}, $(…),
# empty, words without digits) never match; nor do lines marked example/placeholder/changeme/dummy.
V='([A-Za-z_+/=.-]*[0-9]){2}[A-Za-z0-9_+/=.-]{10,}'
GENERIC='(password|passwd|secret)[A-Za-z0-9_]*["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']'"$V"'["'"'"']'
ENVSTYLE='^[[:space:]]*(export[[:space:]]+)?[A-Z0-9_]*(PASSWORD|PASSWD|SECRET|TOKEN|_KEY|_KEYS)[[:space:]]*=[[:space:]]*'"$V"'|FAULTLINE_[A-Z0-9_]*_KEYS?["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?'"$V"
PATTERN='sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|aws_secret_access_key[[:space:]]*=[[:space:]]*[A-Za-z0-9/+=]{40}|xox[baprs]-[A-Za-z0-9-]{20,}'
SELF='^(\./)?scripts/secret_scan\.sh$'
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  files=$(git ls-files --cached --others --exclude-standard)
  env_published=$(printf '%s\n' "$files" | grep -E '(^|/)\.env$' || true)
else
  files=$(find . -type f -not -path './.git/*' -not -path '*/node_modules/*' -not -path './.venv/*' \
          -not -path '*/.next/*' -not -name '.env' -not -name '*.zip' | sed 's#^\./##')
  env_published=""
fi
if [ -z "$files" ]; then echo "secret scan: could not enumerate files" >&2; exit 2; fi
n=$(printf '%s\n' "$files" | wc -l)
hits=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  [[ "$f" =~ $SELF ]] && continue
  out=$(grep -nIE -- "$PATTERN" "$f" 2>/dev/null); rc=$?
  if [ $rc -eq 0 ]; then
    hits+=$(printf '%s\n' "$out" | cut -d: -f1 | sed "s#^#$f:#")$'\n'
  elif [ $rc -gt 1 ]; then
    echo "secret scan: grep failed on $f" >&2; exit 2
  fi
  gen=$( { grep -nIEi -- "$GENERIC" "$f" 2>/dev/null; grep -nIE -- "$ENVSTYLE" "$f" 2>/dev/null; } \
        | grep -viE -- 'example|placeholder|change-?me|dummy|not-a-real|test-only')
  if [ -n "$gen" ]; then
    hits+=$(printf '%s\n' "$gen" | cut -d: -f1 | sed "s#^#$f:#")$'\n'
  fi
done <<< "$files"
if [ -n "$hits" ] || [ -n "$env_published" ]; then
  echo "secret scan: credential-shaped strings at (values not shown):" >&2
  printf '%s' "$hits" >&2
  [ -n "$env_published" ] && echo ".env would be published" >&2
  exit 1
fi
echo "PASS ($n files scanned)"
