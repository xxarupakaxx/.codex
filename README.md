# .codex

User-scope Codex configuration imported from `~/.claude`.

This repository intentionally stores only reproducible configuration:

- `AGENTS.md`
- `agents/*.toml`
- `skills/`
- `commands/`
- `hooks.json`
- `claude-compat/`
- `config.example.toml`

It does not store runtime state, auth files, SQLite databases, histories,
attachments, generated images, plugin caches, or local secret values.

## Apply locally

Use the files as references, then copy or merge into `~/.codex`.
Create a real `~/.codex/config.toml` from `config.example.toml` and restore
secret values from a password manager or local environment.

Codex model routing is pinned to `gpt-5.5` + `priority` by default. Custom
agents should always declare both `model` and `service_tier`.
