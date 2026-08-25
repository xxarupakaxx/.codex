# MT OpenSpec PR review contract

## Cost envelope

絶対条件は `actual_cost_usd < 1.00`。運用上限は0.80 USDとし、残り0.20 USDをreasoning token、計測遅延、料金区分差のreserveにする。

### 許可条件

- model IDは`gpt-5.6-sol`、`gpt-5.6-terra`、`gpt-5.6-luna`のいずれかで、実際のtierを確認できる。
- runtimeが実モデルIDとservice tierを示す。
- runtimeがGoal budgetまたは同等の機構で、実行全体のbillable token hard capを20,000以下に設定できる。
- input、cached input/cache write、visible output、reasoning outputを含むusageを終了前に取得できる。
- 実モデルの全該当区分が40 USD / 1M tokens以下であることを確認できる。
- paid web search、外部LLM、sub-agent、nested workflowを使わない。

worst-caseは全billable tokenへ最大単価を掛ける。

```text
worst_case_usd = billable_token_hard_cap * max_rate_usd_per_million / 1_000_000
20,000 * 40 / 1,000,000 = 0.80 USD
```

モデル、tier、長文context、価格表のいずれかが不明なら安全側の推測をせず`BLOCKED_COST`。hard cap到達、usage欠落、0.80 USD超過でも同じ。料金根拠は実行時のOpenAI公式pricingまたはtrusted runtime pricing metadataとする。ここで使う40 USD ceilingは2026-08-25に公式表の許可model全区分から採った最大値である。2026-11-21より後は再検証する。料金表: https://developers.openai.com/api/docs/pricing

## PR selection and snapshot

PR指定がない定期実行では次を満たすopen PRだけを候補にする。

- repositoryが`THA-inc/ai-president-mt`。
- authorがcurrent principal、またはcurrent principalへreview request済み。
- current head SHAがlocal stateの処理済みSHAと異なる。

1実行1PR。base/head SHAをGitHub APIから取り、local objectのSHAと照合する。diffは`merge_base_sha..head_sha`で取得する。開始後はbranch名を証拠に使わない。

state schema:

```json
{
  "schema_version": 1,
  "repository": "THA-inc/ai-president-mt",
  "pull_requests": {
    "123": {
      "head_sha": "...",
      "reviewed_at": "RFC3339",
      "decision": "NOT_READY"
    }
  }
}
```

symlinkを拒否し、親directoryを0700、fileを0600で作り、同directoryのtemporary fileをfsyncしてrenameする。壊れたstateは上書きせず`BLOCKED`。

## OpenSpec applicability and resolution

`develop` / `main`向けのmaterial changeはOpenSpec対象。materialにはfeature、bug fix、observable behavior、API、schema、security、architecture、tenant boundary、material refactor/tooling/docs workflowを含む。

適用除外はread-only調査、単純typo、behaviorを変えない機械的生成物同期等に限定する。`no-spec` labelだけでは証拠にならず、diffが除外条件を満たす必要がある。spec-level behaviorを変えないmaterial changeはchangeの`.openspec.yaml`に`skip_specs: true`を要求する。

change候補は次の順で集め、objectiveとdiffが一致するものを一意に選ぶ。

1. changed path `openspec/changes/<name>/` またはarchive path。
2. PR本文の明示change path/name。
3. closing Issue番号に一致する`issue-<N>-*`。
4. legacy active changeはrepository規約で許可された既存名だけ。

active changeで実行するread-only checks:

```text
openspec list --json
openspec status --change <name> --json
openspec instructions apply --change <name> --json
openspec validate <name> --strict
```

archive済みchangeはactive用のstatus/apply commandを無理に実行せず、archive artifactと反映後のmain specを読む。`skip_specs: true`ならmain spec不在を許容し、設定とproposal/designがspec-level behavior非変更を裏付けるか確認する。active/archive同名はactive優先。activeではplanning完了、tasksの`0. Readiness gate`、apply state、all_doneをrepositoryの状態判定規約どおり評価する。

## Traceability matrix

artifactから抽出したすべての行を、順序を保って次のschemaへ正規化する。

```yaml
- requirement_id: <capability>#<requirement heading>
  requirement: <要求の要約>
  scenario_or_ac: <AC-N-M / scenario heading / N-A>
  task_ids: [<tasks.md checkbox id>]
  implementation:
    - path: <repo-relative path>
      symbol_or_line: <symbol or line>
      behavior: <この証拠が成立させる挙動>
      provenance: changed | pre-existing
  tests:
    - path: <repo-relative path>
      test: <test name>
      verifies: success | boundary | failure | tenant-isolation | feature-off | contract
  status: covered | partial | missing | contradictory | not-applicable
  finding_id: <missing/partial/contradictory時のfinding>
```

別途task ledgerを作る。

```yaml
- task_id: <tasks.md id>
  checked_in_artifact: true | false
  implementation_refs: [<matrix requirement/scenario ids>]
  evidence: [<path#symbol-or-line>]
  verification: [<test/check>]
  status: proven | unproven | incomplete
```

### 完全性invariants

- extracted Requirement集合 = matrix requirement_id集合。複数Scenarioを持つRequirementは行を共有せず、Scenarioごとにrequirement_idを再掲できる。
- extracted Scenario/AC multiset = matrix scenario_or_ac multiset。AC ID欠落・重複はfinding。
- Readinessを除くtask集合 = task ledger task_id集合。
- checked taskでもevidenceまたはverificationがなければ`unproven`。
- 各Requirementは1件以上のScenario/AC、実装証拠、test証拠を持つ。
- 各changed behaviorはRequirement/Scenarioまたは明示したspec外findingへ逆引きできる。
- test名の類似だけでcoveredにしない。assertionが要求の観測結果を検証することを読む。
- proposal/design/tasksの主張、checkbox、PR本文、comment、CI greenだけを実装証拠にしない。
- `not-applicable`は理由とartifact根拠を必須とし、coverage分母から黙って外さない。

## Finding schema

```yaml
- id: MTREV-001
  severity: CRITICAL | IMPORTANT | MINOR
  title: <短い結果>
  spec_ref: <requirement/scenario/task or N/A>
  location: <path:line>
  preconditions: <入力・tenant・state>
  failure_scenario: <どう到達するか>
  observed_or_missing_behavior: <何が壊れる/欠けるか>
  impact: <利用者・data・運用への影響>
  repository_evidence: [<path:line, test, command result>]
  counter_evidence_checked: [<guard, caller, test>]
  fix_direction: <最小の修正方向>
  verification: <修正後に通すtest/check>
```

severity:

- CRITICAL: tenant跨り、認証/secret漏洩、data破壊、本番事故、要求の中核が成立しない。
- IMPORTANT: Requirement/Scenario/AC/taskの実装漏れ、必要test欠落、契約/互換性違反、再現可能なcorrectness不具合。
- MINOR: mergeを止めない局所的な保守性・明瞭性。好みだけの指摘はfindingにしない。

反証を探してもfailureを立証できない候補はquestionまたはresidual riskへ移す。

## MT-specific gates

差分が触れた場合に必須とする。

| Trigger | Required evidence |
|---|---|
| data access / repository / vector search | `company_id` filter、別tenant拒否test、key/ownership検証 |
| new feature / externally visible behavior | FeatureSetting default false、Controller early return、OFF test |
| Admin API / DTO | generated admin OpenAPI、Dashboard client/type追随、MT先行deploy互換 |
| Firestore entity | `apps/mt/docs/db.md`同期、既存documentの後方互換 |
| BigQuery schema/log | Dashboard query/route追随、partition/cluster/insertId |
| Dashboard behavior | ST Bot / MT Bot双方の仕様とtest |
| controller/use case/gateway | dependency direction、DI、controllerにbusiness logicなし |
| log/error/trace | tenant/secret/PII/prompt非漏洩、汎用error response |
| async/PubSub | company_id attribute、idempotency、path境界 |

## Coverage and checks

coverage ledgerはchanged path集合と完全一致させ、各pathを`human-authored`、`test`、`docs/config`、`generated/vendor`、`lock/data`、`binary/submodule`へ分類する。各pathにreview methodまたはgap理由を付ける。

fresh local checkはリスクに応じて最小化するが、MT production code変更ではprojectの4 checksをrequiredとする。

```text
cwd = apps/mt
uv run ruff format --check --diff .
uv run ruff check .
uv run pytest
uv run mypy domain/ application/ interface_adapters/ infrastructure/ main.py
```

差分限定testを先に実行してよいが、READYにはrequired checksの成功証拠が必要。信頼できる同一head SHAのCI成功を代替にする場合はworkflow、job、head SHA、完了時刻を記録する。未信頼forkの任意codeは隔離済み実行環境がなければ実行しない。

## Decision table

優先順位は上から順。

| Decision | Condition |
|---|---|
| `NOOP` | eligibleな未処理head SHAがない |
| `BLOCKED_COST` | hard budget/usage/model/rate不明、またはworst-case/actualが0.80 USD超 |
| `STALE` | base/head/merge-baseのいずれかが開始時から変化 |
| `BLOCKED_SCOPE` | path/line/token scope上限超過 |
| `BLOCKED` | snapshot/権限/required artifact/check/coverageを信頼可能に取得できない |
| `NOT_READY` | CRITICALまたはIMPORTANTが1件以上、matrixにpartial/missing/contradictory、taskがunproven/incomplete |
| `READY` | CRITICAL=0、IMPORTANT=0、matrix全件covered、task全件proven、coverage gap=0、required checks成功、cost上限内 |

MINORだけならREADYを妨げない。OpenSpec適用除外PRはmatrixを`N/A with verified exemption`として扱えるが、repository correctness、coverage、checks、cost条件は省略しない。
