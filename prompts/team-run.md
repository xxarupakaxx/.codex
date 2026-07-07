---
argument-hint: [task]
description: team-run Skill正本を読み込ませる互換入口。Goal + Team Journal + Review Heat の実行要件は Skill 側に委譲する。
---

# /prompts:team-run

Compatibility shim. The source of truth is `skills/team-run/SKILL.md`.

When this prompt is invoked:

1. Read `skills/team-run/SKILL.md`.
2. Read `context/workflow-rules.md` for Phase 0-5.5, logging, validation, and review rules.
3. Read `context/agent-team-routing.md` for plugin / role routing.
4. Read `context/team-run.md` for team composition, Review Heat, and exit gates.
5. Overlay project `.codex/context/agent-team-routing.md` and then `.codex/context/team-run.md` when present.

Goal tools are runtime-native and are not represented in this frontmatter; use the Skill's goal handling rules.

Do not duplicate the team-run workflow here. Update the Skill and context files instead.
