#!/usr/bin/env bash
# consult-fable.sh の wrapper contract を mock CLI で検証する。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${SCRIPT_DIR}/consult-fable.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/consult-fable-test.XXXXXX")"
MOCK_BIN="${TMP}/bin"
CALLS="${TMP}/calls"
STATE_HOME="${TMP}/state"
TEST_TMPDIR="${TMP}/tmpdir"
INVOKER="${TMP}/invoker"
PROJECT_REAL="${TMP}/projects/real"
PROJECT_ALIAS="${TMP}/projects/alias"
PROJECT_OTHER="${TMP}/projects/other"

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  [[ "$expected" == "$actual" ]] || fail "${message}: expected=${expected} actual=${actual}"
}

call_count() {
  cat "${CALLS}/count"
}

assert_call_count() {
  assert_eq "$1" "$(call_count)" "claude invocation count"
}

has_arg() {
  local call="$1"
  local expected="$2"
  local file
  for file in "${call}"/arg-*; do
    [[ "$(cat "$file")" == "$expected" ]] && return 0
  done
  return 1
}

assert_arg() {
  has_arg "$1" "$2" || fail "argument not found: ${2}"
}

assert_no_arg() {
  if has_arg "$1" "$2"; then
    fail "unexpected argument: ${2}"
  fi
}

value_after() {
  local call="$1"
  local option="$2"
  local file
  local index
  local next
  for file in "${call}"/arg-*; do
    if [[ "$(cat "$file")" == "$option" ]]; then
      index="${file##*-}"
      next="${call}/arg-$((index + 1))"
      [[ -f "$next" ]] || fail "value is missing after ${option}"
      cat "$next"
      return 0
    fi
  done
  fail "option not found: ${option}"
}

assert_arg_pair() {
  local actual
  actual="$(value_after "$1" "$2")"
  assert_eq "$3" "$actual" "value after ${2}"
}

binding_cwd() {
  sed -n '1p' "$1"
}

binding_state() {
  sed -n '2p' "$1"
}

json_session_id() {
  local output="$1"
  local session_id
  session_id="$(sed -n 's/.*"session_id":"\([^"]*\)".*/\1/p' "$output")"
  [[ -n "$session_id" ]] || fail "session_id is missing from JSON output"
  printf '%s' "$session_id"
}

run_wrapper() {
  (
    cd "$INVOKER"
    PATH="${MOCK_BIN}:${PATH}" \
      TMPDIR="$TEST_TMPDIR" \
      XDG_STATE_HOME="$STATE_HOME" \
      CONSULT_FABLE_MAX_PER_DAY=99 \
      "$SCRIPT" "$@"
  )
}

expect_failure() {
  if run_wrapper "$@" >/dev/null 2>&1; then
    fail "expected failure: $*"
  fi
}

mkdir -p "$MOCK_BIN" "$CALLS" "$TEST_TMPDIR" "$INVOKER" "$PROJECT_REAL" "$PROJECT_OTHER"
ln -s "$PROJECT_REAL" "$PROJECT_ALIAS"
PROJECT_CWD="$(cd -P -- "$PROJECT_REAL" && pwd)"

cat > "${MOCK_BIN}/claude" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

CALLS="${CONSULT_FABLE_TEST_CALLS:?}"
call_number=0
if [[ -f "${CALLS}/count" ]]; then
  read -r call_number < "${CALLS}/count"
fi
call_number=$((call_number + 1))
printf '%s\n' "$call_number" > "${CALLS}/count"

call_dir="${CALLS}/${call_number}"
mkdir -p "$call_dir"
pwd > "${call_dir}/cwd"
printf '%s' "${CLAUDE_CODE_DISABLE_AUTO_MEMORY:-}" > "${call_dir}/auto-memory"

index=0
previous=""
session_id="mock"
for arg in "$@"; do
  printf '%s' "$arg" > "${call_dir}/arg-${index}"
  if [[ "$previous" == "--session-id" || "$previous" == "--resume" ]]; then
    session_id="$arg"
  fi
  previous="$arg"
  index=$((index + 1))
done

printf '{"result":"ok","session_id":"%s"}\n' "$session_id"
EOF
chmod +x "${MOCK_BIN}/claude"
export CONSULT_FABLE_TEST_CALLS="$CALLS"

# Default mode uses a stable neutral CWD and does not inherit the invoker CWD.
DEFAULT_OUTPUT="${TMP}/default-output"
run_wrapper "neutral consultation" > "$DEFAULT_OUTPUT"
DEFAULT_CALL="${CALLS}/1"
NEUTRAL_CWD="$(cd -P -- "${STATE_HOME}/consult-fable/neutral" && pwd)"
assert_eq "$NEUTRAL_CWD" "$(cat "${DEFAULT_CALL}/cwd")" "default cwd"
assert_eq "1" "$(cat "${DEFAULT_CALL}/auto-memory")" "auto memory disable env"
assert_arg_pair "$DEFAULT_CALL" "--setting-sources" ""
assert_arg "$DEFAULT_CALL" "--disable-slash-commands"
assert_arg "$DEFAULT_CALL" "--strict-mcp-config"
assert_arg_pair "$DEFAULT_CALL" "--tools" "Read,Grep,Glob"
assert_arg_pair "$DEFAULT_CALL" "--disallowedTools" "mcp__*"
assert_arg_pair "$DEFAULT_CALL" "--permission-mode" "plan"
assert_no_arg "$DEFAULT_CALL" "--cwd"
assert_arg_pair "$DEFAULT_CALL" "--model" "fable"
assert_arg "$DEFAULT_CALL" "--append-system-prompt"
DEFAULT_SESSION="$(json_session_id "$DEFAULT_OUTPUT")"
assert_eq "$(value_after "$DEFAULT_CALL" "--session-id")" "$DEFAULT_SESSION" "JSON session ID"
SESSION_DIR="${STATE_HOME}/consult-fable/sessions"
DEFAULT_BINDING="${SESSION_DIR}/${DEFAULT_SESSION}"
assert_eq "$NEUTRAL_CWD" "$(binding_cwd "$DEFAULT_BINDING")" "default session binding"
assert_eq "available" "$(binding_state "$DEFAULT_BINDING")" "default session state"
assert_eq "700" "$(stat -f '%Lp' "$SESSION_DIR")" "session directory mode"

# A generated ID resumes only in the same default scope.
DEFAULT_RESUME_OUTPUT="${TMP}/default-resume-output"
run_wrapper --resume "$DEFAULT_SESSION" "default follow-up" > "$DEFAULT_RESUME_OUTPUT"
DEFAULT_RESUME_CALL="${CALLS}/2"
assert_eq "$NEUTRAL_CWD" "$(cat "${DEFAULT_RESUME_CALL}/cwd")" "default resume cwd"
assert_arg_pair "$DEFAULT_RESUME_CALL" "--resume" "$DEFAULT_SESSION"
assert_no_arg "$DEFAULT_RESUME_CALL" "--session-id"
assert_no_arg "$DEFAULT_RESUME_CALL" "--model"
assert_arg "$DEFAULT_RESUME_CALL" "--append-system-prompt"
assert_eq "$DEFAULT_SESSION" "$(json_session_id "$DEFAULT_RESUME_OUTPUT")" "resume JSON session ID"
assert_eq "used" "$(binding_state "$DEFAULT_BINDING")" "default session state after resume"

# Explicit scope is canonicalized, and a symlink alias resumes in that same scope.
PROJECT_OUTPUT="${TMP}/project-output"
run_wrapper --cwd "$PROJECT_REAL" "project consultation" > "$PROJECT_OUTPUT"
PROJECT_CALL="${CALLS}/3"
assert_eq "$PROJECT_CWD" "$(cat "${PROJECT_CALL}/cwd")" "explicit cwd"
PROJECT_SESSION="$(json_session_id "$PROJECT_OUTPUT")"
PROJECT_BINDING="${SESSION_DIR}/${PROJECT_SESSION}"
mkdir "${PROJECT_BINDING}.lock"
expect_failure --cwd "$PROJECT_ALIAS" --resume "$PROJECT_SESSION" "busy follow-up"
rmdir "${PROJECT_BINDING}.lock"
run_wrapper --cwd "$PROJECT_ALIAS" --resume "$PROJECT_SESSION" "project follow-up" >/dev/null
PROJECT_RESUME_CALL="${CALLS}/4"
assert_eq "$PROJECT_CWD" "$(cat "${PROJECT_RESUME_CALL}/cwd")" "symlink alias resume cwd"
assert_arg_pair "$PROJECT_RESUME_CALL" "--resume" "$PROJECT_SESSION"

# Unknown, malformed, and cross-scope IDs fail before the mock CLI is invoked.
expect_failure --resume "00000000-0000-0000-0000-000000000000" "unknown session"
expect_failure --resume "../../not-a-uuid" "malformed session"
expect_failure --resume "$DEFAULT_SESSION" "second follow-up"
expect_failure --cwd "$PROJECT_OTHER" --resume "$PROJECT_SESSION" "cross-scope session"
expect_failure --cwd "${TMP}/missing" "missing directory"
assert_call_count "4"

# A prompt beginning with a dash must remain a prompt after the -- guard.
run_wrapper -- "--starts-with-a-dash" >/dev/null
DASH_PROMPT_CALL="${CALLS}/5"
assert_arg_pair "$DASH_PROMPT_CALL" "--" "--starts-with-a-dash"

# The documented stdin form remains available.
printf '%s' "stdin consultation" | run_wrapper - >/dev/null
STDIN_CALL="${CALLS}/6"
assert_arg_pair "$STDIN_CALL" "--" "stdin consultation"

echo "PASS: consult-fable wrapper contract"
