#!/usr/bin/env bash
# PostToolUse hook (Edit|Write): format and lint the file just changed.
# Exit 2 surfaces the problem to Claude so it gets fixed straight away.
set -u
export PATH="$HOME/.local/bin:$PATH"
input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -n "$file" ] && [ -f "$file" ] || exit 0
root="$(cd "$(dirname "$0")/../.." && pwd)"

case "$file" in
  "$root"/api/*.py)
    cd "$root/api" || exit 0
    uv run ruff format "$file" >/dev/null 2>&1
    if ! out=$(uv run ruff check "$file" 2>&1); then
      printf 'ruff check failed for %s:\n%s\n' "$file" "$out" >&2
      exit 2
    fi
    ;;
  "$root"/app/src/*.ts|"$root"/app/src/*.tsx)
    cd "$root/app" || exit 0
    if ! out=$(npx oxlint "$file" 2>&1); then
      printf 'oxlint failed for %s:\n%s\n' "$file" "$out" >&2
      exit 2
    fi
    if ! out=$(npx tsc -b 2>&1); then
      printf 'tsc failed:\n%s\n' "$(printf '%s' "$out" | head -40)" >&2
      exit 2
    fi
    ;;
esac
exit 0
