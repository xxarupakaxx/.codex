---
argument-hint: [PR番号]
description: pr-watch Skill正本を読み込ませる互換入口。PR監視と対応ループの実行要件は Skill 側に委譲する。
---

# /pr-watch

Compatibility shim. The source of truth is `skills/pr-watch/SKILL.md`.

When this command is invoked:

1. Read `skills/pr-watch/SKILL.md`.
2. Read `context/workflow-rules.md` for Phase 0-5.5, logging, validation, and review gates.
3. Follow the Skill's PR state, CI, review, fail-closed, and `/loop` rules.
4. Use `context/loop-engineering.md` only for high-level execution-model context.

Do not duplicate the pr-watch workflow here. Update the Skill and context files instead.
