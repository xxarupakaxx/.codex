# pstack in Codex

pstack skills use Cursor names. In Codex, read this file once per session, then map each Cursor name in a skill with the tables below. `<pstack>` means `~/.codex/skills/pstack`, the folder that holds `skills/`, `agents/`, and `docs/`. If a Cursor field has no row, drop it and say so. Never pass a field or value the tool schema rejects.

This file is local to the `xxarupakaxx/.codex` install. It is not part of upstream pstack. `scripts/sync-pstack.py` keeps it when it refreshes the vendored tree.

## Skill names

Codex lists skills by the frontmatter `name`. Three pstack names collide with skills this Codex home already has, so the vendored copies are renamed. Folder names stay the same, so every `../<name>/SKILL.md` link still works.

| Cursor | Codex |
| --- | --- |
| `/tdd`, the **tdd** skill | `$pstack-tdd` (`<pstack>/skills/tdd/SKILL.md`). `$tdd` is the user's own skill. |
| `/teach`, the **teach** skill | `$pstack-teach` (`<pstack>/skills/teach/SKILL.md`). `$teach` is the user's own skill. |
| `/why`, the **why** skill | `$pstack-why` (`<pstack>/skills/why/SKILL.md`). `$why` is the user's own skill. |
| `Poteto Mode`, `Make Bot UI` | `$poteto-mode`, `$make-bot-ui` |
| Any other `/name` | `$name` |

## Tools

| Cursor | Codex |
| --- | --- |
| `Task` | `spawn_agent`, then `wait_agent` for the result and `close_agent` when done. Give `wait_agent` an explicit `timeout_ms`. |
| `AskQuestion` | Ask in plain text. In `codex exec` nobody answers, so state the assumption and continue. |
| Open a todolist | `update_plan`. Otherwise keep the list in your reply and update it at each phase. |
| Run another pstack skill (`/name` or "the **name** skill") | Read `<pstack>/skills/<name>/SKILL.md` and follow it. When you tell the user to type it, write the Codex name from the table above, such as `$pstack-why`. |
| `Grep`, `Glob` | `rg` and `rg --files` in the shell. |

## Subagent fields

| Cursor | Codex |
| --- | --- |
| `subagent_type: generalPurpose` | `agent_type: "default"` (or `"worker"` for a scoped code change). |
| `poteto-agent`, `comment-sicko` | `agent_type: "poteto-agent"`, `agent_type: "comment-sicko"`, defined in `~/.codex/agents/*.toml`. |
| `readonly: true` | `agent_type: "explorer"`. The brief also says "do not edit files", and you check `git status` afterward. |
| `readonly: false` | Omit. |
| `environment: "cloud"` | No Codex equivalent. Have the worker create a `git worktree` on the named branch or commit and work there, and say so. |
| `environment: "local"` | Omit. |
| `cloud_base_branch: <b>` | Tell the worker to check out `<b>` first. |
| `run_in_background: true` | Omit. `spawn_agent` returns at once; collect results with `wait_agent`. |
| `resume` | `send_input` to the agent if it is still open. Otherwise spawn a new agent and paste the earlier result into its brief. |
| `file_attachments` | List the paths in the brief. |

Codex caps concurrent subagents (`[agents] max_threads` in `config.toml`). When a playbook asks for more parallel agents than the cap, run them in waves and say so.

## Models

| Cursor | Codex |
| --- | --- |
| `claude-*`, `grok-*`, `gemini-*`, `composer-*`, or any other non-OpenAI slug | Omit `model` so the agent uses the session model or `[agents] default_subagent_model`, and say so. Multi-model panels (`arena`, `swarm`, `interrogate`) therefore run every seat on OpenAI models; vary the reasoning effort or the brief instead of the vendor. |
| A `gpt-*` slug | Pass it only when the user asked for that model and Codex lists it. Otherwise omit `model`. |
| Reasoning level or `-fast` suffix | Use `reasoning_effort` when the tool offers it. Drop `-fast`. |
| `auto` or `inherit-parent` | Omit `model`. |
| The `pstack-models.mdc` rule | Codex never loads `.mdc` rules. Read `~/.codex/pstack-models.md` if it exists and treat it as that rule. `setup-pstack` writes that file instead of `~/.cursor/rules/pstack-models.mdc`, with Codex-usable slugs or `inherit-parent`. Never put its role lines in `AGENTS.md`. |

## Paths

| Cursor | Codex |
| --- | --- |
| `.cursor/skills/`, `~/.cursor/skills/` | `.agents/skills/` in a repository, `~/.codex/skills/` for the user. |
| `~/.cursor/plugins/`, `.cursor-plugin/plugin.json` | `<pstack>` and `<pstack>/plugin.json`. pstack is vendored here, not installed as a plugin. |
| `.cursor/rules/*.mdc`, always-applied rules | `AGENTS.md`. Codex never reads `.mdc` files. |
| Transcripts in `~/.cursor/projects/<slug>/agent-transcripts/` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. The newest file whose `session_meta` `cwd` matches this workspace is the current session. Read only this workspace's sessions. |

## Cursor-only features

Cursor automations, Bugbot, Cursor cloud agents, custom modes (option+enter), `/loop`, and Cursor's pull request tool have no Codex equivalent. Say so, skip that step, and continue. Use `gh` for pull request work.

## Host rules win

The user's `~/.codex/AGENTS.md` and the project's `AGENTS.md` outrank pstack. When a pstack step conflicts with them (language, approval gates, commit and push rules, dashboards), follow `AGENTS.md` and say which step you changed.
