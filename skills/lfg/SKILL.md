---
name: lfg
description: "Phase 0-5.5を自律チェーン実行する自律ワークフロー。/lfg <タスクの説明> で使用。"
---

# LFG - Autonomous Workflow Entrypoint

`/lfg <タスクの説明>`は、delivery lifecycleを開始または再開する薄いentrypointである。

## Canonical sources

- Phase、gate、戻り先、LOOP停止条件: `context/workflow-rules.md`
- artifact schemaとsession復元: `context/memory-file-formats.md`
- skill、role、外部write: `context/agent-team-routing.md`
- model capability classとruntime roster: `rules/model-routing.md`
- deterministic routingと次actionの検査: `scripts/agent_delivery_lifecycle.py`

## Entrypoint contract

1. task stateと`05_log.md`を復元する。
2. lifecycle resolverまたは同じ契約で、次の実行可能actionを一つだけ決める。
3. `RUNNING`なら正本が指定するPhaseまたはadapterを実行する。
4. `WAITING_HUMAN`または`ROUTING_BLOCKED`なら副作用なしで停止する。
5. Phase 4の未解決findingは修正へ戻し、上限到達時は停止する。
6. delivery後にescaped defectがあれば記録とreplayへ戻す。
7. `COMPLETE`になった場合だけ終了する。

このSkillはPhase本文、固定reviewer、固定round、artifact field、model表を複製しない。

external write、権限、課金、認証、不可逆操作、runtime policy昇格の承認を推測しない。
