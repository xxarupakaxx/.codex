# Agent Team Routing

Codex が installed plugins / skills / sub-agent roles を選ぶためのルーティング方針。

このファイルの責務は **tool / plugin / skill / agent role の選択** に限定する。

- Phase の順序やゲートは `context/workflow-rules.md` を SSoT とする。
- model / service_tier / agent_type の詳細は `rules/model-routing.md` を SSoT とする。
- `/team-run` のチーム構成・Review Heat・終了判定は `context/team-run.md` を SSoT とする。
- Project 固有の routing 上書きは `.codex/context/agent-team-routing.md` を優先する。
- `/team-run` の entrypoint shim は `skills/team-run/SKILL.md` を最初に読む。Skill 読込後の policy 適用順は `context/workflow-rules.md` → `context/agent-team-routing.md` → `context/team-run.md` → `.codex/context/agent-team-routing.md` → `.codex/context/team-run.md`。Project 側の `team-run.md` は `/team-run` 固有事項にだけ重ねる。

## Leader Defaults

1. **Superpowers を process gate の既定にする**
   - 要求が曖昧・創造的・仕様余地あり: `superpowers:brainstorming`
   - 複数ステップの実装計画: `superpowers:writing-plans`
   - 独立タスクの並列委任: `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development`
   - バグ診断: `superpowers:systematic-debugging`
   - 完了主張の直前: `superpowers:verification-before-completion`
   - merge / PR 前: `superpowers:requesting-code-review` / `superpowers:finishing-a-development-branch`
2. **plugin router skill を focused skill より先に読む**
   - 例: Product Design なら `product-design:index`、Data Analytics なら `data-analytics:index`。
   - router が preflight / context / approval gate を持つ場合は、その指示を focused workflow より優先する。
3. **agent role は実行・レビューの担当、plugin skill はドメイン workflow の担当**
   - plugin が適用されても、sub-agent を起動する理由にはならない。
   - `multi_agent_v1.spawn_agent` は、現在の workflow / skill / user request が delegation, mandatory review, learnings search, or parallel work を要求するときに使う。
4. **local fan-out を先に使う**
   - 独立したファイル読み取りや `rg` は `multi_tool_use.parallel`。
   - 調査質問が独立していて、人間に返す判断が必要なときに explorer 系 agent を使う。
5. **外部書き込みは明示確認する**
   - Slack 投稿、Jira/Confluence 更新、GitHub PR 作成、Calendar 変更、Drive 書き込み、Sites production deploy は、対象と本文/変更内容を確定してから実行する。

## Intent Routing Table

| User intent / signal | Primary plugin / skill route | Agent roles to combine | Notes |
|---|---|---|---|
| high-value multi-turn parallel execution, team-run,複数 role の協調 | `skills/team-run/SKILL.md` with `context/workflow-rules.md` and `context/team-run.md` | `implementation-planner`, `implementer`, reviewers, `go-nogo-advisor` | Use only when Goal, Team Journal, Review Heat, and sub-agent coordination are all useful. |
| ordered handoff chain, fixed sequence of specialist agents, orchestrate | `skills/orchestrate/SKILL.md` with `context/workflow-rules.md` | `requirement-parser`, `implementation-planner`, selected reviewers | Use when order matters more than shared team state. Prefer `team-run` when Goal, Team Journal, and Review Heat must persist across turns. |
| non-trivial coding, multi-step task, workflow discipline | `superpowers:*` gate chosen by task stage | `implementation-planner`, `implementer`, reviewers | Superpowers is the default process layer, not a replacement for repo rules. |
| UX, UI, product flow, screen audit, app redesign, prototype, visual target | `product-design:index` then `get-context`, `audit`, `ideate`, `prototype`, `image-to-code`, or `design-qa` | `ui-ux-reviewer`, `a11y-reviewer`, `implementer` | Use Product Design before generic implementation when user intent includes product/design judgment. |
| frontend implementation with a clear existing spec and no visual exploration | local repo workflow + applicable Superpowers gate | `implementer`, `ui-ux-reviewer`, `a11y-reviewer` | Product Design is optional unless UX/design decisions are being made. |
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
