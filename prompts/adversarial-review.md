---
name: adversarial-review
description: Redのfindingを同じBlueへ逐次渡し、EOF照合後にAuditorが判定する敵対的レビュー。
---

# Adversarial Review compatibility entrypoint

このpromptは互換入口であり、workflowの正本ではない。

実行前に`.codex/skills/adversarial-review/SKILL.md`を最後まで読み、その手順だけを正本として適用する。

特に次の境界を維持する。

- Red findingはdurable queueへ保存してから同じBlue threadへ通知する。
- messageは通知専用とし、監査の正本にしない。
- Red EOFとBlue全応答を照合してsnapshotを固定するまでAuditorを起動しない。
- protocol failure時は保存済みfindingからbatch直列へ降格する。
- findingごとにBlue agentを増やさない。
