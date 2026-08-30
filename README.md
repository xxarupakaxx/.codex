# .codex

Codexのuser-scope設定を、再現可能な正本として管理する。AGENTS.mdは入口、context/とrules/とskills/が詳細を持つ。runtime state、auth、history、SQLite、secret、plugin cache、生成画像は保存しない。

## 配置

    AGENTS.md
    context/       Phase、memory形式、routing、Codemap、HTML契約
    rules/         model、security、complexity、ADR、Git
    skills/        focused workflow
    commands/      互換shim
    prompts/       custom prompt
    agents/        role定義
    scripts/       deterministic check、Roadmap/Codemap生成
    templates/     project入口
    config.example.toml

Claude固有の設定は claude-compat/ に置き、同じworkflowを二重管理しない。

## 使い方

このtreeを参照し、必要なfileを ~/.codex へ配置する。config.example.tomlから実際のconfig.tomlを作り、secretはpassword managerまたはlocal environmentから復元する。新規projectには templates/project/AGENTS.md と templates/project/CLAUDE.md をコピーし、projectの変数、検証command、固有不変条件を置く。

## Canonical route

作業順は context/workflow-rules.md のPhase 0–5.5、条件付きgateは context/workflow-details.md、artifactとsession復元は context/memory-file-formats.md、Skillと委譲は context/agent-team-routing.md が正本である。Roadmapは30_plan.mdを入力に`~/.codex/scripts/sync-roadmap.py`が検査・生成・atomic publishし、HTMLやsnapshotを手編集しない。短い保守はlog-onlyで追跡し、Roadmapを自動強制しない。

lfgは skills/lfg/SKILL.md がcanonicalで、commands/lfg.md、prompts/lfg.md、skills/source-command-lfg/SKILL.mdは互換shimである。shimへPhase手順を戻さない。

## 検証

任意のproject cwdから、user-scopeの絶対home入口で次を実行する。

    python3 ~/.codex/scripts/validate-agent-harness.py
    python3 ~/.codex/scripts/validate-agent-harness.py --contracts
    python3 ~/.codex/scripts/validate-agent-harness.py --full-replay
    python3 -m unittest discover -s ~/.codex/tests -p 'test_*.py'
    node --test ~/.codex/tests/roadmap-viewer.test.mjs
    bash -n ~/.codex/hooks/*.sh ~/.codex/claude-compat/hooks/*.sh

artifactを別rootで検証する場合は --artifact-dir を指定する。設定済みと実行済み、構文PASSとuser outcomeは別に報告する。

## Team Run

高価値で複数turnのGoal、Team Journal、Review Heat、独立roleが必要なときだけ skills/team-run/SKILL.md を使う。graph-engineeringは複数loopをtyped state、auditable edge、異なるauthorityで統治する場合だけ重ねる。

読む順序:

1. skills/team-run/SKILL.md
2. context/workflow-rules.md
3. context/agent-team-routing.md
4. context/team-run.md
5. projectのAGENTS.mdとproject override

commands/team-run.md と prompts/team-run.md は入口shimであり、正本を更新する。

## Skill routing

skills/ask-skill-router/SKILL.mdで、user-invokedの進路変更とmodel-invokedの局所disciplineを分ける。Superpowers、team-run、orchestrate、blueprint、外部Skillの導入・更新は既定にせず、明示要求または条件付きgateで使う。必要なSkillだけを読み、成果とfresh検証を残す。

## Codemap

code-changing taskは最初のedit前にtask-local Codemapをrefresh / checkし、編集後もfreshnessを確認する。workspaceを検査し、codemap.json、codemap.lock、roadmap.htmlはtask memoryに置く。verified relationにはpath:line evidenceを付け、unknown relationを推測で埋めない。

    python3 ~/.codex/scripts/generate-codemap.py refresh \
      --root WORKSPACE --artifact-dir TASK_MEMORY \
      --input TASK_MEMORY/codemap.source.json
    python3 ~/.codex/scripts/generate-codemap.py check \
      --root WORKSPACE --artifact-dir TASK_MEMORY

ClaudeからRoadmapを同期する場合も、旧generatorを直接呼ばず、~/.codex/scripts/sync-roadmap.pyを明示入口として使用する。
