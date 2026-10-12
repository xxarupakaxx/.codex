#!/bin/bash

_TASK_MEMORY_LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
_TASK_MEMORY_CORE="${SESSION_HANDOVER_CORE:-$_TASK_MEMORY_LIB_DIR/../../scripts/session_handover.py}"

select_task_directory() {
  local memory_base="$1"
  local session_id="${2:-}"
  local thread_id="${3:-}"
  local expected_worktree="${4:-}"
  local expected_project="${5:-}"
  case "$memory_base" in
    */.local/memory|*/memory) ;;
    *) return 2 ;;
  esac
  [ -n "$expected_worktree" ] || expected_worktree=$(pwd -P) || return 2
  [ -n "$expected_project" ] || expected_project="$expected_worktree"
  local args=(resolve --cwd "$expected_worktree" --memory-base "$memory_base"
    --worktree-path "$expected_worktree" --project-path "$expected_project")
  [ -z "$session_id" ] || args+=(--session-id "$session_id")
  [ -z "$thread_id" ] || args+=(--thread-id "$thread_id")
  python3 "$_TASK_MEMORY_CORE" "${args[@]}"
}

session_handover_path() {
  local local_root="$1"
  local session_id="${2:-}"
  local thread_id="${3:-}"
  local args=(path --local-root "$local_root")
  [ -z "$session_id" ] || args+=(--session-id "$session_id")
  [ -z "$thread_id" ] || args+=(--thread-id "$thread_id")
  python3 "$_TASK_MEMORY_CORE" "${args[@]}"
}
