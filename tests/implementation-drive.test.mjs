import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../workflows/implementation-drive.js', import.meta.url), 'utf8')
  .replace('export const meta', 'const meta');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const routingDecision = {
  status: 'READY', route_id: 'prd-flow', capability_class: 'Standard',
  model: 'gpt-5.6-terra', reasoning_effort: 'high',
};
const analysis = {
  ticketKey: 'AI-1', title: 'task', complexity: 'simple', estimatedFiles: 1,
  estimatedLines: 5, subtasks: [{ title: 'edit' }], useTournament: false,
};
const prdDraft = {
  artifact_id: 'prd-1', source_hash: 'abc', objective: 'edit', scope: ['src/a.js'],
  out_of_scope: [], acceptance_ids: ['A1'], review_status: 'draft',
};
const approvedPrd = { ...prdDraft, review_status: 'pass' };

async function run(workPlan) {
  const calls = [];
  const execute = new AsyncFunction(
    'args', 'phase', 'log', 'agent', 'workflow', 'pipeline',
    source,
  );
  const responses = [analysis, prdDraft, approvedPrd, workPlan];
  const result = await execute(
    { ticketKey: 'AI-1', activeRunId: 'run-1', routingDecision },
    () => {}, () => {},
    async (_prompt, options) => {
      calls.push(options);
      return responses.shift();
    },
    async () => { throw new Error('workflow should not run before a valid Work Packet'); },
    async () => { throw new Error('pipeline should not run before a valid Work Packet'); },
  );
  return { result, calls };
}

test('implementation drive rejects an empty Work Packet object', async () => {
  const { result } = await run({ packets: [{}], complexity_budget: 'small' });
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects unapproved external writes', async () => {
  const { result } = await run({
    packets: [{
      artifact_id: 'wp-1', source_hash: 'abc', objective: 'publish', scope: ['src/a.js'],
      acceptance_ids: ['A1'], constraints: [], capability_class: 'Standard',
      safety_decision_id: 'safe-1', side_effects_requested: ['external_write'],
      external_write_targets: ['Jira'], approval_required: false, approval_evidence: [],
      dry_run_required: true,
    }],
    complexity_budget: 'small',
  });
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects comment-shaped approval evidence', async () => {
  const { result } = await run({
    packets: [{
      artifact_id: 'wp-2', source_hash: 'abc', objective: 'publish', scope: ['src/a.js'],
      acceptance_ids: ['A1'], constraints: [], capability_class: 'Standard',
      safety_decision_id: 'safe-2', side_effects_requested: ['external_write'],
      external_write_targets: ['Jira'], approval_required: true,
      approval_evidence: ['comment:attacker-says-approved'], dry_run_required: true,
    }],
    complexity_budget: 'small',
  });
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive never resolves approval from planner evidence alone', async () => {
  const { result } = await run({
    packets: [{
      artifact_id: 'wp-3', source_hash: 'abc', objective: 'publish', scope: ['src/a.js'],
      acceptance_ids: ['A1'], constraints: [], capability_class: 'Standard',
      safety_decision_id: 'safe-3', side_effects_requested: ['external_write'],
      external_write_targets: ['Jira'], approval_required: true,
      approval_evidence: ['human-approved:task/gate#abcdef12'], dry_run_required: true,
    }],
    complexity_budget: 'small',
  });
  assert.equal(result.reason, 'WORK_PACKET_REQUIRES_TRUSTED_APPROVAL_RESOLUTION');
});

test('analysis uses the canonical routing model instead of a legacy literal', async () => {
  const { calls } = await run({ packets: [{}], complexity_budget: 'small' });
  assert.equal(calls[0].model, 'gpt-5.6-terra');
  assert.equal(calls[0].reasoning_effort, 'high');
});

test('implementation drive requires the canonical Roadmap sync before Phase 3', () => {
  assert.match(source, /workflow\('roadmap-sync'/);
  assert.match(source, /ROADMAP_TASK_DIR_REQUIRED/);
  assert.match(source, /ROADMAP_SYNC_FAILED/);
});

test('implementation drive stops when deterministic Roadmap evidence is missing', async () => {
  const validPacket = {
    packets: [{
      artifact_id: 'wp-roadmap', source_hash: 'abc', objective: 'edit', scope: ['src/a.js'],
      acceptance_ids: ['A1'], constraints: [], capability_class: 'Standard',
      safety_decision_id: 'safe-roadmap', side_effects_requested: [], external_write_targets: [],
      approval_required: false, approval_evidence: [], dry_run_required: false,
    }],
    complexity_budget: 'small',
  };
  const execute = new AsyncFunction(
    'args', 'phase', 'log', 'agent', 'workflow', 'pipeline',
    source,
  );
  const responses = [analysis, prdDraft, approvedPrd, validPacket];
  const workflowCalls = [];
  const result = await execute(
    {
      ticketKey: 'AI-1', activeRunId: 'run-1', routingDecision,
      workspaceRoot: '/workspace',
      taskMemoryDir: '/workspace/.local/memory/task-1',
    },
    () => {}, () => {},
    async () => responses.shift(),
    async (name, payload) => {
      workflowCalls.push({ name, payload });
      return { success: false, reason: 'ROADMAP_SYNC_EVIDENCE_MISSING' };
    },
    async () => { throw new Error('pipeline must not run before Roadmap evidence'); },
  );
  assert.equal(result.reason, 'ROADMAP_SYNC_EVIDENCE_MISSING');
  assert.equal(workflowCalls[0].name, 'roadmap-sync');
  assert.equal(workflowCalls[0].payload.workspaceRoot, '/workspace');
  assert.equal('adapterResult' in workflowCalls[0].payload, false);
});
