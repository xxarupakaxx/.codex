# Workflow・context・計画運用の一次資料調査

- 調査日: 2026-08-31
- 件数: 31件（原論文20件、公式記事・公式文書・公式仕様11件）
- 対象: context engineering、progressive disclosure、long-running harness、planning、dependency/requirement traceability、evals、agent memory、reflectionの限界、multi-agentの費用と境界
- 検証方法: すべてのURLをwebで直接openした。検索結果のsnippetは根拠に数えていない。
- 読めた範囲: 原論文はarXivのメタデータとabstractを中心に確認し、PDF全文を読んだとは扱わない。公式記事・仕様は各項目に記した主要節を直接確認した。日付はページで検証できた場合だけ記録した。
- 一次性: arXivは著者が公開する原論文ページ、Anthropic/OpenAIは当該社の公式記事・文書、NASAは公式handbook、MCPは公式仕様である。公式記事・case studyは査読研究とは区別する。

## 調査から得た共通原則

### 1. 常駐contextは短い入口にし、詳細は必要時に取得する

長い入力では、関連情報の位置によって検索性能が下がる実験がある（[S31](https://arxiv.org/abs/2307.03172)）。Anthropicも有限の注意資源、context rot、JIT retrieval、圧縮のトレードオフを説明している（[S01](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)）。したがって、毎回すべてのworkflow・phase・履歴を読む構成は採らない。

最小の入口には、目的、scope、安全境界、現在の一単位、完了条件、次に読む参照先だけを置く。必要なときにphase、関連module、過去のevidence、domainの正本をたどる。JIT retrievalや圧縮にも誤検索・遅延・情報欠落があるため、取得元の版または更新時刻を記録し、重要な制約を要約へ隠さない。

### 2. 計画は作業の一覧ではなく、検証可能な契約にする

Plan-and-Solveは先に分解してから解く効果を報告するが、plan自体の誤りや実環境の依存を扱わない（[S10](https://arxiv.org/abs/2305.04091)）。SWE-benchは現実のissue、複数ファイル、実行環境、テストを一体で測る（[S09](https://arxiv.org/abs/2310.06770)）。Anthropicのlong-running harnessでも、feature listと一つずつの作業、次回への構造化artifactが、早期の勝利宣言を抑える実験上の手段になっている（[S04](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）。

最小schemaは `requirement_id`、`goal`、`scope`、`depends_on`、`planned_paths`、`acceptance`、`verification`、`evidence`、`status`、`last_verified_at` を持つ。要件から変更・検証へ進むforward traceと、変更・証跡から要件へ戻るbackward traceの両方を検査する。計画の存在や自然言語の「完了」は証拠ではない。

### 3. 完了は外部の状態・テスト・traceで判定する

NASAのhandbookはbidirectional traceabilityで未対応要件と親のない要素を見つけることを勧める（[S27](https://swehb.nasa.gov/spaces/7150/pages/16450285/SWE-052%2B-%2BBidirectional%2BTraceability%2BBetween%2BHigher%2BLevel%2BRequirements%2Band%2BSoftware%2BRequirements)）。Anthropicのeval設計は、task、trial、grader、transcript、outcome、harnessを分け、coding taskではテストと安定した環境を中心に置く（[S25](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)）。Web・desktop benchmarkも、画面の文章ではなく操作後の状態を採点する（[S16](https://arxiv.org/abs/2307.13854), [S22](https://arxiv.org/abs/2404.07972)）。

したがって `task_state=completed` は、(a)全acceptanceが存在する、(b)それぞれに検証方法と実行済みevidenceがある、(c)evidenceの対象path・revisionが現在と整合する、(d)依存とscopeに孤立がない、を満たすときだけ許可する。未検証、証跡なし、stale、片方向trace、依存未完了は `blocked` または `needs_review` に戻す。

### 4. 評価は決定的な層を主にし、主観graderを補助にする

Anthropicはcode-based graderを高速・安価・再現可能、model-based graderを柔軟だが非決定的、human graderを高品質だが高コストと整理している（[S25](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)）。自己評価は過度に肯定的になりやすく、独立evaluatorを置いても浅い探索や見逃しが残る（[S03](https://www.anthropic.com/engineering/harness-design-long-running-apps)）。内在的な自己訂正だけでは性能が上がらず悪化する場合もある（[S13](https://arxiv.org/abs/2310.01798)）。

小さい実装では、構文・schema・リンク・依存・ファイル状態・テスト・HTML生成の決定的検査を完了gateにする。自由記述の品質や設計判断だけをmodel/human reviewへ渡す。capability用の難しいfixtureと、既存動作を守るregression fixtureを分け、同じtaskを複数回走らせる必要がある場合はtrialごとの成功とばらつきを記録する（[S18](https://arxiv.org/abs/2406.12045), [S25](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)）。

### 5. 複数agent・探索・resetはリスクに応じたオプションにする

単純なlocalization→repair→validation pipelineが、SWE-bench Liteで複雑なagent構成に対して良い費用対効果を報告している（[S20](https://arxiv.org/abs/2407.01489)）。一方、planner、generator、evaluatorを使う著者実験では、長いアプリの要件抜けや実行時bugを発見しやすくなった（[S03](https://www.anthropic.com/engineering/harness-design-long-running-apps)）。同じ記事で構成を削ると、より新しいモデルではsprintやper-sprint evaluatorが不要になるtaskもあった。複数agentのframework研究も、協調の表現力は示すが、agent数の増加が常に品質向上することやtoken overheadを証明していない（[S19](https://arxiv.org/abs/2308.08155)）。

既定経路は一つの短いworkflowとし、曖昧性、変更範囲、長さ、失敗損失、モデルの既知の弱点が閾値を越えた場合だけ、独立review、候補探索、context reset、複数agentへ分岐する。導入・削除は同一fixtureで一要素ずつablationし、成功率、再現率、token、latency、費用を比較する。改善したという印象だけで固定化しない。

### 6. memoryは事実・訂正・制約・次の行動を中心にし、反省は候補として扱う

MemGPTは限られたmain contextと外部memoryを層として管理する設計を示す（[S14](https://arxiv.org/abs/2310.08560)）。Generative AgentsやReflexionは経験から要約・反省を作るが、主な検証環境はsimulationや外部feedback付きtaskである（[S15](https://arxiv.org/abs/2304.03442), [S07](https://arxiv.org/abs/2303.11366)）。OpenAIの社内data agent事例でも、memoryは非自明な訂正や制約、runtime check、gold outcomeと組み合わせている（[S30](https://openai.com/index/inside-our-in-house-data-agent/)）。

永続memoryには、観測事実、再現手順、失敗のevidence、採用済みの制約、次の確認を保存する。反省や改善提案は `candidate` として根拠・適用範囲・期限・試行結果を持たせ、検証に通るまでworkflow規則へ昇格しない。要件、安全境界、合意済みevidenceは自動忘却の対象から外す。

### 7. token削減は構成と実測を分け、保証しない

Anthropicのprompt cachingは同一prefixの再利用で処理時間・入力コストを下げるが、prefix全体をcacheし、不要な情報を意味的に減らす機能ではない（[S26](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)）。long-running taskの能力にも時間horizonがあり、無期限の継続を前提にできない（[S24](https://arxiv.org/abs/2503.14499)）。したがって「HTML化で何％削減」「JITで必ずtoken減」とは断定せず、入力token、cache hit、turn数、tool call数、latency、費用、再開成功率をfixtureごとに計測する。

## 今回の最小実装への勧告

1. **正本と表示を分ける。** 短いMarkdownまたはJSONの計画を機械的な正本にし、HTMLはそこから生成する読み取り用projectionにする。HTMLへ手で状態を書き戻さない。HTMLには、要件ID、依存、変更対象、検証コマンド、evidence、最終検証時刻、stale/uncheckedの理由を表示する（[S03](https://www.anthropic.com/engineering/harness-design-long-running-apps), [S04](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)）。

2. **既定のcontextを一画面相当のbriefにする。** `goal/scope/constraints/current unit/acceptance/next reads`だけを入口にし、workflow全文、phase詳細、過去log、domain資料は依存関係から必要時に開く。重要な要件と安全境界はbriefに残し、履歴の連結で長いpromptを作らない（[S01](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [S31](https://arxiv.org/abs/2307.03172)）。

3. **完了検査をstatus更新より先にする。** acceptanceごとに一つ以上の検証とevidenceを要求し、evidenceのpath・revision・実行時刻を検査する。完了済みtaskの依存漏れ、要件の未リンク、変更された後に古くなった証跡を負例としてfixture化する。未検証のまま完了statusだけを生成器へ渡す経路は閉じる（[S09](https://arxiv.org/abs/2310.06770), [S25](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), [S27](https://swehb.nasa.gov/spaces/7150/pages/16450285/SWE-052%2B-%2BBidirectional%2BTraceability%2BBetween%2BHigher%2BLevel%2BRequirements%2Band%2BSoftware%2BRequirements)）。

4. **改善を候補→試行→採否の三段階にする。** 失敗またはreviewから候補を作り、代表taskとheld-out taskで試し、成功率・漏れ・token・latency・費用・副作用を記録する。採用しなかった候補も理由と有効範囲だけ残す。自己反省文だけでpolicyや常駐contextを変更しない（[S07](https://arxiv.org/abs/2303.11366), [S12](https://arxiv.org/abs/2303.17651), [S13](https://arxiv.org/abs/2310.01798), [S29](https://www.anthropic.com/engineering/writing-tools-for-agents)）。

5. **複雑化は条件付きにする。** 初期は決定的なparser、dependency checker、evidence/freshness checker、HTML renderer、少数の実行evalで構成する。planner、独立evaluator、複数agent、Tree of Thoughts、context resetは、高riskまたは固定evalで失敗が再現した場合だけ候補にする。モデル更新ごとにload-bearingか再測定し、不要なscaffoldを残さない（[S02](https://www.anthropic.com/engineering/building-effective-agents), [S03](https://www.anthropic.com/engineering/harness-design-long-running-apps), [S11](https://arxiv.org/abs/2305.10601), [S19](https://arxiv.org/abs/2308.08155), [S20](https://arxiv.org/abs/2407.01489)）。

6. **ツールの返却値を検証可能にする。** context loader、plan parser、evidence checker、browser/state checkerは、曖昧な長文でなく、対象、revision、status、差分、エラー、次の操作を返す。realistic taskとheld-out taskで、tool選択、引数、出力サイズ、再現率、エラーを測る（[S21](https://arxiv.org/abs/2405.15793), [S23](https://arxiv.org/abs/2412.05467), [S29](https://www.anthropic.com/engineering/writing-tools-for-agents)）。

## 反証と不採用の境界

| 候補 | 採用しない既定理由 | 条件付きで試す条件 |
|---|---|---|
| 全履歴・全規則を常駐promptへ連結 | 長contextの位置効果、context rot、読み飛ばしのリスク | context位置・必要情報のretrieval evalで有効性が確認できる場合 |
| 自由な自己reflectionをmemoryへ保存 | self-correctionが失敗・悪化し得て、反省文は事実の証拠でない | 外部test/state/human feedbackに結び付いた候補記録として |
| 全taskを複数agentで処理 | coordination、token、latency、誤り伝播。単純pipelineが強い反証もある | 長期・高不確実性でsingle-agentの失敗が再現し、ablationでliftが確認できる場合 |
| planner/sprint/evaluator/resetの固定 | モデル更新でload-bearing性が変わる。第一者実験にも過剰な例がある | task riskと現在モデルの評価器で必要性が確認できる場合 |
| LLMだけの完了判定 | 自己評価が甘く、graderも未探索bugを残す | 決定的test/state検査の補助スコアとして |
| memoryの自動forgetting | 要件・安全・evidenceの消失が復旧不能になり得る | 低価値の一過性ログだけに期限と復元元を付けて |
| prompt cachingをcontext設計の代替にする | cacheは再計算を減らすが、不要contextとstale情報を除かない | stable prefixを測定後にcacheし、freshnessを別検査する場合 |
| vendor SDKのsessionを正本にする | API・仕様の変更で再現性と移植性を失う | 自前schemaへexportし、SDKはruntime/tracingの補助に限定する場合 |

## Source catalogue

### S01 — [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

- **type / date / primaryity:** official engineering article / 2025-09-29 / Anthropicの公式第一者記事。
- **核心:** 有限の注意資源に高信号情報だけを入れ、JIT retrieval、圧縮、要約、subagentを使う。
- **限界:** 一般workflowのcontrolled comparisonではない。JITは遅延・誤検索、圧縮は細部欠落を伴う。
- **今回の判断:** 短い入口＋依存関係に基づくオンデマンド読込を採用。全量常駐は不採用。
- **読めた範囲:** context rot、JIT context、圧縮、要約、subagentの主要節を直接open。

### S02 — [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

- **type / date / primaryity:** official engineering article / 2024-12-19 / Anthropicの公式第一者記事。
- **核心:** 単純で組み合わせ可能なworkflowを先に使い、曖昧な経路だけagent、orchestrator、evaluatorへ広げる。
- **限界:** 顧客事例と設計指針であり、構成の普遍的な優劣やtoken削減率を示さない。
- **今回の判断:** 短い既定経路と条件付き深掘り、停止条件、環境の実結果を採用。
- **読めた範囲:** workflow/agentの使い分け、prompt chaining、routing、parallelization、orchestrator-workers、evaluator-optimizerを直接open。

### S03 — [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)

- **type / date / primaryity:** official experiment article / 2026-03-24 / Anthropicの公式第一者実験記事。
- **核心:** planner、generator、evaluator、構造化handoff、分割、実行中アプリを触るQAが、長い開発の要件抜けと実行時bugを拾う。
- **限界:** 特定のモデル、Webアプリ、prompt、evaluatorによる事例。evaluatorも浅い検査や甘い判定を残す。後続モデルでsprint/resetの必要性が下がった。
- **今回の判断:** contractとevidenceは採用するが、planner/sprint/evaluator/resetは固定せず一要素ずつablation。
- **読めた範囲:** reset対compaction、3agent構成、sprint contract、Playwright QA、Solo対Full、モデル更新後の簡素化、限界を直接open。

### S04 — [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

- **type / date / primaryity:** official experiment article / 2025-11-26 / Anthropicの公式第一者実験記事。
- **核心:** initializer、継続agent、feature list、progress file、git履歴、一回一feature、end-to-end testingでcontext跨ぎと早期完了宣言を抑える。
- **限界:** Claude SDKとWebアプリclone中心で、他モデル・他taskへの移植性は未検証。ブラウザ能力にも見逃しが残る。
- **今回の判断:** 次回brief、未完了要件、直近evidence、次の一単位を保存し、status更新を外部検証へ従属させる。
- **読めた範囲:** long-running problem、initializer/coding、JSON feature list、incremental progress、clean state、testing、起動時手順、失敗表を直接open。

### S05 — [A practical guide to building agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)

- **type / date / primaryity:** official product/engineering guide / 日付はページ上で検証できず / OpenAIの公式第一者文書。
- **核心:** agentはLLMでworkflowを制御し、toolを状態に応じて選び、guardrailの下で外部状態を扱う。決定的な処理には通常の自動化が適する。
- **限界:** 複数導入の知見をまとめたguideで、独立比較や特定taskの性能証明ではない。内容は更新され得る。
- **今回の判断:** 計画生成と外部writeを分け、モデル変更はevalで測る。
- **読めた範囲:** agent/workflow定義、agentを使う条件、LLM・tools・guardrails、model選択とevalの主要節を直接open。

### S06 — [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)

- **type / date / primaryity:** research paper abstract / 2023-03-10（arXiv v3改訂）/ 原論文。
- **核心:** 推論と環境への行動を交互に行い、結果を次の判断へ反映する。
- **限界:** 特定benchmarkとfew-shot設定で、任意の長期workflowの保証ではない。tool品質と行動回数に依存する。
- **今回の判断:** observe→plan更新→action→result確認の小さいloopを採用。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S07 — [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)

- **type / date / primaryity:** research paper abstract / 2023-10-10（arXiv v4改訂）/ 原論文。
- **核心:** 試行結果から自然言語反省を作り、episodic memoryとして次試行へ渡す。
- **限界:** feedback、反復、benchmark、model依存。反省文だけで正しい改善になるとは示さず、反復費用もある。
- **今回の判断:** 反省は外部evidenceに結び付けたcandidateとしてのみ保存。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S08 — [AgentBench: Evaluating LLMs as Agents](https://arxiv.org/abs/2308.03688)

- **type / date / primaryity:** research paper abstract / 2023-08-07（original submission）/ 原論文。
- **核心:** 8環境でagentを評価し、長期推論・意思決定・指示追従を共通の難所として扱う。
- **限界:** 環境、task、tool、graderに依存し、現行モデルの性能へ外挿できない。
- **今回の判断:** final textだけでなく、state、instruction、tool trace、途中失敗をfixtureへ含める。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S09 — [SWE-bench: Can Language Models Resolve Real-World GitHub Issues?](https://arxiv.org/abs/2310.06770)

- **type / date / primaryity:** research paper abstract / 2023-10-10（original submission）/ 原論文。
- **核心:** 実GitHub issue、複数file、repo環境、長文脈、test実行を含めて、理解から修正・検証まで測る。
- **限界:** repository、issue品質、test、環境に依存し、当時の性能数値は現在へ外挿できない。
- **今回の判断:** requirement→path→change→test→evidenceのtraceを完了条件にする。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S10 — [Plan-and-Solve Prompting](https://arxiv.org/abs/2305.04091)

- **type / date / primaryity:** research paper abstract / 2023-05-26（arXiv v3改訂）/ 原論文。
- **核心:** 先に分解planを作り、その後subtaskを解くことでzero-shot CoTの欠落・計算・意味解釈エラーを減らす。
- **限界:** GPT-3系とNLP benchmark中心で、実repoの依存・tool・evidenceを扱わない。plan誤りは伝播する。
- **今回の判断:** 要件・依存・検証方法を短くplanへ置くが、planを証拠にはしない。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S11 — [Tree of Thoughts](https://arxiv.org/abs/2305.10601)

- **type / date / primaryity:** research paper abstract / 2023-12-03（arXiv v2改訂）/ 原論文。
- **核心:** 複数候補を生成し、評価・先読み・backtrackする探索で一部の難taskを改善する。
- **限界:** 3課題と探索計算量に依存し、branch増加でtoken・latency・評価誤りが増える。
- **今回の判断:** 高不確実性・高損失の分岐だけ、予算と停止条件付きで試す。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S12 — [Self-Refine](https://arxiv.org/abs/2303.17651)

- **type / date / primaryity:** research paper abstract / 2023-05-25（arXiv v2改訂）/ 原論文。
- **核心:** 同じLLMが生成、feedback、refinementを反復し、7 taskで平均改善を報告する。
- **限界:** task、model、metricに依存し、独立criticではない。feedback誤り、過剰修正、反復費用がある。
- **今回の判断:** 最大round数と独立graderを置き、自己reviewを完了gateにしない。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S13 — [Large Language Models Cannot Self-Correct Reasoning Yet](https://arxiv.org/abs/2310.01798)

- **type / date / primaryity:** research paper abstract / 2024-03-14（arXiv改訂）/ 原論文。
- **核心:** 外部feedbackなしのintrinsic self-correctionは有効でなく、悪化する場合もある。
- **限界:** 検証model、task、promptに基づく結果で、外部feedback付きの検証を否定しない。
- **今回の判断:** modelの確信や反省文をevidenceにせず、test、state、diff、独立reviewを使う。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S14 — [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)

- **type / date / primaryity:** research paper abstract / 2023-10-12（original submission）/ 原論文。
- **核心:** 仮想memoryの発想でmain contextと外部memoryをpaging・interruptで管理する。
- **限界:** 文書分析・対話中心で、requirement traceやcode changeの一般解ではない。memory選択ミスで情報を失う。
- **今回の判断:** short brief、requirements/evidence、長期candidateを層に分け、read/writeを明示する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S15 — [Generative Agents](https://arxiv.org/abs/2304.03442)

- **type / date / primaryity:** research paper abstract / 2023-08-06（arXiv改訂）/ 原論文。
- **核心:** 経験記録、反省合成、記憶検索、計画で仮想社会の整合的行動を作る。
- **限界:** 25 agentのsimulationとbelievability評価で、engineering correctnessを測らない。整合的な物語は事実とは限らない。
- **今回の判断:** event、要約、根拠、期限を分け、主観的reflectionをpolicyへ直接反映しない。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S16 — [WebArena](https://arxiv.org/abs/2307.13854)

- **type / date / primaryity:** research paper abstract / 2024-04-16（arXiv改訂）/ 原論文。
- **核心:** 再現可能なcommerce/forum/dev/CMSのWeb環境で、状態変化を伴う長期taskを評価する。
- **限界:** サイト、task、初期状態のsnapshotで、現Web・現modelの性能を表さない。
- **今回の判断:** HTML表示だけでなく、操作後のend state、初期状態、リンクをfixture化する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S17 — [GAIA](https://arxiv.org/abs/2311.12983)

- **type / date / primaryity:** research paper abstract / 2023-11-21（original submission）/ 原論文。
- **核心:** 現実的な質問にreasoning、Web/tool、multimodalityを組み合わせる能力を測る。
- **限界:** 問題、tool、gold answer、benchmark版に依存し、古いbaselineを現性能にしない。答えだけでは状態変更を測らない。
- **今回の判断:** 内部taskをprompt、gold outcome、tool、隠し検証へ分ける。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S18 — [τ-bench](https://arxiv.org/abs/2406.12045)

- **type / date / primaryity:** research paper abstract / 2024-06-17（original submission）/ 原論文。
- **核心:** user simulation、domain API、policy、DB状態を組み合わせ、目標状態とpass^kで信頼性を測る。
- **限界:** simulator、policy、DB、model実装に依存する。単回pass率だけでは再現性と安全性を表さない。
- **今回の判断:** 永続状態・policy遵守・複数trialを完了評価へ含める。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S19 — [AutoGen](https://arxiv.org/abs/2308.08155)

- **type / date / primaryity:** research paper abstract / 2023-08-16（original submission）/ 原論文。
- **核心:** LLM、human、toolを会話可能な複数agentとして組み合わせるframework。
- **限界:** 表現力と例が中心で、agent数増加の品質効果やtoken overheadを証明しない。自由会話は重複・誤り伝播・停止不能を招く。
- **今回の判断:** role、artifact、最大turn、停止条件を固定し、single-agentと測定比較する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S20 — [Agentless](https://arxiv.org/abs/2407.01489)

- **type / date / primaryity:** research paper abstract / 2024-07-01（original submission）/ 原論文。
- **核心:** 自律的tool操作を避けたlocalization→repair→patch validationの単純pipelineが、SWE-bench Liteで強い費用対効果を示す。
- **限界:** 特定benchmark・設定・costであり、探索的・長期task全般でagentが不要とは示さない。
- **今回の判断:** parser、dependency checker、evidence checker、HTML生成を決定的にし、自由探索を必要箇所へ限定する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S21 — [SWE-agent](https://arxiv.org/abs/2405.15793)

- **type / date / primaryity:** research paper abstract / 2024-05-06（original submission）/ 原論文。
- **核心:** agent向けrepo閲覧・編集・test interfaceが同じLLMのsoftware engineering能力を左右する。
- **限界:** benchmark、interface、prompt、時間予算依存で、plan storageやHTMLを直接検証しない。
- **今回の判断:** tool出力をpath、行、差分、error中心に小さく安定させ、interface自体をevalする。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S22 — [OSWorld](https://arxiv.org/abs/2404.07972)

- **type / date / primaryity:** research paper abstract / 2024-04-11（original submission）/ 原論文。
- **核心:** 実desktop/Webアプリをまたぐ369 taskを初期状態から操作し、execution結果で評価する。
- **限界:** OS image、app版、操作器、model世代依存。見た目やtext planだけでは成果を保証しない。
- **今回の判断:** 必要なHTML操作、file state、browser interactionを実行ベースで確認する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S23 — [The BrowserGym Ecosystem for Web Agent Research](https://arxiv.org/abs/2412.05467)

- **type / date / primaryity:** research paper abstract / 2025-02-28（arXiv v4改訂）/ 原論文。
- **核心:** BrowserGymとAgentLabでWeb benchmarkの観測・行動、agent作成、テスト、分析、experiment管理を揃える。
- **限界:** Web benchmark/ecosystem設計であり、全業務環境やplan品質を証明しない。サイトとmodel差が大きい。
- **今回の判断:** task、初期状態、action、grader、resultを同一schemaで再現可能に保存する。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

### S24 — [Measuring AI Ability to Complete Long Software Tasks](https://arxiv.org/abs/2503.14499)

- **type / date / primaryity:** research paper abstract / 2025-03-18（original submission）/ 原論文。
- **核心:** software taskを完了できる時間horizonを測定し、単発正答率と長期能力を分離する。
- **限界:** task、model版、測定設計に依存し、外部妥当性に限界がある。改訂版の傾向や数値を現在・将来へ断定しない。
- **今回の判断:** taskサイズ、context跨ぎ、経過時間、復旧、最終成功を別指標として扱う。
- **読めた範囲:** arXiv metadataとabstract、現行版の限界記述を直接open。PDF全文は未読。

### S25 — [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

- **type / date / primaryity:** official evaluation engineering article / 2026-01-09 / Anthropicの公式第一者記事。
- **核心:** evalをtask、trial、grader、transcript、outcome、harnessへ分け、code/model/human graderを用途で組み合わせる。capabilityとregressionを分ける。
- **限界:** 内部・顧客経験に基づく設計記事。code graderはbrittle、model graderは非決定的、人手は高コスト。
- **今回の判断:** deterministic test/state/traceを主gate、主観評価を補助にし、固定regressionと探索capabilityを保存する。
- **読めた範囲:** eval構造、3種grader、capability/regression、coding test、transcript metrics、grader例を直接open。

### S26 — [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

- **type / date / primaryity:** official platform documentation / 日付はページ上で検証できず / Anthropic公式文書。
- **核心:** 同一prefixをcacheし、5分または1時間TTLで反復promptの処理時間と入力コストを下げる。対象はtools/system/messagesのprefix。
- **限界:** 現行Claude API仕様で、TTL、価格、model、条件は更新され得る。cacheは不要contextやstale情報を除かない。
- **今回の判断:** stable briefとdynamic stateを分けた後、測定した反復経路だけcacheする。
- **読めた範囲:** 概要、automatic/explicit breakpoint、TTL、prefix範囲、用途、価格表を直接open。

### S27 — [SWE-052 Bidirectional Traceability](https://swehb.nasa.gov/spaces/7150/pages/16450285/SWE-052%2B-%2BBidirectional%2BTraceability%2BBetween%2BHigher%2BLevel%2BRequirements%2Band%2BSoftware%2BRequirements)

- **type / date / primaryity:** official engineering handbook guidance / 2017-10-06（page last updated）/ NASA公式政府guidance。
- **核心:** requirements、design、code、test dataを双方向にtraceし、missing requirementとorphan elementを見つける。固有ID、source、owner、継続更新、小規模ならtext matrixを勧める。
- **限界:** NASAの安全・品質プロセス向けで、個人AI workflowへの規制や独立実証ではない。手動matrixはstaleになり得る。
- **今回の判断:** 最小schemaでforward/backward検査を自動化し、高riskから優先する。
- **読めた範囲:** RationaleとGuidanceのtrace、missing/orphan、matrix、ID/source/owner、電子管理、小規模projectの記述を直接open。

### S28 — [Model Context Protocol Specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18)

- **type / date / primaryity:** official protocol specification / 2025-06-18（仕様版）/ 公式open protocol。
- **核心:** resources、prompts、tools、roots、progress、cancellation、error、loggingなどの契約を定義し、data access/tool実行のuser consent、privacy、safetyを要求する。
- **限界:** 規格は実装の安全性・正確性・LLM品質を実証しない。仕様版、server、権限境界の差が残る。
- **今回の判断:** context/resource/toolをschema化し、scopeと外部writeを可視化する。計画と実行を分離する。
- **読めた範囲:** Overview、feature一覧、resources/prompts/tools、progress/cancellation/error/logging、security節を直接open。

### S29 — [Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)

- **type / date / primaryity:** official engineering article / 2025-09-11 / Anthropicの公式第一者記事。
- **核心:** realistic taskとverifiable outcomeでtoolを評価し、目的別の少数tool、明確なschema、短い意味のある出力、held-out testを使う。
- **限界:** Anthropicのtool開発経験と内部結果で、全domain/modelの最適解ではない。厳しすぎるverifierは有効な別解を落とす。
- **今回の判断:** loader、checker、state viewerを小さく名前空間化し、path/status/diff/errorを返す。held-out回帰で更新する。
- **読めた範囲:** tool試作、realistic task、verifiable outcome、held-out、出力設計、runtime/toolcall/token/error指標を直接open。

### S30 — [Inside OpenAI’s in-house data agent](https://openai.com/index/inside-our-in-house-data-agent/)

- **type / date / primaryity:** official case study / 2026-01-29 / OpenAIの公式第一者case study。
- **核心:** schema注釈、code enrichment、組織知識、memory、runtime contextを層に分け、gold SQL/result equivalence、continuous regression、runtime修正を組み合わせる。
- **限界:** OpenAI内部のdata platformとmodelに特化した事例で、controlled baselineや他domainへの一般化はない。
- **今回の判断:** contextを層に分け、memoryを訂正・制約中心にし、gold outcome・前提・権限・freshnessで自己改善を検証する。
- **読めた範囲:** 規模と失敗要因、layered context、code-backed semantics、memory、runtime checks、gold outcome、regression、access controlの主要節を直接open。

### S31 — [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172)

- **type / date / primaryity:** research paper abstract / 2023-11-20（arXiv v3改訂、TACL 2023情報）/ 原論文。
- **核心:** multi-document QAとkey-value retrievalで、関連情報が入力中央にあると先頭・末尾より性能が下がる。
- **限界:** 2種類のretrieval taskと当時のmodel中心で、すべての現行long-context modelや実環境へ直接外挿できない。
- **今回の判断:** 要件・停止条件・安全境界を短い入口と明示的取得結果へ置き、位置変化をcontext evalへ含める。
- **読めた範囲:** arXiv metadataとabstractを直接open。PDF全文は未読。

## 取り込み時の注意

- ここでの結論は、31件の一次資料から今回の小さい実装へ移す設計判断であり、将来の無欠陥、現在・将来モデルの性能、一定のtoken削減率を保証しない。
- 公式engineering記事とcase studyは、実験条件・モデル版・taskが限定された著者の経験として扱う。論文abstractは研究の主張と限界の入口であり、詳細な実験条件の最終確認にはPDF全文が別途必要になる。
- 反省、memory、複数agent、cache、HTMLは、要件・evidence・freshnessを置き換えない。採用後も代表fixture、held-out fixture、回帰fixtureの実測で継続判断する。
