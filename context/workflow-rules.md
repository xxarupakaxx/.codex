# 作業規模と完了境界

新規の作業計画全文とレビューの参照先は、[セッションダッシュボードの計画契約](session-dashboard.md#計画の正本とレビュー)に従う。計画の正本はHTML内の安定したanchorと版で指定し、目的・計画レビュー、実装、検証、完了レビューを同じ本文へ結ぶ。審査対象の本文と現行本文を実装前・完了前に照合する。以下の30_plan・旧CLI・機械審査形式は過去taskの互換記録であり、新方式の開始条件には使用しない。審査・承認・検証の実質的な条件は維持する。

## 現行の表示方式

新規・再開セッションの表示は[セッションダッシュボード](session-dashboard.md)に統一する。routeは`session-dashboard`。通常作業にも最初の依頼でHTMLを作成して開き、節目に更新する。旧Roadmapのsync、generator、Task Hub、snapshot生成、旧CLIへのroute入力は行わない。

以下の`roadmap` / `explicit-roadmap`とその表示・同期・機械形式の説明は過去artifactを読むための互換記録であり、新規作成や自動実行の指示には使わない。既存の要件・承認・未完了gateは保持する。作業規模・実装・審査・検証の品質条件は引き続き適用し、新方式では計画・完了条件・根拠をHTMLと必要な正本へ記録する。ダッシュボードを作るだけで通常作業を大規模な管理工程へ変更しない。

この文書はCodexの作業開始時の入口である。Phase 0で以下を判断し、必要な参照だけを読む。モデル名による工程の固定はしない。

## Phase 0: 目的と影響範囲を把握する

目的、完了条件、対象、既存の制約をユーザー依頼と関連ファイルから確認する。判断に影響する仮定・不明点は短く伝える。対象の実装・設定・testを先に調べ、関連が分かった依存へ読む範囲を広げる。

| 状況 | 進め方 |
|---|---|
| 質問、調査、局所的な編集・修正で、影響と検証方法が明確 | 下記の通常作業 |
| 複数工程の依存、広い設計判断、複数writer、継続共有・引継ぎが必要 | [管理する作業](workflow-phases.md) |
| 計画書・Roadmap・Team Runを明示要求、または既存の管理taskを継続 | [管理する作業](workflow-phases.md)と該当Skill |

ファイル数だけで決めない。通常作業の途中で依存や重要な未決事項が増えたら、管理する作業へ移り、以後の計画と検証を記録する。既存の管理taskの未完了gateを、通常作業への切替で消さない。

外部write、権限・認証・課金、不可逆操作、runtime policy変更では、規模によらず[User Validation Gate](workflow-details.md#user-validation-gate)と[Review escalation](workflow-details.md#review-escalation)を確認する。新しいUI/UX判断には同文書のUI/UX Design Approvalを適用する。

## 通常作業は必要な変更と直接検証で閉じる

完了条件に沿って実装し、変更に対応する既存の検証を行い、その変更に起因する失敗を修正する。実行や画面確認を含む依頼では、起動・結果の確認・必要な修正まで続ける。調査・計画だけの依頼はその成果で完了する。

- 作業記録は会話の要点と最終報告で足りる。memory directory、Phaseごとのartifact、Delegation Decision、派生図生成、Roadmap同期を一律には要求しない。
- code変更では呼出元・影響先・関連testを必要な範囲で確認する。この範囲が把握できなければ調査し、複数moduleのarchitecture/data flowを計画へ残す必要があれば、明示fragmentとArchify figureへ記録する。
- batch、queue、durable workflow、外部API同期、pollingを変更する場合は、`rules/durable-workflow-safety.md`で最大件数時のpayload、履歴増加、rate limit、全終端状態の収束を検証する。dry-runの非更新性だけで処理容量や停止性を合格扱いにしない。
- testは変更箇所と影響先に合わせて選ぶ。全suiteはprojectの必須条件、共通基盤への影響、関連検証だけでは解消できない懸念がある場合に実行する。文書だけの変更には差分・参照・内容の確認を使う。
- 新しい変更、失敗、未解消の懸念がなければ、合格済みの検証を繰り返さない。必要な独立reviewは具体的なriskに対応させる。
- 変更量は`rules/complexity-budget.md`に従って判断・報告する。通常作業に専用の計画artifactは要求しない。

完了条件と影響範囲の既存契約を満たし、完了を妨げる既知の問題がなくなったら報告する。追加の機能や任意の調査を、終了を延ばす理由にしない。

## 管理する作業の参照

[workflow-phases.md](workflow-phases.md)に既存のPhase 0–5.5、log-only / roadmap / explicit-roadmap、Acceptance Contract、Delivery lifecycleを置く。`log-only`は記録を管理するrouteであり、通常作業の別名ではない。通常作業用のroute値を既存CLIへ渡さない。

管理する作業では、[memory-file-formats.md](memory-file-formats.md)のartifactと[agent-team-routing.md](agent-team-routing.md)の委譲契約を使う。code変更の影響は対象source、呼出元・呼出先、直接import、style、testを確認し、architecture/data flowを計画へ載せる場合だけ明示fragmentを作る。計画表示は`skills/viewing-plans/SKILL.md`を参照する。

## Delivery lifecycleと自律LOOP

管理taskの詳細は[Delivery lifecycle](workflow-phases.md#delivery-lifecycleと自律loop)を使う。`completion_target`に対して `implemented < wired < piloted < effective < adopted` の実証済み段階だけを報告し、不足は WIRE / PILOT / MEASURE / ADOPT へ戻す。必要な承認がなければWAITING_HUMAN、必要modelを解決できなければROUTING_BLOCKEDとする。

### Workflow route

管理taskのfast-track / prd-flow / multi-packet-flowとmodel capability classは別軸である。選択条件、成果物、遷移は[管理する作業のWorkflow route](workflow-phases.md#workflow-route)を参照する。

<!-- skill-governance-contract:workflow:start -->
外部Skillのruntime変更は、固定revision catalog、全内容hash、安全審査、価値eval、人間承認、Codex・Claude parity、配布証明の順にgateする。自動install、無審査update、自動deleteは行わない。
<!-- skill-governance-contract:workflow:end -->
