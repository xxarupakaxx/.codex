#!/bin/bash

select_task_directory() {
  local memory_base="$1"
  local session_id="$2"
  local thread_id="${3:-}"
  local matches=()
  local meta

  while IFS= read -r meta; do
    [ -n "$meta" ] || continue
    if [ -n "$session_id" ] && [ "$session_id" != "unknown" ] \
      && [ "$(jq -r '.session_id // empty' "$meta" 2>/dev/null)" = "$session_id" ]; then
      matches+=("$(dirname "$meta")")
    fi
  done < <(find -H "$memory_base" -mindepth 2 -maxdepth 2 -name task-meta.json -type f 2>/dev/null | sort)

  if [ "${#matches[@]}" -eq 1 ]; then
    printf '%s\n' "${matches[0]}"
    return 0
  fi
  if [ "${#matches[@]}" -gt 1 ]; then
    return 1
  fi

  if [ -n "$thread_id" ] && [ "$thread_id" != "unknown" ]; then
    while IFS= read -r meta; do
      [ -n "$meta" ] || continue
      if [ "$(jq -r '.thread_id // empty' "$meta" 2>/dev/null)" = "$thread_id" ]; then
        matches+=("$(dirname "$meta")")
      fi
    done < <(find -H "$memory_base" -mindepth 2 -maxdepth 2 -name task-meta.json -type f 2>/dev/null | sort)
    if [ "${#matches[@]}" -eq 1 ]; then
      printf '%s\n' "${matches[0]}"
      return 0
    fi
    if [ "${#matches[@]}" -gt 1 ]; then
      return 1
    fi
  fi

  matches=()
  while IFS= read -r meta; do
    [ -n "$meta" ] || continue
    case "$(jq -r '.task_state // empty' "$meta" 2>/dev/null)" in
      active|waiting|verifying) matches+=("$(dirname "$meta")") ;;
    esac
  done < <(find -H "$memory_base" -mindepth 2 -maxdepth 2 -name task-meta.json -type f 2>/dev/null | sort)

  if [ "${#matches[@]}" -eq 1 ]; then
    printf '%s\n' "${matches[0]}"
    return 0
  fi
  return 1
}

session_handover_path() {
  local local_root="$1"
  local session_id="$2"
  local safe_id
  safe_id=$(printf '%s' "${session_id:-unknown}" | tr -c 'A-Za-z0-9._-' '_')
  printf '%s/handovers/%s.md\n' "$local_root" "${safe_id:-unknown}"
}
