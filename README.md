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

## Apply locally

Use the files as references, then copy or merge into `~/.codex`.
Create a real `~/.codex/config.toml` from `config.example.toml` and restore
secret values from a password manager or local environment.

Codex model routing is pinned to `gpt-5.5` + `priority` by default. Custom
agents should always declare both `model` and `service_tier`.

## Team Run

`team-run` is maintained as a Codex Skill at `skills/team-run/SKILL.md`.
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
`research`, `tdd`, `diagnosing-bugs`, `ubiquitous-language`, and verification.

Superpowers remains available as a strong option, but it is no longer treated
as the default route for every non-trivial task.
