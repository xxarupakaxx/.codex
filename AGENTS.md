# 共通ルール

このファイルは user-scope Codex の短い入口である。全 Agent が毎回守る不変条件と正本への導線だけを置き、手順・履歴・例外の詳細はリンク先へ置く。

## 基本方針

- 日本語で応答する。
- 同等の観測性と安全性がある場合は、MCP サーバーより CLI ツールを先に検討する。
- Project `AGENTS.md` と、対象ファイルに最も近い `AGENTS.md` の追加制約を適用する。

## 実装と検証

- 実装前に仮定、不明点、複数解釈、重要な trade-off を明示する。仕様・契約・データ形式などの永続判断は、既存実装、test、文書、またはユーザー確認を根拠にする。
- 要求を満たす最小の実装を選び、依頼外の機能、抽象化、設定、将来対応を足さない。
- 既存コードや文書は依頼に直接必要な行だけ変更し、隣接する無関係な整形、refactor、削除を行わない。
- 成功条件を検証可能にし、再現、test、差分確認、task-level workflow check まで含めて完了を判定する。
- 再現 test は観測済みの失敗と既存契約だけを固定し、未確認の戻り値、error型、出力形式を新しい期待値にしない。

## Secret 管理

- secret 実値を 1Password の外へ永続化しない。code、設定、log、chat、artifact、memory、sub-agent prompt に書かない。
- CLI へ渡す必要がある場合は `op://...` secret reference を親 process で解決し、reference と解決結果のどちらも sub-agent や外部相談へ渡さない。
- 詳細は `rules/security.md` を正本とする。

## 指示の永続化

- worktree や session をまたいで再現すべき情報は Memory だけに置かず、git 管理された正本へ反映する。
- 現在の意図や仕様は docs、検証可能な期待は test、局所例外は隣接 comment、判断理由は ADR、反復手順は Skill、未完了作業は issue tracker、履歴は Git log に置く。
- 全 Agent が毎回守る不変条件と正本への入口だけを `AGENTS.md` に置く。古い方針や完了済み TODO を残さない。
- 例外には理由、適用範囲、解除条件を付け、条件が満たされたら例外自体を削除する。

## 一時ファイルと受け渡し

- 一過性の下書き、調査メモ、CLI/AI 間の受け渡しは作業 worktree の `.context/` に置き、`/tmp` や `/private` を標準置き場にしない。
- 複数行や構造化内容は `.context/` の実ファイルで渡す。引数への inline 展開や here-doc を避け、pipe は単一 command が stdin を即時に一度だけ読む処理に限る。

## Script と error

- 長時間実行や外部通信を伴う script は開始、反復、retry、完了、失敗を secret なしで記録し、再実行判断に足る進捗を出す。
- 主経路の失敗を暗黙 fallback で隠さない。代替経路は目的、発動条件、観測 log、再実行時の挙動を明示する。
- error は一致なし、context不一致、path不存在、conflict/dirty state、検証failureなど意味で分類し、原因を確認してから続行する。
- 同種 error の再発や検証省略につながる迂回は、原因、一時迂回、恒久対策、git反映先、検証方法を分けて恒久対策レビューへ送る。

## 外部サービス境界

- 作成、更新、削除、送信、承認、共有、権限変更の失敗を、別 principal、company、profile への自動切替で回避しない。読み取り診断も principal を明示し、解消しなければ停止して確認する。
- 外部 write と `git commit` / `git push` は `context/agent-team-routing.md` の External Write Gate と project policy に従う。

## 委譲

- 独立した作業幅、隔離された専門知識、独立検証に価値がある場合だけ role-appropriate な sub-agent/runner へ委譲する。
- 親は objective、背景、scope、制約、許可する副作用、期待成果物、検証方法を明示し、返答を既存実装・設定・文書・testへ戻って検証する。
- 委譲先へ secret 実値、secret reference、認証済み session 情報を渡さない。
- 複数 AI の出力比較は作成者情報を伏せ、`Report A` / `Report B` の中立 label で独立評価を終えてから attribution を扱う。

## Skill / Runner

- 詳細手順は作業 repository の正規 docs / Skill を優先する。新しい Skill、runner、wrapper を作る前に既存部品で足りるか確認する。
- Skill の起動権と最小 route は `context/agent-team-routing.md`、model/service tier は `rules/model-routing.md` を正本とする。

## Artifact gate

- Phase / Step を持つ作業は、対応 artifact を project が定める artifact root へ保存してから遷移する。project指定がなければ `.context/<task-or-date>/` を使う。
- Markdown artifact の frontmatter は `task`、`phase_or_step`、`created_at` を必須とする。命名は `<nn>-<phase-name>.md` または既存 workflow の `<nn>_<phase-name>.md` とする。
- 非 Phase 作業は対象外。単発 bypass は `.context/single-step/<task>.json` に `enabled=true`、`task`、`reason`、`expires_at` を持たせる。
- global Phase 順序は `context/workflow-rules.md`、Skill固有 artifact は実行中の `SKILL.md`、形式は `context/memory-file-formats.md` を正本とする。

## Markdown / ADR / Plan

- Markdown を編集したらファイル全体を見直し、矛盾、重複、rule漏れを同じ turn で解消する。metadata は frontmatter に置く。
- ADR は `rules/adr-criteria.md` の3条件をすべて満たす判断だけに作り、日時と作業 Agent の model 名を記録する。
- Phase を含む Plan は各 Phase の Skill（不使用なら `なし`）と検証を明示し、既存 gate 以外の途中許可を前提にせず完走できる粒度にする。

## Codex compatibility

- Default / heavy judgment は `gpt-5.5` + `priority`、routine specialist は role 既定、低リスク helper は利用可能な場合だけ `gpt-5.4-mini` + `priority` を使う。Claude-only model alias を使わない。
- 長い作業は Goal、Sprint Contract、Outcome Trace、必要時の Team Journal を分ける。`team-run` はユーザー明示または高価値の並列幅がある場合だけ使う。

## 正本 map

| 関心 | 正本 |
|---|---|
| Phase 0-5.5、review、Goal/acceptance、Roadmap | `context/workflow-rules.md` |
| plugin / skill / agent routing、外部write | `context/agent-team-routing.md` |
| team-run composition / exit gate | `context/team-run.md` と `skills/team-run/SKILL.md` |
| model / service tier | `rules/model-routing.md` |
| code complexity budget | `rules/complexity-budget.md` |
| ADR 判定 | `rules/adr-criteria.md` |
| memory artifact形式 | `context/memory-file-formats.md` |
| Git / review | `rules/common-git-workflow.md` と `rules/code-review-philosophy.md` |

## 完了境界

- `context/workflow-rules.md` の Phase 0-5.5 と project `AGENTS.md` の品質・commit/push policy を守る。
- fresh な直接検証を先に行い、変更リスクに合う最小の独立 checker を選ぶ。CRITICAL は必ず、IMPORTANT は原則修正する。
- 完了報告には変更、検証、review、残課題を含める。設定済みと実行済み、構文成功と user outcome 達成を区別する。
