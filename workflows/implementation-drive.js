export const meta = {
  name: 'implementation-drive',
  description: 'Jiraチケット分析 → 実装方針決定 → 実装・テスト・レビュー',
  whenToUse: 'Jiraチケットの実装を自動化したいとき。LFG runtimeが解決したroutingDecisionが必須。args: {ticketKey, routingDecision, useTournament?, allowExternalWrite?, approvalEvidence?}',
  phases: [
    { title: 'Analyze', detail: 'チケット分析 + コードベース調査' },
    { title: 'Spec', detail: '仕様書ドラフト生成' },
    { title: 'Implement', detail: '実装（直接 or A/Bトーナメント）' },
    { title: 'Verify', detail: 'テスト + レビュー' },
    { title: 'Report', detail: 'Jiraに結果記録' },
  ],
}

const TASK_ANALYSIS_SCHEMA = {
  type: 'object',
  properties: {
    ticketKey: { type: 'string' },
    title: { type: 'string' },
    complexity: { type: 'string', enum: ['simple', 'medium', 'complex'] },
    estimatedFiles: { type: 'number' },
    estimatedLines: { type: 'number' },
    affectedModules: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
    subtasks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          title: { type: 'string' },
          description: { type: 'string' },
          estimatedLines: { type: 'number' },
        },
        required: ['title'],
      },
    },
    useTournament: { type: 'boolean' },
  },
  required: ['ticketKey', 'title', 'complexity', 'subtasks', 'useTournament'],
}

const ticketKey = args?.ticketKey
if (!ticketKey) {
  log('ticketKey が指定されていません')
  return { success: false, reason: 'ticketKey required in args' }
}
const routingDecision = args?.routingDecision
const activeRunId = args?.activeRunId ?? ''
if (
  routingDecision?.status !== 'READY'
  || !['Fast', 'Standard', 'Heavy', 'Judgment'].includes(routingDecision?.capability_class)
  || typeof routingDecision?.model !== 'string'
  || typeof routingDecision?.reasoning_effort !== 'string'
) {
  return { success: false, reason: 'ROUTING_BLOCKED: canonical routingDecision is required' }
}
if (!activeRunId) {
  return { success: false, reason: 'activeRunId is required before implementation writes' }
}
const validApprovalEvidence = (items) => Array.isArray(items)
  && items.length > 0
  && items.every((item) => typeof item === 'string'
    && /^(human-approved|user-validation):[A-Za-z0-9._/-]+#[a-f0-9]{8,64}$/.test(item))
const forceTournament = args?.useTournament ?? false

// --- Phase 1: Analyze ---
phase('Analyze')
log(`チケット ${ticketKey} の分析を開始`)

const analysis = await agent(`
Jiraチケット ${ticketKey} を分析してください。

## 手順
1. Jira MCPでチケット詳細を取得（説明、受入基準、コメント、関連チケット）
2. チケット内容からコードベースの関連箇所をGrep/Globで調査
3. 影響範囲を特定

## 判定基準
- simple: 1-5ファイル、100行以下、既存パターン踏襲
- medium: 5-15ファイル、100-500行、一部新規パターン
- complex: 15ファイル超 or 500行超 or 新規アーキテクチャ

## トーナメント推奨条件
以下のいずれかに該当する場合、useTournament=trueを設定:
- 複数の実装アプローチが考えられる
- パフォーマンスが重要
- complexityがcomplex
${forceTournament ? '\n**注意: ユーザーがトーナメント使用を明示的に指定しています。useTournament=trueにしてください。**' : ''}
`, {
  label: 'analyze',
  phase: 'Analyze',
  model: routingDecision.model,
  reasoning_effort: routingDecision.reasoning_effort,
  service_tier: 'priority',
  schema: TASK_ANALYSIS_SCHEMA,
})

if (!analysis) {
  return { success: false, reason: 'analysis failed' }
}

log(`分析完了: ${analysis.complexity} (${analysis.estimatedFiles}ファイル, ~${analysis.estimatedLines}行, tournament=${analysis.useTournament})`)

// --- Phase 2: Spec ---
phase('Spec')

const PRD_SCHEMA = {
  type: 'object',
  properties: {
    artifact_id: { type: 'string' }, source_hash: { type: 'string' }, objective: { type: 'string' },
    scope: { type: 'array', items: { type: 'string' } },
    out_of_scope: { type: 'array', items: { type: 'string' } },
    acceptance_ids: { type: 'array', items: { type: 'string' } },
    review_status: { type: 'string', enum: ['draft', 'pass', 'revise', 'block'] },
  },
  required: ['artifact_id', 'source_hash', 'objective', 'scope', 'out_of_scope', 'acceptance_ids', 'review_status'],
}

const prdDraft = await agent(`
Jiraチケット ${ticketKey} のApproved PRDドラフトを生成してください。

## チケット分析結果
${JSON.stringify(analysis)}

外部へ書き込まず、PRD_SCHEMAに従うJSONだけを返してください。review_statusはdraftにしてください。
`, {
  label: 'prd-draft',
  phase: 'Spec',
  agentType: 'requirement-parser',
  schema: PRD_SCHEMA,
})

const prdReview = await agent(`
次のPRDドラフトを、元のチケット分析とコード調査事実に照らしてread-onlyでレビューしてください。
Git、Jira、GitHub、artifactへの書き込みは禁止です。pass / revise / blockのいずれかを返し、passの場合だけ同じartifact_idのreview_statusをpassにしたPRDを返してください。

## 分析
${JSON.stringify(analysis)}

## PRDドラフト
${JSON.stringify(prdDraft)}
`, {
  label: 'prd-review', phase: 'Spec', agentType: 'prd-reviewer', schema: PRD_SCHEMA,
})

if (!prdReview || prdReview.review_status !== 'pass') {
  return { success: false, reason: `PRD_${String(prdReview?.review_status ?? 'REVIEW_FAILED').toUpperCase()}`, prd: prdReview }
}

const WORK_PACKET_PLAN_SCHEMA = {
  type: 'object',
  properties: {
    packets: {
      type: 'array', minItems: 1,
      items: {
        type: 'object',
        properties: {
          artifact_id: { type: 'string' }, source_hash: { type: 'string' }, objective: { type: 'string' },
          scope: { type: 'array', items: { type: 'string' } },
          acceptance_ids: { type: 'array', items: { type: 'string' } },
          constraints: { type: 'array', items: { type: 'string' } },
          capability_class: { type: 'string', enum: ['Fast', 'Standard', 'Heavy', 'Judgment'] },
          safety_decision_id: { type: 'string' },
          side_effects_requested: { type: 'array', items: { type: 'string' } },
          external_write_targets: { type: 'array', items: { type: 'string' } },
          approval_required: { type: 'boolean' },
          approval_evidence: { type: 'array', items: { type: 'string' } },
          dry_run_required: { type: 'boolean' },
        },
        required: [
          'artifact_id', 'source_hash', 'objective', 'scope', 'acceptance_ids', 'constraints',
          'capability_class', 'safety_decision_id', 'side_effects_requested',
          'external_write_targets', 'approval_required', 'approval_evidence', 'dry_run_required',
        ],
      },
    },
    complexity_budget: { type: 'string' },
  },
  required: ['packets', 'complexity_budget'],
}
const workPlan = await agent(`
Approved PRDから、実装者へ渡すWork Packetを作成してください。各packetにartifact_id、source_hash、objective、scope、acceptance_ids、constraints、capability_class、safety_decision_id、side_effects_requested、external_write_targets、approval_required、approval_evidence、dry_run_requiredを含めてください。

## Approved PRD
${JSON.stringify(prdReview)}

## canonical routing decision
${JSON.stringify(routingDecision)}
`, {
  label: 'work-packet-plan', phase: 'Spec', agentType: 'implementation-planner', schema: WORK_PACKET_PLAN_SCHEMA,
})

if (!workPlan?.packets?.length) {
  return { success: false, reason: 'WORK_PACKET_MISSING' }
}
const approvalGatedEffects = new Set([
  'external_write', 'permission_change', 'billing_change', 'authentication_change',
  'destructive_action', 'runtime_policy_change', 'go_nogo_decision',
])
const invalidPacket = workPlan.packets.find((packet) => {
  const hasContractShape = packet
    && typeof packet.artifact_id === 'string'
    && typeof packet.source_hash === 'string'
    && typeof packet.objective === 'string'
    && Array.isArray(packet.scope)
    && Array.isArray(packet.acceptance_ids)
    && Array.isArray(packet.constraints)
    && typeof packet.safety_decision_id === 'string'
    && Array.isArray(packet.side_effects_requested)
    && Array.isArray(packet.external_write_targets)
    && typeof packet.approval_required === 'boolean'
    && Array.isArray(packet.approval_evidence)
    && typeof packet.dry_run_required === 'boolean'
  if (!hasContractShape) return true
  const requiresApproval = packet.external_write_targets.length > 0
    || packet.side_effects_requested.some((effect) => approvalGatedEffects.has(effect))
  return packet.capability_class !== routingDecision.capability_class
    || (requiresApproval && (
      packet.approval_required !== true || !validApprovalEvidence(packet.approval_evidence)
    ))
})
if (invalidPacket) {
  return { success: false, reason: 'WORK_PACKET_INVALID', artifact_id: invalidPacket.artifact_id }
}
if (workPlan.packets.some((packet) => packet.approval_required)) {
  return {
    success: false,
    reason: 'WORK_PACKET_REQUIRES_TRUSTED_APPROVAL_RESOLUTION',
    workPackets: workPlan.packets,
  }
}

// --- Phase 3: Implement ---
phase('Implement')

let implResult

if (analysis.useTournament) {
  log('A/Bトーナメントモードで実装')
  implResult = await workflow('tournament-ab', {
    task: `${ticketKey}: ${analysis.title}`,
    spec: JSON.stringify({ approved_prd: prdReview, work_packets: workPlan.packets }),
  })
  // セキュリティ下限割れ等で勝者なしなら、下流に流さず失敗扱い
  if (implResult && implResult.winner === null) {
    log(`トーナメント勝者なし: ${implResult.reason ?? 'no winner'}`)
    return { success: false, reason: implResult.reason ?? 'tournament: no winner', tournament: implResult }
  }
} else if (analysis.complexity === 'simple' || !analysis.subtasks?.length) {
  log('シンプル実装モード')
  implResult = await agent(`
以下の仕様に基づいてコードを実装してください。

## チケット: ${ticketKey} — ${analysis.title}

## 仕様
${JSON.stringify({ approved_prd: prdReview, work_packets: workPlan.packets })}

## サブタスク
${analysis.subtasks.map((s, i) => `${i + 1}. ${s.title}: ${s.description ?? ''}`).join('\n')}

## ルール
- テストも一緒に書く
- 既存パターンに合わせる
- YAGNI: 依頼にない機能は追加しない
- commit / push / external commentはこのworkflow内では行わない
`, {
    label: 'implement-simple', phase: 'Implement', agentType: 'implementer',
    model: routingDecision.model, reasoning_effort: routingDecision.reasoning_effort, service_tier: 'priority',
  })
} else {
  log('パイプライン実装モード')
  implResult = await pipeline(
    analysis.subtasks,
    (subtask, _, idx) => agent(`
サブタスク ${idx + 1}/${analysis.subtasks.length} を実装してください。

## 親チケット: ${ticketKey} — ${analysis.title}
## サブタスク: ${subtask.title}
${subtask.description ? `## 説明\n${subtask.description}` : ''}

## 仕様コンテキスト
${JSON.stringify({ approved_prd: prdReview, work_packet: workPlan.packets[idx] ?? workPlan.packets[0] })}

## ルール
- このサブタスクの範囲のみ実装
- 直前のサブタスクの変更の上に積み増す（同一ブランチ/作業ツリー）
- テストも書く
- commit / push / external commentはこのworkflow内では行わない
    `, {
      label: `impl-${idx}`,
      phase: 'Implement',
      agentType: 'implementer',
      model: routingDecision.model,
      reasoning_effort: routingDecision.reasoning_effort,
      service_tier: 'priority',
      // 逐次サブタスクは互いの変更を前提に積み増すため worktree 隔離しない
      // （隔離すると後続サブタスクが前の成果を見られず、かつメイン未統合になる）
    }),
  )
}

// --- Phase 4: Verify（共通review→fix→re-review LOOP）---
phase('Verify')
log('検証＋自動修正ループ実行中（CRITICAL/IMPORTANTが0になるまで最大3ラウンド）')
const verifyResult = await workflow('pr-review-loop', {
  baseBranch: args?.baseBranch ?? '',
  maxRounds: 3,
  autoFix: true,
  reviewDimensions: args?.reviewDimensions,
  safetyTriggers: args?.safetyTriggers ?? [],
  changedPaths: args?.changedPaths ?? [],
  externalEvidence: [],
})

if (verifyResult?.result !== 'SHIP') {
  return { success: false, reason: `VERIFY_${String(verifyResult?.result ?? 'FAILED')}`, verifyResult }
}

// --- Phase 5: Report ---
phase('Report')

const reportWrite = {
  status: 'pending_trusted_approval_resolution',
  writes_performed: [],
  summary: { complexity: analysis.complexity, verifyResult },
}

log(`${ticketKey} の実装フローが完了`)

return {
  success: true,
  ticketKey,
  complexity: analysis.complexity,
  approvedPrd: prdReview,
  workPackets: workPlan.packets,
  routingDecision,
  reportWrite,
  tournament: analysis.useTournament,
  subtasks: analysis.subtasks.length,
}
