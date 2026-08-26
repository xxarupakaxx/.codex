---
allowed-tools: Bash(git:*), Bash(gh:*), Bash(python3:*)
argument-hint: [base-branch]
description: 検証・承認後にDraft PRを作成
---

# /pr compatibility shim

`skills/pr/SKILL.md`をCodex home基準で全文読み、その契約だけを正本として実行する。
このshimへ文案生成、push、PR作成の手順を複製しない。
