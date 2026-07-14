---
name: consult-fable
description: "GPT(Codex)オーケストレーターが、必要な局面だけ Claude Fable 5 に単発の戦略相談を投げる Model-invoked スキル。不可逆分岐・案の拮抗・2周連続失敗・taste判断のときに使う。並列ワーカー・並列レビューアーの起動には使わない（それは spawn_agent）。"
---

# /consult-fable — Fable 5 への単発戦略相談（Board Advisor）

Codex が Plan → Delegate → Verify → Synthesize の主ループを担う。Fable 5 は hot path に入れない on-demand の Board Advisor であり、このスキル経由でだけ使う。

## いつ呼ぶ

次のいずれかを満たすときだけ呼ぶ。

1. 後戻りが難しい設計分岐（公開 API、データモデル、アーキテクチャなど）。
2. 複数案が拮抗し、自己判断の確信が低い。
3. 同じ合格基準で2回連続して詰まった。
4. 命名、文言、設計の質感などの taste 判断。
5. ユーザーが明示的に求めた。

routine 実装、機械検証、最初の失敗、並列実装・並列レビューには使わない。並列作業は `spawn_agent` を使う。

## 実行方法とスコープ

```bash
# 既定: 呼び出し元に依存しない中立 scope
~/.codex/scripts/consult-fable.sh "（下の骨格で組んだ相談）"

# コードや設定を読むときだけ対象 directory を明示する
~/.codex/scripts/consult-fable.sh --cwd /absolute/or/relative/path "相談内容"

# 追い質問（最大1回）: 同じ scope で、直前の JSON の session_id を使う
~/.codex/scripts/consult-fable.sh --cwd /same/path --resume <session_id> "追い質問"
```

- default は `$XDG_STATE_HOME/consult-fable/neutral`（未設定時は `~/.local/state/...`）を CWD にする。呼び出し元の repository や directory を暗黙には使わない。
- `--cwd` は相談の読取対象を明示するだけであり、その directory の指示、skills、hooks、MCP を opt-in しない。
- 両 mode で user/project/local の filesystem settings、`CLAUDE.md`、skills、slash commands、auto memory を無効にする。MCP は strict config と deny rule の両方で使わせない。
- built-in tool は Read / Grep / Glob のみ、permission mode は `plan`。書き込み・コマンド実行は許可しない。
- managed policy と host-level global config は Claude Code の仕様上この wrapper だけでは隔離できない。これは OS sandbox ではないため、相談文で対象 scope 外の path を指定しない。

## Resume の境界

- 新規相談では wrapper が UUID を発行し、canonical CWD と private state directory 内で対応付ける。
- `--resume` は wrapper が発行した UUID だけを受け付け、同一 canonical CWD でのみ使える。symlink alias は同一 scope とみなす。
- 追い質問は成功した1回だけ。2回目は新規相談に切り替える。
- 過去の wrapper が作った session、unknown ID、別 directory の session は resume できない。前回の結論を相談文に添えて新規相談を開始する。

## 相談プロンプト骨格

```text
## 相談種別
（不可逆分岐 / 案の比較 / スタック打開 / taste判断）

## 背景（3-5行）
何のタスクで、いま何が決まっていて、何が決まっていないか。

## 論点（1つに絞る）
判断してほしいことを疑問文で1つ。

## 自分の現在の案と確信度
A案: … / B案: …（自分は A 寄り、確信60%）

## 制約・参照
締切・互換性・コスト等。`--cwd` を指定した場合だけ、その配下で読んでほしい相対パスを列挙する。
```

## 形式と責務のガード

- **1往復原則**。追い質問は最大1回。それでも決まらなければ、相談ではなくタスク委任または人間へのエスカレーションに切り替える。
- 出力は JSON（`result`、`session_id`、`total_cost_usd` など）。相談の要旨と回答は、その作業の記録先に残し、同じ論点を再相談しない。
- 日次上限は既定で8回。超過時は本当に必要かを確認する。
- Board Advisor と CWD 範囲の指示は、新規相談と追い質問のどちらにも注入される。
- `claude -p` の使用はこの Fable 相談だけに限る。`fable` は claude CLI の引数であり、`spawn_agent` の model には書かない。
