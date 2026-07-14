#!/usr/bin/env bash
# consult-fable.sh — GPT(Codex) オーケストレーターから Claude Fable 5 への単発戦略相談ブリッジ。
# 呼び出し規律（昇格条件・1往復原則・セキュリティ境界）は skills/consult-fable/SKILL.md を参照。
#
# 使い方:
#   consult-fable.sh "相談内容"                                   # 中立 scope の新規相談
#   consult-fable.sh --cwd <directory> "相談内容"                   # 読取対象を明示した新規相談
#   consult-fable.sh --cwd <directory> --resume <session_id> "追い質問" # 同一 scope の追い質問
#   echo "相談内容" | consult-fable.sh -                # stdin から
#
# 出力: claude CLI の --output-format json をそのまま stdout へ
#       （result に回答本文、session_id、total_cost_usd などを含む）
set -euo pipefail
umask 077

MAX_CALLS_PER_DAY="${CONSULT_FABLE_MAX_PER_DAY:-8}"
TIMEOUT_SECS="${CONSULT_FABLE_TIMEOUT:-300}"
COUNT_DIR="${TMPDIR:-/tmp}/consult-fable"
COUNT_FILE="${COUNT_DIR}/count-$(date +%Y%m%d)"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="${STATE_HOME}/consult-fable"
NEUTRAL_DIR="${STATE_DIR}/neutral"
SESSION_DIR="${STATE_DIR}/sessions"

usage() {
  echo "usage: consult-fable.sh [--cwd <directory>] [--resume <session_id>] [--] \"相談内容\"" >&2
  exit 2
}

die() {
  echo "consult-fable: $*" >&2
  exit 2
}

canonical_dir() {
  local path="$1"
  [[ -d "$path" ]] || die "directory が存在しない: $path"
  (cd -P -- "$path" && pwd)
}

is_uuid() {
  [[ "$1" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{4}-[[:xdigit:]]{12}$ ]]
}

ensure_session_dir() {
  mkdir -p "$STATE_DIR" "$SESSION_DIR"
  chmod 700 "$STATE_DIR" "$SESSION_DIR"
}

write_binding() {
  local session_file="$1"
  local cwd="$2"
  local state="$3"
  local binding_tmp
  binding_tmp="$(mktemp "${SESSION_DIR}/.binding.XXXXXX")"
  printf '%s\n%s\n' "$cwd" "$state" > "$binding_tmp"
  mv "$binding_tmp" "$session_file"
}

verify_resume_binding() {
  local bound_cwd
  local bound_state
  [[ -f "$SESSION_FILE" && ! -L "$SESSION_FILE" ]] || die "未登録の session_id は resume できない。前回の結論を相談文に添えて新規相談を開始してください"
  IFS= read -r bound_cwd < "$SESSION_FILE" || die "session binding を読み取れない"
  [[ "$bound_cwd" == "$WORKDIR" ]] || die "session_id は別の scope に紐付いている"
  bound_state="$(sed -n '2p' "$SESSION_FILE")"
  [[ "$bound_state" == "available" ]] || die "session_id はすでに追い質問に使われた。必要なら新規相談を開始してください"
}

RESUME_LOCK_DIR=""
release_resume_lock() {
  local status=$?
  if [[ -n "$RESUME_LOCK_DIR" && -d "$RESUME_LOCK_DIR" ]]; then
    rmdir "$RESUME_LOCK_DIR" || true
  fi
  return "$status"
}
trap release_resume_lock EXIT

RESUME_ID=""
REQUESTED_CWD=""
while (( $# > 0 )); do
  case "$1" in
    --cwd)
      (( $# >= 2 )) || die "--cwd には directory が必要"
      [[ -z "$REQUESTED_CWD" ]] || die "--cwd は1回だけ指定できる"
      REQUESTED_CWD="$2"
      shift 2
      ;;
    --resume)
      (( $# >= 2 )) || die "--resume には session_id が必要"
      [[ -z "$RESUME_ID" ]] || die "--resume は1回だけ指定できる"
      RESUME_ID="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -)
      break
      ;;
    -*)
      die "unknown option: $1（ダッシュ始まりの相談文は -- の後に指定する）"
      ;;
    *)
      break
      ;;
  esac
done

PROMPT="$*"
if [[ "$PROMPT" == "-" ]]; then
  PROMPT="$(cat)"
fi
if [[ -z "$PROMPT" ]]; then
  usage
fi

if [[ -n "$REQUESTED_CWD" ]]; then
  WORKDIR="$(canonical_dir "$REQUESTED_CWD")"
else
  mkdir -p "$NEUTRAL_DIR"
  WORKDIR="$(canonical_dir "$NEUTRAL_DIR")"
fi

NEW_SESSION_ID=""
SESSION_FILE=""
if [[ -n "$RESUME_ID" ]]; then
  is_uuid "$RESUME_ID" || die "--resume は wrapper が発行した UUID を指定する"
  RESUME_ID="$(printf '%s' "$RESUME_ID" | tr '[:upper:]' '[:lower:]')"
  ensure_session_dir
  SESSION_FILE="${SESSION_DIR}/${RESUME_ID}"
  verify_resume_binding
  RESUME_LOCK_CANDIDATE="${SESSION_FILE}.lock"
  mkdir "$RESUME_LOCK_CANDIDATE" 2>/dev/null || die "session_id は別の追い質問で使用中"
  RESUME_LOCK_DIR="$RESUME_LOCK_CANDIDATE"
  verify_resume_binding
else
  ensure_session_dir
  NEW_SESSION_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
  is_uuid "$NEW_SESSION_ID" || die "session_id の生成に失敗した"
  SESSION_FILE="${SESSION_DIR}/${NEW_SESSION_ID}"
  [[ ! -e "$SESSION_FILE" && ! -L "$SESSION_FILE" ]] || die "session_id が衝突した。再実行してください"
fi

# 乱用ガード: 1往復原則の機械的な裏付け（日次上限）
mkdir -p "$COUNT_DIR"
COUNT=$(( $(cat "$COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
if (( COUNT > MAX_CALLS_PER_DAY )); then
  echo "consult-fable: 日次上限 ${MAX_CALLS_PER_DAY} 回を超過したため停止する（hot path 化防止ガード）。" >&2
  echo "本当に必要ならユーザー承認を得て ${COUNT_FILE} を削除するか、CONSULT_FABLE_MAX_PER_DAY を上げる。" >&2
  exit 1
fi
printf '%s' "$COUNT" > "$COUNT_FILE"

ADVISOR_ROLE='あなたは Board Advisor（戦略アドバイザー）として、GPTオーケストレーターから単発の相談を受けている。
役割: 戦略への批評、タスク分解の妥当性判断、リスク指摘、taste判断。実装・修正・ファイル変更は行わない。
必要なら Read/Grep/Glob で対象コードや設定を確認してから判断する。
読取対象は現在の CWD 配下に限り、CWD 外の path は探索しない。
出力: 結論を最初の1文で述べ、根拠は3点以内、代替案は最大1つ。相談は原則1往復なので、質問を返さずその場で判断を下す。'

# filesystem customization と auto memory を読ませず、built-in / MCP / write boundary を固定する。
# プロンプトは -- の後の位置引数として最後に置き、ダッシュ始まりの相談文も安全に扱う。
ARGS=(
  -p
  --output-format json
  --setting-sources ""
  --disable-slash-commands
  --strict-mcp-config
  --tools "Read,Grep,Glob"
  --disallowedTools "mcp__*"
  --permission-mode plan
  --append-system-prompt "$ADVISOR_ROLE"
)
if [[ -n "$RESUME_ID" ]]; then
  ARGS+=(--resume "$RESUME_ID")
else
  ARGS+=(--session-id "$NEW_SESSION_ID" --model fable)
fi
ARGS+=(-- "$PROMPT")

run_claude() {
  if command -v timeout >/dev/null 2>&1; then
    timeout "$TIMEOUT_SECS" claude "${ARGS[@]}"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$TIMEOUT_SECS" claude "${ARGS[@]}"
  else
    claude "${ARGS[@]}"
  fi
}

(
  cd -- "$WORKDIR"
  export CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
  run_claude
)

if [[ -n "$NEW_SESSION_ID" ]]; then
  write_binding "$SESSION_FILE" "$WORKDIR" "available"
elif [[ -n "$RESUME_ID" ]]; then
  if ! write_binding "$SESSION_FILE" "$WORKDIR" "used"; then
    RESUME_LOCK_DIR=""
    die "session binding の更新に失敗した。${SESSION_FILE}.lock を確認してください"
  fi
  rmdir "$RESUME_LOCK_DIR"
  RESUME_LOCK_DIR=""
fi
