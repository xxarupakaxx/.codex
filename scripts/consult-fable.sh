#!/usr/bin/env bash
# consult-fable.sh — GPT(Codex) オーケストレーターから Claude Fable 5 への単発戦略相談ブリッジ。
# 呼び出し規律（昇格条件・1往復原則・セキュリティ境界）は skills/consult-fable/SKILL.md を参照。
#
# 使い方:
#   consult-fable.sh "相談内容"                        # 新規相談（Board Advisor 役割を注入）
#   consult-fable.sh --resume <session_id> "追い質問"   # 追い質問（1回まで）
#   echo "相談内容" | consult-fable.sh -                # stdin から
#
# 出力: claude CLI の --output-format json をそのまま stdout へ
#       （result に回答本文、session_id、total_cost_usd などを含む）
set -euo pipefail

MAX_CALLS_PER_DAY="${CONSULT_FABLE_MAX_PER_DAY:-8}"
TIMEOUT_SECS="${CONSULT_FABLE_TIMEOUT:-300}"
COUNT_DIR="${TMPDIR:-/tmp}/consult-fable"
COUNT_FILE="${COUNT_DIR}/count-$(date +%Y%m%d)"

RESUME_ID=""
if [[ "${1:-}" == "--resume" ]]; then
  RESUME_ID="${2:?--resume には session_id が必要}"
  shift 2
fi

PROMPT="${1:-}"
if [[ -z "$PROMPT" || "$PROMPT" == "-" ]]; then
  PROMPT="$(cat)"
fi
if [[ -z "$PROMPT" ]]; then
  echo "usage: consult-fable.sh [--resume <session_id>] \"相談内容\"" >&2
  exit 2
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
出力: 結論を最初の1文で述べ、根拠は3点以内、代替案は最大1つ。相談は原則1往復なので、質問を返さずその場で判断を下す。'

# プロンプトは -- の後の位置引数として最後に置く。ダッシュ始まりプロンプトの
# オプション誤解釈と、可変長引数 --allowedTools への吸い込みを両方防ぐ（claude CLI検証済み）
ARGS=(-p --output-format json --allowedTools Read Grep Glob)
if [[ -n "$RESUME_ID" ]]; then
  ARGS+=(--resume "$RESUME_ID")
else
  ARGS+=(--model fable --append-system-prompt "$ADVISOR_ROLE")
fi
ARGS+=(-- "$PROMPT")

if command -v timeout >/dev/null 2>&1; then
  timeout "$TIMEOUT_SECS" claude "${ARGS[@]}"
elif command -v gtimeout >/dev/null 2>&1; then
  gtimeout "$TIMEOUT_SECS" claude "${ARGS[@]}"
else
  claude "${ARGS[@]}"
fi
