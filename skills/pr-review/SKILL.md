---
name: pr-review
description: PRレビュー。PR番号・ブランチ名指定時またはレビュー依頼時に使用。サブエージェント並列レビュー＋重要度別Roundで対話的にユーザーと確認。
context: fork
allowed-tools: Bash(gh:*), Read, Grep, Glob
---

# PRレビュー

## トリガー条件

- PRレビューを依頼された場合
- PR番号またはブランチ名が指定された場合

## 実行手順

### 1. PR情報の取得

```bash
# PR詳細を取得
gh pr view <番号> --json title,body,author,headRefName,baseRefName,files

# diffを取得
gh pr diff <番号> > /tmp/pr-<番号>.diff
```

### 2. PJルールの確認

CLAUDE.mdを読み、以下を把握:
- アーキテクチャルール
- 命名規則
- コーディング規約

### 3. サブエージェント並列レビュー

**CRITICAL: `claude -p` CLIは使わない。`multi_agent_v1.spawn_agent` で専門サブエージェントを並列起動すること。**

変更ファイル一覧を取得後、コアレビューアー + 変更内容に応じた追加レビューアーを **`multi_agent_v1.spawn_agent` で並列起動**。

#### コアレビューアー（常時起動）

| subagent_type | レビュー観点 |
|---------------|-------------|
| `security-reviewer` | セキュリティ（認証認可、入力検証、機密情報露出、インジェクション） |
| `perf-reviewer` | パフォーマンス（N+1、メモリリーク、アルゴリズム効率） |
| `arch-reviewer` | アーキテクチャ（レイヤー依存、責務分離、既存パターン整合性） |
| `test-reviewer` | テスト（カバレッジ不足、エッジケース、テストの独立性） |
| `code-quality-reviewer` | コード品質（命名、重複、関数長、ネスト深度） |

#### 追加レビューアー（変更内容に応じて選択）

PR diffの内容を分析し、該当するトリガーに合致するレビューアーを追加起動する。

| トリガー（diffに含まれる内容） | subagent_type | レビュー観点 |
|---|---|---|
| try/catch、エラーハンドリング、外部API呼び出し、リトライ処理 | `error-handling-reviewer` | エラー握りつぶし、リトライ/サーキットブレーカー欠如、リソースリーク |
| ログ出力、メトリクス、トレース、console.log | `observability-reviewer` | 構造化ログ、ログレベル、機密情報のログ出力、トレース欠如 |
| async/await、Promise、Worker、並行処理、トランザクション | `concurrency-reviewer` | レースコンディション、デッドロック、非同期エラー処理 |
| APIルート/エンドポイントの追加・変更 | `api-contract-reviewer` | 後方互換性、RESTful規約、エラーレスポンス形式 |
| JSX/TSX、UIコンポーネント、CSS | `a11y-reviewer` | WCAG準拠、ARIA属性、キーボードナビゲーション |
| 翻訳キー、i18n関連、ロケール処理 | `i18n-reviewer` | ハードコード文字列、ロケール依存処理 |
| 個人情報処理、認証、権限、ライセンス | `compliance-reviewer` | GDPR対応、監査ログ、OSSライセンス互換性 |
| Dockerfile、CI/CD設定、IaC、環境変数 | `devops-reviewer` | Dockerベストプラクティス、CI/CD設定、シークレット管理 |

**IMPORTANT**: 追加レビューアーはdiffの内容から自動判断する。判断に迷う場合は追加する側に倒す（見逃しより過検出のほうが安全）。

**各サブエージェントに渡す情報:**
- PR diff（`/tmp/pr-<番号>.diff`）のパス
- 変更対象ファイルのフルパス一覧
- PJのCLAUDE.mdのパス
- レビュー観点と出力形式（CRITICAL/IMPORTANT/MINOR 分類。CLAUDE.md `severity` 標準）

**サブエージェントへのプロンプトテンプレート:**
```
以下のPR変更を{観点}の観点でレビューしてください。

## レビュー対象
- PR diff: /tmp/pr-<番号>.diff
- 変更ファイル: [ファイルパス一覧]

## PJルール
[CLAUDE.mdの内容を読んで参照してください: <CLAUDE.mdパス>]

## 出力形式
問題を以下の分類で出力してください。問題がなければ「指摘なし」と出力:

### CRITICAL
- [ファイル:行番号] 指摘内容と理由

### IMPORTANT
- [ファイル:行番号] 指摘内容と理由

### MINOR
- [ファイル:行番号] 指摘内容と理由
```

### 4. 結果の統合

各サブエージェントの結果を統合し、重複を排除。同じ問題が複数の観点から指摘された場合は最も高い重要度を採用。

### 5. Round形式の対話的確認（IMPORTANT）

**レビュー結果をユーザーに一括レポートとして投げるのではなく、重要度別Roundで対話的に確認する。**

#### Round 1: CRITICAL（マージブロッカー）

CRITICAL指摘がある場合、AskUserQuestionで提示:

```
各CRITICAL指摘について:
- question: "[ファイル:行番号] 指摘内容の要約。詳細: ..."
- header: "CRITICAL"
- options:
  - "修正する": この指摘に対応する修正を行う
  - "対応不要": 理由を説明して対応しない判断とする
  - "後で対応": PR外で別途対応する
```

**1回のAskUserQuestionで最大4問まで。5問以上は複数回に分割。**

CRITICAL指摘が0件の場合はRound 1をスキップし、その旨を伝えてRound 2へ。

#### Round 2: IMPORTANT（強く推奨）

Round 1の対応完了後、IMPORTANT指摘をAskUserQuestionで提示:

```
各IMPORTANT指摘について:
- question: "[ファイル:行番号] 指摘内容の要約。詳細: ..."
- header: "IMPORTANT"
- options:
  - "修正する": この指摘に対応する修正を行う
  - "対応不要": 理由がある場合
  - "後で対応": 別タスクで対応
```

IMPORTANT指摘が0件の場合はRound 2をスキップ。

#### Round 3: MINOR（改善推奨）

Round 2の対応完了後、MINOR指摘をAskUserQuestionで提示:

```
各MINOR指摘について:
- question: "[ファイル:行番号] 指摘内容の要約"
- header: "MINOR"
- options:
  - "修正する"
  - "対応不要"
  - "後で対応"
```

MINOR指摘が0件の場合はRound 3をスキップ。

### 6. 最終レポート

全Roundの結果を統合してレポート:

```markdown
# PRレビュー: #<番号>

## 対象
- PR: #<番号> - <タイトル>
- ブランチ: <ブランチ> → <ベース>

## レビュー結果サマリ

### コアレビュー
| 観点 | CRITICAL | IMPORTANT | MINOR |
|------|----------|-----------|-------|
| セキュリティ | 0 | 1 | 0 |
| パフォーマンス | 0 | 0 | 2 |
| アーキテクチャ | 1 | 0 | 0 |
| テスト | 0 | 1 | 1 |
| コード品質 | 0 | 0 | 3 |

### 追加レビュー（該当する場合のみ表示）
| 観点 | CRITICAL | IMPORTANT | MINOR |
|------|----------|-----------|-------|
| エラーハンドリング | 0 | 0 | 1 |
| ... | ... | ... | ... |

## 対応状況

### CRITICAL
- [x] [指摘] → 修正済み / 対応不要（理由） / 後で対応

### IMPORTANT
- [x] [指摘] → 修正済み / 対応不要（理由） / 後で対応

### MINOR
- [x] [指摘] → 修正済み / 対応不要（理由） / 後で対応

## マージ推奨: [Yes/No/条件付き]
- CRITICAL未対応: [あり/なし]
- IMPORTANT未対応: [あり/なし]
```

## 問題の分類（CLAUDE.md severity 標準準拠）

| 分類 | 説明 | 対応 |
|-----|------|------|
| CRITICAL | バグ、セキュリティ、破壊的変更 | マージ前に必須修正 |
| IMPORTANT | アーキテクチャ違反、テスト不足、一貫性違反 | 強く推奨 |
| MINOR | 命名、コメント、軽微な改善 | 改善推奨 |
| Good | 良い実装 | 賞賛（Roundには含めない） |

## 実績由来の知見

- **gh認証フォールバック**: `gh auth status` が失敗する場合は `git fetch origin pull/<id>/head:refs/remotes/origin/pr/<id>` で直接取得し、`origin/<base>...origin/pr/<id>` で差分比較する。private repoではまず `gh auth switch` でアカウント切替を試す。6件のPRレビューで実証済みの手順（出典: memories/rollout_summaries/2026-06-15T02-19-06-lD3O-pr_review_booking_event_redeem_cancel_2945.md「Key steps」、memories/rollout_summaries/2026-06-23T08-02-54-uEIX-pr_3012_review_push_billing_refund_slack_fix.md「Key steps」、MEMORY.md:365,268）
- **環境ノイズとコード指摘の分離**: サンドボックス起因の検証失敗（DB接続不可、認証エラー等）をコードの問題として報告しない（出典: memories/rollout_summaries/2026-06-16T04-32-09-W9wb-pr_2921_booking_event_reminder_review.md「Failures and how to do differently」）
- **サブエージェント起動不可時の代替**: sub-agent起動がスレッド/ポリシー制約で使えない場合、並列レビューを断念せず優先度の高い観点（security, concurrency, API contract, test）から手動レビューで代替する（出典: memories/rollout_summaries/2026-06-15T03-24-07-Cneo-pr_review_2940_booking_event_validation.md「Failures and how to do differently」、memories/rollout_summaries/2026-06-22T05-52-03-qgnt-dependency_tarball_ci_pr_and_review.md「Failures and how to do differently」）
- **短い依頼の解釈**: 「pr-reviewして」だけの依頼はスコープ確認なしで全ワークフローを開始する。「修正してプッシュして」が付けば実装修正とpushまで含む（出典: memories/rollout_summaries/2026-06-15T02-19-06-lD3O-pr_review_booking_event_redeem_cancel_2945.md「Preference signals」、memories/rollout_summaries/2026-06-16T03-53-25-JmlJ-pr_2954_billing_review_fix_push.md「Preference signals」）
- **レビューコメント返信の404フォールバック**: REST経由の直接返信が404の場合、GraphQLでレビュースレッドIDを取得し `addPullRequestReviewThreadReply` を使う（出典: memories/memory_summary.md:27,67、memories/raw_memories.md:2338-2339,2347）
