import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';


const html = readFileSync(new URL('../tools/roadmap_viewer.html', import.meta.url), 'utf8');
const sourceMatch = html.match(/\/\* ROADMAP_MODEL_START \*\/([\s\S]*?)\/\* ROADMAP_MODEL_END \*\//);
assert.ok(sourceMatch, 'viewer must expose its model source');

const context = vm.createContext({
  console, Date, Intl, JSON, Math, Map, Object, RegExp, Set, String,
  globalThis: {}
});
vm.runInContext(sourceMatch[1], context, { filename: 'roadmap-viewer-model.js' });
const modelApi = context.globalThis.__ROADMAP_MODEL__;

const codemapSnapshot = {
  schemaVersion: 1,
  version: 1,
  kind: 'codemap',
  title: 'Viewer subsystem',
  generatedAt: '2026-08-05T12:00:00Z',
  sourceFingerprint: 'abc123def456',
  lanes: [
    { id: 'entrypoints', title: 'Entrypoints', order: 0 },
    { id: 'runtime', title: 'Runtime', order: 1 },
    { id: 'tests', title: 'Tests', order: 2 }
  ],
  nodes: [
    { id: 'skill', title: 'viewing-plans', kind: 'entrypoint', lane: 'entrypoints', path: 'skills/viewing-plans/SKILL.md', summary: 'Starts both maps' },
    { id: 'generator', title: 'Generator', kind: 'module', lane: 'runtime', path: 'scripts/generate-roadmap-view.py', summary: 'Builds snapshots' },
    { id: 'viewer', title: 'Viewer', kind: 'ui', lane: 'runtime', path: 'tools/roadmap_viewer.html', summary: 'Renders topology' },
    { id: 'test', title: 'Viewer tests', kind: 'test', lane: 'tests', path: 'tests/roadmap-viewer.test.mjs', summary: 'Guards the viewer' }
  ],
  edges: [
    {
      id: 'caller', from: 'skill', to: 'generator', relation: 'calls', status: 'verified',
      evidence: [{ path: 'skills/viewing-plans/SKILL.md', line: 20, note: 'invokes generator' }]
    },
    {
      id: 'impact', from: 'generator', to: 'viewer', relation: 'affects', status: 'verified',
      evidence: [{ path: 'scripts/generate-roadmap-view.py', line: 719, note: 'injects snapshot' }]
    },
    {
      id: 'guard', from: 'test', to: 'viewer', relation: 'guards', status: 'unknown',
      reason: 'The precise DOM assertion is not confirmed.', evidence: []
    }
  ],
  counts: { lanes: 3, nodes: 4, edges: 3, unknown: 1 }
};

test('normalizeSnapshot preserves codemap machine fields and signature tracks relations', () => {
  const normalized = modelApi.normalizeSnapshot(codemapSnapshot);
  assert.equal(normalized.kind, 'codemap');
  assert.equal(normalized.sourceFingerprint, 'abc123def456');
  assert.equal(normalized.lanes.length, 3);
  assert.equal(normalized.nodes.length, 4);
  assert.equal(normalized.edges.length, 3);

  const changed = structuredClone(codemapSnapshot);
  changed.edges[2].status = 'verified';
  changed.edges[2].evidence = [{ path: 'tests/roadmap-viewer.test.mjs', line: 1 }];
  assert.notEqual(modelApi.snapshotSignature(codemapSnapshot), modelApi.snapshotSignature(changed));
});

test('codemap adapter keeps lane order and evidence-backed predicates', () => {
  const tree = modelApi.buildTreeViewModel(modelApi.buildModel(codemapSnapshot));

  assert.equal(tree.codemap, true);
  assert.equal(tree.explicitGraphMap, true);
  assert.deepEqual(Array.from(tree.lanes, lane => lane.id), ['entrypoints', 'runtime', 'tests']);
  assert.deepEqual(
    Array.from(tree.nodes, node => [node.id, node.lane, node.gridColumn, node.path, node.artifact]),
    [
      ['skill', 'entrypoints', 1, 'skills/viewing-plans/SKILL.md', ''],
      ['generator', 'runtime', 2, 'scripts/generate-roadmap-view.py', ''],
      ['viewer', 'runtime', 2, 'tools/roadmap_viewer.html', ''],
      ['test', 'tests', 3, 'tests/roadmap-viewer.test.mjs', '']
    ]
  );
  assert.deepEqual(Array.from(tree.edges, edge => edge.verb), ['calls', 'affects', 'guards']);

  const caller = tree.edges.find(edge => edge.id === 'caller');
  assert.equal(caller.status, 'verified');
  assert.equal(caller.evidence[0].path, 'skills/viewing-plans/SKILL.md');
  assert.equal(caller.kind, 'predicate');

  const guard = tree.edges.find(edge => edge.id === 'guard');
  assert.equal(guard.status, 'unknown');
  assert.equal(guard.kind, 'unknown');
  assert.match(guard.reason, /not confirmed/);
  assert.ok(tree.propositions.some(item => item.includes('UNKNOWN')));
});

test('codemap adapter exposes callers impact and guarding tests from explicit edges only', () => {
  const tree = modelApi.buildCodemapViewModel(modelApi.normalizeSnapshot(codemapSnapshot));
  const viewer = tree.nodes.find(node => node.id === 'viewer');
  const incoming = tree.edges.filter(edge => edge.to === viewer.id);

  assert.deepEqual(Array.from(incoming, edge => edge.verb), ['affects', 'guards']);
  assert.equal(tree.edges.filter(edge => edge.verb === 'calls').length, 1);
  assert.equal(tree.edges.filter(edge => edge.verb === 'guards').length, 1);
  assert.equal(tree.edges.filter(edge => edge.status === 'unknown').length, 1);
  assert.equal(
    modelApi.codemapEvidenceLabel(tree.edges.find(edge => edge.id === 'guard')),
    'UNKNOWN — The precise DOM assertion is not confirmed.'
  );
  assert.equal(
    modelApi.codemapEvidenceLabel(tree.edges.find(edge => edge.id === 'caller')),
    'skills/viewing-plans/SKILL.md:20 — invokes generator'
  );
});

test('ordinary roadmap snapshots still route graph-map through the legacy adapter', () => {
  const roadmap = {
    title: 'Normal roadmap',
    generatedAt: '2026-08-05T12:00:00Z',
    files: {
      'graph-map.md': `\`\`\`mermaid\nflowchart LR\n  A["Fact"]\n  B["Decision"]\n  A -->|"supports"| B\n\`\`\``
    }
  };
  const tree = modelApi.buildTreeViewModel(modelApi.buildModel(roadmap));

  assert.equal(tree.explicitGraphMap, true);
  assert.equal(tree.codemap, undefined);
  assert.equal(tree.edges[0].predicate, 'supports');
});

test('roadmap snapshots preserve an embedded codemap workspace view', () => {
  const roadmap = modelApi.normalizeSnapshot({
    title: 'Unified workspace',
    files: { '00_spec.md': '# Spec' },
    codemapStatus: 'fresh',
    codemap: codemapSnapshot
  });
  assert.equal(roadmap.codemapStatus, 'fresh');
  assert.equal(roadmap.codemap.kind, 'codemap');
  assert.equal(roadmap.codemap.nodes.length, 4);
  assert.notEqual(modelApi.snapshotSignature(roadmap), modelApi.snapshotSignature({
    ...roadmap,
    codemapStatus: 'stale',
    codemap: null
  }));
});

test('codemap markup keeps semantic lanes, path copy, and mode restoration hooks', () => {
  assert.match(html, /class="codemap-lane-group"[^>]*role="group"/);
  assert.match(html, /id="copy-codemap-path"/);
  assert.match(html, /conceptMapOpenBeforeCodemap/);
  assert.match(html, /id="workspace-view-plan"/);
  assert.match(html, /id="workspace-view-code"/);
  assert.match(html, /id="codemap-gate"/);
  assert.match(html, /updateWorkspaceUrl/);
  assert.match(html, /searchParams\.set\('view', 'code'\)/);
  assert.match(html, /body\.codemap-mode \.explicit-node-layer \.node-meta[^}]*11px/);
});

test('codemap polish keeps metrics lanes states direction and evidence visually explicit', () => {
  assert.match(html, /class="codemap-metric/);
  assert.match(html, /class="codemap-lane-count"/);
  assert.match(html, /class="node-state status-unknown"/);
  assert.match(html, /class="relation-status status-/);
  assert.match(html, /id="graph-arrow-active"/);
  assert.match(html, /marker-end="url\(#graph-arrow-/);
  assert.match(html, /workspaceTitle} · Code Map/);
  assert.match(html, /body\.codemap-mode \.explicit-node-layer \.graph-node\[aria-current="true"\][^}]*var\(--accent\)/);
  assert.match(html, /body\.codemap-mode \.explicit-node-layer \.graph-node\[aria-current="true"\] \.node-glyph[^}]*var\(--accent\)/);
  assert.match(html, /id="codemap-mobile-context"/);
  assert.match(html, /class="mobile-context-evidence"/);
  assert.match(html, /\.mobile-context-title\s*\{[^}]*grid-column:\s*1/);
  assert.match(html, /markerWidth="9"/);
  assert.match(html, /--codemap-radius:\s*4px/);
});
