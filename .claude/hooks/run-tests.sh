#!/usr/bin/env bash
# Stop hook: refuse to finish while tests fail. Only runs suites whose source changed.
# Guard: blocks at most twice per session so a genuinely broken suite cannot loop forever.
set -u
export PATH="$HOME/.local/bin:$PATH"
input=$(cat)
session=$(printf '%s' "$input" | jq -r '.session_id // "nosession"')
root="$(cd "$(dirname "$0")/../.." && pwd)"
counter="${TMPDIR:-/tmp}/budget-buddy-stop-${session}"

changed() { [ -n "$(git -C "$root" status --porcelain -- "$@")" ]; }

failures=""
if changed api; then
  if ! out=$(cd "$root/api" && uv run pytest -q 2>&1); then
    failures+=$'\n== pytest ==\n'"$(printf '%s' "$out" | tail -40)"
  fi
fi
if changed app/src app/package.json app/vite.config.ts; then
  if ! out=$(cd "$root/app" && npx vitest run 2>&1); then
    failures+=$'\n== vitest ==\n'"$(printf '%s' "$out" | tail -40)"
  fi
fi

if [ -z "$failures" ]; then
  rm -f "$counter"
  exit 0
fi

count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
printf '%s' "$count" > "$counter"
if [ "$count" -gt 2 ]; then
  printf '{"systemMessage":"Tests still failing after %s attempts. The stop hook is standing down for this session. Fix the suite before merging."}\n' "$count"
  exit 0
fi
printf 'Tests failed. Fix them before finishing (attempt %s of 2).%s\n' "$count" "$failures" >&2
exit 2
