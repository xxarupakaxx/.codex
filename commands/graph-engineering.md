---
argument-hint: [contract-or-task]
description: Graph Engineering Skill正本を読み、複数loopを検証済みcontractで統治する互換入口。
---

# /graph-engineering

Compatibility shim. The source of truth is `skills/graph-engineering/SKILL.md`.

When this command is invoked:

1. Read `skills/graph-engineering/SKILL.md`.
2. Read `context/graph-engineering.md` for the contract, adoption boundary, and execution protocol.
3. Read `context/workflow-rules.md`, `context/agent-team-routing.md`, `skills/team-run/SKILL.md`, and `context/team-run.md`.
4. Overlay project `AGENTS.md` and project `.codex/context/` files when present.

Do not duplicate the graph workflow here. Update the Skill and context files instead.
