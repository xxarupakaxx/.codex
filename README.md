# .codex

User-scope Codex configuration imported from `~/.claude`.

This repository intentionally stores only reproducible configuration:

- `AGENTS.md`
- `agents/*.toml`
- `skills/`
- `commands/`
- `prompts/`
- `config/user.example.json`
- `context/`
- `rules/`
- `templates/`
- `tools/`
- `workflows/`
- `scheduled-tasks/`
- `hooks.json`
- `claude-compat/`
- `config.example.toml`

It does not store runtime state, auth files, SQLite databases, histories,
attachments, generated images, plugin caches, or local secret values.
Claude-only runtime/configuration references are kept under `claude-compat/`.

`AGENTS.md` is intentionally a short table of contents. Detailed workflow,
routing, security, ADR, and review rules live under `context/`, `rules/`, and
`skills/`; keep history and task-local exceptions out of the entrypoint.

## Apply locally

Use the files as references, then copy or merge into `~/.codex`.
Create a real `~/.codex/config.toml` from `config.example.toml` and restore
secret values from a password manager or local environment.

For a new project, copy `templates/project/AGENTS.md` and
`templates/project/CLAUDE.md`. Put project variables, verification commands,
and project-only invariants in `AGENTS.md`; `CLAUDE.md` only imports it.

## Validate the harness

```bash
python3 scripts/validate-agent-harness.py
python3 scripts/validate-agent-harness.py --contracts
python3 scripts/validate-agent-harness.py --full-replay
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/roadmap-viewer.test.mjs
bash -n hooks/*.sh claude-compat/hooks/*.sh
```

To validate Phase artifacts stored in a project-specific directory:

```bash
python3 scripts/validate-agent-harness.py --artifact-dir .context
```

Codex delivery routing uses the Local / Fast / Standard / Heavy / Judgment
capability classes in `rules/model-routing.md`. The current runtime resolves
them to Luna, Terra, and Sol and fails closed when a required model is absent.

`lfg` is maintained at `skills/lfg/SKILL.md`. Its command, prompt, and
source-command surfaces are compatibility shims. Phase order and gates remain
in `context/workflow-rules.md`; artifact schemas remain in
`context/memory-file-formats.md`.

## Team Run

`team-run` is maintained as a Codex Skill at `skills/team-run/SKILL.md`.
`graph-engineering` is maintained as a Codex Skill at
`skills/graph-engineering/SKILL.md`; its contract and adoption boundary live in
`context/graph-engineering.md`, and execution reuses `team-run`.
Use it for high-value multi-turn work where Goal, Team Journal, reviewer
heat, and sub-agent coordination need to move together.

Read order:

1. `skills/team-run/SKILL.md`
2. `context/workflow-rules.md`
3. `context/agent-team-routing.md`
4. `context/team-run.md`
5. Project `AGENTS.md` and project overrides such as `.codex/context/agent-team-routing.md` / `.codex/context/team-run.md`, when present

The legacy `commands/team-run.md` and `prompts/team-run.md` files are
compatibility entrypoints only. Update the Skill and context files instead of
duplicating workflow text in those shims.

Claude-style command markdown files are mirrored into `prompts/` for Codex
custom prompts. Invoke them as `/prompts:<name>` after restarting Codex.

## Skill Routing

`skills/ask-skill-router/SKILL.md` is the lightweight router for choosing a
workflow before reaching for a heavy process gate. It keeps the distinction
between user-invoked flows, such as `team-run`, `orchestrate`, `grill-me`,
PRD writing, and issue splitting, and model-invoked disciplines, such as
`research`, `tdd`, `diagnosing-bugs`, `modeling-domains`, and verification.

Superpowers remains available as a strong option, but it is no longer treated
as the default route for every non-trivial task.

## Codemap preflight

Code-changing tasks use a task-local evidence map before the first edit. The
map validates files in the workspace, but its artifacts stay in the current
task memory directory and out of Git:

- `codemap.json` is the AI-readable topology.
- `roadmap.html` is the single Task Workspace for plan/progress and the evidence-backed Code Map.
- `codemap.lock` records source, map, template, and HTML fingerprints.

Author the map beside the task artifacts, then generate all three outputs together:

```bash
python3 scripts/generate-codemap.py refresh \
  --root <workspace-root> \
  --artifact-dir <task-memory-directory> \
  --input <task-memory-directory>/codemap.source.json
python3 scripts/generate-codemap.py check \
  --root <workspace-root> \
  --artifact-dir <task-memory-directory>
```

Verified relations require repository path and line evidence. Unproven relations
remain explicit `unknown` edges with a reason. See `context/codemap.md` for the
preflight, freshness, and Roadmap/Codemap separation contracts.
