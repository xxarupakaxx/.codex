#!/bin/bash
# Unregistered compatibility adapter. The helper runs a local compiler once.
CORE="${HOOK_OBSERVATIONS_SCRIPT:-$HOME/.claude/scripts/hook_observations.py}"
if [ ! -f "$CORE" ]; then
  printf '%s\n' '{"hook":"typescript","status":"unknown","reason":"helper_missing"}' >&2
  exit 0
fi
exec python3 "$CORE" typescript --runtime codex
