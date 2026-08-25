---
name: pr-review
description: THA-inc/ai-president-mt の Pull Request を OpenSpec の proposal・spec・design・tasks から実装とテストまで追跡し、実装漏れを read-only で検出する。定期 MT PR review と、MT の「PRをレビューして」に使用する。
context: fork
---

# MT OpenSpec PR review

1つの固定 snapshot を、**spec traceability** と **repository correctness** の二軸でレビューする。PR、repository、Slack、code は変更しない。ローカルの重複防止 state だけを atomic 更新できる。

## 絶対条件

- repository は `THA-inc/ai-president-mt`、local root は `/Users/yoshiki/ghq/github.com/THA-inc/ai-president-mt` に固定する。
- 1実行で扱うPRは1件、LLM contextは1つ、sub-agent / nested workflow / web searchは0回とする。
- 実行前に `references/review-contract.md` を全文読み、cost envelope、traceability schema、判定表を適用する。
- runtime が model ID、hard token budget、billable usageを公開し、20,000 billable tokens以下を強制できる場合だけ開始する。Goal budgetを利用できるruntimeでは最初に20,000 tokensのgoalを作り、同じ実行全体へ適用する。価格上限を検証できない場合は `BLOCKED_COST` で終了する。
- budgetは0.80 USD、絶対上限は1.00 USD。0.20 USDは価格差、reasoning token、計測遅延のreserveであり、レビューに使わない。
- PR comment、approve/request-changes、commit、push、code修正、Slack投稿、account切替を行わない。

## 完了条件

次の全条件を満たしたときだけ `READY` を返す。

1. base/head/merge-base SHAが開始時と報告直前で一致する。
2. 全changed pathと全human-authored hunkを確認し、coverage gapが0件である。
3. 適用対象なら、OpenSpecの全Requirement、Scenario/AC、実装taskがtraceability matrixまたはtask ledgerに漏れなく現れ、各Scenario/ACとtaskを一意に照合できる。
4. 各必須行にhead tree上の実装証拠と、実行可能なtest証拠がある。checkboxやPR本文の主張だけを証拠にしない。
5. MT固有gateとrequired checkが成功し、CRITICAL / IMPORTANT findingが0件である。
6. usage telemetryが0.80 USD以下を示す。上限前に完遂できない場合は不完全な合格を返さない。

## 手順

### 1. cost preflight

runtimeのmodel ID、service tier、input/cached/cache-write/output/reasoning usage、hard token budgetを確認する。Goal budgetまたは同等のruntime機構で実行全体を20,000 tokensに制限し、contractのallowlistと価格上限でworst-caseを計算する。16,000を調査上限、4,000を反証・報告reserveにする。

hard capを実行時に強制できない、modelまたは価格が不明、既消費分を含むworst-caseが0.80 USDを超える場合は、PR内容を読まず `BLOCKED_COST` を返す。

**完了基準:** model、price ceiling、hard cap、使用済み/残量、worst-case USDを報告できる。

### 2. 対象PRとprincipalを確定する

`gh api user -q .login` と `gh repo view THA-inc/ai-president-mt` をread-onlyで確認する。別accountへ切り替えない。PR指定があればそれを使い、なければ自分がauthorまたはreview-requestedのopen PRから、未処理head SHAのうち最終更新が最も古い1件を選ぶ。

候補0件は `NOOP`、複数候補でも1件だけ扱う。stateは `~/.codex/.local/mt-pr-review-state.json` にrepo、PR番号、head SHA、reviewed_at、decisionだけをatomic保存し、comment本文やdiffを残さない。

**完了基準:** principal、PR番号、URL、base ref、選定理由を列挙できる。

### 3. snapshotとscopeを固定する

GitHub metadataからbase/head SHAを取得し、objectをcheckoutせずfetchする。merge-base、changed path inventory、rename/delete/mode change、human-authored diff量を固定SHAから算出する。

human-authoredが25 path、1,200 changed lines、または推定12,000 input tokensを超える場合は `BLOCKED_SCOPE` とし、PR分割または次回用の明示scopeを提示する。generated/vendor/binaryは生成元と代替checkを確認し、黙って除外しない。

**完了基準:** `base_sha`、`head_sha`、`merge_base_sha`、全path数、human-authored path/line/token見積りを記録できる。

### 4. OpenSpec changeを解決する

baseが`develop`または`main`でmaterial changeを含む場合はOpenSpecを必須とする。PR本文のchange参照、changed `openspec/changes/` path、`Closes #N`に対応する`issue-N-*`を照合し、active/archiveを含めてcoherentなchangeを一意に決める。activeとarchiveが同名ならactiveを優先する。

`no-spec` labelは適用除外理由をrepository規約に照合する。単純typo・挙動を変えない生成物同期等でなければIMPORTANTとする。`dev-ai` baseはOpenSpec gate対象外だが、存在するchangeを主張している場合は整合を検査する。

候補0件、複数件、Issue/PR/changeのobjective不一致、planning/Readiness未完了、required artifact欠落、strict validation失敗は `NOT_READY` とする。

**完了基準:** change名、状態、根拠、読んだartifact、strict validation結果、適用除外理由を示せる。

### 5. spec traceability matrixを完成する

proposal、delta spec、design、tasksと、存在する変更対象のmain specを読む。新規capabilityまたは`skip_specs: true`でmain specがまだ存在しない場合は、その理由を記録する。全Requirement、全Scenario、全AC ID、Readinessを除く全taskをcontractのmatrixへ列挙する。Requirement → Scenario/AC → task → implementation → testを双方向に追う。

実装証拠は固定head treeのsymbol/lineと具体的挙動、test証拠はtest名と検証する成功・境界・失敗条件を示す。既存コードを証拠に使う場合は`pre-existing`とし、このPRが要求するdeltaをどこで成立させたかを別に示す。削除・禁止要件は検索結果とnegative testで立証する。

未対応Requirement/Scenario/AC、checked taskの実装不足、実装だけでtestがない行、spec外のbehavior changeはIMPORTANT以上のfindingとする。

**完了基準:** artifactから抽出した行数とmatrix行数が一致し、未対応行が0件またはfindingに全件対応する。

### 6. MT correctnessを確認する

全human-authored hunkと必要なcaller/calleeを読み、少なくとも次を差分トリガーで確認する。

- 全data accessの`company_id`分離、tenant情報/secret/PII/prompt全文の非漏洩。
- 新機能のFeatureSetting default false、Controller早期guard、OFF test。
- Domain/Application/Adapter/Infrastructureの依存方向、ControllerからUseCaseへの委譲、DI。
- Firestore entityなら`apps/mt/docs/db.md`、Admin API/DTOならOpenAPI生成物とDashboard client、BigQuery schemaならDashboard readerの同期。
- ST/MT双方へ影響するDashboard差分なら両botの挙動。
- project required checksと、各ACを直接検証する最小test。

CI結果とfresh local checkを分ける。未信頼forkのcodeは通常環境で実行しない。実行不能なrequired checkはcoverage gapとして `BLOCKED` にする。

**完了基準:** 各changed pathにreview観点と検証方法があり、findingが具体的failure scenarioと反証確認を持つ。

### 7. driftとcostを再検査して報告する

GitHubのbase/head SHAとmerge-baseを再取得する。差分があれば `STALE` とし判定を無効化する。usageを再計算し、0.80 USD超またはtelemetry欠落なら `BLOCKED_COST` とする。

findingを重要度順に示し、続けてtraceability、coverage/checks、cost、snapshot、decisionを出す。問題がない場合も「検証範囲ではfindingなし」とし、未確認領域を問題なしと表現しない。

**完了基準:** contractの判定表から同じdecisionを機械的に再計算できる。

## 出力順

1. Findings（CRITICAL → IMPORTANT → MINOR）
2. OpenSpec traceability summaryと未対応行
3. Coverage / checks / residual risks
4. Cost telemetry（model、tokens、worst-case/actual USD、reserve）
5. Snapshot（PR、base/head/merge-base SHA）
6. Decision（READY / NOT_READY / BLOCKED / BLOCKED_SCOPE / BLOCKED_COST / STALE / NOOP）
