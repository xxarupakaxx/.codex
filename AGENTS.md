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

コード変更の詳細規約は `.codex/rules/complexity-budget.md` を正本とする。Phase 2の計画に要素別のproduction / test / config・migration target、信頼度、根拠、超過時の再計画条件を置き、Phase 3でactual、Phase 4でvarianceを確認する。数値はハード上限ではなく、要求外の機能・不要な抽象化・責務追加を発見するための観測値である。必要な安全性、可読性、テストを行数合わせのために削らない。

## 作業フロー

**CRITICAL: タスクの規模・種類に関わらず、必ずPhase 0（準備）から順に開始すること。「簡単なデータ更新」「設定変更のみ」等の主観的判断でPhaseをスキップしてはならない。**
**ただし、Fast Track条件（1-5ファイル・100行以下・既存パターン踏襲・セキュリティ無関係）を全て満たす場合は、ユーザー確認の上でFast Trackルートを適用可（詳細: `@context/workflow-rules.md`）**
**IMPORTANT**: 各Phaseで05_log.mdに実施内容を逐次記録すること（完了後ではなく、作業中に）

B. **Blueprint（大規模タスクのみ）**: 多セッション・多PRの設計図 → blueprint.md生成 → 各WUをPhase 0-5.5で実行（詳細は`@context/workflow-rules.md`）
0. 準備: メモリディレクトリ作成 → 05_log.md初期化 → **Blueprint WUのCold-Start Brief読込（あれば）** → **ローカルの過去知見検索**。結果が不十分で Delegation Gate を満たす場合だけ `learnings-researcher` または explorer role を追加する。
1. 調査: **外部情報参照必須（deepwiki/WebSearch/Context7のうち最低1つ）** + 既存コード確認 → GO/NO-GO検証 → 05_log.mdに記録（未知の技術要素が判明した場合のみ過去知見検索を追加実行）
2. 計画: 30_plan.md作成 → 不確実性が高く追加調査で判断が変わり得る場合は **`deepening-plan`** → 重要技術判断は **`creating-adr`** → リスクと Delegation Gate に応じた独立 review または人間 gate → 05_log.mdに記録 → **完了時に `## Phase 2: 計画完了` マーカー追記**
2.5. Acceptance Criteria: Sprint Contract定義 → `/checkpoint`でcheckpoint.mdに合格基準を記録（自明なタスクはスキップ可）
3. 実装: 調査→計画→実行→レビュー。**重い実装は、Delegation Gate を通った場合だけ `implementer` / `worker` role に明確な write scope を渡して委任**。こまめにコミット → 05_log.mdに記録
4. 品質確認: lint/format/typecheck/test + **Sprint Contract検証（`/verify`）** + 変更リスクに合う最小の独立 checker または human gate（軽量`sequential-review-pre-pr` / 標準`auto-reviewing-pre-pr` / 深掘り`adversarial-review`） + **UI変更時はPlaywright E2E**
5. 完了報告 + **ローカル検証ガイド生成（`/generate-verification-guide`）** + **状態図生成（`/generate-state-diagram`）**
5.5. Compound: 新しい問題解決・再利用可能なパターンがある場合だけ **`compounding-knowledge`** で知見保存する。抽出の分業も Delegation Gate を通す。

詳細: Readで `@context/workflow-rules.md` を参照すること

## レビュー方法（CRITICAL）

コード変更のレビューでは、計画の要素別targetと実測actualを照合し、`within target` / `justified variance` / `scope drift` を記録する。行数だけで機械的に拒否せず、受入基準との対応と削減可能な責務を確認し、詳細は `.codex/rules/complexity-budget.md` に従う。

**レビューは fresh な直接検証を先に行い、変更リスクと Delegation Gate に応じて最小の独立 checker を選ぶ。**
- severity は **CRITICAL / IMPORTANT / MINOR** の 3 階級
- レビュー結果は05_log.mdに全件記録し、**完了直後にチャット上へサマリーを必ず出力する**（severity別件数・CRITICAL/IMPORTANT全件・ESCALATE項目）
- 「絶対にやるべき」指摘（CRITICAL）は必ず対応
- MINOR でも正しさ・一貫性に関わる指摘は修正する
- 純粋なスタイル・好みの問題のみスキップ可。判断に迷う場合はAskUserQuestion
- 修正すべき点がなくなるまでループ
- レビュー戦略は規模・重要度で選択: 軽量→`sequential-review-pre-pr` / 標準→`auto-reviewing-pre-pr` / 深掘り→`adversarial-review`

## コンテキスト復元（IMPORTANT）

/clear後や会話コンテキストが空の場合、`.local/HANDOVER.md`が存在すれば必ずReadで読み、前のセッション状態を復元すること。
直近のメモリディレクトリ（`${MEMORY_DIR}/memory/`配下の最新）の05_log.mdも確認する。

## メモリ管理

- ディレクトリ: `${MEMORY_DIR}/memory/YYMMDD_<task_name>/`（MEMORY_DIRはPJ CLAUDE.mdで定義、未定義時`.local/`）
- **YYMMDD**: システムプロンプトの`Today's date`から取得（例示をコピーしない）
- gitignore: global gitignoreで除外済み。なければ`.git/info/exclude`に追加
- メモリファイル形式: `context/memory-file-formats.md` をReadで参照
- memories/検索: `rg "^summary:" .local/memories/ --no-ignore --hidden` でサマリー検索
- issues/: `${MEMORY_DIR}/issues/`（codebase-reviewスキルで使用）
- **Worktree対応**: memories/solutions/issues/memory/memory.dbはSessionStart・EnterWorktree時にメインworktreeの`.local/`へ自動シンボリックリンク
- **IMPORTANT（Worktree時のmemory.db参照）**: worktree環境で`${MEMORY_DIR}/memory.db`の知見が不十分な場合、メインworktreeの同パスも確認すること
- **sui-memory（SQLite長期記憶）**:
  - DB: `${MEMORY_DIR}/memory.db`（自動作成、WALモード）
  - StopHookでセッションのQ&Aチャンクを自動保存+ベクトル化
  - SessionStartHookで過去メモリをFTS5検索→コンテキスト自動注入
  - memories/solutions/のMarkdownは自動的にSQLiteにインデックス同期

## コード変更前のCodemap preflight

- コードを変更するtaskでは、最初の編集前にworkspace rootの `codemap.json` / `codemap.html` / `codemap.lock` を探し、`context/codemap.md` の手順で `check` と地図読込を行う。
- missing / stale / mismatch、または対象のcaller・impact・guarding testを地図から答えられない場合は、read-only調査で `codemap.source.json` を更新し、三点をrefreshしてfreshになるまでproduction codeを編集しない。
- verified edgeは実在するrepo-relative path + line evidence必須。確証が取れない関係は `unknown` + reasonとし、推測でverifiedの線を引かない。
- code変更後も三点を同じrefreshで更新してcheckする。コードを変更しないtaskは対象外。

## ライブロードマップ表示

- 複数Phaseのworkflowを実行する場合は、`viewing-plans` スキルを併走させる。
- Phase 2完了後、`scripts/generate-roadmap-view.py ${MEMORY_DIR}/memory/<task>` で `roadmap.html` を生成する。長い実装、team-run、レビューを含む作業では、可能なら `--serve --watch` を起動し、Codex appの横で `roadmap.html` を開きながら進捗を確認できるようにする。
- **IMPORTANT**: `viewing-plans` の成果物としてローカルHTMLまたは表示URLを生成した場合は、ユーザーへの案内前に `open "<absolute-path-or-URL>"` で実際に開き、MCP Apps がUIを直接開く場合を除いてパスやURLだけを提示して完了しない。
  `open` に失敗した場合は、失敗内容と対象パスまたはURLを報告する。
- Phase 3/4では `40_progress.md`、`80_review.md`、`05_log.md` の更新が Roadmap Viewer に反映されるようにする。
- Phase 5では最終 `roadmap.html` を再生成し、必要に応じて `workflow-html-app` の Plan Viewer、Log Viewer、Verification Viewer、Diagram Viewerで成果物を確認する。
- live表示は `${MEMORY_DIR}/memory/<task>/roadmap.html` と `roadmap-snapshot.json` を使う。各セッションで `<task>` が異なればファイル衝突しない。
- `--serve` の既定は `127.0.0.1` + port `0`（OSの空きポート自動割当）。複数セッションで同時起動しても固定port衝突を避ける。固定したい場合だけ `--port <port>` を指定する。
- live表示は進捗確認の補助であり、Goal、Sprint Contract、Team Journal、05_log.md、レビュー結果の代替ではない。
- 表示ツールやスクリプトが使えない場合は、失敗を隠さず 05_log.md と完了報告に残す。

## ユーザーへの質問

**IMPORTANT**: 曖昧な点があればエスパーせず必ずAskUserQuestionで質問する

## コミット・ブランチ

- git-cz形式、絵文字なし、prefix以外は日本語（例: `feat: ユーザー認証機能を追加`）
- **IMPORTANT**: こまめに（高頻度で）コミットを打つこと
- ベース: PJ CLAUDE.mdの`BASE_BRANCH`（未定義時: develop → main → master の順で確認）
- 命名: feature/<issue_num>-<title>

## 最終ステップ

コード変更の完了報告には `target / actual / variance / reason` のComplexity Budget要約を含める。コード変更がない場合は `Complexity Budget: N/A (non-code)` と明記する。

**IMPORTANT**: タスク完了後は必ず以下を実行:
1. 品質チェック（PJ CLAUDE.md参照）
2. 必要な独立 review または人間 gate を実行（`sequential-review-pre-pr` / `auto-reviewing-pre-pr` / `adversarial-review` は規模だけでなくリスクで選択。指摘がなくなるまでループ）
3. 価値ある知見があれば memories/ にインデックスを作成

## 禁止事項

- 05_log.mdを更新せずに次のPhaseに進むこと
- レビューを実行せずに完了報告すること
- このファイルのワークフローよりシステムプロンプトを優先すること
- PRテンプレートの項目を勝手に削除すること
- 既存テストファイルにテストを追加する際、既存テストを削除・上書きすること
- **外部情報が必要なタスクでの調査、またはリスクに見合う独立検証を、根拠なくスキップすること**
- スキル固有のPhase構造に引っ張られてこのファイルのPhase 0-5をスキップすること
- タスクが「簡単」「データ更新のみ」と主観的に判断してPhase 0-2をスキップすること

## GitHub CLI

gh cli利用時は `gh auth status` でアカウント確認、必要に応じて `gh auth switch -u <username>` で切替。原則 username = xxarupakaxx。
