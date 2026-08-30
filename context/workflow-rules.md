# 作業ルール（Phase 0–5.5）

この文書は、Codex user-scope の作業順序と遷移 gate の正本である。スキルやコマンドはここを参照し、Phaseの説明を複製しない。artifactの形式は context/memory-file-formats.md、委譲とSkillの選択は context/agent-team-routing.md、条件付きgateは context/workflow-details.md、Task Workspaceは skills/viewing-plans/SKILL.md と context/codemap.md を参照する。

## 既定lane

通常の作業は、把握（Phase 0–1）→計画（Phase 2–2.5）→実装と検証（Phase 3–4.5）→完了と学習（Phase 5–5.5）で進める。既存のPhase番号、成果物名、互換表示は維持する。

Phase 0で次のrouteを一つ記録する。

| route | 適用 | 必須の表示・保存 |
|---|---|---|
| log-only | 手順と完了条件が既知で、一回の実行と検証で閉じる | 05_log.md。30_plan、HTML、Evidence Bundleは要求しない |
| roadmap | 設計判断、複数Task、依存、継続共有、引継ぎがある | 30_plan.md → sync → roadmap.html |
| explicit-roadmap | ユーザーが計画書またはRoadmap表示を求めた | roadmapと同じ。表示を省略しない |

routeは変更量だけで決めない。途中で設計判断や依存が増えたら、05_log.mdに変更理由を残し、roadmapへ昇格してから成果物を作る。log-onlyでも安全条件、Phase記録、freshな直接検証は省略しない。Fast Track、Blueprint、Goal readiness、UI/UX、HTML artifactの条件付きgateは context/workflow-details.md を発火時だけ読む。

### Phase 0: 準備

1. 最も近い AGENTS.md とプロジェクト固有の正本を読み、MEMORY_DIR（未定義なら .local/）と作業境界を確定する。
2. システムの日付で MEMORY_DIR/memory/YYMMDD_<task>/ を作り、05_log.mdに指示、Goal、acceptance、仮定、不明点、重要なtrade-off、roadmap_routeを記録する。
3. session ID、次にthread IDの完全一致で handover とtaskを復元する。一致しない候補を更新時刻や名前だけで選ばない。active / waiting / verifying が一件だけの場合だけ互換fallbackを使い、選択理由を記録する。
4. memories、solutions、issuesをローカル検索する。調査価値があり、Delegation Gateを満たす場合だけ独立探索を追加する。
5. コード変更は編集前にCodemap gateを通す。workspace rootを検査対象、codemap成果物をtask memoryだけに置き、stale / missing / mismatch / insufficientならrefreshしてから編集する。

### Phase 1: 把握と調査

ローカルの実装、test、設定、既存artifactを先に読み、影響範囲と実行経路を確認する。変化するAPI、未知の仕様、明示依頼には一次資料を確認し、出典と不確実性を05_log.mdへ残す。既知手順の低riskなlog-onlyでは不要な外部調査を強制しない。

GO / CONDITIONAL / NO-GO / DEFERを、実現可能性、工数、依存、リスクとともに記録する。NO-GOまたはDEFERは理由と再開条件を保存する。Goalを使うtaskは観測可能なbaselineを確認し、goal-setterのReadiness checkを通す。Goalのoutcome、Done、evidence、scopeを黙って置き換えない。

### Phase 2: 計画

roadmap routeでは、30_plan.mdを人とLLMが読む正本として保存する。Taskごとに目的、変更対象、実装、成果物、検証、blockedBy、acceptance ID、source根拠、write scopeを対応させる。roadmap.htmlとroadmap-snapshot.jsonは既存parser / generatorによる派生viewであり、手で編集しない。

Roadmapのschema、v2とlegacyの境界、source hash、timeline、invalid時の停止は context/memory-file-formats.md に集約する。LLMにHTML全文を書かせず、保存済み30_plan.mdを`~/.codex/scripts/sync-roadmap.py`へ渡し、sync自身の検査・生成・publish結果を使う。Phase 2 artifact保存後は全routeで次のtrusted local executorを実行し、exit codeとJSONを05_log.mdに記録する。Phase 3/4/5も同じTASK、root、run-idでphaseだけを変える。log-onlyはskip証跡を残す。

    python3 ~/.codex/scripts/sync-roadmap.py TASK --workspace-root WORKSPACE --memory-root MEMORY/memory --run-id RUN --phase 2

コード変更では、rules/complexity-budget.mdの方法で要素ごとのtargetを記録し、実装時actualとreview時varianceを更新する。targetはsoft goalであり、必要な機能・安全性・testを行数合わせで削らない。materialな技術判断だけADR criteriaに従って記録する。deepening-planは追加調査で計画が変わる場合だけ使う。

計画reviewはリスクに応じた最小の独立checkerを選ぶ。固定全員reviewや固定roundを要求しない。CRITICAL、正しさに関わるIMPORTANT / MINORを修正し、未解決findingが残る場合は修正→fresh検証→必要なreviewを続ける。

### Phase 2.5: Acceptance Contract

roadmap routeでは、各Taskのacceptanceをcheckpointまたは同等のartifactへ明示する。Goal outcome / requirement / direct requirement → TaskまたはWU → acceptance → evidence の対応を一意にたどれるようにする。negative pathとholistic checkを含め、未対応のacceptanceや未検証の自己申告で完了にしない。log-onlyにはこのartifactを強制しない。

### Phase 3: 実装

開始前に最新のDelegation Decision、route、acceptance、write scopeを照合する。独立した実装単位は条件が揃うときだけworker / implementerへ渡し、同じfileを複数writerに割り当てない。小さく密結合した作業はleadが逐次実装する。

実装者にはJIT briefだけを渡す。briefは目的、次の未完了Task、対象、依存、検証、決定、不明点、source参照を含み、会話全文やsecretを含めない。task-contextは`~/.codex/scripts/task-context.py`を明示root・task付きで使い、引数と出力schemaはそのhelperの実装とtestを正本として扱う。ここで別schemaを発明せず、要求外の抽象化、設定、refactor、外部write、policy promotionを追加しない。

### Phase 4: 品質確認

freshな直接検証を先に行い、対象のAGENTS.md、test、lint、typecheck、HTML/Codemap gateを実行する。roadmap routeのcompletion検査は既存syncとEvidence Bundle validatorへ接続し、log-onlyにEvidence Bundleを強制しない。構造検査は意味的なuser outcomeの代替ではない。

変更リスクに応じて最小の独立checkerを選ぶ。レビュー結果を05_log.mdへ全件記録し、CRITICALと正しさに関わる指摘は修正する。LLMだけの反復を無制限に続けず、必要なら静的検査、外部feedback、人間gateを挟む。未解決finding、stale source、対応しないacceptance、計画外のwriteがあればPhase 2または3へ戻す。

### Phase 4.5: 引継ぎ

再開に必要なhandover、変更量のtarget / actual / variance、検証結果、残課題を保存する。Markdownは全文を再読し、矛盾と重複を同じturnで解消する。

## Delivery lifecycleと自律LOOP

これは既存のartifact/state adapterを参照する契約であり、新しいlifecycleを追加しない。scripts/agent_delivery_lifecycle.pyは状態と次actionを検査し、workflow本文の第二の正本にはしない。

| state | 必要条件 | 次action | 停止・戻り先 |
|---|---|---|---|
| RECEIVED | taskと05_log.md | SURVEY | 調査不能なら WAITING_HUMAN |
| SURVEYED | route decision | PRDまたはWork Packet | model不在なら ROUTING_BLOCKED |
| IMPLEMENTED | Work Packet | REVIEW | 実装失敗はbounded retry |
| REVIEWED | CRITICAL / IMPORTANTが0 | Evidenceとcompletion targetを照合 | findingはFIX、不足は WIRE / PILOT / MEASURE / ADOPT |
| DELIVERED | delivery evidence | 完了またはdefect record | 漏れはRECORD_ESCAPED_DEFECT |
| REPLAYED | replay PASS | COMPLETE | 防止不能ならWAITING_HUMAN |

completionは単一booleanにせず、implemented < wired < piloted < effective < adopted の順で扱う。unit testだけでwired、sample 0件でpiloted、baselineなしでeffective、owner・承認・rollbackなしでadoptedと判定しない。要求されたcompletion_targetまで届かない場合は完了報告をせず、WIRE / PILOT / MEASURE / ADOPTの不足工程へ戻す。retry上限、承認なしの外部write、権限・課金・認証・不可逆操作・runtime policy昇格はWAITING_HUMANで停止する。必要なmodelを解決できなければ弱いmodelへfallbackせずROUTING_BLOCKEDで停止する。

### Workflow route

Workflow routeは工程の形であり、Local / Fast / Standard / Heavy / Judgmentのcapability classとは別軸である。

- fast-track: low-riskなdirect requirement。必要時だけ一名のcheckerを使う。
- prd-flow: Approved PRD → Work Packet → maker → checker → Evidence。
- multi-packet-flow: Approved PRDを独立packetへ分け、packetごとにwriterを一人に固定する。

### Phase 5: 完了

変更内容、検証、review、残課題、route、completion_state、completion_target、commit / pushの状態を報告する。構文・機械PASSとuser outcomeの達成を分ける。コード変更は変更量をtarget / actual / variance / reasonで示す。measured tokens（tokenizerで実測した入出力token）とmeasured bytes（読込・書込byte）、proxy（行数、呼び出し数、推定token）を別項目にし、proxyを実測tokenと呼ばない。external writeは承認証跡がある場合だけ行う。

### Phase 5.5: Compound / 改善

再利用価値のある失敗や成功だけを、候補→trial（回帰検査と外部feedback）→adoptの順で記録する。adoptは人間承認、owner、rollback、review dateを持つ。外部feedbackなしの自動policy promotion、Skill / hook / contextの自動更新は行わない。知見はmemories / solutionsのfrontmatterとrelatedを保ち、phasesは新規生成時に付ける。

## 安全と完了境界

外部サービスへの投稿・更新、public share、git push、権限・課金・認証変更、削除・不可逆上書き、secret操作は対象、差分、承認、dry-runを確定してから行う。権限errorやcontext不一致を別principalへ自動切替しない。主経路の失敗を旧generatorや別CLIへ黙ってfallbackしない。削除・改名なし、user由来dirtyを保持し、leadが統合・一次資料確認・fresh検証・最終判断を担う。

関連する詳細:
- context/memory-file-formats.md
- context/agent-team-routing.md
- skills/viewing-plans/SKILL.md
- context/codemap.md
- context/html-artifact-contract.md と config/html-surfaces.json
- rules/model-routing.md、rules/complexity-budget.md、rules/adr-criteria.md、rules/security.md
