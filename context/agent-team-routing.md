# Agent Team Routing

Codex が installed plugins / skills / sub-agent roles を選ぶためのルーティング方針。

このファイルの責務は **tool / plugin / skill / agent role の選択** に限定する。

- Phase の順序やゲートは `context/workflow-rules.md` を SSoT とする。
- model / service_tier / agent_type の詳細は `rules/model-routing.md` を SSoT とする。
- `/team-run` のチーム構成・Review Heat・終了判定は `context/team-run.md` を SSoT とする。
- Project 固有の routing 上書きは `.codex/context/agent-team-routing.md` を優先する。
- `/team-run` の entrypoint shim は `skills/team-run/SKILL.md` を最初に読む。Skill 読込後の policy 適用順は `context/workflow-rules.md` → `context/agent-team-routing.md` → `context/team-run.md` → `.codex/context/agent-team-routing.md` → `.codex/context/team-run.md`。Project 側の `team-run.md` は `/team-run` 固有事項にだけ重ねる。

## Leader Defaults

1. **重い process gate を既定にしない**
   - まず `ask-skill-router` の分類で、要求の不一致、共有語彙、feedback loop不足、設計劣化、外部調査不足のどれかを切り分ける。
   - 仕様余地が大きく、人間の判断が必要: 下記 Engineering Lanes で codebase の有無と route の既知 / 未知を判定する。
   - 複数ターン・複数担当・高価値の実装: `team-run` または `orchestrate` を user-invoked として使う。
   - バグ診断: `diagnosing-bugs` または `tdd` を model-invoked discipline として使う。
   - 完了直前: `verification-loop`、`verify`、必要に応じてレビューskillを使う。
   - Superpowers は明示依頼、既存計画がSuperpowers前提、または重い設計探索が必要なときの選択肢であり、通常タスクの既定flowではない。
2. **plugin router skill を focused skill より先に読む**
   - 例: Product Design なら `product-design:index`、Data Analytics なら `data-analytics:index`。
   - router が preflight / context / approval gate を持つ場合は、その指示を focused workflow より優先する。
3. **agent role は実行・レビューの担当、plugin skill はドメイン workflow の担当**
   - plugin が適用されても、sub-agent を起動する理由にはならない。
   - 現在の session が提供する collaboration API（例: `spawn_agent`）は、Delegation Gate を通過した task だけに使う。API がなければ lead が同じ acceptance で逐次実行する。
4. **local fan-out を先に使う**
   - 独立したファイル読み取りや `rg` は `multi_tool_use.parallel`。
   - 調査質問が独立していて、人間に返す判断が必要なときに explorer 系 agent を使う。
5. **外部書き込みは明示確認する**
   - Slack 投稿、Jira/Confluence 更新、GitHub PR 作成、Calendar 変更、Drive 書き込み、Sites production deploy は、対象と本文/変更内容を確定してから実行する。

## Delegation Gate

sub-agent へ委任する前に、次の条件をすべて確認する。満たさない条件があれば Codex lead が逐次実行する。

| 条件 | PASS の基準 |
|---|---|
| Local-first | `rg`、read-only tool call、または小さなローカル実行だけでは不足する |
| 並列利益 | 独立作業の速度・専門性の利益が、委任と統合のコストを上回る |
| 独立証拠 | objective、acceptance、成果物または checker を lead から独立して定義できる |
| Write scope | maker ごとの write scope が disjoint、または同じ対象の writer が一人に固定される |
| 外部副作用 | 外部書き込みがない、または対象と操作が既存 project policy かユーザー承認で許可されている |

同一ファイルの密結合作業、逐次依存、低価値な要約は fan-out しない。reviewer は maker の自己申告ではなく、成果物と fresh な検証証拠を見る。

## Context Boundary

- **Alignment**: `grill-me` / `grilling` は、人間の選好と未決事項を一問ずつ明らかにする。ここでは実装・文書更新を始めない。
- **Durable artifact**: `grilling-with-docs`、`writing-specifications`、`handing-off-context` は、確認済みの合意だけを保存する。保存先と外部公開は別 gate である。
- **Fresh implementation context**: route と acceptance が確定した実装単位は、必要な artifact の抽出だけを持って開始する。会話全文や未決の仮説を丸ごと引き継がない。

`mapping-large-projects` は route が霧に包まれた大規模 effort の decision map であり、`team-run` は route と acceptance が既知で、共有状態と独立検証が価値を生む実行協調である。

## Research Ticket Gate

AFK research ticket は facts を集めるためだけに使う。
local-first の後、Delegation Gate をすべて満たす独立調査だけを委任し、source link と不確実性を持つ asset を lead に返す。
claim、tracker 作成、comment、label、close は External Write Gate を通す。

## Engineering Lanes

ここに載せるのは shared route として採用した promoted skill と既存の canonical flow だけである。

Matt Pocock skill の全件判定はfixed revisionごとの監査artifactで管理する。
このroutingには41件の詳細を複製せず、運用カテゴリと入口だけを置く。

- **canonical**：`ask-skill-router`、`grilling`、`grilling-with-docs`、`wayfinder`、`to-spec`、`to-tickets`、`implement`、`tdd`、`diagnosing-bugs`、`reviewing-code`、`modeling-domains`、`designing-codebases`、`handing-off-context`。
- **implementation name**：`wayfinder`、`to-spec`、`to-tickets`、`implement`、`teach` は discovery 用の user-invoked entry であり、実行規律はそれぞれ `mapping-large-projects`、`writing-specifications`、`creating-tracer-tickets`、`implementing-work`、`teaching-concepts` を読む。
- **optional**：`prototyping-solutions`、`improving-codebase-architecture`、`setting-up-engineering-skills`、writing 系、setup 系、niche migration 系。明示依頼または対象repo条件がそろう場合だけ使う。
- **compat/reference**：`choosing-skills` などの旧名やClaude専用補助。入口は既存canonical routeへ寄せる。
- **in-progress/user-invoked**：`batch-grill-me` と `to-questionnaire` は明示起動時だけ使い、安定版の既定経路として推奨しない。
- **retired**：deprecatedな `design-an-interface`、`conducting-quality-assurance`、`planning-refactors`、`ubiquitous-language` はruntimeから削除済み。置換先は `brainstorming` と `designing-codebases`、`triaging-issues` と `diagnosing-bugs`、architecture surveyと`to-spec`と`to-tickets`、`modeling-domains`。

`teach`（実装規律は`teaching-concepts`）は post-stabilization の教育laneである。
通常の設計、実装、状態図生成では、読者に教えるための原則だけを使い、teaching workspace は明示された教育タスクでだけ作る。

### Engineering Flow Shape

これは route の条件分岐であり、Phase 順序の第二の正本ではない。

- route が見えない巨大案件だけ `mapping-large-projects` を situational on-ramp として使い、判断がそろった後に `writing-specifications` または直接 `implementing-work` へ渡す。
- route が明確で、単一 session に収まり direct requirement と acceptance criterion で検証できる作業は、spec と ticket を省略して `implementing-work` へ進める。この分岐を `direct lane` と呼ぶ。
- 複数 session に分ける作業は durable spec または handoff artifact を残し、実行単位をtracker化する場合だけ `creating-tracer-tickets` を使う。各実装単位は durable artifact から fresh context で始める。
- route が明確な大規模作業を WU と依存へ分ける場合は `blueprint` を使い、fog-of-war の探索と混同しない。

これらの skill は user-invoked である。ある route の完了は次 route の提案条件を満たすだけで、後続 skill の自動実行、tracker 公開、commit、push を許可しない。

| 条件付きlane | 使う条件 | 次の判断 |
|---|---|---|
| `mapping-large-projects` → `writing-specifications` | 目的地はあるがrouteが不明で、decision map後も durable spec が必要 | 未決事項が残るなら alignment に戻す |
| `writing-specifications` → `creating-tracer-tickets` | 承認済みspecを複数の垂直sliceへ分ける必要がある | tracker公開は別承認 |
| `creating-tracer-tickets` → `implementing-work` | ticket単位で acceptance と frontier が明確 | fresh context だけを渡して実装する |
| direct requirement → `implementing-work` | 単一sessionで検証でき、specやticketが過剰 | `tdd`、`diagnosing-bugs`、reviewを必要な分だけ重ねる |

| Signal | Primary route | 起動権 | 境界 |
|---|---|---|---|
| 要件が曖昧で codebase または状態付き docs がある | `grilling-with-docs` | user-invoked | 同じ文脈で alignment を進める。codebase がない場合は `grill-me`。次 route は規模と不確実性で選ぶ |
| 目的地はあるが route がまだ分からない巨大案件 | `mapping-large-projects` | user-invoked | decision map を作る situational on-ramp。route が明確なら spec または直接実装を提案し、tracker 書き込みは別 gate とする |
| route が明確な大規模作業で、依存DAG、Cold-Start Brief、または複数PRの設計図が必要 | `blueprint` | user-invoked | WU と依存を設計する。通常の複数session分割や未知routeの探索には使わない |
| 会話だけでは決められない一つの design question | `prototyping-solutions` | model-invoked | decision evidence を作る。production 実装ではなく、branch / issue / commit は別 gate |
| material な未決事項がない会話を durable spec にする | `writing-specifications` | user-invoked | tracker 公開は別承認。未決事項が残る場合は synthesis で埋めず、alignment route へ戻す |
| 承認済み spec を垂直 slice と blocking edge にする | `creating-tracer-tickets` | user-invoked | 粒度と依存の承認後に公開する。`blueprint` や `deepening-plan` を置き換えない |
| spec / ticket または direct requirement を実装する | `implementing-work` | user-invoked | unblocked frontier と検証可能な acceptance criterion を前提とする。品質確認と commit / push は global policy に従う |
| 外部から届いた raw issue / PR を agent-ready にする | `triaging-issues` | user-invoked | 生成済み tracer ticket を再 triage しない。comment / label 更新は別承認 |
| 固定点からの差分を Standards / Spec の二軸で見る | `reviewing-code` | model-invoked | read-only review discipline。Phase 4 の mandatory review と出荷判定を置き換えない |
| domain vocabulary を問い直す | `modeling-domains` | model-invoked | glossary / decision vocabulary。process flow の代替にしない |
| module shape、interface、seam を設計する | `designing-codebases` | model-invoked | deep-module vocabulary。実装や broad refactor の許可ではない |
| 新規systemの境界、bounded context、DDD判断を設計する | `software-architecture` | model-invoked | greenfield / major redesignのsystem boundary。既存codebaseの改善surveyや選択済みmoduleの局所改善ではない |
| architecture の deepening opportunity を scoped survey する | `improving-codebase-architecture` | user-invoked | ユーザー指定範囲または recent git hot spot に絞って HTML 候補を提示する。選択後の設計・実装は別 route |
| 選択済みの1〜3 module または一つの関心事を段階的に改善する | `improving-architecture` | model-invoked | Deletion Test、Seam、Locality で改善案を作る。実装、ADR、broad survey は別 gate |
| session / agent 間へ durable context を渡す | `handing-off-context` | user-invoked | handoff artifact を作る。別 session の起動や外部投稿は行わない |

Tracker、triage label、domain doc layout が hard dependency の route で設定が欠ける場合だけ、`setting-up-engineering-skills` を **user-invoked の提案**として返す。提案しただけでは実行しない。

## External Write Gate

Route 選択だけでは、次の操作を許可しない。

- issue / PR / comment / label、Slack 等の対人送信、Calendar、Drive、production deploy、secret store の更新。
- `git commit` / `git push`。明示された project policy またはユーザー承認に従う。
- prototype branch や tracker artifact の作成。decision evidence と production artifact を分ける。

実行前に対象、操作、本文または差分を確定する。sub-agent や plugin へ委任しても、この gate は緩和されない。

## Intent Routing Table

| User intent / signal | Primary plugin / skill route | Agent roles to combine | Notes |
|---|---|---|---|
| high-value multi-turn parallel execution, team-run,複数 role の協調 | `skills/team-run/SKILL.md` with `context/workflow-rules.md` and `context/team-run.md` | `implementation-planner`, `implementer`, reviewers, `go-nogo-advisor` | Use only when Goal, Team Journal, Review Heat, and sub-agent coordination are all useful. |
| ordered handoff chain, fixed sequence of specialist agents, orchestrate | `skills/orchestrate/SKILL.md` with `context/workflow-rules.md` | `requirement-parser`, `implementation-planner`, selected reviewers | Use when order matters more than shared team state. Prefer `team-run` when Goal, Team Journal, and Review Heat must persist across turns. |
| skill / workflow selection, ask-matt相当, どのskillを使うべきか | `skills/ask-skill-router/SKILL.md` | none by default | Classify user-invoked vs model-invoked before starting a heavy flow. |
| third-party Skill discovery, reputation, provenance, full catalog, install, update, retirement | `skills/skill-governance/SKILL.md`; read-only estate review may call `skill-stocktake` | none by default | Read-only inventory is model-invoked. Promotion, update, retirement, deletion, or runtime mutation is user-invoked and must pass the governance gates. |
<!-- skill-governance-contract:routing:start -->
第三者Skillは `skill-governance` で候補catalogとactive runtimeを分離する。read-only inventoryだけをmodel-invokedとし、promotion、update、retirement、delete、runtime mutationはuser-invokedかつ人間承認を必須にする。
<!-- skill-governance-contract:routing:end -->
| non-trivial coding, multi-step task, workflow discipline | `ask-skill-router` then `tdd`, `diagnosing-bugs`, `verification-loop`, `team-run`, `orchestrate`, or explicit `superpowers:*` | `implementation-planner`, `implementer`, reviewers | Superpowers is optional, not the default process layer. Prefer the smallest discipline that closes the actual risk. |
| UX, UI, product flow, screen audit, app redesign, prototype, visual target | `product-design:index` then `get-context`, `audit`, `ideate`, `prototype`, `image-to-code`, or `design-qa` | `ui-ux-reviewer`, `a11y-reviewer`, `implementer` | Use Product Design before generic implementation when user intent includes product/design judgment. |
| frontend implementation with a clear existing spec and no visual exploration | local repo workflow + applicable skill discipline | `implementer`, `ui-ux-reviewer`, `a11y-reviewer` | Product Design is optional unless UX/design decisions are being made. Use Superpowers only on explicit request or when the selected plan already depends on it. |
| website, app, dashboard, portal, tracker, hosted prototype | `sites:sites-building`; `sites:sites-hosting` for save/deploy | `implementer`, `ui-ux-reviewer`, `devops-reviewer` | Always use Sites when `.openai/hosting.json` exists. Deploy only saved versions. |
| source-backed analytics, metrics, KPI, dashboard, report, data quality | `data-analytics:index` then focused workflow | `data-modeler`, `perf-reviewer`, `go-nogo-advisor` | Run plugin preflight and verify live sources when required. |
| creative marketing visuals, ads, mood boards, logos, generated assets | `creative-production:explore` then focused explorer | `ui-ux-reviewer` if implemented in UI | Use creative path chooser before generation-heavy work. |
| GitHub repo / PR / issue / CI / publish workflow | `github:github`, then `gh-address-comments`, `gh-fix-ci`, or `yeet` | `code-quality-reviewer`, `test-reviewer`, `security-reviewer` | Connector first for structured PR/issue data; local `git`/`gh` for branch and CI gaps. |
| Jira, Confluence, company knowledge, specs to backlog | `atlassian-rovo:*` or `atlassian:*` focused skill | `prd-reviewer`, `docs-reviewer`, `api-contract-reviewer` | Use the connector as source of truth for pages/issues; cite exact versions when reviewing specs. |
| Slack read, summarize, draft, reply, post | `slack:slack`, then focused Slack workflow | `docs-reviewer` for announcements, `go-nogo-advisor` for sensitive posts | Any send/post/reply must route through `slack-outgoing-message`. |
| Google Drive / Docs / Sheets / Slides work | `google-drive:*` focused skill | `docs-reviewer`, `test-reviewer` for generated artifacts | Prefer connector reads/writes over ad hoc local exports. Route analysis-heavy Sheets work through Data Analytics as the primary route. |
| Calendar scheduling, daily brief, meeting prep | `google-calendar:*` focused skill | `daily-planner`, `go-nogo-advisor` | Check availability before scheduling; calendar writes need explicit confirmation. |
| PDF / document / spreadsheet / presentation file creation or editing | `pdf:pdf`, `documents:documents`, `spreadsheets:Spreadsheets`, `presentations:Presentations` | `docs-reviewer`, `test-reviewer` for generated artifacts | Use workspace dependencies for local file manipulation when needed. |
| browser interaction, visual inspection, web app control | `browser:control-in-app-browser` or `chrome:control-chrome` | `ui-ux-reviewer`, `a11y-reviewer` | Prefer Browser/Chrome with `node_repl`; use Computer Use only when explicitly needed. |
| local GUI automation or OS-level interaction | `computer-use:computer-use` | `go-nogo-advisor` for risky actions | Requires user-visible caution; do not use for simple shell/file tasks. |
| OpenAI product/API docs | `openai-docs` | `api-contract-reviewer` | Use official OpenAI sources; browse official docs if local docs are insufficient. |
| library / framework / SDK / cloud service docs | `context7` via tool search when available | `technical-evaluator`, `implementation-planner` | Use current primary docs before coding against changing APIs. |
| repo architecture documentation | `deepwiki` when available | `architecture-explorer`, `dependency-mapper` | Useful in Phase 1 and plan deepening. |
| sales workflow, account, CRM, forecast, meeting prep | `sales:index` | `go-nogo-advisor`, `docs-reviewer` | Run Sales preflight before evidence retrieval or drafting. |
| investment banking deal work | `investment-banking:investment-banking` | `data-modeler`, `go-nogo-advisor`, `docs-reviewer` | Use only for investment-banking workflows. Treat as high-stakes; verify current market/data sources. |
| public equity investing work | `public-equity-investing:public-equity-investing` | `data-modeler`, `go-nogo-advisor`, `docs-reviewer` | Use only for public-equity workflows. For accounting, payments, insurance, lending, or FP&A, do not force these routes; use a more specific installed router if present or ask for scope. |

## Routing Output

After selecting a route, the leader should know:

- primary plugin or skill router;
- focused skill(s) to read before acting;
- agent role(s) only if the active workflow requires delegation or review;
- external write approvals required before any connector action;
- plugin-specific completion gates to satisfy before final handoff.

For `/team-run`, record those fields and the Review Heat from `context/team-run.md` in the Team Journal defined by `skills/team-run/SKILL.md`.

## Fallbacks

- If a plugin is mentioned but its tools are not loaded, use `tool_search` first.
- If a user explicitly asks for an unavailable plugin/connector and `tool_search` cannot expose it, use plugin install discovery only for the exact requested plugin.
- If a plugin router requires unavailable source access, stop that path and report the missing source instead of substituting weaker evidence silently.
- If multiple plugin routes apply, choose the route that owns the user-visible deliverable, and treat the others as supporting source or review paths.
