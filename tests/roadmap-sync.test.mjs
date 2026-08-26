import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../workflows/roadmap-sync.js', import.meta.url), 'utf8')
  .replace('export const meta', 'const meta');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

async function run(args) {
  const execute = new AsyncFunction('args', 'phase', source);
  return execute(args, () => {});
}

test('missing evidence cannot advance the workflow', async () => {
  const result = await run({});
  assert.equal(result.reason, 'ROADMAP_TRUSTED_EXECUTOR_REQUIRED');
});

test('synthetic matching evidence is rejected as model-controlled input', async () => {
  const hash = 'a'.repeat(64);
  const result = await run({
    workspaceRoot: '/workspace',
    taskDir: '/workspace/.local/memory/task-1',
    runId: 'run-1',
    phase: '2',
    adapterResult: {
      status: 'synchronized',
      route: 'roadmap',
      phase: '2',
      run_id: 'run-1',
      workspace_root: '/workspace',
      task_dir: '/workspace/.local/memory/task-1',
      generated_at_unix: Date.now() / 1000,
      source_fingerprints: { '05_log.md': hash, '30_plan.md': hash },
      artifact_fingerprints: {
        'roadmap.html': hash,
        'roadmap-snapshot.json': hash,
      },
    },
  });
  assert.equal(result.success, false);
  assert.equal(result.reason, 'ROADMAP_TRUSTED_EXECUTOR_REQUIRED');
});
