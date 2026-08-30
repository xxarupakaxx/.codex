export const meta = {
  name: 'implementation-drive',
  description: 'Jiraチケット分析 → 実装方針決定 → 実装・テスト・レビュー',
  whenToUse: 'Jiraチケットを仕様化し、trusted Roadmap executor channelが未接続なら実装前に安全停止するとき。args: {ticketKey, workspaceRoot, taskMemoryDir, routingDecision, useTournament?, allowExternalWrite?, approvalEvidence?}',
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
const nonEmptyText = (value) => typeof value === 'string' && value.trim().length > 0
const listOfText = (value) => Array.isArray(value) && value.every(nonEmptyText)
const requiredWorkPacketFields = [
  'artifact_id', 'source_hash', 'objective', 'scope', 'out_of_scope', 'owned_paths',
  'acceptance_ids', 'constraints', 'capability_class', 'safety_decision_id',
  'side_effects_requested', 'external_write_targets', 'approval_required',
  'approval_evidence', 'dry_run_required', 'baseline', 'reality_contract',
  'verification', 'dependencies', 'handoff_requirements', 'reviewer_focus',
  'journey_scenarios', 'negative_paths', 'completion_target',
]
const workPacketListFields = [
  'scope', 'out_of_scope', 'owned_paths', 'acceptance_ids', 'constraints',
  'side_effects_requested', 'external_write_targets', 'approval_evidence',
  'baseline', 'reality_contract', 'verification', 'dependencies',
  'handoff_requirements', 'reviewer_focus', 'journey_scenarios', 'negative_paths',
]
const nonEmptyContractLists = [
  'scope', 'out_of_scope', 'owned_paths', 'acceptance_ids', 'baseline',
  'reality_contract', 'verification', 'dependencies', 'handoff_requirements',
  'reviewer_focus', 'journey_scenarios', 'negative_paths',
]
const completionTargets = new Set(['implemented', 'wired', 'piloted', 'effective', 'adopted'])
const completionRank = new Map([
  ['implemented', 0],
  ['wired', 1],
  ['piloted', 2],
  ['effective', 3],
  ['adopted', 4],
])
const completionTargetAction = new Map([
  ['wired', 'WIRE'],
  ['piloted', 'PILOT'],
  ['effective', 'MEASURE'],
  ['adopted', 'ADOPT'],
])
const highCompletionStates = new Set(['effective', 'adopted'])
const normalizeRelativePath = (value) => String(value).replace(/^(\.\/)+/, '').replace(/\/+$/, '')
const safeOwnedPath = (value) => {
  if (!nonEmptyText(value) || value.includes('\\') || value.startsWith('/')) return false
  const normalized = normalizeRelativePath(value)
  if (!normalized || normalized === '.' || normalized.startsWith('../') || normalized.includes('/../')) return false
  if (normalized.split('/').some((segment) => !segment || segment === '.' || segment === '..')) return false
  return !/[*?[\]{}]/.test(normalized)
}
const escapeRegExp = (value) => value.replace(/[.+?^${}()|[\]\\]/g, '\\$&')
const globToRegExp = (pattern) => {
  let regex = ''
  const input = String(pattern)
  for (let index = 0; index < input.length; index += 1) {
    if (input[index] === '*' && input[index + 1] === '*') {
      regex += '.*'
      index += 1
    } else if (input[index] === '*') {
      regex += '[^/]*'
    } else {
      regex += escapeRegExp(input[index])
    }
  }
  return new RegExp(`^${regex}$`)
}
const scopeCoversOwnedPath = (scopeEntry, ownedPath) => {
  if (!nonEmptyText(scopeEntry)) return false
  const scope = normalizeRelativePath(scopeEntry)
  const owned = normalizeRelativePath(ownedPath)
  if (scope === '*' || scope === '.') return true
  if (scope.includes('*')) return globToRegExp(scope).test(owned)
  return owned === scope || owned.startsWith(`${scope}/`)
}
const ownedPathsOverlap = (left, right) => {
  const a = normalizeRelativePath(left)
  const b = normalizeRelativePath(right)
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`)
}
const pathWithinOwnedPath = (ownedPath, writePath) => {
  const owned = normalizeRelativePath(ownedPath)
  const write = normalizeRelativePath(writePath)
  return write === owned || write.startsWith(`${owned}/`)
}
const evidenceBundleFields = [
  'artifact_id', 'source_hash', 'acceptance_evidence', 'tests', 'findings',
  'residual_risks', 'writes_performed', 'safety_decision_id', 'policy_source',
  'lineage', 'journey_evidence', 'negative_path_evidence', 'completion_state',
]
const evidenceBundleArrayFields = [
  'acceptance_evidence', 'tests', 'findings', 'residual_risks',
  'writes_performed', 'lineage', 'journey_evidence', 'negative_path_evidence',
]
const requiredEvidenceLists = [
  'acceptance_evidence', 'tests', 'writes_performed',
  'lineage', 'journey_evidence', 'negative_path_evidence',
]
const validCompletionEvidence = (evidence) => {
  const completionEvidence = evidence?.completion_evidence
  return completionEvidence
    && completionEvidence.status === 'pass'
    && completionEvidence.state === evidence.completion_state
    && completionEvidence.source_hash === evidence.source_hash
    && listOfText(completionEvidence.checks)
    && completionEvidence.checks.length > 0
}
const validateEvidenceBundle = (packet, evidence) => {
  const hasShape = evidence
    && evidenceBundleFields.every((field) => Object.prototype.hasOwnProperty.call(evidence, field))
    && ['artifact_id', 'source_hash', 'safety_decision_id', 'policy_source'].every((field) => nonEmptyText(evidence[field]))
    && evidenceBundleArrayFields.every((field) => Array.isArray(evidence[field]))
    && requiredEvidenceLists.every((field) => listOfText(evidence[field]) && evidence[field].length > 0)
    && completionTargets.has(evidence.completion_state)
  if (!hasShape) return { ok: false, reason: 'EVIDENCE_BUNDLE_INVALID' }
  if (highCompletionStates.has(evidence.completion_state) && !validCompletionEvidence(evidence)) {
    return { ok: false, reason: 'COMPLETION_EVIDENCE_REQUIRED' }
  }
  const sourceBound = evidence.source_hash === packet.source_hash
    && evidence.safety_decision_id === packet.safety_decision_id
    && evidence.lineage.includes(packet.artifact_id)
    && packet.acceptance_ids.every((id) => (
      evidence.acceptance_evidence.some((item) => item === id || item.startsWith(`${id}:`) || item.startsWith(`${id} `))
    ))
    && evidence.writes_performed.every((path) => (
      safeOwnedPath(path)
      && packet.owned_paths.some((ownedPath) => pathWithinOwnedPath(ownedPath, path))
    ))
  if (!sourceBound) return { ok: false, reason: 'EVIDENCE_BUNDLE_INVALID' }
  if (completionRank.get(evidence.completion_state) < completionRank.get(packet.completion_target)) {
    return {
      ok: false,
      reason: `COMPLETION_TARGET_UNMET_${completionTargetAction.get(packet.completion_target) ?? 'IMPLEMENT'}`,
    }
  }
  return { ok: true }
}
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
          scope: { type: 'array', minItems: 1, items: { type: 'string' } },
          out_of_scope: { type: 'array', minItems: 1, items: { type: 'string' } },
          owned_paths: { type: 'array', minItems: 1, items: { type: 'string' } },
          acceptance_ids: { type: 'array', minItems: 1, items: { type: 'string' } },
          constraints: { type: 'array', items: { type: 'string' } },
          capability_class: { type: 'string', enum: ['Fast', 'Standard', 'Heavy', 'Judgment'] },
          safety_decision_id: { type: 'string' },
          side_effects_requested: { type: 'array', items: { type: 'string' } },
          external_write_targets: { type: 'array', items: { type: 'string' } },
          approval_required: { type: 'boolean' },
          approval_evidence: { type: 'array', items: { type: 'string' } },
          dry_run_required: { type: 'boolean' },
          baseline: { type: 'array', minItems: 1, items: { type: 'string' } },
          reality_contract: { type: 'array', minItems: 1, items: { type: 'string' } },
          verification: { type: 'array', minItems: 1, items: { type: 'string' } },
          dependencies: { type: 'array', minItems: 1, items: { type: 'string' } },
          handoff_requirements: { type: 'array', minItems: 1, items: { type: 'string' } },
          reviewer_focus: { type: 'array', minItems: 1, items: { type: 'string' } },
          journey_scenarios: { type: 'array', minItems: 1, items: { type: 'string' } },
          negative_paths: { type: 'array', minItems: 1, items: { type: 'string' } },
          completion_target: { type: 'string', enum: ['implemented', 'wired', 'piloted', 'effective', 'adopted'] },
        },
        required: [
          'artifact_id', 'source_hash', 'objective', 'scope', 'out_of_scope', 'owned_paths',
          'acceptance_ids', 'constraints', 'capability_class', 'safety_decision_id',
          'side_effects_requested', 'external_write_targets', 'approval_required',
          'approval_evidence', 'dry_run_required', 'baseline', 'reality_contract',
          'verification', 'dependencies', 'handoff_requirements', 'reviewer_focus',
          'journey_scenarios', 'negative_paths', 'completion_target',
        ],
      },
    },
    complexity_budget: { type: 'string' },
  },
  required: ['packets', 'complexity_budget'],
}
const workPlan = await agent(`
Approved PRDから、実装者へ渡すWork Packetを作成してください。

各packetには次のfieldを必ず含めてください:
artifact_id, source_hash, objective, scope, out_of_scope, owned_paths, acceptance_ids, constraints, capability_class, safety_decision_id, side_effects_requested, external_write_targets, approval_required, approval_evidence, dry_run_required, baseline, reality_contract, verification, dependencies, handoff_requirements, reviewer_focus, journey_scenarios, negative_paths, completion_target。

scope / out_of_scope / owned_paths / acceptance_ids / baseline / reality_contract / verification / dependencies / handoff_requirements / reviewer_focus / journey_scenarios / negative_paths は非空listにしてください。依存がないpacketは dependencies: ["none"] と明示してください。dependency IDは別packetのartifact_idだけを参照し、owned_pathsはscopeのsubsetかつpacket間で重複しない安全なrepo相対pathにしてください。

## Approved PRD
${JSON.stringify(prdReview)}

## canonical routing decision
${JSON.stringify(routingDecision)}
`, {
  label: 'work-packet-plan', phase: 'Spec', agentType: 'implementation-planner', schema: WORK_PACKET_PLAN_SCHEMA,
})

if (!Array.isArray(workPlan?.packets) || !workPlan.packets.length) {
  return { success: false, reason: 'WORK_PACKET_MISSING' }
}
const approvalGatedEffects = new Set([
  'external_write', 'permission_change', 'billing_change', 'authentication_change',
  'destructive_action', 'runtime_policy_change', 'go_nogo_decision',
])
const artifactIds = new Set()
let invalidPacket
for (const packet of workPlan.packets) {
  if (!nonEmptyText(packet?.artifact_id) || artifactIds.has(packet.artifact_id)) {
    invalidPacket = packet
    break
  }
  artifactIds.add(packet.artifact_id)
}
const artifactOrder = new Map(workPlan.packets.map((packet, index) => [packet.artifact_id, index]))
const ownedPaths = []
if (!invalidPacket) {
  invalidPacket = workPlan.packets.find((packet, packetIndex) => {
    const hasContractShape = packet
      && requiredWorkPacketFields.every((field) => Object.prototype.hasOwnProperty.call(packet, field))
      && ['artifact_id', 'source_hash', 'objective', 'safety_decision_id'].every((field) => nonEmptyText(packet[field]))
      && workPacketListFields.every((field) => listOfText(packet[field]))
      && typeof packet.approval_required === 'boolean'
      && typeof packet.dry_run_required === 'boolean'
      && completionTargets.has(packet.completion_target)
    if (!hasContractShape) return true
    if (nonEmptyContractLists.some((field) => packet[field].length === 0)) return true
    if (packet.capability_class !== routingDecision.capability_class) return true
    if (packet.side_effects_requested.some((effect) => !approvalGatedEffects.has(effect))) return true
    if (!packet.owned_paths.every(safeOwnedPath)) return true
    if (!packet.owned_paths.every((path) => packet.scope.some((scope) => scopeCoversOwnedPath(scope, path)))) return true
    if (!packet.owned_paths.every((path) => prdReview.scope.some((scope) => scopeCoversOwnedPath(scope, path)))) return true
    if (packet.owned_paths.some((path) => prdReview.out_of_scope.some((scope) => scopeCoversOwnedPath(scope, path)))) return true
    const dependencyIds = packet.dependencies.filter((dependency) => dependency !== 'none')
    if (packet.dependencies.includes('none') && packet.dependencies.length > 1) return true
    if (dependencyIds.some((dependency) => (
      dependency === packet.artifact_id
      || !artifactIds.has(dependency)
      || artifactOrder.get(dependency) >= packetIndex
    ))) return true
    if (packet.owned_paths.some((path) => ownedPaths.some((existing) => ownedPathsOverlap(existing, path)))) return true
    ownedPaths.push(...packet.owned_paths)
    const requiresApproval = packet.external_write_targets.length > 0
      || packet.side_effects_requested.length > 0
      || packet.approval_required
    return requiresApproval && (
      packet.approval_required !== true || !validApprovalEvidence(packet.approval_evidence)
    )
  })
}
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

const workspaceRoot = args?.workspaceRoot
const taskMemoryDir = args?.taskMemoryDir
if (
  typeof workspaceRoot !== 'string'
  || !workspaceRoot.startsWith('/')
  || typeof taskMemoryDir !== 'string'
  || !taskMemoryDir.startsWith(`${workspaceRoot}/.local/memory/`)
) {
  return { success: false, reason: 'ROADMAP_TASK_DIR_REQUIRED' }
}
const roadmapSync = await workflow('roadmap-sync', {
  workspaceRoot,
  taskDir: taskMemoryDir,
  runId: args?.activeRunId,
  phase: '2',
})
if (!roadmapSync?.success) {
  return { success: false, reason: roadmapSync?.reason ?? 'ROADMAP_SYNC_FAILED' }
}

// --- Phase 3: Implement ---
phase('Implement')

let implResult

if (analysis.useTournament) {
  log(`A/BトーナメントモードでWork Packet単位実装: ${workPlan.packets.length}件`)
  implResult = []
  for (let idx = 0; idx < workPlan.packets.length; idx += 1) {
    const packet = workPlan.packets[idx]
    implResult.push(await workflow('tournament-ab', {
      task: `${ticketKey}: ${analysis.title} / Work Packet ${idx + 1}: ${packet.artifact_id}`,
      spec: JSON.stringify({ approved_prd: prdReview, work_packet: packet }),
    }))
  }
  const failedTournament = implResult.find((result) => result && result.winner === null)
  if (failedTournament) {
    log(`トーナメント勝者なし: ${failedTournament.reason ?? 'no winner'}`)
    return { success: false, reason: failedTournament.reason ?? 'tournament: no winner', tournament: failedTournament }
  }
} else {
  log(`Work Packet単位の実装モード: ${workPlan.packets.length}件`)
  implResult = []
  for (let idx = 0; idx < workPlan.packets.length; idx += 1) {
    const packet = workPlan.packets[idx]
    implResult.push(await agent(`
Work Packet ${idx + 1}/${workPlan.packets.length} を実装してください。このpromptの実装契約は次の1packetだけです。

## 親チケット
${ticketKey} — ${analysis.title}

## Approved PRD context
${JSON.stringify({
  artifact_id: prdReview.artifact_id,
  source_hash: prdReview.source_hash,
  objective: prdReview.objective,
  acceptance_ids: prdReview.acceptance_ids,
})}

## Work Packet contract
${JSON.stringify(packet, null, 2)}

## 必ず読むcold-start fields
artifact_id, source_hash, objective, scope, out_of_scope, owned_paths, acceptance_ids, constraints, capability_class, safety_decision_id, side_effects_requested, external_write_targets, approval_required, approval_evidence, dry_run_required, baseline, reality_contract, verification, dependencies, handoff_requirements, reviewer_focus, journey_scenarios, negative_paths, completion_target

## ルール
- owned_paths内だけを変更し、scope外や他packetのowned_pathsへ書かない
- baselineとreality_contractを現在のsourceで確認してから実装する
- verificationに記載された検証を実行する
- acceptance evidence、journey evidence、negative path evidence、writes_performedをpacket-specificに報告する
- handoff_requirementsに従い、残課題とreviewer_focus向けの確認点を返す
- commit / push / external commentはこのworkflow内では行わない
    `, {
      label: `impl-${packet.artifact_id}`,
      phase: 'Implement',
      agentType: 'implementer',
      model: routingDecision.model,
      reasoning_effort: routingDecision.reasoning_effort,
      service_tier: 'priority',
      // Work Packetは親workflowの同一作業ツリー上で順序どおり統合する。
    }))
  }
}

if (
  !Array.isArray(implResult)
  || implResult.length !== workPlan.packets.length
  || implResult.some((result) => !result)
) {
  return { success: false, reason: 'IMPLEMENTATION_RESULT_MISSING' }
}
for (let idx = 0; idx < workPlan.packets.length; idx += 1) {
  const packet = workPlan.packets[idx]
  const evidence = analysis.useTournament ? implResult[idx]?.evidence_bundle : implResult[idx]
  const evidenceCheck = validateEvidenceBundle(packet, evidence)
  if (!evidenceCheck.ok) {
    return { success: false, reason: evidenceCheck.reason, artifact_id: packet.artifact_id, evidence }
  }
}

// --- Phase 4: Verify（read-only reviewとfix packet routing）---
phase('Verify')
log('検証＋read-only reviewを実行中（findingはfix用Work Packetへ戻す）')
const verifyResult = await workflow('pr-review-loop', {
  baseBranch: args?.baseBranch ?? '',
  autoFix: false,
  reviewDimensions: args?.reviewDimensions,
  safetyTriggers: args?.safetyTriggers ?? [],
  changedPaths: args?.changedPaths ?? workPlan.packets.flatMap((packet) => packet.owned_paths),
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
