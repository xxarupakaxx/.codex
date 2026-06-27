# Loop Engineering System — リファレンスドキュメント

> 自律的な開発・レビューループを実現する Codex 設定群の全体像。
> このドキュメント単体でシステムの理解・セットアップ・運用が可能。

## 実行モデル（正典）

**指揮者 = Codex。** オーケストレーションは Codex で利用できる機構に一本化する。Claude Code 専用の team coordination API は正典では使わない。

| 用途 | 機構 |
|------|------|
| ローカル並列実行・独立コマンド | `multi_tool_use.parallel` |
| 専門レビュー・調査・軽量ワーカー | `multi_agent_v1.spawn_agent(agent_type: "...")` |
| 複数ターンの協調 | `team-run` skill（`/team-run` shim）+ Goal + Team Journal + Review Heat + `spawn_agent` |
| 重い実装の委任 | `implementer` / `worker` role に write scope を明示して `spawn_agent` |
| プラグイン由来の運用規律 | Superpowers skills（計画・レビュー・完了前検証など） |

> **parallel と team-run の使い分け**: 独立した読み取り・検証は `multi_tool_use.parallel` で足りる。複数ロールが状態を共有しながら継続判断する場合だけ `team-run` skill を使い、Goal、Team Journal、Review Heat で目的・担当・未解決事項・疑い方を同期する。

## 現状ステータス（2026-06-17 時点）

- **配線済み・自律稼働**: `hour-calendar`(毎時) / `morning-kickoff`(09:00) / `jira-spec-poll`(毎時) / `evening-review`(18:00) / `pr-review`(毎時, pr-review-loop経由) / `security-audit`(毎朝) / `slack-to-jira`(毎時) / `generate-diagram-pr`(毎時) / `daily-news`(09:10)
- **スケジューラの制約（重要）**: これらは Codex アプリ/ランタイム起動中のみ発火する**ベストエフォート**。OSレベルの cron/launchd ではないため「毎時」は保証されない（アプリ未起動時はスキップ、次回起動時に実行）。24/7 が必要なループは launchd 等でCLIをヘッドレス起動する構成が別途必要。
- **dead/未配線**: `orchestrator` agent は現状どの実行系からも `agent_type` 起動されない（このファイルが定義する Conductor パターンの**参照仕様**であり、実際の指揮者役は Codex メインセッションが担う）。`implementer`/`ab-judge`/`minutes-classifier` も互換 workflow 内では inline プロンプトで代替している。

## アーキテクチャ概要

### 3層構成

```
Layer 1: Global Foundation  (~/.codex/ — git管理)
  agents/ workflows/ hooks/ commands/ scheduled-tasks/ context/ templates/

Layer 2: User Config        (~/.codex/config.toml — gitignore)
  model, service_tier, tools, local secrets ...

Layer 3: Project Override   (<repo>/.codex/ or AGENTS.md — PJごと)
  AGENTS.md(BASE_BRANCH等) context/team-run.md agents/domain-reviewer.toml backlog.md
```

- Layer 1はgit cloneで任意のPCに展開可能
- Layer 2はマシン固有（`config.example.toml`をコピーして作成）
- Layer 3はプロジェクトリポジトリに同梱（`templates/project-setup/`を雛形として使用）

### 実行レイヤー

```
┌─────────────────────────────────────────────────────┐
│                  Scheduled Tasks                     │
│  morning-kickoff(9:00) │ hour-calendar(毎時)        │
│  jira-spec-poll(毎時)  │ evening-review(18:00)      │
└──────────┬──────────────┬──────────────┬────────────┘
           │  config.toml / 環境設定を参照
           ▼              ▼              ▼
┌──────────────────────────────────────────────────────┐
│              Compatible Workflows                     │
│  morning-kickoff.js  │ implementation-drive.js       │
│  tournament-ab.js    │ evening-review.js             │
│  (Codex config / runtime context からユーザー設定取得)
└──────────┬──────────────┬──────────────┬─────────────┘
           │              │              │
           ▼              ▼              ▼
┌──────────────────────────────────────────────────────┐
│                  Agent Definitions                    │
│  orchestrator │ implementer │ cost-monitor            │
│  daily-planner │ minutes-classifier │ jira-spec-writer│
│  ab-judge │ harness-improver                         │
└──────────┬──────────────┬──────────────┬─────────────┘
           │              │              │
           ▼              ▼              ▼
┌──────────────────────────────────────────────────────┐
│                  Infrastructure                       │
│  Hooks: post-cost-track / stop-harness-improve       │
│  Commands: /loop-status                              │
│  Settings: PostToolUse + Stop hook entries            │
└──────────────────────────────────────────────────────┘
```

## エージェント一覧（4点契約）

### orchestrator
| 項目 | 内容 |
|------|------|
| **目的** | ワークフロー全体制御、タスク分解、適切なエージェントへの委任 |
| **出力形式** | Orchestration Report（委任先・理由・結果のJSON構造） |
| **ツール** | `multi_agent_v1.spawn_agent`, `multi_tool_use.parallel`, Read/Grep/Glob相当, Bash, Write/Edit相当, Team Journal |
| **境界** | 直接コード編集しない。実装はimplementerに委任 |
| **モデル** | `gpt-5.5` + `priority` |

### implementer
| 項目 | 内容 |
|------|------|
| **目的** | コード実装（implement → verify → fix ループ、最大3回） |
| **出力形式** | 変更ファイル一覧 + テスト結果 + 差分サマリー |
| **ツール** | Read/Edit/Write相当, Bash, bounded write scope |
| **境界** | 自分のworktree内のみ。他worktreeへの書き込み禁止 |
| **モデル** | `gpt-5.5` + `priority` |

### cost-monitor
| 項目 | 内容 |
|------|------|
| **目的** | トークン使用量追跡、コスト見積もり、閾値超過アラート |
| **出力形式** | CostReport JSON（date, total_cost_usd, breakdown, alert_level, recommendations） |
| **ツール** | Codex logs/state 読み取り, Grep, 集計コマンド |
| **境界** | 読み取り専用。設定変更の提案のみ（実行しない） |
| **モデル** | `gpt-5.5` + `priority` |

### minutes-classifier
| 項目 | 内容 |
|------|------|
| **目的** | 議事録アクション項目をAIタスク/人間タスク/情報に分類 |
| **出力形式** | 分類結果JSON（items[].type: auto_execute/human_action/info_only） |
| **ツール** | Read, Grep, Write, Bash |
| **境界** | 曖昧なものはhuman_actionに分類（安全側）。金額・契約・人事は必ずhuman_action |
| **モデル** | `gpt-5.5` + `priority` |

### jira-spec-writer
| 項目 | 内容 |
|------|------|
| **目的** | Jiraチケットから仕様書ドラフトを生成 |
| **出力形式** | Markdown仕様書（概要/要件/技術設計/テスト計画/リスク/サブタスク） |
| **ツール** | Read, Grep, Glob, Write, Bash, WebSearch（Jira/Confluence MCPはToolSearch経由で利用可能） |
| **境界** | ドラフトのみ生成（レビュー前マーク）。既存仕様書は上書きしない |
| **モデル** | `gpt-5.5` + `priority` |

### ab-judge
| 項目 | 内容 |
|------|------|
| **目的** | A/B実装の品質比較、3人独立ジャッジによる匿名評価 |
| **出力形式** | Verdict JSON（winner, confidence, scores, reasoning, notable_differences） |
| **ツール** | Read, Grep, Bash(test/lint) |
| **境界** | 評価のみ。コード修正しない。セキュリティスコア2以下は勝者にしない |
| **モデル** | `gpt-5.5` + `priority` |

### harness-improver
| 項目 | 内容 |
|------|------|
| **目的** | 失敗パターン分析 → AGENTS.md/rules/context改善提案の生成 |
| **出力形式** | 改善提案（パターン/根拠/提案ルール/適用先） |
| **ツール** | Read, Grep, Glob, Write |
| **境界** | 提案のみ（自動適用しない）。1セッション最大3件。既存ルールとの矛盾チェック必須 |
| **モデル** | `gpt-5.5` + `priority` |

### daily-planner
| 項目 | 内容 |
|------|------|
| **目的** | Jira/Calendar/未完了タスク/PRレビューから優先順位付き日次計画を作成 |
| **出力形式** | DailyPlan JSON（focus, p0[], p1[], p2[], meetings[], carryover[], estimated_hours） |
| **ツール** | Read, Grep, Bash, Write |
| **境界** | 計画作成のみ。タスク実行しない。最大8時間分。P0が3件以上なら確認を要求 |
| **モデル** | `gpt-5.5` + `priority` |

## ワークフロー実行フロー

### tournament-ab.js
```
args: {task, spec, testCmd?, baseFile?}

Implement ──→ parallel([plan-a(worktree), plan-b(worktree)])
    │
Test ──────→ parallel([test-a, test-b])
    │
Judge ─────→ parallel([judge-correctness(gpt-5.5/priority), judge-maintainability(gpt-5.5/priority), judge-performance(gpt-5.5/priority)])
    │
Decide ────→ 多数決 + 加重スコア平均 → winner(A/B/tie)
```

### morning-kickoff.js
```
Gather ──→ parallel([jira-tickets, calendar-events, carryover-tasks, pr-reviews])
    │
Plan ────→ daily-planner(gpt-5.5/priority) → DailyPlan JSON
    │
Notify ──→ Slack投稿
```

### implementation-drive.js
```
args: {ticketKey, useTournament?}

Analyze ──→ チケット分析 → complexity(simple/medium/complex)
    │
Spec ─────→ jira-spec-writer(gpt-5.5/priority) → 仕様書ドラフト
    │
Implement ─→ simple: 直接実装(worktree)
             medium: pipeline(subtasks, impl→test→review)
             complex/tournament: `workflows/tournament-ab.js` を直接実行、または `team-run` skill で分割実行
    │
Verify ───→ テスト + lint + typecheck + コードレビュー
    │
Report ───→ Jiraコメントに記録
```

### evening-review.js
```
Cost ─────→ cost-monitor → CostReport(alert_level)
    │
Failures ─→ harness-improver → FailurePatterns
    │
Improve ──→ [alert≥warning] → モデルダウングレード提案
             [failures.high≥1] → ルール改善提案
    │
Summary ──→ Slack日次サマリー投稿
```

## スケジュールタスク一覧（登録済み）

| タスク | 間隔 | 内容 | 委任先 |
|--------|------|------|-------------|
| `morning-kickoff` | 毎朝9:00 | 日次計画作成→Slack通知 | morning-kickoff.js |
| `hour-calendar` | 毎時 | 議事録要約→dailyノート追記 + アクション分類→自律実行 | 直接実行（config駆動: notes.daily_dir） |
| `jira-spec-poll` | 毎時 | 新規チケット検出→仕様書ドラフト生成 | 直接実行 |
| `evening-review` | 毎夕18:00 | コスト/失敗分析→改善提案→Slackサマリー | evening-review.js |
| `pr-review` | 毎時 | PRコメント検知→レビュー→修正→再レビュー | pr-review-loop.js |
| `security-audit` | 毎朝 | Security Audit Criticalメール→調査→冪等にJira起票+PR | 直接実行（冪等性ガードあり） |
| `slack-to-jira` | 毎時 | 直近1hの自投稿→チームタスクを冪等にJira起票 | 直接実行（dedup+時間窓） |
| `generate-diagram-pr` | 毎時 | オープンPRに状態図を冪等に投稿/更新 | generate-state-diagram スキル |
| `daily-news` | 毎朝9:10 | 野球ニュース要約（個人用・実験的） | 直接実行 |

> 旧 `hour-calnedar`（typo）は無効化済み。後継は `hour-calendar`。

## Hook定義

| Hook | トリガー | 内容 |
|------|---------|------|
| `post-cost-track.sh` | PostToolUse(Bash\|Agent) | ツール呼び出しを日次ログに記録 |
| `stop-harness-improve.sh` | Stop | セッション終了時に失敗パターンを検出→候補ファイル保存 |

## コマンド

| コマンド | 説明 |
|---------|------|
| `/loop-status` | 全ループの状態表示（スケジュールタスク/ワークフロー/コスト/改善提案） |
| `/pr-watch [PR]` | PRのCI/レビューを監視し未対応を自動対応。`/loop` を起動できる環境では `/loop 30m /pr-watch <PR>` を開始し、できない環境では起動コマンドを提示（Esc で停止） |
| `/team-run "<タスク>"` (`/team-run` shim) | Agent Team編成。完了後に `/pr-watch <PR>` を実行すると、可能な環境ではCI/レビュー継続監視を開始 |

> **`/pr-watch` 監視と `scheduled-tasks/pr-review` の役割差**: `/pr-watch <PR>` は `/loop` を起動できる環境では `/loop 30m /pr-watch <PR>` を開始し、**現セッション中**に特定PR1本を30分おき能動監視する（team-run成果のコンテキストを引き継げる／`Esc` で停止）。自動起動APIがない環境では、起動コマンドをユーザーに提示し、本サイクルは1回だけ実行する。2回目以降の呼び出しは state の `loop_active: true` により二重起動を防止。一方 `scheduled-tasks/pr-review` は**全 watch_repos** を毎時バッチ巡回（アプリ起動中のベストエフォート）。CI失敗の自動修正（`gh pr checks`→失敗ログ→修正→push）は `/pr-watch` のみが行う。

## Codex role ディスパッチ

| 用途 | 呼び出し方法 | モデル方針 |
|------|---------|------------|
| コードベース探索 | `multi_agent_v1.spawn_agent(agent_type: "explorer")` / `architecture-explorer` | role既定 |
| 軽量ワーカー | `multi_agent_v1.spawn_agent(agent_type: "worker")` | role既定 |
| 判定・設計判断・レビュー | `technical-evaluator` / `go-nogo-advisor` / reviewer role | role既定 |
| 重い実装 | `implementer` / `worker` に write scope を明示 | `gpt-5.5` + `priority` |
| 専門レビュー | `arch-reviewer` 等 | role既定 |
| 過去知見検索 | `learnings-researcher` | role既定 |
| パイプライン制御 | `multi_tool_use.parallel` + `multi_agent_v1.wait_agent` | — |

詳細: `rules/model-routing.md`（model / service_tier の SSoT）。plugin / skill / agent role の選択は `context/agent-team-routing.md` を参照する。

## ファイル配置

```
~/.codex/
├── config.example.toml             # Codex設定テンプレート（git管理）
├── config.toml                     # 実値（gitignore）
├── agents/*.toml                   # Codex agent role 定義
├── skills/                         # Skill正本
│   ├── team-run/SKILL.md
│   ├── pr-watch/SKILL.md
│   └── orchestrate/SKILL.md
├── commands/                       # 互換入口
│   ├── loop-status.md
│   ├── orchestrate.md
│   ├── pr-watch.md
│   └── team-run.md
├── prompts/                        # Codex custom prompts mirror
├── workflows/                      # 互換ワークフロースクリプト
├── scheduled-tasks/                # スケジュールタスク
├── templates/                      # PJテンプレート
│   └── project/
│       ├── AGENTS.md
│       └── ...
├── context/
│   ├── workflow-rules.md
│   ├── agent-team-routing.md
│   ├── team-run.md
│   └── loop-engineering.md
└── claude-compat/                  # Claude専用互換資産
```

## セットアップ確認手順

### 1. 前提条件
```bash
# GitHub CLI
gh auth status

# Codex CLI
which codex

# Cursor Agent（オプション）
which cursor-agent
```

### 1.5. ユーザー設定の初期化
```bash
# テンプレートをコピーして自分の情報を入力
cp ~/.codex/config.example.toml ~/.codex/config.toml
# config.toml を編集: model, service_tier, tools, auth などを設定
```

### 2. ファイル存在確認
```bash
# エージェント定義
ls ~/.codex/agents/*.toml

# ワークフロー互換スクリプト
ls ~/.codex/workflows/{tournament-ab,morning-kickoff,implementation-drive,evening-review}.js

# hooks.json
ls ~/.codex/hooks.json

# スケジュールタスク
ls ~/.codex/scheduled-tasks/{morning-kickoff,hour-calendar,jira-spec-poll,evening-review}/SKILL.md

# Skill正本と互換入口
ls ~/.codex/skills/{team-run,pr-watch,orchestrate}/SKILL.md
ls ~/.codex/commands/{loop-status,orchestrate,pr-watch,team-run}.md
```

### 3. config / hooks確認
```bash
# Goal tools と model routing
grep "features.goals" ~/.codex/config.toml
grep "gpt-5.5" ~/.codex/config.toml

# Hook登録
grep "post-cost-track" ~/.codex/hooks.json
grep "stop-harness-improve" ~/.codex/hooks.json
```

### 4. 動作確認
```bash
# ループステータス表示
# Codex で /prompts:loop-status または対応する command shim を実行

# 手動ワークフロー相当の確認
# 対応する scheduled-task Skill または workflow script を明示的に起動する
```

## コスト管理

### アラート閾値
| レベル | 金額 | アクション |
|--------|------|-----------|
| ok | $0-5 | 通常運用 |
| info | $5-15 | 日報に記載 |
| warning | $15-30 | モデルダウングレード検討 |
| critical | $30+ | 即時対応、`gpt-5.5` 対象を重要判断に絞り routine は `gpt-5.4` role へ寄せる |

### コスト追跡データ
- 日次ログ: `~/.codex/.local/cost-track/YYYYMMDD.log`
- 改善提案: `~/.codex/.local/harness-suggestions/YYYYMMDD_HHMMSS.json`

## 安全設計

1. **自律タスクの安全弁**: 信頼タスク（hour-calendar等）の auto_execute は確認なしで自律実行する方針。ただし金額・契約・人事・本番操作・対人連絡は必ず human_action に分類して実行しない（曖昧なものも human_action 側へ倒す）。外部書き込み（Jira起票/PR作成/Slack投稿）は冪等性ガード（既存検索→更新 or 新規）を必須とする。
2. **ハーネス改善の承認制**: harness-improver / evening-review の AGENTS.md・rules・context 改変提案は**自動適用しない**（自己改変は全自律の例外、必ず人間承認）。
3. **コスト追跡**: post-cost-track hook（実装済）+ evening-review のアラート（実装済）でコストを可視化。※ `budget.remaining()` による workflow 内ハードガードは**未実装（TODO）**。
4. **Worktree分離**: tournament-ab の**並列A/B実装**のみ isolation:"worktree" で競合を防止（比較用。勝者worktreeのメイン統合は手動）。implementation-drive の逐次サブタスクは隔離せず同一作業ツリーで積み増す（前段成果の上に実装）。
5. **セキュリティ判定（コード強制）**: tournament-ab は security 平均が閾値（≦2）以下の案を勝者から除外するハードガードを **Decide フェーズのコードで強制**（両案違反なら winner:null → implementation-drive 側も失敗扱い）。プロンプト文言だけに依存しない。
