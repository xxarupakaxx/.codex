---
argument-hint: <workflow-type> "<task>"
description: orchestrate Skill正本を読み込ませる互換入口。順序付きエージェントチェーンの実行要件は Skill 側に委譲する。
---

# /orchestrate

Compatibility shim. The source of truth is `skills/orchestrate/SKILL.md`.

When this command is invoked:

1. Read `skills/orchestrate/SKILL.md`.
2. Read `context/workflow-rules.md` for Phase 0-5.5, logging, validation, and review rules.
3. Read `context/agent-team-routing.md` and `rules/model-routing.md` for agent_type and model routing.

Do not duplicate the orchestrate workflow here. Update the Skill and context files instead.
