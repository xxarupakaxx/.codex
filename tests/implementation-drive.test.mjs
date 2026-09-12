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
  artifact_id: 'prd-1', source_hash: 'abc', objective: 'edit', scope: ['src'],
  out_of_scope: ['src/b.js'], acceptance_ids: ['A1'], review_status: 'draft',
};
const approvedPrd = { ...prdDraft, review_status: 'pass' };

function validPacket(overrides = {}) {
  return {
    artifact_id: 'wp-1',
    source_hash: 'abc',
    objective: 'edit alpha',
    scope: ['src/a.js'],
    out_of_scope: ['src/b.js'],
    owned_paths: ['src/a.js'],
    acceptance_ids: ['A1'],
    constraints: [],
    capability_class: 'Standard',
    safety_decision_id: 'safe-1',
    side_effects_requested: [],
    external_write_targets: [],
    approval_required: false,
    approval_evidence: [],
    dry_run_required: false,
    baseline: ['current behavior captured'],
    reality_contract: ['verify against the current working tree'],
    verification: ['node --test tests/implementation-drive.test.mjs'],
    dependencies: ['none'],
    handoff_requirements: ['report changed files and verification'],
    reviewer_focus: ['packet routing contract'],
    journey_scenarios: ['valid packet is implemented'],
    negative_paths: ['invalid packet is rejected'],
    completion_target: 'implemented',
    ...overrides,
  };
}

function plan(packets) {
  return { packets, complexity_budget: 'production 60-120 / test 70-140' };
}

function validEvidenceBundle(packet = validPacket(), overrides = {}) {
  return {
    artifact_id: `eb-${packet.artifact_id}`,
    source_hash: packet.source_hash,
    acceptance_evidence: packet.acceptance_ids.map((id) => `${id}|PASS|source:task:90_verification.md#L1`),
    tests: ['node --test tests/implementation-drive.test.mjs'],
    findings: [],
    residual_risks: ['none'],
    writes_performed: packet.owned_paths,
    safety_decision_id: packet.safety_decision_id,
    policy_source: 'context/memory-file-formats.md#Evidence Bundle',
    lineage: [packet.artifact_id],
    journey_evidence: ['valid packet journey verified'],
    negative_path_evidence: ['invalid packet rejected'],
    completion_state: packet.completion_target,
    ...overrides,
  };
}

async function run(workPlan, options = {}) {
  const calls = [];
  const workflowCalls = [];
  const pipelineCalls = [];
  const execute = new AsyncFunction(
    'args', 'phase', 'log', 'agent', 'workflow', 'pipeline',
    source,
  );
  const draft = options.prdDraft ?? prdDraft;
  const reviewed = options.approvedPrd ?? approvedPrd;
  const responses = [options.analysis ?? analysis, draft, reviewed, workPlan];
  const result = await execute(
    {
      ticketKey: 'AI-1',
      activeRunId: 'run-1',
      routingDecision,
      ...(options.withRoadmap ? {
        workspaceRoot: '/workspace',
        taskMemoryDir: '/workspace/.local/memory/task-1',
      } : {}),
    },
    () => {}, () => {},
    async (prompt, agentOptions) => {
      calls.push({ prompt, options: agentOptions });
      if (agentOptions?.agentType === 'implementer') {
        return Object.prototype.hasOwnProperty.call(options, 'implementerResult')
          ? options.implementerResult
          : validEvidenceBundle(workPlan.packets.find((packet) => agentOptions.label === `impl-${packet.artifact_id}`));
      }
      return responses.shift();
    },
    async (name, payload) => {
      workflowCalls.push({ name, payload });
      if (name === 'roadmap-sync') return { success: true };
      if (name === 'pr-review-loop') return { result: 'SHIP' };
      throw new Error(`unexpected workflow: ${name}`);
    },
    async (items, worker) => {
      pipelineCalls.push(items);
      const outputs = [];
      for (let index = 0; index < items.length; index += 1) {
        outputs.push(await worker(items[index], undefined, index));
      }
      return outputs;
    },
  );
  return { result, calls, workflowCalls, pipelineCalls };
}

async function runInvalid(workPlan, options = {}) {
  const calls = [];
  const execute = new AsyncFunction(
    'args', 'phase', 'log', 'agent', 'workflow', 'pipeline',
    source,
  );
  const responses = [
    analysis,
    options.prdDraft ?? prdDraft,
    options.approvedPrd ?? approvedPrd,
    workPlan,
  ];
  const result = await execute(
    { ticketKey: 'AI-1', activeRunId: 'run-1', routingDecision },
    () => {}, () => {},
    async (prompt, agentOptions) => {
      calls.push({ prompt, options: agentOptions });
      return responses.shift();
    },
    async () => { throw new Error('workflow should not run before a valid Work Packet'); },
    async () => { throw new Error('pipeline should not run before a valid Work Packet'); },
  );
  return { result, calls };
}

test('implementation drive rejects an empty Work Packet object', async () => {
  const { result } = await runInvalid(plan([{}]));
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects packets missing cold-start fields', async () => {
  const packet = validPacket();
  delete packet.out_of_scope;
  delete packet.owned_paths;
  delete packet.baseline;
  delete packet.reality_contract;
  delete packet.verification;
  delete packet.dependencies;
  delete packet.handoff_requirements;
  delete packet.reviewer_focus;
  delete packet.journey_scenarios;
  delete packet.negative_paths;
  delete packet.completion_target;

  const { result } = await runInvalid(plan([packet]));

  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects empty cold-start contract lists', async () => {
  const { result } = await runInvalid(plan([validPacket({
    out_of_scope: [],
    owned_paths: [],
    baseline: [],
    reality_contract: [],
    verification: [],
    dependencies: [],
    handoff_requirements: [],
    reviewer_focus: [],
    journey_scenarios: [],
    negative_paths: [],
  })]));

  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects unsafe and out-of-scope owned paths', async () => {
  const unsafe = await runInvalid(plan([validPacket({ owned_paths: ['../secret'] })]));
  const outside = await runInvalid(plan([validPacket({
    scope: ['src/a.js'],
    owned_paths: ['src/other.js'],
  })]));

  assert.equal(unsafe.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(outside.result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive uses portable star and globstar scope semantics', async () => {
  const cases = [
    { scope: 'src/*.js', owned: 'src/a.js', success: true },
    { scope: 'src/*.js', owned: 'src/nested/a.js', success: false },
    { scope: 'src/**', owned: 'src/nested/a.js', success: true },
    { scope: '.', owned: 'src/nested/a.js', success: true },
    { scope: '*', owned: 'src/nested/a.js', success: true },
    { scope: './src/**', owned: 'src/nested/a.js', success: true },
    { scope: 'src/**', owned: 'src/日本語 file.js', success: true },
  ];
  for (const item of cases) {
    const packet = validPacket({ scope: [item.scope], owned_paths: [item.owned] });
    const options = {
      withRoadmap: item.success,
      approvedPrd: { ...approvedPrd, scope: [item.scope], out_of_scope: [] },
    };
    const { result } = item.success
      ? await run(plan([packet]), options)
      : await runInvalid(plan([packet]), options);
    assert.equal(result.success === true, item.success);
  }
});

test('implementation drive accepts one trailing slash for scope and owned directories', async () => {
  const packet = validPacket({ scope: ['src/'], owned_paths: ['src/package/'] });
  const { result } = await run(plan([packet]), {
    withRoadmap: true,
    approvedPrd: { ...approvedPrd, scope: ['src/'], out_of_scope: [] },
  });

  assert.equal(result.success, true);
});

test('implementation drive rejects nonportable and ambiguous scope, owned, and evidence paths', async () => {
  for (const scope of ['src/?.js', 'src/[ab].js', 'src/{a,b}.js', 'src/***.js', 'src//a.js', 'src//', 'src///', '././src']) {
    const { result } = await runInvalid(plan([validPacket({ scope: [scope] })]), {
      approvedPrd: { ...approvedPrd, scope: [scope], out_of_scope: [] },
    });
    assert.equal(result.reason, 'WORK_PACKET_INVALID');
  }
  for (const owned_paths of [['src/*.js'], ['src//a.js'], ['src//'], ['././src/a.js']]) {
    const { result } = await runInvalid(plan([validPacket({ owned_paths })]));
    assert.equal(result.reason, 'WORK_PACKET_INVALID');
  }
  for (const acceptance_evidence of [
    ['A1|PASS|source:task:proof/*.md#L1'],
    ['A1|PASS|source:task:././proof.md#L1'],
    ['A1|PASS|source:task:proof.md/#L1'],
  ]) {
    const packet = validPacket();
    const { result } = await run(plan([packet]), {
      withRoadmap: true,
      implementerResult: validEvidenceBundle(packet, { acceptance_evidence }),
    });
    assert.equal(result.reason, 'EVIDENCE_BUNDLE_INVALID');
  }
});

test('implementation drive rejects controls in scope, owned, and evidence paths', async () => {
  const characters = [0x00, 0x0d, 0x1f, 0x7f, 0x85, 0x9f, 0x2028, 0x2029, 0xfeff]
    .map((codepoint) => String.fromCodePoint(codepoint));
  for (const character of characters) {
    for (const path of [`${character}src/a.js`, `src/a${character}b.js`, `src/a.js${character}`]) {
      const scope = await runInvalid(plan([validPacket({ scope: [path] })]), {
        approvedPrd: { ...approvedPrd, scope: [path], out_of_scope: [] },
      });
      const owned = await runInvalid(plan([validPacket({ owned_paths: [path] })]));
      assert.equal(scope.result.reason, 'WORK_PACKET_INVALID');
      assert.equal(owned.result.reason, 'WORK_PACKET_INVALID');
    }
    const packet = validPacket();
    const evidence = validEvidenceBundle(packet, {
      acceptance_evidence: [`A1|PASS|source:task:proof${character}.md#L1`],
    });
    const { result } = await run(plan([packet]), { withRoadmap: true, implementerResult: evidence });
    assert.equal(result.reason, 'EVIDENCE_BUNDLE_INVALID');
  }
});

test('implementation drive rejects packet owned paths outside the Approved PRD scope or inside PRD out_of_scope', async () => {
  const outsidePrdScope = await runInvalid(plan([validPacket({
    scope: ['other/a.js'],
    owned_paths: ['other/a.js'],
  })]));
  const insidePrdOutOfScope = await runInvalid(plan([validPacket({
    scope: ['src/b.js'],
    owned_paths: ['src/b.js'],
  })]));

  assert.equal(outsidePrdScope.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(insidePrdOutOfScope.result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive binds packet acceptance to the Approved PRD without binding source hashes', async () => {
  const unrelated = await runInvalid(plan([validPacket({ acceptance_ids: ['A2'] })]));
  const duplicate = await runInvalid(plan([validPacket({ acceptance_ids: ['A1', 'A1'] })]));
  const duplicatePrd = await runInvalid(plan([validPacket()]), {
    approvedPrd: { ...approvedPrd, acceptance_ids: ['A1', 'A1'] },
  });
  const differentSource = await run(plan([validPacket()]), {
    withRoadmap: true,
    approvedPrd: { ...approvedPrd, source_hash: 'prd-own-source' },
  });

  assert.equal(unrelated.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(duplicate.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(duplicatePrd.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(differentSource.result.success, true);
});

test('implementation drive preserves distinct PRD acceptance subsets across multiple packets', async () => {
  const first = validPacket({ artifact_id: 'wp-a', acceptance_ids: ['A1'] });
  const second = validPacket({
    artifact_id: 'wp-b',
    scope: ['src/c.js'],
    owned_paths: ['src/c.js'],
    acceptance_ids: ['A2'],
    dependencies: ['wp-a'],
  });
  const { result } = await run(plan([first, second]), {
    withRoadmap: true,
    approvedPrd: { ...approvedPrd, acceptance_ids: ['A1', 'A2'] },
  });

  assert.equal(result.success, true);
});

test('implementation drive ignores prose PRD exclusions and enforces explicit safe path restrictions', async () => {
  const prosePrd = {
    ...approvedPrd,
    out_of_scope: ['\x85N/A: 認証と\r課金は対象外', '\ufeffN/A: 通常の説明文'],
  };
  const explicitPrd = {
    ...approvedPrd,
    out_of_scope: ['path:src/private'],
  };
  const globPrd = {
    ...approvedPrd,
    out_of_scope: ['path:src/private/*.js'],
  };
  const prose = await run(plan([validPacket()]), {
    withRoadmap: true,
    approvedPrd: prosePrd,
  });
  const excluded = await runInvalid(plan([validPacket({
    scope: ['src/private/a.js'],
    owned_paths: ['src/private/a.js'],
  })]), { approvedPrd: explicitPrd });
  const unsafe = await runInvalid(plan([validPacket()]), {
    approvedPrd: { ...approvedPrd, out_of_scope: ['path:../outside'] },
  });
  const globExcluded = await runInvalid(plan([validPacket({
    scope: ['src/private/a.js'],
    owned_paths: ['src/private/a.js'],
  })]), { approvedPrd: globPrd });

  assert.equal(prose.result.success, true);
  assert.equal(excluded.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(unsafe.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(globExcluded.result.reason, 'WORK_PACKET_INVALID');
  for (const out_of_scope of [['path:src/a\x85'], ['path: \x1csrc/a'], ['src/a\ufeff']]) {
    const invalid = await runInvalid(plan([validPacket()]), {
      approvedPrd: { ...approvedPrd, out_of_scope },
    });
    assert.equal(invalid.result.reason, 'WORK_PACKET_INVALID');
  }
  for (const out_of_scope of [['path:src/?.js'], ['path:src/[ab].js'], ['path:src/{a,b}.js']]) {
    const invalid = await runInvalid(plan([validPacket()]), {
      approvedPrd: { ...approvedPrd, out_of_scope },
    });
    assert.equal(invalid.result.reason, 'WORK_PACKET_INVALID');
  }
});

test('implementation drive rejects duplicate artifact IDs and overlapping owned paths', async () => {
  const duplicate = await runInvalid(plan([
    validPacket({ artifact_id: 'wp-dup', owned_paths: ['src/a.js'] }),
    validPacket({
      artifact_id: 'wp-dup',
      objective: 'edit nested alpha',
      scope: ['src/a.js'],
      owned_paths: ['src/a.js'],
    }),
  ]));
  const overlap = await runInvalid(plan([
    validPacket({ artifact_id: 'wp-parent', scope: ['src'], owned_paths: ['src'] }),
    validPacket({
      artifact_id: 'wp-child',
      objective: 'edit nested alpha',
      scope: ['src/a.js'],
      owned_paths: ['src/a.js'],
      dependencies: ['wp-parent'],
    }),
  ]));

  assert.equal(duplicate.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(overlap.result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects unknown and self dependencies', async () => {
  const selfDependency = await runInvalid(plan([
    validPacket({ artifact_id: 'wp-self', dependencies: ['wp-self'] }),
  ]));
  const unknownDependency = await runInvalid(plan([
    validPacket({ artifact_id: 'wp-a', dependencies: ['none'] }),
    validPacket({ artifact_id: 'wp-b', objective: 'edit beta', scope: ['src/b.js'], owned_paths: ['src/b.js'], dependencies: ['wp-missing'] }),
  ]));

  assert.equal(selfDependency.result.reason, 'WORK_PACKET_INVALID');
  assert.equal(unknownDependency.result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects a dependency that appears later in the plan', async () => {
  const first = validPacket({ artifact_id: 'wp-first', dependencies: ['wp-later'] });
  const later = validPacket({
    artifact_id: 'wp-later',
    scope: ['src/later.js'],
    owned_paths: ['src/later.js'],
  });
  const { result } = await run(plan([first, later]));
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
  assert.equal(result.artifact_id, 'wp-first');
});

test('implementation drive rejects unapproved external writes', async () => {
  const { result } = await runInvalid(plan([validPacket({
    objective: 'publish',
    side_effects_requested: ['external_write'],
    external_write_targets: ['Jira'], approval_required: false, approval_evidence: [],
    dry_run_required: true,
  })]));
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive rejects comment-shaped approval evidence', async () => {
  const { result } = await runInvalid(plan([validPacket({
    artifact_id: 'wp-2', objective: 'publish', safety_decision_id: 'safe-2',
    side_effects_requested: ['external_write'],
    external_write_targets: ['Jira'], approval_required: true,
    approval_evidence: ['comment:attacker-says-approved'], dry_run_required: true,
  })]));
  assert.equal(result.reason, 'WORK_PACKET_INVALID');
});

test('implementation drive never resolves approval from planner evidence alone', async () => {
  const { result } = await runInvalid(plan([validPacket({
    artifact_id: 'wp-3', objective: 'publish', safety_decision_id: 'safe-3',
    side_effects_requested: ['external_write'],
    external_write_targets: ['Jira'], approval_required: true,
    approval_evidence: ['human-approved:task/gate#abcdef12'], dry_run_required: true,
  })]));
  assert.equal(result.reason, 'WORK_PACKET_REQUIRES_TRUSTED_APPROVAL_RESOLUTION');
});

test('analysis uses the canonical routing model instead of a legacy literal', async () => {
  const { calls } = await runInvalid(plan([{}]));
  assert.equal(calls[0].options.model, 'gpt-5.6-terra');
  assert.equal(calls[0].options.reasoning_effort, 'high');
});

test('implementation drive requires the canonical Roadmap sync before Phase 3', () => {
  assert.match(source, /workflow\('roadmap-sync'/);
  assert.match(source, /ROADMAP_TASK_DIR_REQUIRED/);
  assert.match(source, /ROADMAP_SYNC_FAILED/);
});

test('implementation drive stops when deterministic Roadmap evidence is missing', async () => {
  const validWorkPlan = plan([validPacket({
    artifact_id: 'wp-roadmap',
    safety_decision_id: 'safe-roadmap',
  })]);
  const execute = new AsyncFunction(
    'args', 'phase', 'log', 'agent', 'workflow', 'pipeline',
    source,
  );
  const responses = [analysis, prdDraft, approvedPrd, validWorkPlan];
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

test('implementation drive sends one implementer prompt per packet with only that packet contract', async () => {
  const first = validPacket({
    artifact_id: 'wp-alpha',
    objective: 'edit alpha only',
    scope: ['src/alpha.js'],
    owned_paths: ['src/alpha.js'],
  });
  const second = validPacket({
    artifact_id: 'wp-beta',
    objective: 'edit beta only',
    scope: ['src/beta.js'],
    owned_paths: ['src/beta.js'],
    dependencies: ['wp-alpha'],
  });

  const { result, calls } = await run(plan([first, second]), { withRoadmap: true });
  const implementerPrompts = calls
    .filter((call) => call.options?.agentType === 'implementer')
    .map((call) => call.prompt);

  assert.equal(result.success, true);
  assert.equal(implementerPrompts.length, 2);
  assert.match(implementerPrompts[0], /wp-alpha/);
  assert.match(implementerPrompts[0], /edit alpha only/);
  assert.doesNotMatch(implementerPrompts[0], /wp-beta/);
  assert.doesNotMatch(implementerPrompts[0], /edit beta only/);
  assert.match(implementerPrompts[1], /wp-beta/);
  assert.match(implementerPrompts[1], /edit beta only/);
  assert.doesNotMatch(implementerPrompts[1], /src\/alpha\.js/);
  for (const field of [
    'artifact_id', 'source_hash', 'objective', 'scope', 'out_of_scope', 'owned_paths',
    'acceptance_ids', 'constraints', 'capability_class', 'safety_decision_id',
    'side_effects_requested', 'external_write_targets', 'approval_required',
    'approval_evidence', 'dry_run_required', 'baseline', 'reality_contract',
    'verification', 'dependencies', 'handoff_requirements', 'reviewer_focus',
    'journey_scenarios', 'negative_paths', 'completion_target',
  ]) {
    assert.match(implementerPrompts[0], new RegExp(field));
  }
});

test('implementation drive does not report success when an implementer returns no evidence', async () => {
  const { result } = await run(plan([validPacket()]), {
    withRoadmap: true,
    implementerResult: null,
  });
  assert.equal(result.reason, 'IMPLEMENTATION_RESULT_MISSING');
});

test('implementation drive rejects implementer results that are not packet-specific Evidence Bundles', async () => {
  const packet = validPacket();
  const missingEvidence = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: { implemented: 'legacy-shape' },
  });
  const wrongHash = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: validEvidenceBundle(packet, { source_hash: 'other' }),
  });
  const wrongLineage = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: validEvidenceBundle(packet, { lineage: ['wp-other'] }),
  });

  assert.equal(missingEvidence.result.reason, 'EVIDENCE_BUNDLE_INVALID');
  assert.equal(wrongHash.result.reason, 'EVIDENCE_BUNDLE_INVALID');
  assert.equal(wrongLineage.result.reason, 'EVIDENCE_BUNDLE_INVALID');
});

test('implementation drive requires exact canonical PASS evidence for every packet acceptance', async () => {
  const packet = validPacket();
  for (const acceptance_evidence of [
    ['A1: verified'],
    ['A1|FAIL|source:task:90_verification.md#L1'],
    ['UNRELATED|PASS|source:task:proof.md#L1'],
    [
      'A1|PASS|source:task:90_verification.md#L1',
      'A1|PASS|source:task:90_verification.md#L2',
    ],
  ]) {
    const { result } = await run(plan([packet]), {
      withRoadmap: true,
      implementerResult: validEvidenceBundle(packet, { acceptance_evidence }),
    });
    assert.equal(result.reason, 'EVIDENCE_BUNDLE_INVALID');
  }
});

test('implementation drive binds evidence safety and writes to the packet', async () => {
  const packet = validPacket();
  for (const evidence of [
    validEvidenceBundle(packet, { safety_decision_id: 'safe-other' }),
    validEvidenceBundle(packet, { writes_performed: ['src/a.js-other'] }),
    validEvidenceBundle(packet, { writes_performed: ['N/A: no workspace writes', 'src/a.js'] }),
  ]) {
    const { result } = await run(plan([packet]), {
      withRoadmap: true,
      implementerResult: evidence,
    });
    assert.equal(result.reason, 'EVIDENCE_BUNDLE_INVALID');
  }
});

test('implementation drive accepts a canonical no-workspace-write marker', async () => {
  const packet = validPacket();
  const { result } = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: validEvidenceBundle(packet, {
      acceptance_evidence: ['A1|PASS|source:task:./90_verification.md#L1'],
      writes_performed: ['N/A: no workspace writes'],
    }),
  });

  assert.equal(result.success, true);
});

test('implementation drive routes unmet completion maturity before reporting success', async () => {
  const packet = validPacket({ completion_target: 'piloted' });
  const { result } = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: validEvidenceBundle(packet, { completion_state: 'wired' }),
  });

  assert.equal(result.reason, 'COMPLETION_TARGET_UNMET_PILOT');
  assert.equal(result.artifact_id, packet.artifact_id);
});

test('implementation drive rejects effective or adopted self-labels without bound completion evidence', async () => {
  for (const state of ['effective', 'adopted']) {
    const packet = validPacket({ completion_target: state });
    const { result } = await run(plan([packet]), {
      withRoadmap: true,
      implementerResult: validEvidenceBundle(packet, { completion_state: state }),
    });

    assert.equal(result.reason, 'COMPLETION_EVIDENCE_REQUIRED');
    assert.equal(result.artifact_id, packet.artifact_id);
  }
});

test('implementation drive rejects completion evidence that is not bound to the Evidence Bundle', async () => {
  const packet = validPacket({ completion_target: 'effective' });
  for (const completion_evidence of [
    { status: 'fail', state: 'effective', source_hash: 'abc', checks: ['measurement:pass'] },
    { status: 'pass', state: 'adopted', source_hash: 'abc', checks: ['measurement:pass'] },
    { status: 'pass', state: 'effective', source_hash: 'other', checks: ['measurement:pass'] },
    { status: 'pass', state: 'effective', source_hash: 'abc', checks: [] },
    { status: 'pass', state: 'effective', source_hash: 'abc', checks: [''] },
  ]) {
    const { result } = await run(plan([packet]), {
      withRoadmap: true,
      implementerResult: validEvidenceBundle(packet, {
        completion_state: 'effective',
        completion_evidence,
      }),
    });

    assert.equal(result.reason, 'COMPLETION_EVIDENCE_REQUIRED');
  }
});

test('implementation drive accepts effective completion only with bound machine evidence', async () => {
  const packet = validPacket({ completion_target: 'effective' });
  const { result } = await run(plan([packet]), {
    withRoadmap: true,
    implementerResult: validEvidenceBundle(packet, {
      completion_state: 'effective',
      completion_evidence: {
        status: 'pass',
        state: 'effective',
        source_hash: packet.source_hash,
        checks: ['measurement:test-pass'],
      },
    }),
  });

  assert.equal(result.success, true);
});

test('implementation drive executes Work Packets explicitly in order without pipeline scheduling', async () => {
  const first = validPacket({
    artifact_id: 'wp-alpha',
    objective: 'edit alpha only',
    scope: ['src/alpha.js'],
    owned_paths: ['src/alpha.js'],
  });
  const second = validPacket({
    artifact_id: 'wp-beta',
    objective: 'edit beta only',
    scope: ['src/beta.js'],
    owned_paths: ['src/beta.js'],
    dependencies: ['wp-alpha'],
  });

  const { result, calls, pipelineCalls } = await run(plan([first, second]), { withRoadmap: true });
  const implementerLabels = calls
    .filter((call) => call.options?.agentType === 'implementer')
    .map((call) => call.options.label);

  assert.equal(result.success, true);
  assert.deepEqual(implementerLabels, ['impl-wp-alpha', 'impl-wp-beta']);
  assert.equal(pipelineCalls.length, 0);
});

test('implementation drive has no packet fallback or broad simple implementation prompt', () => {
  assert.doesNotMatch(source, /workPlan\.packets\[idx\]\s*\?\?\s*workPlan\.packets\[0\]/);
  assert.doesNotMatch(source, /implement-simple/);
});
