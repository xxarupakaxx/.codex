# Agent Team Routing

この文書は、Codex が必要な Skill、plugin、worker、reviewer roleを選ぶ正本である。Phaseの順序は context/workflow-rules.md、artifact形式は context/memory-file-formats.md、model / service tierは rules/model-routing.md、Team Runは context/team-run.md を参照する。

## 責務境界と既定

leadは要件、route、統合、一次資料確認、fresh検証、最終判断、commit / push、外部writeを保持する。Skillは現在Phaseのdiscipline、workerは境界を切った実装、reviewerはmakerから独立した確認を担当する。pluginが使えることだけを理由にworkerを起動しない。

最初にlocal read、rg、既存test、決定的な小さな実行を行い、最小のrouteを選ぶ。大きなflow、固定全員review、件数合わせのspawnは既定にしない。user-invokedのSkill / commandは明示要求または既存の承認済み依頼が対象のときだけ起動し、通常のroute選択で自動起動しない。ユーザーが指定したSkillは先にそのSKILL.mdを全文確認する。第三者Skillの発見・評判・導入・更新・廃止は skill-governance を入口にし、人気順の自動導入や無審査promotionを行わない。

<!-- skill-governance-contract:routing:start -->
第三者Skillは `skill-governance` で候補catalogとactive runtimeを分離する。read-only inventoryだけをmodel-invokedとし、promotion、update、retirement、delete、runtime mutationはuser-invokedかつ人間承認を必須にする。
<!-- skill-governance-contract:routing:end -->

## Delegation Gate

worker / implementer / reviewerを起動する前に、次の全条件を評価する。

| 条件 | PASS |
|---|---|
| Local-first | leadがscopeと既存patternを先に確認し、一操作では閉じない |
| 委譲利益 | 速度、専門性、隔離、または独立証拠の利益が統合コストを上回る |
| 独立証拠 | objective、acceptance、成果物またはcheckerを独立に定義できる |
| Write scope | writerごとのowned_pathsがdisjoint、または対象ごとにwriterを一人へ固定できる |
| 外部副作用 | 外部writeがない、または対象・操作・承認が確定している |

同一fileの密結合作業、逐次依存、低価値の要約はleadが行う。Gateを満たした非自明な実装は、sessionのcollaboration capabilityがあればworker / implementerへ委任する。capabilityがないときは弱いmodelへfallbackせずleadが逐次実行し、不在理由を記録する。

### Delegation Decision

route、実装単位、acceptance、write scopeを決めた直後、対象成果物への最初のwriteより前に、05_log.mdへDecisionを保存する。decision_unit、gate、passed_conditions、failed_conditions、local_first_evidence、reason、write_scope、acceptance、lead_retainsを含める。lead実装、read-only、capability不在も理由を省略しない。material change後は旧判断をsupersedesで参照し、write再開前に再評価する。

workerへ渡す正規単位はWork Packetである。objective、scope、out_of_scope、owned_paths、acceptance_ids、constraints、capability_class、safety_decision_id、side_effects_requested、external_write_targets、approval_required、approval_evidence、dry_run_required、baseline、reality_contract、verification、dependencies、handoff_requirements、reviewer_focus、journey_scenarios、negative_paths、completion_targetを含める。空欄ではなく N/A: <理由> を使う。makerはEvidence Bundle draft、checkerはreview sectionを担当し、makerが最終判定を兼ねない。

## 非同期作業の心拍監視

継続監視を依頼された場合は、Lunaで状態を確認し、対応が必要なときだけ担当のSol taskへ引き継ぐ。監視を理由に作業範囲や権限を広げない。

- 起動前にheartbeatの実行model、監視対象、間隔、通知先を確認する。Lunaを指定できない場合は、その制約を報告し、別modelやcronへ黙って置き換えない。
- `list_threads`で対象を絞り、`wait_threads`の短いsnapshotとcursorで前回との差分を確認する。詳細が必要な対象だけ`read_thread`で読む。全履歴の再読、常時待機する子Agent、監視ごとの一斉spawnは避ける。
- 通知対象は、新しい失敗、確認済みの停滞、依存作業の完了、人間の判断が必要な状態とする。idle表示や更新時刻だけで失敗・停滞と断定しない。同じ事象を重複通知せず、変化がなければno-opとする。
- 通知先はthread IDと実際の担当・依頼範囲で確認する。タイトルの類似だけで送らず、担当が不明ならユーザーに確認する。通知には事実、根拠、影響、求める対応だけを含め、secretや会話全文は転送しない。
- Lunaの責務は監視と許可されたtask内通知までとする。Solは元の依頼と証拠を再確認して判断・修正する。承認待ちは承認済みと扱わず、新規task作成、既存taskのmodel変更、外部writeを自動で追加しない。
- 設定保存、実際の心拍実行、通知の到達は別々に検証する。監視対象がなくなったら停止し、対象や通知先が変わったら設定を見直す。

## Context BoundaryとJIT brief

alignment（grilling）は未決事項を明らかにするだけで実装しない。durable spec / handoffは確認済みの合意だけを保存し、別sessionの起動や外部投稿を自動化しない。実装単位は会話全文でなく、目的、次の未完了Task、対象、依存、検証、決定、不明点、source参照から成るJIT briefで開始する。secret、認証済みsession、全tool outputを渡さない。

task-contextは`~/.codex/scripts/task-context.py`を明示root・指定task付きで呼び、引数と出力schemaはcontext helperの実装とtestを正本にする。routing側で新schemaを作らず、list / briefはread-onlyに限定する。

## Route選択

| 状況 | route | 境界 |
|---|---|---|
| 既知の小さな実装 | direct lane / implementing-work | acceptanceとfresh検証で閉じる |
| routeが未知の大規模作業 | mapping-large-projects | decision map後にspecまたは実装へ渡す |
| 合意済みの要件をspecへ残す | writing-specifications | tracker公開は別gate |
| Approved specを複数sliceへ分ける | creating-tracer-tickets | writerとblocking edgeを固定する |
| 依存DAGやCold-Start Briefが必要 | blueprint | 各WUのPhase 0–5.5は省略しない |
| 複数turnでGoal、Team Journal、Review Heatが有効 | team-run | user-invoked overlayとして使う |
| 固定順の専門chainが必要 | orchestrate | 外部副作用は別gate |
| UI/UXの新しい判断 | designing-ui-ux | User Validation / HTML gateを先に通す |
| 固定点からの差分レビュー | reviewing-code | Phase 4のseverityと出荷判定を置き換えない |
| goal再構築から方案・security・実装を順に監査 | reviewing-codebases-architecture-first | read-only。既存codebase-reviewのissue収集契約を置き換えない |
| 1–3 moduleのarchitecture改善 | improving-architecture | broad refactorの許可ではない |

実装入口のcanonical nameは `wayfinder`（mapping-large-projects）、`to-spec`（writing-specifications）、`to-tickets`（creating-tracer-tickets）、`implement`（implementing-work）、`teach`（teaching-concepts）である。`batch-grill-me` と `to-questionnaire` は明示起動時だけのin-progress入口として扱う。retired nameを新しい既定routeに戻さない。

### Delivery lifecycle routing

Workflow routeとLocal / Fast / Standard / Heavy / Judgmentのcapability classは別に決める。

- fast-track: low-risk direct requirement。必要時だけ一名のchecker。
- prd-flow: requirement-parser → read-only prd-reviewer → planner → maker → checker。
- multi-packet-flow: Approved PRDをpacketへ分け、packetごとにwriterを一人に固定する。

必要modelをruntime rosterから解決できない場合はROUTING_BLOCKEDで停止する。承認なしの外部write、権限、課金、認証、不可逆操作、runtime policy変更はWAITING_HUMANで停止する。completion_targetとcompletion_stateはmemory-file-formatsの定義に従う。

## SkillとHTMLの条件付き入口

状況に応じて読む最小Skillを選ぶ。

- 調査不足: research / iterative-retrieval / search-first。
- 実装: implementing-work、必要ならtddまたはdiagnosing-bugs。
- 品質: verification-loop、reviewing-code、リスクに合うchecker。
- 計画表示: viewing-plans。html-plan route、manifest、Codemap freshness、static/browser gateを先に確認する。
- 複数turn協調: team-run。graph-engineeringは複数loop、typed state、異なるauthorityが必要な場合だけ使う。
- architecture: modeling-domains / designing-codebases / improving-architectureを対象範囲に応じて使う。

HTMLを生成・更新・配布する場合は context/html-artifact-contract.md と config/html-surfaces.jsonを確認し、登録済みproducerだけを使う。新しい図の正本はSVGで、MarkdownへMermaidを生成しない。計画は30_plan.htmlを編集し、`~/.codex/scripts/sync-roadmap.py`で検査・生成・atomic publishする。派生roadmap.htmlの手編集やstale source fallbackはしない。

## 改善候補の扱い

失敗や改善案は候補として記録し、trialで回帰検査と外部feedbackを確認してからadoptを判断する。adoptにはowner、承認、rollback、review dateを付ける。外部feedbackなしの自動policy promotion、Skill / hook / contextの自動更新は行わない。実測token / byte / 時間と、行数・呼び出し数・概算tokenのproxyを別々に記録する。

## External Write Gate

routeや委譲は外部writeを許可しない。issue、PR、comment、label、Slack、Calendar、Drive、deploy、secret store、public share、git pushは対象・差分・principal・承認証跡を確定してからleadが行う。commitは検証成功後にproject policyへ従って行う。権限errorやcontext不一致を別principalへ自動切替しない。workerへsecret実値、secret reference、認証済みsession情報を渡さない。

commit / PR文案だけは、価値がある場合に`~/.codex/scripts/draft_delivery_message.py`経由のtoolなしFast workerへ渡せる。ephemeral、read-only sandbox、user config無効、shell / browser / apps / multi-agent無効で起動し、文案とclaim_referencesだけを返す。Fast workerはGit/GitHub tool、approval、commit、push、PR作成を持たない。親がtrusted snapshotとEvidenceを検証し、external writeを実行する。

## IntentとFallback

intentの詳細な組合せは、対象Skill、projectのAGENTS.md、team-run / HTML / securityの正本を参照する。routeが重なるときはuser-visible deliverableを所有するrouteをprimaryにし、他をsourceまたはreviewへ限定する。

Skill、plugin、collaboration capabilityが使えないときは存在を捏造しない。local fallbackまたはlead逐次実行へ戻し、同じacceptance・安全境界・fresh検証を維持する。主経路の失敗を旧generatorや別CLIへ黙ってfallbackしない。
