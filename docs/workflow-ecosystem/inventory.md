# 2026-08-31 実装前の棚卸し

以下は変更前の観測記録であり、現在の操作手順ではない。行番号・件数は調査時点。Claude側の一時複製adapter案は採用せず、Codexの共通CLIを直接使う判断へ更新した。現在の手順は[運用ガイド](overview.md)を参照する。

# Codexユーザースコープの棚卸し

対象は `/Users/yoshiki/.codex`（実体 `/Users/yoshiki/ghq/github.com/xxarupakaxx/.codex`）。2026-08-31の作業開始時点。認証情報・会話本文・履歴DBは読んでいない。

| 領域 | 確認した実装と状態 | 不足・判断 |
| --- | --- | --- |
| 入口 | AGENTS.md → workflow-rules/routing/memory/codemap/Skill | 入口自体は短いが、辿る必須文書はworkflow784行/routing263行/memory768行 |
| スキル | 159個のSKILL.md、context14文書 | 全部読む構成にしない。選択時にだけ具体Skill全文を読む |
| Phase | workflow-rules.mdに0–5.5、Fast Track、Delivery lifecycle、Blueprint、review/UI/HTML/Goal gate | Phaseを維持しつつ既定経路と条件付き詳細を分離できる |
| 計画保存 | `.local/memory/<task>/30_plan.md`、`roadmap_plan_contract.py` が単一parser | 要件からacceptance、evidenceへの接続は実行時検査として不十分 |
| 計画表示 | sync-roadmap.py → generate-roadmap-view.py → tools/roadmap_viewer.html | Task graph/Source hash/HTML static/atomic publishは既存で再利用可能 |
| 蓄積 | global22task/13plan/13HTML、参考としてVault417task/250plan/190HTML | log-onlyを含むのでplan欠落率ではない。保存先分散と発見可能性を改善対象とする |
| 完了 | sync-roadmap.py PHASE_STATES['5']='completed' | 未完了checkboxと証跡不在でもdry-runがcompletedへ進むことを再現 |
| 表示上の完了 | parserはprogress100%からstatus/件数をcompleteへ投影 | 完了gateはraw checkboxと証跡を見る必要がある |
| hook | active hooks.jsonはherdr SessionStartのみ | phase/stop/handover用scriptの存在を配線済みと扱わない |
| custom workflow | workflows/roadmap-sync.jsはtrusted executor不在でfail-closed | 安全境界を解除しない。通常のlocal executorによるCLI同期を利用 |
| context復元 | task-meta thread/session完全一致、Codemap freshness、memory index | briefで次の実行単位に絞れる。最新日付だけの自動選択は不適切 |
| 長期記憶 | active configのmemories=false、SQLite自動注入なし | Markdown/indexによる明示取得と機械的な蓄積確認を使う |
| 改善 | Evidence Bundle/Escaped Defect/promotion境界の既存schema | 観測した失敗→検査へ戻す。ポリシーを無人で自己変更しない |

## 実測

- `validate-agent-harness.py --contracts`: PASS。
- `test_sync_roadmap.py`: 33件PASS。
- 全Python test: 301件中3件FAIL。開始前から存在した未追跡 `skills/reviewing-openspec-change/SKILL.md` の未登録HTML参照2件が3testへ波及。今回差分とは分離する。
- task-local計画: 5Task/5依存edgeの同期PASS、HTML static errors0。
- desktop: 1440x900、pageerror0、横overflowなし、Detailの検証表示、Escape閉鎖・起点focus復帰PASS。

## 仮説の評価

H1「計画生成経路の分断」は、custom workflowでtrusted executorがなく停止すること、MCPがsessionに出ないことから一部支持。ただしlocal generatorは動く。

H2「必須context過多で計画が省略」は、文書量と重複によるリスクとして支持。実タスクでの因果・token削減率はまだ未測定。

H3「計画構造は十分だが蓄積/表示が不足」は、既存parserとtask-local表示の成功で一部支持。保存件数だけでは個々の不足を判定できない。

最も確実な修正対象は、未完了を完了表示へ送れる同期境界。既定文書の短縮とplanの発見/briefは、その修正を日常運用へつなぐために行う。


# Claude workflow ecosystem inventory

調査日: 2026-08-31。対象は `/Users/yoshiki/.claude` の設定・正本・commands・hooks・workflows・Roadmap/HTML実装だけ。既存のdirty/untrackedファイルは変更していない。環境変数・認証値、transcript、projects、session、credentials の内容は出力・集計対象にしていない。

## 実際の経路

| 段階 | 根拠 | 実態 |
|---|---|---|
| 入口 | `CLAUDE.md:7-8,97-104` | `context/workflow-rules.md` と `05_log.md` を必須とする文書入口。 |
| Phase/計画 | `context/workflow-rules.md:149-156,215-240` | Phase 0 のメモリ初期化、Phase 2 の `30_plan.md`、条件付き `deepening-plan` を指示するが、実行器ではない。 |
| `/lfg` | `commands/lfg.md:8-30,32-45` | Phaseチェーンを説明するprompt。ファイル作成・agent起動・renderer呼出しを行うコードはない。 |
| Hook | `settings.json:25-386` | 36 hook entry が登録済み。`UserPromptSubmit` は `pre-prompt-phase-gate.sh:31-62` で最新ログを探して警告するだけ、`Stop` は `stop-workflow-check.sh:21-94` の文字列heuristicだけで、plan/HTML/verifyは呼ばない。 |
| Workflow | `CLAUDE.md:44-69`, `context/loop-engineering.md:250-252,351-360` | `Workflow` はhost capabilityとして参照される。`.claude` 内にrunner/loader登録は見つからず、利用不能時は逐次実行という記述。`workflows/roadmap-sync.js:8-12` は常に trusted local executor 必須でfail-closed。 |

`generate-roadmap-view.py`、`sync-roadmap.py`、`verify-html-surfaces.py`、`html_artifact_contract.py`、`roadmap_task_hub.py` の実体はすべて存在し、Python構文検査も通った。「missing generator/parser」ではなく、Phase遷移からこれらを呼ぶローカル配線が未確認なのが本質である。

## 30_plan / HTML の実態

`skills/viewing-plans/SKILL.md:38-44,75-104` と `context/workflow-rules.md:646-661` は Phase 2/5 にRoadmapとMCP Viewerを自動表示すると記述する。しかし `settings.json:431-438` で実際に登録されているのは `workflow-html-app` MCPだけで、generator/syncのhook登録はない。MCP serverのPlan/Log/Verification tool/resourceは `mcp-servers/workflow-html-app/server.ts:15-115,175-229` にあり、dist実体もある。Log resourceも `server.ts:98` でplan-viewer.htmlを共有する。

Trusted adapterとして `scripts/sync-roadmap.py:123-194,250-282` は route、`05_log`、Phase 2 Delegation Decision、`30_plan`、generator存在を検査し、`scripts/generate-roadmap-view.py` を起動する。ただし起動後はartifact存在とfingerprint確認だけ (`sync-roadmap.py:213-247`) で、HTML static gateを呼ばない。generatorは `generate-roadmap-view.py:167-181` でatomic writeするが、`write_outputs:902-930` で `task-meta.json` とHTMLを直接更新する。契約文書が一時出力を検証してからpublishするとする記述 (`context/html-artifact-contract.md:52-58,85`) と実装がずれている。

### 不採用案の履歴: 一時taskへの複製

以下は調査時の案で、採用していない。現在はCodex共通CLIを直接使う。

既存 `30_plan.md` を守る調査時の暫定案は、元task directoryを直接渡さず、`30_plan.md` と `05_log.md`（必要な成果物だけ）を一時の新規task directoryへ複製し、`--source-root` を明示してgeneratorを実行し、`verify-html-surfaces.py`/単体HTML契約を通過した出力だけを採用すること。`--output`だけでは `ensure_task_meta()` が元task directoryへ書くため (`generate-roadmap-view.py:889-908`)、dirty/untracked保護にならない。renderer間のsymlink/aliasは確認できなかった。

## 完了・学習の接続

- Phase 5 は `90_verification.md` と状態図を条件付き必須とする (`context/workflow-rules.md:471-490`) が、両Skillのfrontmatterは `invocation: user` (`skills/generate-verification-guide/SKILL.md:9-10`, `skills/generate-state-diagram/SKILL.md:11-12`)。自動Hookはない。
- Phase 5.5 はsolutions/memories保存を指示する (`context/workflow-rules.md:492-508`) が、`compounding-knowledge/SKILL.md:174-197` は提案→AskUserQuestion→承認後Write。`settings.json:363-386` のSubagentStop実体 `hooks/stop-subagent-compound.sh:14-31` は完了ログと実行提案だけで、知識を保存しない。
- `stop-workflow-check.sh:70-94` はPhase 3/4/5の語句を探すだけで、acceptance、Delegation Decision、checkpoint、Roadmap、verification、learningを検証しない。

## 欠落・重複

- `context/workflow-rules.md:89,361-369,465` が参照する `skills/subagent-driven-development/SKILL.md` と `skills/interrogating-pre-pr/SKILL.md` は存在しない。
- `README.md:54,91,328-349` が示す `large-task` Skill/commandも存在しない。
- `/lfg` は「常にdeepening・規模別固定ラウンド」とする (`commands/lfg.md:34-45`) 一方、workflow正本は不確実性が高い時だけdeepening (`workflow-rules.md:228-240`)、リスク制でreviewし早期完了可 (`workflow-rules.md:262-280`) とする。薄い入口という説明とも重複・矛盾する。
- `context/html-artifact-contract.md:85` のstatic検証→publish保証は、上記generator/syncの呼出し経路に実装されていない。

## メモリ蓄積（`.claude/.local/memory` 直下のみ）

直下task directoryは15件。`30_plan.md` 6件、`05_log.md` 14件、両方6件、`task-meta.json` 4件、`roadmap.html` 4件、`roadmap-snapshot.json` 0件、`checkpoint.md` 2件、`80_review.md` 1件。`30_plan.md`のないログtaskは8件。直下taskとその配下のsymlinkは0件。

## 安全な確認と小修正案

実行済みの読み取り専用確認: settings JSON parse + hook literal target存在 PASS、全hook `bash -n` PASS、関連Python 7本のcompile PASS、workflow JSの`node --check` PASS、`verify-html-surfaces.py --root /Users/yoshiki/.claude` PASS (0 errors/0 warnings)。

優先度順に、(1) trusted local launcherを1本だけ正本化し、`sync-roadmap.py`→生成→HTML static gate→PASS時publishを実装する、(2) `/lfg` と `workflow-rules` のreview/deepening条件を一方へ寄せる、(3) 不在Skill/large-task参照を実体追加または現行経路へのリンクへ整理する、が小さい修正である。この時点では一時taskでのadapter検証を提案していた。この案は不採用となり、実装ではCodex共通CLIを直接利用する。
