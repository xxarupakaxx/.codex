import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const playwrightModule = process.env.CODEX_PLAYWRIGHT_MODULE || '/Users/yoshiki/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright';
let chromium = null;
if (existsSync(playwrightModule)) {
  try { ({ chromium } = require(playwrightModule)); } catch { chromium = null; }
}
const chromiumExecutable = process.env.CODEX_PLAYWRIGHT_EXECUTABLE || '';
const launchChromium = () => chromium.launch({
  headless: true,
  args: ['--no-default-browser-check'],
  ...(chromiumExecutable ? { executablePath: chromiumExecutable } : {})
});

const html = readFileSync(new URL('../tools/roadmap_viewer.html', import.meta.url), 'utf8');
const viewingPlansSkill = readFileSync(new URL('../skills/viewing-plans/SKILL.md', import.meta.url), 'utf8');
const memoryFileFormats = readFileSync(new URL('../context/memory-file-formats.md', import.meta.url), 'utf8');
const sourceMatch = html.match(/\/\* ROADMAP_MODEL_START \*\/([\s\S]*?)\/\* ROADMAP_MODEL_END \*\//);

assert.ok(sourceMatch, 'roadmap_viewer.html must expose the exact browser model source between markers');

const context = vm.createContext({
  console,
  Date,
  Intl,
  JSON,
  Math,
  Map,
  Object,
  RegExp,
  Set,
  String,
  globalThis: {}
});
vm.runInContext(sourceMatch[1], context, { filename: 'roadmap-viewer-model.js' });
const model = context.globalThis.__ROADMAP_MODEL__;

assert.ok(model, 'model API must be exported for the browser and tests');

const plan = `# Roadmap Viewer UX

## Task 0：視覚方向を選ぶ

**変更対象:** design/option-3.png

- [x] 案3を選択

## Task 1.5: Markdown正規化

**blockedBy:** Task 0
**備考:** 表記揺れを同じ意味へまとめる

- [x] 見出しを読む
- [ ] 進捗表を読む

### タスク 2：計画キャンバスを実装

- [ ] 初期画面
- [ ] レスポンシブ

## リスクと懸念

| リスク | 影響度 | 対策 |
| --- | --- | --- |
| 古い更新を稼働中と誤認する | 高 | staleなら待ちにする |

## 比較表

| 候補 | 長所 | 短所 |
| --- | --- | --- |
| 案3 | 計画が見える | 情報量が多い |
`;

const progress = `# 進捗

- [x] Task 0 視覚方向を選ぶ
- [ ] タスク 1.5 Markdown正規化

| タスク | 状態 | 進捗 |
| --- | --- | --- |
| Task 1.5 | 進行中 | 1/2 |
| タスク 2 | 未着手 | 0/2 |
`;

const reviews = `# Review

Severity: CRITICAL 0
IMPORTANT：2件

| Severity | Count |
| --- | ---: |
| MINOR | 1 |
`;

const files = {
  '30_plan.md': plan,
  '40_progress.md': progress,
  '80_review.md': reviews,
  '05_log.md': '## Phase 2: 計画完了\n\n案3を選択した。'
};

const structuredPlanFixture = () => ({
  schemaVersion: 2,
  parserVersion: '2.0.0',
  sourceHash: 'plan-v2-fixture',
  tasks: [
    {
      number: '1',
      title: '構造化Task',
      purpose: '構造化された目的',
      targets: ['src/structured.js'],
      implementation: ['parserの結果を使う'],
      outputs: ['structured output'],
      verification: ['独立checker'],
      blockedBy: '',
      steps: [{ label: '構造化step', complete: false }],
      done: 0,
      total: 1,
      status: 'in-progress',
      body: 'このbodyは表示用の根拠',
      source: { file: '30_plan.md', lineStart: 2, lineEnd: 16 }
    },
    {
      number: '2',
      title: '依存Task',
      purpose: '依存関係を表示する',
      targets: ['src/dependent.js'],
      implementation: ['依存edgeを描画する'],
      outputs: ['dependent output'],
      verification: ['edgeを検証する'],
      blockedBy: '',
      steps: [],
      done: 0,
      total: 0,
      status: 'planned',
      body: '依存Taskのbody',
      source: { file: '30_plan.md', lineStart: 17, lineEnd: 28 }
    }
  ],
  edges: [{ id: 'edge-1', from: '1', to: '2', kind: 'blockedBy', relation: 'blockedBy' }],
  progress: { done: 0, total: 2, globalComplete: false, signals: {} },
  diagnostics: [],
  sources: { plan: '30_plan.md', progress: '40_progress.md' }
});

const generatedAt = '2026-07-12T02:59:30.000Z';
const nowMs = Date.parse('2026-07-12T03:00:00.000Z');
const graphMap = `# View Plan Graph

\`\`\`diagram-json
{
  "direction": "TB",
  "nodes": [
    {"id":"G","label":"判断を見落とさず決定"},
    {"id":"F1","label":"Slackの現状"},
    {"id":"F2","label":"GitHubの現状"},
    {"id":"D","label":"判断通知の設計","shape":"decision"},
    {"id":"R","label":"安全と失敗の境界","shape":"decision"},
    {"id":"A1","label":"通知ポリシー"},
    {"id":"A2","label":"Knowledgeノート"},
    {"id":"A3","label":"Daily導線"},
    {"id":"V","label":"pilotと独立レビュー"}
  ],
  "edges": [
    {"from":"G","to":"D","label":"必要とする"},
    {"from":"F1","to":"D","label":"判断材料にする"},
    {"from":"F2","to":"D","label":"判断材料にする"},
    {"from":"R","to":"D","label":"制約する"},
    {"from":"D","to":"A1","label":"記録する"},
    {"from":"A1","to":"A2","label":"反映する"},
    {"from":"A2","to":"A3","label":"導線を作る"},
    {"from":"V","to":"A1","label":"検証する"}
  ]
}
\`\`\`
`;

const executionBriefFiles = {
  '00_spec.md': `# Roadmap Viewer

## 目的

具体的な実行計画を第一画面で理解できるようにする。

## 背景・目的

選択中Taskから読むと、計画全体の意図を見失う。

## 必須要件

- [ ] Taskと仕様を同時に読める。
- [ ] 成果物へ直接移動できる。

## 制約事項

- snapshot schema version 1を維持する。

## 完了条件

- 初見の読者が目的と実装順序を説明できる。

## 現在の事実

- snapshotにはMarkdown本文が残っている。

## 採用判断

- 第一画面をbrief-firstにする。

## 未確定

- 古いtaskの見出し揺れ。
`,
  '20_survey.md': `# 調査

## 現在の事実

- explicit graphがTask列を空にする。
`,
  '30_plan.md': `# 実装計画

## 実装方針

\`buildExecutionBrief()\` を \`.codex/tools/roadmap_viewer.html\` に追加する。

## Task 1: contractを固定する

### 目的

第一画面の読解要件をtestにする。

### 変更対象

- \`.codex/tests/roadmap-viewer.test.mjs\`

### 成果物

- contract test

### 検証

\`node --test .codex/tests/roadmap-viewer.test.mjs\`

## Task 2: brief UIを実装する

### 目的

6項目を画面へ表示する。

### 変更対象

- \`.codex/tools/roadmap_viewer.html\`

## 未確定

- viewportごとの情報量。
`,
  '40_progress.md': `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 進行中 | 1/2 |
| Task 2 | 未着手 | 0/1 |

## 実測

- Node baselineは35件green。
`,
  'team-journal.md': `# Team Journal

## Decisions

- primary briefとgraph inspectorを分離する。

## Open Questions

- code anchorがないtaskの表示。
`,
  'graph-map.md': graphMap
};

const implementationPreviewFiles = {
  '30_plan.md': `# 実装プレビュー計画

## Task 1: source契約を固定する

### 目的

実コード抜粋の契約を先に固定する。

### 実装

- [x] optional fieldを正規化する。
- [x] live signatureへsourceを含める。

## Task 2: 選択Taskへ実コードを結び付ける

### 目的

計画と現在の実コードを同じdetailで読めるようにする。

### 実装

- [ ] Task indexから選択状態を決める。
- [ ] 選択Taskと同じtaskNumberのsourceだけを表示する。

## Task 3: 完了済みTask

### 実装

- [x] legacy fallbackを維持する。
`,
  '40_progress.md': `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 完了 | 2/2 |
| Task 2 | 進行中 | 0/2 |
| Task 3 | 完了 | 1/1 |
`
};

const implementationSourcePreviews = [
  {
    taskNumber: '1',
    path: '.codex/scripts/generate-roadmap-view.py',
    anchor: 'def build_snapshot',
    language: 'python',
    startLine: 178,
    endLine: 180,
    code: 'def build_snapshot(task_dir):\n    files = read_files(task_dir)\n    return {"files": files}',
    status: 'resolved',
    message: '',
    truncated: false
  },
  {
    taskNumber: '2',
    path: '.codex/tools/roadmap_viewer.html',
    anchor: 'function buildExecutionBrief',
    language: 'javascript',
    startLine: 3130,
    endLine: 3132,
    code: 'function buildExecutionBrief(model) {\n  const plan = model.snapshot.files["30_plan.md"];\n  return { plan };',
    status: 'resolved',
    message: '',
    truncated: false,
    evidenceRevision: 'source-revision-2'
  }
];

const implementationUiPreviews = [
  {
    taskNumber: '1',
    version: 1,
    screen: 'Detail drawer actions',
    title: 'Evidence action wording',
    layout: 'topnav',
    isNewScreen: false,
    status: 'verified',
    before: {
      status: 'verified',
      items: [
        { id: 'detail', label: 'Detailを開く', kind: 'button', state: 'primary', change: 'same' },
        { id: 'sources', label: 'Sources', kind: 'tab', state: 'secondary', change: 'modified' },
        { id: 'help', label: 'Help', kind: 'link', state: 'secondary', change: 'same' }
      ]
    },
    after: {
      status: 'planned',
      items: [
        { id: 'detail', label: 'Detailを開く', kind: 'button', state: 'primary', change: 'same' },
        { id: 'help', label: 'Help', kind: 'link', state: 'secondary', change: 'same' },
        { id: 'sources', label: 'Evidence', kind: 'tab', state: 'secondary', change: 'modified' },
        { id: 'diff', label: 'UI差分', kind: 'section', state: 'new', change: 'added' }
      ]
    },
    provenance: {
      evidenceRevision: 'abc1234',
      path: '.codex/tools/roadmap_viewer.html',
      anchor: 'data-detail-open="sources"',
      planSource: '30_plan.md#Task 1'
    },
    uncertainty: ['hover stateは実ブラウザ確認で確定する。'],
    ignoredHtml: '<script>alert(1)</script>'
  },
  {
    taskNumber: '2',
    version: 1,
    screen: 'UI Preview panel',
    title: '新規UI差分panel',
    layout: 'list',
    newScreen: true,
    status: 'planned',
    before: { status: 'source-unavailable', items: [] },
    after: [
      { id: 'summary', label: '要約', kind: 'region', state: 'visible', change: 'added' },
      { id: 'preview', label: 'Before / After', kind: 'region', state: 'planned', change: 'added' }
    ],
    evidenceRevision: 'def5678',
    provenance: {
      path: '.codex/tools/roadmap_viewer.html',
      anchor: 'function renderExecutionBrief(model)',
      planSource: '30_plan.md#Task 2'
    },
    uncertainty: ['generator統合後にbase ref statusを再確認する。']
  },
  {
    taskNumber: '3',
    version: 1,
    screen: 'Skipped preview',
    title: '別Task preview',
    layout: 'settings',
    before: [],
    after: [{ id: 'flag', label: 'Flag', kind: 'toggle', state: 'off', change: 'added' }]
  }
];

const generatorExactUiPreviews = [
  {
    taskNumber: '1',
    version: 1,
    screen: 'Detail drawer actions',
    title: 'Evidence action wording',
    layout: 'topnav',
    status: 'unverified',
    message: 'base refのanchor確認待ち',
    source: {
      path: '.codex/tools/roadmap_viewer.html',
      anchor: 'data-detail-open="sources"',
      status: 'anchor-missing',
      message: 'source anchor drift',
      evidenceRevision: 'feed1234'
    },
    provenance: {
      before: {
        source: 'repo:.codex/tools/roadmap_viewer.html#data-detail-open="sources"',
        baseRef: 'origin/main',
        observedLabels: ['Detailを開く', 'Sources']
      },
      after: {
        source: '30_plan.md#Task 1'
      }
    },
    before: {
      items: [
        { id: 'detail', label: 'Detailを開く', kind: 'button', state: 'primary', change: 'same' },
        { id: 'sources', label: 'Sources', kind: 'tab', state: 'secondary', change: 'modified' }
      ]
    },
    after: {
      items: [
        { id: 'detail', label: 'Detailを開く', kind: 'button', state: 'primary', change: 'same' },
        { id: 'sources', label: 'Evidence', kind: 'tab', state: 'secondary', change: 'modified' }
      ]
    },
    ignoredHtml: '<img src=x onerror=alert(1)>'
  },
  {
    taskNumber: '2',
    version: 1,
    screen: 'UI Preview panel',
    title: '新規UI差分panel',
    layout: 'list',
    status: 'planned',
    message: 'new screen has no before source',
    provenance: {
      before: { baseRef: 'origin/main', observedLabels: [] },
      after: { source: '30_plan.md#Task 2' }
    },
    before: { items: [] },
    after: {
      items: [
        { id: 'summary', label: '要約', kind: 'region', state: 'visible', change: 'added' },
        { id: 'preview', label: 'Before / After', kind: 'region', state: 'planned', change: 'added' }
      ]
    }
  }
];

function contrastRatio(foreground, background) {
  const channel = value => {
    const normalized = value / 255;
    return normalized <= 0.03928 ? normalized / 12.92 : ((normalized + 0.055) / 1.055) ** 2.4;
  };
  const luminance = hex => {
    const value = hex.replace('#', '');
    const rgb = [0, 2, 4].map(offset => Number.parseInt(value.slice(offset, offset + 2), 16));
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  };
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

test('groups tasks into running, waiting and recent completed sections', () => {
  const grouped = model.groupTaskSections([
    { id: '1', section: 'running' },
    { id: '2', section: 'waiting' },
    { id: '3', section: 'recent_completed' },
    { id: '4', section: 'unsupported' }
  ]);

  assert.deepEqual(Array.from(grouped.running, task => task.id), ['1']);
  assert.deepEqual(Array.from(grouped.waiting, task => task.id), ['2']);
  assert.deepEqual(Array.from(grouped.recent_completed, task => task.id), ['3']);
});

test('separates design and implementation plans and normalizes approval', () => {
  const result = model.extractPlanSections({
    files: {
      '00_spec.md': '# Design plan',
      '30_plan.md': '# Implementation plan'
    },
    metadata: { approvalState: 'approved' }
  });

  assert.equal(result.designPlan, '# Design plan');
  assert.equal(result.implementationPlan, '# Implementation plan');
  assert.equal(result.approval, 'approved');
});

test('does not treat candidate memory matches as confirmed plans', () => {
  const result = model.extractPlanSections({
    matchState: 'candidate',
    matchCandidates: [{ detail: { files: { '00_spec.md': '# Candidate design' } } }],
    detail: { files: { '30_plan.md': '# Confirmed implementation' } }
  });

  assert.equal(result.designPlan, '');
  assert.equal(result.implementationPlan, '# Confirmed implementation');
  assert.equal(result.approval, 'unknown');
});

test('clamps task hub settings and defaults invalid stored values', () => {
  assert.deepEqual(
    JSON.parse(JSON.stringify(model.taskHubSettings({ staleMinutes: 'oops', recentCompletedHours: 0, recentCompletedCollapsed: false }))),
    { staleMinutes: 15, recentCompletedHours: 24, recentCompletedCollapsed: false }
  );
  assert.equal(model.taskHubSettings({ staleMinutes: 9999, recentCompletedHours: 48 }).staleMinutes, 1440);
});

test('normalizes heading, colon, decimal task, Japanese checklist and progress table variants', () => {
  const normalized = model.normalizeSnapshot({
    version: 1,
    title: 'Roadmap Viewer UX',
    taskDir: '/tmp/task',
    generatedAt,
    files
  });
  const result = model.buildModel(normalized, { nowMs });

  assert.deepEqual(Array.from(result.tasks, task => task.number), ['0', '1.5', '2']);
  assert.equal(result.tasks[0].status, 'complete');
  assert.equal(result.tasks[1].status, 'in-progress');
  assert.equal(result.tasks[1].blockedBy, 'Task 0');
  assert.equal(result.tasks[1].done, 1);
  assert.equal(result.tasks[1].total, 2);
  assert.equal(result.tasks[2].status, 'planned');
  assert.equal(result.activeTask.number, '1.5');
  assert.deepEqual(Array.from(result.nextSteps, task => task.number), ['1.5', '2']);
});

test('structured plan is the task and progress source even when Markdown uses different headings', () => {
  const structured = structuredPlanFixture();
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': '# Legacy text\n\n## Task 99: MarkdownだけのTask\n\n- [x] これは使わない',
      '40_progress.md': '| Task | Status | Progress |\n| --- | --- | --- |\n| Task 99 | complete | 1/1 |'
    },
    plan: structured,
    timeline: []
  });
  const result = model.buildModel(normalized, { nowMs });

  assert.equal(result.taskSource, 'structured');
  assert.deepEqual(Array.from(result.tasks, task => task.number), ['1', '2']);
  assert.equal(result.tasks[0].title, '構造化Task');
  assert.deepEqual(JSON.parse(JSON.stringify(result.fixedProgress)), { done: 0, total: 2 });
  assert.equal(result.plan.valid, true);
  assert.equal(result.timelineSource, 'structured');
});

test('structured dependency edges drive the graph independently of blockedBy Markdown text', () => {
  const structured = structuredPlanFixture();
  structured.tasks[1].blockedBy = 'Task 99（Markdown由来なら無効）';
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: { '30_plan.md': '## Task 99: legacy dependency' },
    plan: structured
  }), { nowMs });
  const tree = model.buildTreeViewModel(result);

  assert.ok(tree.edges.some(edge => edge.from === 'task-1' && edge.to === 'task-2' && edge.kind === 'dependency'));
  assert.equal(tree.edges.some(edge => edge.to === 'task-2' && edge.from === 'task-99'), false);
  assert.deepEqual(result.plan.edges.map(edge => [edge.from, edge.to]), [['1', '2']]);
});

test('malformed structured plan is an explicit error and never falls back to Markdown Task parsing', () => {
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: { '30_plan.md': '## Task 99: legacy Task\n\n- [x] hidden fallback' },
    plan: { schemaVersion: 2, tasks: 'not-an-array', edges: [], progress: { done: 0, total: 0 } }
  });
  const result = model.buildModel(normalized, { nowMs });
  const tree = model.buildTreeViewModel(result);

  assert.equal(result.taskSource, 'structured');
  assert.deepEqual(Array.from(result.tasks), []);
  assert.equal(result.plan.valid, false);
  assert.match(result.planState.errors.join(' '), /tasks must be an array/);
  assert.equal(tree.planError, true);
  assert.match(tree.propositions.join(' '), /Plan error/);
  assert.doesNotMatch(tree.propositions.join(' '), /Task 99/);
});

test('structured timeline remains chronological and does not use legacy log headings', () => {
  const structured = structuredPlanFixture();
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': '## Task 99: legacy Task',
      '05_log.md': '## 2026-01-01 Legacy heading\n\nこれは表示しない'
    },
    plan: structured,
    timeline: [
      { id: 'event-2', title: '実装', phase: '2', time: '2026-08-30T02:00:00.000Z', tasks: ['2'], summary: '後のevent', source: '05_log.md' },
      { id: 'event-1', title: '調査', phase: '1', time: '2026-08-30T01:00:00.000Z', tasks: ['1'], summary: '先のevent', source: '05_log.md' }
    ]
  });
  const result = model.buildModel(normalized, { nowMs });

  assert.equal(result.timelineSource, 'structured');
  assert.deepEqual(Array.from(result.entries, event => event.id), ['event-2', 'event-1']);
  assert.deepEqual(Array.from(result.timeline, event => event.id), ['event-2', 'event-1']);
  assert.equal(result.entries.some(event => event.title.includes('Legacy heading')), false);
});

test('structured timeline preserves source provenance and exposes error status in the model', () => {
  const structured = structuredPlanFixture();
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: { '30_plan.md': '## Task 1: structured' },
    plan: structured,
    timeline: [
      {
        id: 'timeline-error-kind',
        title: 'source validation',
        kind: 'error',
        time: '2026-08-30T01:00:00.000Z',
        source: { file: '.codex/scripts/generate-roadmap-view.py', lineStart: 118, lineEnd: 124 },
        summary: 'source validation failed'
      },
      {
        id: 'timeline-error-status',
        title: 'independent check',
        kind: 'verification',
        status: 'failed',
        source: { file: '90_verification.md', lineStart: 7, lineEnd: 7 },
        summary: 'check failed'
      }
    ]
  });
  const result = model.buildModel(normalized, { nowMs });

  assert.deepEqual(
    JSON.parse(JSON.stringify(result.timeline.map(event => [event.id, event.source, event.status, event.error]))),
    [
      ['timeline-error-kind', { file: '.codex/scripts/generate-roadmap-view.py', lineStart: 118, lineEnd: 124 }, 'error', true],
      ['timeline-error-status', { file: '90_verification.md', lineStart: 7, lineEnd: 7 }, 'failed', true]
    ]
  );
  assert.match(html, /function renderVerification\(model\)/);
  assert.match(html, /id="timeline-list"/);
  assert.match(html, /明示された更新記録はありません/);
});

test('invalid structured timeline is explicit and never keeps a successful plan status', () => {
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: { '30_plan.md': '## Task 99: legacy Task' },
    plan: structuredPlanFixture(),
    timeline: { event: 'not-an-array' }
  });
  const result = model.buildModel(normalized, { nowMs });

  assert.equal(result.plan.valid, true);
  assert.equal(result.timelineState.valid, false);
  assert.match(result.timelineState.errors.join(' '), /snapshot\.timeline must be an array/);
  assert.match(html, /model\.timelineState/);
  assert.match(html, /Timeline error/);
  assert.match(html, /role="alert"/);
});

test('first screen exposes structured plan status and human-readable timeline', () => {
  for (const id of ['plan-contract-alert', 'verification', 'timeline-list']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /function renderOrientation\(model, brief\)/);
  assert.match(html, /function renderVerification\(model\)/);
  assert.match(html, /Plan contract error/);
  assert.match(html, /model\.plan && model\.plan\.valid/);
});

test('sourcePreviewsはsnapshot v1のoptional additive fieldとして正規化されるべき', () => {
  const normalized = model.normalizeSnapshot({
    version: 1,
    generatedAt,
    files: implementationPreviewFiles,
    sourcePreviews: [{
      ...implementationSourcePreviews[1],
      ignoredAbsolutePath: '/Users/example/private/source.js'
    }]
  });

  assert.equal(normalized.version, 1);
  assert.ok(Array.isArray(normalized.sourcePreviews), 'sourcePreviews must normalize to an array');
  assert.deepEqual(
    JSON.parse(JSON.stringify(normalized.sourcePreviews)),
    [implementationSourcePreviews[1]]
  );
  assert.equal(normalized.sourcePreviews[0].evidenceRevision, 'source-revision-2');
  const legacy = model.normalizeSnapshot({ version: 1, files: {} });
  assert.ok(Array.isArray(legacy.sourcePreviews), 'legacy snapshots must receive an empty sourcePreviews array');
  assert.deepEqual(
    JSON.parse(JSON.stringify(legacy.sourcePreviews)),
    []
  );
});

test('source previewの変更はsnapshot signatureを変えてlive更新対象になるべき', () => {
  const base = {
    version: 1,
    generatedAt,
    files: implementationPreviewFiles,
    sourcePreviews: implementationSourcePreviews
  };
  const changed = {
    ...base,
    sourcePreviews: implementationSourcePreviews.map(preview => preview.taskNumber === '2'
      ? { ...preview, code: `${preview.code}\n// changed at source` }
      : preview)
  };

  assert.notEqual(model.snapshotSignature(base), model.snapshotSignature(changed));
});

test('uiPreviewsはsnapshot v1のoptional additive fieldとして許可fieldだけ正規化されるべき', () => {
  const normalized = model.normalizeSnapshot({
    version: 1,
    generatedAt,
    files: implementationPreviewFiles,
    uiPreviews: [
      implementationUiPreviews[0],
      { ...implementationUiPreviews[1], unexpected: 'drop me' },
      { taskNumber: '2', version: 1, screen: 'Bad', title: 'Bad', layout: 'canvas', before: [], after: [] }
    ]
  });

  assert.equal(normalized.version, 1);
  assert.ok(Array.isArray(normalized.uiPreviews), 'uiPreviews must normalize to an array');
  assert.equal(normalized.uiPreviews.length, 2);
  assert.deepEqual(Object.keys(normalized.uiPreviews[0]).sort(), [
    'after',
    'before',
    'evidenceRevision',
    'isNewScreen',
    'layout',
    'provenance',
    'screen',
    'status',
    'taskNumber',
    'title',
    'uncertainty',
    'version'
  ]);
  assert.equal(normalized.uiPreviews[0].layout, 'topnav');
  assert.equal(normalized.uiPreviews[0].before.items[1].change, 'modified');
  assert.equal(normalized.uiPreviews[0].after.items.find(item => item.id === 'diff').change, 'added');
  assert.equal(normalized.uiPreviews[0].provenance.evidenceRevision, 'abc1234');
  assert.equal(normalized.uiPreviews[0].ignoredHtml, undefined);
  assert.doesNotMatch(JSON.stringify(normalized.uiPreviews), /drop me|ignoredHtml/);

  const legacy = model.normalizeSnapshot({ version: 1, files: {} });
  assert.deepEqual(JSON.parse(JSON.stringify(legacy.uiPreviews)), []);
});

test('generator exact-shapeのuiPreviewはsourceとprovenance.beforeからViewer modelへ適合すべき', () => {
  const normalized = model.normalizeSnapshot({
    version: 1,
    generatedAt,
    files: implementationPreviewFiles,
    uiPreviews: generatorExactUiPreviews
  });

  assert.equal(normalized.uiPreviews.length, 2);
  assert.equal(normalized.uiPreviews[0].provenance.path, '.codex/tools/roadmap_viewer.html');
  assert.equal(normalized.uiPreviews[0].provenance.anchor, 'data-detail-open="sources"');
  assert.equal(normalized.uiPreviews[0].provenance.evidenceRevision, 'feed1234');
  assert.equal(normalized.uiPreviews[0].provenance.baseRef, 'origin/main');
  assert.equal(normalized.uiPreviews[0].before.status, 'anchor-missing');
  assert.equal(normalized.uiPreviews[0].before.message, 'source anchor drift');
  assert.equal(normalized.uiPreviews[0].source, undefined);
  assert.equal(normalized.uiPreviews[0].provenance.before, undefined);
  assert.doesNotMatch(JSON.stringify(normalized.uiPreviews), /ignoredHtml|observedLabels|onerror/);

  assert.equal(normalized.uiPreviews[1].isNewScreen, true);
  assert.equal(normalized.uiPreviews[1].before.items.length, 0);
  assert.equal(normalized.uiPreviews[1].after.items.length, 2);

  const result = model.buildModel(normalized, { nowMs });
  const brief = model.buildExecutionBrief(result, '1');
  assert.equal(brief.selectedUiPreviews[0].provenance.path, '.codex/tools/roadmap_viewer.html');
  assert.equal(brief.selectedUiPreviews[0].before.status, 'anchor-missing');
  assert.equal(brief.selectedUiPreviews[0].before.message, 'source anchor drift');
  assert.equal(model.buildExecutionBrief(result, '2').selectedUiPreviews[0].isNewScreen, true);
});

test('source付きで未確認のBeforeは新規画面にせず、sourceなしの計画だけを新規画面とする', () => {
  const normalized = model.normalizeSnapshot({
    version: 1,
    files: { '30_plan.md': '# Plan\n' },
    uiPreviews: [{
      version: 1,
      taskNumber: '1',
      layout: 'list',
      title: 'source付きの未確認Before',
      status: 'unverified',
      isNewScreen: true,
      provenance: {
        before: { source: 'repo:src/old.js#render', baseRef: 'a'.repeat(40) },
        after: { source: '30_plan.md#Task 1' }
      },
      before: { items: [] },
      after: { items: [{ id: 'new', label: 'New', kind: 'section', state: 'planned', change: 'added' }] }
    }, {
      version: 1,
      taskNumber: '2',
      layout: 'list',
      title: '実際の新規画面',
      status: 'planned',
      isNewScreen: true,
      provenance: { before: {}, after: { source: '30_plan.md#Task 2' } },
      before: { items: [] },
      after: { items: [{ id: 'new', label: 'New', kind: 'section', state: 'planned', change: 'added' }] }
    }]
  });

  assert.equal(normalized.uiPreviews[0].isNewScreen, false);
  assert.equal(normalized.uiPreviews[1].isNewScreen, true);
});

test('uiPreviewの変更はsnapshot signatureを変えてlive更新対象になるべき', () => {
  const base = {
    version: 1,
    generatedAt,
    files: implementationPreviewFiles,
    uiPreviews: implementationUiPreviews
  };
  const changed = {
    ...base,
    uiPreviews: implementationUiPreviews.map(preview => preview.taskNumber === '2'
      ? { ...preview, title: '新規UI差分panel revised' }
      : preview)
  };

  assert.notEqual(model.snapshotSignature(base), model.snapshotSignature(changed));
});

test('Taskの実装sectionは選択Taskのこう実装する手順として抽出されるべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: implementationPreviewFiles,
    sourcePreviews: implementationSourcePreviews
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.deepEqual(
    Array.from(brief.selectedImplementation),
    ['Task indexから選択状態を決める。', '選択Taskと同じtaskNumberのsourceだけを表示する。']
  );
});

test('default選択はactive Taskを使い、実装説明とsource previewを同じTaskへ結び付けるべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: implementationPreviewFiles,
    sourcePreviews: implementationSourcePreviews
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.equal(brief.selectedTask.number, '2');
  assert.equal(brief.selectedSourcePreview.taskNumber, '2');
  assert.match(brief.selectedImplementation.join(' '), /同じtaskNumber/);
  assert.match(brief.selectedSourcePreview.code, /buildExecutionBrief/);

  const explicitlySelected = model.buildExecutionBrief(result, '1');
  assert.equal(explicitlySelected.selectedTask.number, '1');
  assert.equal(explicitlySelected.selectedSourcePreview.taskNumber, '1');
  assert.match(explicitlySelected.selectedImplementation.join(' '), /optional field/);
  assert.doesNotMatch(explicitlySelected.selectedSourcePreview.code, /buildExecutionBrief/);
});

test('active Taskがなければ最初の未完了Task、全完了なら最後の完了Taskをdefault選択すべき', () => {
  const firstIncomplete = model.buildModel(model.normalizeSnapshot({
    files: {
      '30_plan.md': `## Task 1: 完了

### 実装

- [x] 完了した。

## Task 2: 未完了

### 実装

- [ ] これから実装する。`
    }
  }), { nowMs });
  assert.equal(model.buildExecutionBrief(firstIncomplete).selectedTask.number, '2');

  const allComplete = model.buildModel(model.normalizeSnapshot({
    files: {
      '30_plan.md': `## Task 1: 一つ目

### 実装

- [x] 完了した。

## Task 2: 二つ目

### 実装

- [x] 完了した。`
    }
  }), { nowMs });
  const completeBrief = model.buildExecutionBrief(allComplete);
  assert.equal(completeBrief.currentTask, null, 'unknown freshness must not promote a recorded Task to Current');
  assert.equal(completeBrief.selectedTask.number, '2');
});

test('legacy snapshotはsource未記録を明示し、planからcodeを補作しないべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    files: {
      '30_plan.md': `## Task 1: legacy Task

### 実装

- [ ] \`function inventedAfterCode() {}\` を実装する。`
    }
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.equal(brief.selectedTask.number, '1');
  assert.equal(brief.selectedSourcePreview.status, 'source-unavailable');
  assert.equal(brief.selectedSourcePreview.code, '');
  assert.ok(brief.selectedSourcePreview.message);
  assert.doesNotMatch(JSON.stringify(brief.selectedSourcePreview), /inventedAfterCode/);
});

test('uiPreviewは選択Taskだけに結び付き、item IDで変更内容と順序変更を分けるべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: implementationPreviewFiles,
    sourcePreviews: implementationSourcePreviews,
    uiPreviews: implementationUiPreviews
  }), { nowMs });

  const first = model.buildExecutionBrief(result, '1');
  assert.equal(first.selectedTask.number, '1');
  assert.equal(first.selectedSourcePreview.taskNumber, '1');
  assert.equal(first.selectedUiPreviews.length, 1);
  assert.equal(first.selectedUiPreviews[0].taskNumber, '1');
  assert.deepEqual(
    JSON.parse(JSON.stringify(first.selectedUiPreviews[0].pairs.map(pair => [pair.id, pair.change, pair.orderChanged]))),
    [
      ['detail', 'same', false],
      ['sources', 'modified', true],
      ['help', 'same', true],
      ['diff', 'added', false]
    ]
  );

  const second = model.buildExecutionBrief(result, '2');
  assert.equal(second.selectedTask.number, '2');
  assert.equal(second.selectedUiPreviews.length, 1);
  assert.equal(second.selectedUiPreviews[0].isNewScreen, true);
  assert.equal(second.selectedUiPreviews[0].pairs.every(pair => pair.change === 'added'), true);

  const absent = model.buildExecutionBrief(result, '9');
  assert.equal(absent.selectedTask.number, '2');
  assert.equal(absent.selectedUiPreviews[0].taskNumber, '2');

  const noPreview = model.buildExecutionBrief(model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: implementationPreviewFiles,
    uiPreviews: implementationUiPreviews.filter(preview => preview.taskNumber === '3')
  }), { nowMs }), '2');
  assert.equal(noPreview.selectedTask.number, '2');
  assert.deepEqual(noPreview.selectedUiPreviews, []);
});

test('missing・secret・unavailable sourceは理由だけを返しcodeを保持しないべき', () => {
  for (const [status, message] of [
    ['anchor-missing', 'anchorが見つかりません'],
    ['secret-content', 'secret patternを検出しました'],
    ['source-unavailable', 'sourceを読み取れません']
  ]) {
    const result = model.buildModel(model.normalizeSnapshot({
      files: {
        '30_plan.md': `## Task 1: source状態を表示する

### 実装

- [ ] 理由を明示する。`
      },
      sourcePreviews: [{
        taskNumber: '1',
        path: '.codex/tools/roadmap_viewer.html',
        anchor: 'missing-anchor',
        language: 'html',
        startLine: 0,
        endLine: 0,
        code: '<script>never-render-this()</script>',
        status,
        message,
        truncated: false
      }]
    }), { nowMs });
    const preview = model.buildExecutionBrief(result).selectedSourcePreview;

    assert.equal(preview.status, status);
    assert.equal(preview.code, '', `${status} must not preserve source code`);
    assert.equal(preview.message, message);
  }
});

test('具体的な計画があるとき first-screen brief は現在と次のTaskを返すべき', () => {
  const normalized = model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  });
  const result = model.buildModel(normalized, { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.equal(brief.currentTask.number, '1');
  assert.equal(brief.nextTask.number, '2');
  assert.deepEqual(Array.from(brief.flow, task => task.number), ['1', '2']);
});

test('roadmap routeはTask順序と現在・次・選択中を別の状態として保持すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const brief = model.buildExecutionBrief(result, '2');
  const route = model.buildRoadmapRoute(brief);

  assert.deepEqual(
    Array.from(route.tasks, task => [task.number, task.status, task.isCurrent, task.isNext, task.isSelected]),
    [
      ['1', 'in-progress', true, false, false],
      ['2', 'planned', false, true, true]
    ]
  );
  assert.match(route.summary, /現在: Task 1/);
  assert.match(route.summary, /次: Task 2/);
  assert.match(route.summary, /選択中: Task 2/);
  assert.match(route.summary, /Task 1 進行中/);
  assert.match(route.summary, /Task 2 未着手/);
  assert.doesNotMatch(route.visibleSummary, /全体:/);
});

test('roadmap routeはblockedを未着手へ丸めず文字でも区別すべき', () => {
  const route = model.buildRoadmapRoute({
    currentTask: null,
    nextTask: null,
    selectedTask: { number: '1', title: '停止中' },
    flow: [{ number: '1', title: '停止中', status: 'blocked' }]
  });

  assert.match(route.summary, /Task 1 ブロック/);
  assert.match(html, /statusLabel\(task\.status\)/);
});

test('Task indexは一読UI内のスクロール位置へ直接移動できる', () => {
  assert.match(html, /id="plan-index-list"/);
  assert.match(html, /data-plan-jump/);
  assert.match(html, /href="#' \+ id/);
  assert.match(html, /target\.scrollIntoView/);
  assert.doesNotMatch(html, /function renderRoadmapRoute\(route\)/);
});

test('Taskに目的・変更対象・成果物・検証があるとき flowは実行契約を保持すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const task = model.buildExecutionBrief(result).flow[0];

  assert.match(task.purpose, /読解要件をtest/);
  assert.equal(task.target, '.codex/tests/roadmap-viewer.test.mjs');
  assert.deepEqual(Array.from(task.outputs), ['contract test']);
  assert.deepEqual(Array.from(task.verification), ['node --test .codex/tests/roadmap-viewer.test.mjs']);
});

test('目的・要件・制約が明示されているとき first-screen brief は目的と仕様を分離すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.match(brief.purpose.summary, /具体的な実行計画/);
  assert.match(brief.spec.summary, /要件:/);
  assert.match(brief.spec.summary, /制約:/);
  assert.notEqual(brief.purpose.summary, brief.spec.summary);
  assert.equal(brief.spec.source, '00_spec.md');
});

test('設計書summaryは要求・判断・境界・完了条件を明示sourceから構成すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const design = model.buildExecutionBrief(result).design;

  assert.match(design.goal.text, /具体的な実行計画/);
  assert.equal(design.goal.source, '00_spec.md');
  assert.match(design.context.text, /計画全体の意図/);
  assert.deepEqual(Array.from(design.requirements, item => item.text), [
    'Taskと仕様を同時に読める。',
    '成果物へ直接移動できる。'
  ]);
  assert.equal(design.requirements[0].section, '必須要件');
  assert.match(design.approach.text, /buildExecutionBrief/);
  assert.deepEqual(Array.from(design.decisions, item => item.text), [
    '第一画面をbrief-firstにする。'
  ]);
  assert.equal(design.decisions[0].section, '採用判断');
  assert.deepEqual(Array.from(design.boundaries, item => item.text), [
    'snapshot schema version 1を維持する。'
  ]);
  assert.deepEqual(Array.from(design.done, item => item.text), [
    '初見の読者が目的と実装順序を説明できる。'
  ]);
});

test('設計書summaryは欠落した設計情報をTask本文から補作しないべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': '## 目的\n\n小さな計画。',
      '30_plan.md': '## Task 1: 実装する\n\n### 実装\n\n- [ ] 推測してはいけない。'
    }
  }), { nowMs });
  const design = model.buildExecutionBrief(result).design;

  assert.equal(design.goal.text, '小さな計画。');
  assert.equal(design.context.text, '');
  assert.deepEqual(Array.from(design.requirements), []);
  assert.equal(design.approach.text, '');
  assert.deepEqual(Array.from(design.decisions), []);
  assert.deepEqual(Array.from(design.boundaries), []);
  assert.deepEqual(Array.from(design.done), []);
  assert.doesNotMatch(JSON.stringify(design), /推測してはいけない/);
});

test('実装方針が明示されているとき first-screen brief はcode anchorを返すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.match(brief.approach.summary, /buildExecutionBrief/);
  assert.deepEqual(
    Array.from(brief.approach.anchors, anchor => anchor.label),
    ['buildExecutionBrief()', '.codex/tools/roadmap_viewer.html']
  );
});

test('final implementation supersessionがあるとき first-screen brief は旧案ではなく最終案を返すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': `## 採用する最小モデル

Dashboard labelを起点にする旧案。

## 2026-07-30 Final implementation supersession

中央Development Mapで \`pending_pdm\` を抽出する最終案。
`
    }
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.match(brief.approach.summary, /中央Development Map/);
  assert.doesNotMatch(brief.approach.summary, /旧案/);
  assert.ok(brief.approach.anchors.some(anchor => anchor.label === 'pending_pdm'));
});

test('複数sourceに明示分類があるとき first-screen brief は事実・判断・未確定を分離すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.match(brief.claims.facts[0].text, /Node baseline/);
  assert.equal(brief.claims.facts[0].source, '40_progress.md');
  assert.match(brief.claims.decisions[0].text, /primary brief/);
  assert.equal(brief.claims.decisions[0].source, 'team-journal.md');
  assert.match(brief.claims.openItems[0].text, /code anchor/);
  assert.equal(brief.claims.openItems[0].source, 'team-journal.md');
});

test('実装根拠と分類sourceがないとき first-screen brief は推論せず空集合を返すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': '## 目的\n\n古い計画を読む。',
      '30_plan.md': '## Task 1: 記録だけのTask\n\n- [ ] 実行する'
    }
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.deepEqual(Array.from(brief.approach.anchors), []);
  assert.deepEqual(Array.from(brief.claims.facts), []);
  assert.deepEqual(Array.from(brief.claims.decisions), []);
  assert.deepEqual(Array.from(brief.claims.openItems), []);
});

test('first-screen brief は仕様・計画・進捗・reviewを優先成果物として返すべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: executionBriefFiles
  }), { nowMs });
  const brief = model.buildExecutionBrief(result);

  assert.deepEqual(
    Array.from(brief.artifacts, artifact => [artifact.path, artifact.exists]),
    [
      ['00_spec.md', true],
      ['30_plan.md', true],
      ['40_progress.md', true],
      ['80_review.md', false]
    ]
  );
});

test('normalizes review spelling variants and limits risks to risk sections', () => {
  const result = model.buildModel(model.normalizeSnapshot({ generatedAt, files }), { nowMs });

  assert.deepEqual(
    { critical: result.reviews.critical, important: result.reviews.important, minor: result.reviews.minor },
    { critical: 0, important: 2, minor: 1 }
  );
  assert.equal(result.reviews.hasReview, true);
  assert.deepEqual(Array.from(result.risks, risk => risk.title), ['古い更新を稼働中と誤認する']);
});

test('legacy, manual JSON and generated v1 snapshots share one semantic model', () => {
  const legacy = model.buildModel(model.normalizeSnapshot({ files, generated_at: generatedAt }), { nowMs });
  const manual = model.buildModel(model.normalizeSnapshot({ title: 'Manual', generatedAt, files }), { nowMs });
  const generated = model.buildModel(model.normalizeSnapshot({
    version: 1,
    title: 'Generated',
    taskDir: '/tmp/task',
    generatedAt,
    fingerprint: 'abc',
    files,
    artifacts: [
      { name: '30_plan.md', path: '30_plan.md', type: '.md', size: 2048, modifiedAt: generatedAt }
    ]
  }), { nowMs });

  const semantic = value => ({
    tasks: Array.from(value.tasks, task => [task.number, task.status, task.done, task.total]),
    reviews: [value.reviews.critical, value.reviews.important, value.reviews.minor],
    risks: Array.from(value.risks, risk => risk.title),
    phases: Array.from(value.phases, phase => [phase.number, phase.status])
  });

  assert.deepEqual(semantic(legacy), semantic(manual));
  assert.deepEqual(semantic(manual), semantic(generated));
  assert.equal(generated.artifacts[0].path, '30_plan.md');
  assert.ok(legacy.artifacts.some(artifact => artifact.path === '30_plan.md'));
  assert.ok(manual.artifacts.some(artifact => artifact.path === '40_progress.md'));
});

test('reads progress status only from the status cell and stops task bodies at the next peer section', () => {
  const scopedFiles = {
    '30_plan.md': `# Scoped parser

## Task 5: 完了報告を作る

- [ ] レポートを書く

## リスク

- [x] 受容済み
`,
    '40_progress.md': `| タスク | 状態 | 進捗 |
|---|---|---|
| Task 5 完了報告を作る | 未着手 | 0/1 |
`
  };
  const result = model.buildModel(model.normalizeSnapshot({ generatedAt, files: scopedFiles }), { nowMs });

  assert.equal(result.tasks[0].status, 'planned');
  assert.equal(result.tasks[0].done, 0);
  assert.equal(result.tasks[0].total, 1);
  assert.deepEqual(Array.from(result.tasks[0].steps, step => step.label), ['レポートを書く']);
});

test('scopes phase signals to status sources and keeps Phase 5 distinct from Phase 5.5', () => {
  const phaseFiles = {
    '30_plan.md': '# Plan\n\nPhase 5 完了という例示',
    '40_progress.md': '# 進捗\n\n- 現在地: Phase 3 実装中',
    '05_log.md': '## Phase 2: 計画完了\n\n- Phase 5完了という誤判定を修正する',
    '20_survey_external.md': 'Phase 0からPhase 5.5まで完了と書かれた外部比較'
  };
  const result = model.buildModel(model.normalizeSnapshot({ generatedAt, files: phaseFiles }), { nowMs });
  const states = Object.fromEntries(Array.from(result.phases, phase => [phase.number, phase.status]));

  assert.equal(states['3'], 'in-progress');
  assert.equal(states['5'], 'planned');
});

test('maps workflow subphases 2.5 and 5.5 onto the six-phase rail without losing the source number', () => {
  for (const [workflowNumber, displayNumber] of [['2.5', '2'], ['5.5', '5']]) {
    const result = model.buildModel(model.normalizeSnapshot({
      generatedAt,
      files: { '40_progress.md': `- 現在地: Phase ${workflowNumber} 進行中` }
    }), { nowMs });
    const active = result.phases.find(phase => phase.status === 'in-progress');

    assert.equal(active.number, displayNumber);
    assert.equal(active.workflowNumber, workflowNumber);
  }
});

test('does not turn review headings about completion criteria into phase completion', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '40_progress.md': '- 現在地: Phase 3 実装中',
      '80_review.md': '## Phase 5 完了条件のレビュー\n\nまだPhase 3です'
    }
  }), { nowMs });
  const states = Object.fromEntries(Array.from(result.phases, phase => [phase.number, phase.status]));

  assert.equal(states['3'], 'in-progress');
  assert.equal(states['5'], 'planned');
});

test('later completion events supersede historical phase start events', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '05_log.md': [
        '## Phase 0 準備開始',
        '## Phase 0 完了、Phase 1 調査開始',
        '## Phase 1 完了、Phase 2 計画開始',
        '## Phase 2 完了',
        '## Phase 3 実装開始',
        '## Phase 5 完了'
      ].join('\n\n')
    }
  }), { nowMs });

  assert.deepEqual(Array.from(result.phases, phase => phase.status), Array(6).fill('complete'));
});

test('stops parent task bodies before nested task headings', () => {
  const nested = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': '## Task 1: 親\n\n- [ ] 親作業\n\n### Task 1.1: 子\n\n- [x] 子作業'
    }
  }), { nowMs });

  assert.deepEqual(Array.from(nested.tasks, task => [task.number, task.done, task.total]), [['1', 0, 1], ['1.1', 1, 1]]);
});

test('treats an explicit global 100 percent progress signal as task completion', () => {
  const tasks = model.extractTasks({
    '30_plan.md': `## Task 1: 調査\n\n- [x] 事実を確認\n\n## Task 2: 設計\n\n- [ ] 契約を定義`,
    '40_progress.md': `## ステータス\n\n- 進捗: 100%`
  });

  assert.equal(tasks.map(task => task.status).join(','), 'complete,complete');
  assert.equal(tasks.map(task => task.done).join(','), '1,1');
});

test('stale snapshots stop presenting recorded work as actively running', () => {
  const staleNow = Date.parse('2026-07-12T04:00:00.000Z');
  const result = model.buildModel(model.normalizeSnapshot({ generatedAt, files }), { nowMs: staleNow });

  assert.equal(result.freshness.state, 'stale');
  assert.equal(result.activeTask, null);
  assert.equal(result.recordedActiveTask.number, '1.5');
  assert.match(result.waiting.reason, /更新/);
});

test('unknown snapshot freshness does not claim recorded work is active', () => {
  const result = model.buildModel(model.normalizeSnapshot({ files }), { nowMs });

  assert.equal(result.freshness.state, 'unknown');
  assert.equal(result.activeTask, null);
  assert.equal(result.recordedActiveTask.number, '1.5');
});

test('stale and unknown freshness keep the recorded Task secondary in the execution brief', () => {
  const stale = model.buildModel(model.normalizeSnapshot({ generatedAt, files }), { nowMs: Date.parse('2026-07-12T04:00:00.000Z') });
  const staleBrief = model.buildExecutionBrief(stale);
  assert.equal(staleBrief.currentTask, null);
  assert.equal(staleBrief.nextTask, null);
  assert.equal(staleBrief.recordedTask.number, '1.5');
  assert.match(staleBrief.waitingReason, /古い/);
  assert.equal(model.buildRoadmapRoute(staleBrief).tasks.some(task => task.isCurrent), false);

  const unknown = model.buildModel(model.normalizeSnapshot({ files }), { nowMs });
  const unknownBrief = model.buildExecutionBrief(unknown);
  assert.equal(unknownBrief.currentTask, null);
  assert.equal(unknownBrief.nextTask, null);
  assert.equal(unknownBrief.recordedTask.number, '1.5');
  assert.match(unknownBrief.waitingReason, /不明/);
  assert.equal(model.buildRoadmapRoute(unknownBrief).tasks.some(task => task.isCurrent), false);
  assert.match(html, /記録上・|stale・更新待ち|現在地未記録/);
});

test('artifact completion labels require phase evidence instead of file existence', () => {
  const planned = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': '# Plan',
      '20_survey_external.md': '# Survey'
    }
  }), { nowMs });
  const completed = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': '# Plan',
      '20_survey_external.md': '# Survey',
      '05_log.md': '## Phase 1: 調査完了\n\n## Phase 2: 計画完了'
    }
  }), { nowMs });
  const planArtifact = { path: '30_plan.md' };
  const surveyArtifact = { path: '20_survey_external.md' };

  assert.equal(model.artifactStateFor(planArtifact, planned), '計画');
  assert.equal(model.artifactStateFor(surveyArtifact, planned), '調査記録');
  assert.equal(model.artifactStateFor(planArtifact, completed), '計画確定');
  assert.equal(model.artifactStateFor(surveyArtifact, completed), '調査済み');
});

test('parses a complete explicit Outcome Trace from Team Journal first', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': '- [ ] fallback should not win',
      'team-journal.md': `# Team Journal

## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-1 Ship trace-first viewer | 00_spec.md R1 | Task 3-4 | AC-05 | node tests and browser evidence | matched |
`
    }
  }), { nowMs });

  assert.equal(result.traceSummary.hasExplicitTrace, true);
  assert.equal(result.traceSummary.total, 1);
  assert.equal(result.traceSummary.matched, 1);
  assert.equal(result.outcomes[0].outcome, 'O-1 Ship trace-first viewer');
  assert.equal(result.outcomes[0].state, 'matched');
});

test('parses human review, objections and revision events without weakening the trace', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | Human Review | Objection | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| O-1 Clear first screen | R1 | Task 5 | AC-05 | browser test | explain the next check in one minute | details may be hidden | matched |

## Revision Log

| ID | Observed | Plan change | Revalidate | Status |
| --- | --- | --- | --- | --- |
| REV-01 | Formal names were missing | add user-invoked entries | AC-03 | planned |
`
    }
  }), { nowMs });

  assert.equal(result.outcomes[0].humanReview, 'explain the next check in one minute');
  assert.equal(result.outcomes[0].objection, 'details may be hidden');
  assert.equal(result.revisions.length, 1);
  assert.equal(result.revisions[0].id, 'REV-01');
  assert.equal(result.revisions[0].revalidate, 'AC-03');
});

test('distinguishes every Outcome Trace missing state without weakening task parsing', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-1 |  | Task 1 | AC-01 | tests | missing-spec |
| O-2 | R2 |  | AC-02 | tests | missing-implementation |
| O-3 | R3 | Task 3 |  | tests | missing-acceptance |
| O-4 | R4 | Task 4 | AC-04 |  | missing-evidence |
`
    }
  }), { nowMs });

  assert.deepEqual(Array.from(result.outcomes, outcome => outcome.state), [
    'missing-spec',
    'missing-implementation',
    'missing-acceptance',
    'missing-evidence'
  ]);
  assert.equal(result.traceSummary.missingSpec, 1);
  assert.equal(result.traceSummary.missingImplementation, 1);
  assert.equal(result.traceSummary.missingAcceptance, 1);
  assert.equal(result.traceSummary.missingEvidence, 1);
});

test('marks holistic failure as the next decision before ordinary missing evidence', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-1 holistic | R1 | Task 5 | AC-10 | browser fixture | failed-holistic |
| O-2 missing evidence | R2 | Task 4 | AC-06 | pending | missing-evidence |
`,
      '90_verification.md': 'Holistic Check: FAIL'
    }
  }), { nowMs });

  assert.equal(result.traceSummary.failedHolistic, 1);
  assert.equal(result.traceSummary.missingTotal, 2);
  assert.equal(result.nextDecision.state, 'failed-holistic');
  assert.match(result.nextDecision.label, /holistic/);
});

test('uses the final review verdict instead of historical revision rounds', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-1 shipped | R1 | Task 1 | AC-01 | tests | matched |
`,
      '80_review.md': `# Review

最終判定：APPROVE。CRITICAL 0、IMPORTANT 0、MINOR 0。

| Round | 判定 |
| --- | --- |
| 1 | NEEDS-REVISION |
| 2 | APPROVE |

## 修正済みIMPORTANT

1. historical findingを修正した。
`
    }
  }), { nowMs });

  assert.equal(result.traceSummary.failedHolistic, 0);
  assert.equal(result.traceSummary.matched, 1);
  assert.equal(result.outcomes[0].state, 'matched');
  assert.equal(result.reviews.important, 0);
});

test('falls back safely when Outcome Trace is absent', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': `## 必須要件

- [ ] 第一画面で未接続outcomeを判別できる
- [ ] 実ブラウザで主要表示を確認する
`,
      'checkpoint.md': `| ID | 基準 |
| --- | --- |
| AC-05 | 第一画面で判別できる |
| AC-06 | traceを区別する |
`
    }
  }), { nowMs });

  assert.equal(result.traceSummary.hasExplicitTrace, false);
  assert.equal(result.outcomes.length, 2);
  assert.equal(result.outcomes[0].state, 'missing-implementation');
  assert.ok(result.artifactWarnings.some(warning => warning.kind === 'missing-trace'));
  assert.ok(result.artifactWarnings.some(warning => warning.file === '30_plan.md'));
});

test('groups a notification design into discovery design and guardrail outcomes without dropping items', () => {
  const requirements = [
    'Slackチャンネルの現在の用途と、担当者への到達方法を読み取りで確認する。',
    'GitHub Issue、Project、Actionsの現行通知を読み取りで確認する。',
    '通知するイベントと通知しないイベントを分ける。',
    'GitHub IssueとSlackの責務を分ける。',
    '通知本文の最小契約を定義する。',
    'メンション、重複防止、再通知、解決時の扱いを定義する。',
    'Slack障害がCIを壊さない失敗分離を定義する。',
    '機密情報、未検証テキスト、prompt injectionの境界を定義する。',
    '少数Issueで試せるpilotを定義する。',
    '既存Knowledgeノートへ事実と提案を分けて追記する。'
  ];
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': `## 必須要件\n\n${requirements.map(item => `- [ ] ${item}`).join('\n')}`,
      '30_plan.md': '# 実装計画',
      'checkpoint.md': '# Sprint Contract'
    }
  }), { nowMs });
  const tree = model.buildTreeViewModel(result);
  const outcomes = tree.nodes.filter(node => node.kind === 'outcome');

  assert.equal(outcomes.length, requirements.length);
  assert.equal(outcomes.filter(node => node.cluster === 'discovery').length, 2);
  assert.equal(outcomes.filter(node => node.cluster === 'guardrail').length, 2);
  assert.ok(outcomes.some(node => node.displayTitle === '通知の境界'));
  assert.ok(outcomes.some(node => node.displayTitle === '安全な入力境界'));
});

test('builds an outcome task artifact tree with dependency edges and no stale active branch', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      ...files,
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-1 Reduce cognitive load | R1 | Task 1.5 | AC-01 | 90_verification.md | missing-evidence |
`
    }
  }), { nowMs });
  const tree = model.buildTreeViewModel(result);

  assert.ok(tree.nodes.some(node => node.kind === 'outcome' && node.title.includes('Reduce cognitive load')));
  assert.ok(tree.nodes.some(node => node.kind === 'outcome' && node.cluster === 'design'));
  assert.ok(tree.nodes.some(node => node.kind === 'outcome' && node.displayTitle));
  assert.ok(tree.nodes.some(node => node.kind === 'task' && node.taskNumber === '1.5'));
  assert.ok(tree.nodes.some(node => node.kind === 'evidence' && node.title === '90_verification.md'));
  assert.ok(tree.edges.some(edge => edge.from.includes('trace') && edge.to === 'task-1.5' && edge.kind === 'implementation' && edge.verb === 'implemented by'));
  assert.ok(tree.edges.some(edge => edge.from === 'task-0' && edge.to === 'task-1.5' && edge.kind === 'task-flow' && edge.verb === 'then'));
  assert.ok(tree.edges.some(edge => edge.from === 'task-0' && edge.to === 'task-1.5' && edge.kind === 'dependency' && edge.verb === 'waits for'));
  assert.ok(tree.edges.some(edge => edge.from === 'task-1.5' && edge.to.startsWith('artifact-') && edge.kind === 'evidence' && edge.verb === 'proves'));
  assert.equal(tree.activeNodeId, 'task-1.5');

  const stale = model.buildModel(model.normalizeSnapshot({ generatedAt, files }), { nowMs: Date.parse('2026-07-12T04:00:00.000Z') });
  const staleTree = model.buildTreeViewModel(stale);
  assert.notEqual(staleTree.activeNodeId, 'task-1.5');
  assert.equal(staleTree.edges.some(edge => edge.active), false);
});

test('orders graph ranks by explicit relations instead of raw file order', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '00_spec.md': '# Goal',
      '30_plan.md': `## Task 2: Second\n\n**変更対象:** review-security.md\n\n## Task 1: First\n\n**変更対象:** github-automation.md`,
      'team-journal.md': `## Outcome Trace

| Outcome | Requirement | Implementation | Acceptance | Evidence | State |
| --- | --- | --- | --- | --- | --- |
| O-2 安全を守る | R2 | Task 2 | AC-02 | review-security.md | matched |
| O-1 現状を知る | R1 | Task 1 | AC-01 | github-automation.md | matched |
`,
      'github-automation.md': '# Research',
      'review-security.md': '# Review'
    }
  }), { nowMs });
  const tree = model.buildTreeViewModel(result);

  assert.deepEqual(
    Array.from(tree.columns.outcome.filter(node => node.kind === 'outcome'), node => node.cluster),
    ['discovery', 'guardrail']
  );
  assert.deepEqual(Array.from(tree.columns.task, node => node.taskNumber), ['1', '2']);
  assert.deepEqual(
    Array.from(tree.columns.artifact, node => node.title).slice(0, 2),
    ['github-automation.md', 'review-security.md']
  );
});

test('parses graph-map diagram JSON into explicit SVG node-link contract', () => {
  const parsed = model.parseSvgDiagramSpec(graphMap);

  assert.equal(parsed.explicitGraphMap, true);
  assert.equal(parsed.nodes.length, 9);
  assert.equal(parsed.edges.length, 8);
  assert.deepEqual(
    Array.from(parsed.nodes, node => [node.id, node.kind, node.title]),
    [
      ['G', 'goal', '判断を見落とさず決定'],
      ['F1', 'fact', 'Slackの現状'],
      ['F2', 'fact', 'GitHubの現状'],
      ['D', 'decision', '判断通知の設計'],
      ['R', 'risk', '安全と失敗の境界'],
      ['A1', 'artifact', '通知ポリシー'],
      ['A2', 'artifact', 'Knowledgeノート'],
      ['A3', 'artifact', 'Daily導線'],
      ['V', 'verification', 'pilotと独立レビュー']
    ]
  );
  for (const edge of parsed.edges) {
    assert.ok(edge.from);
    assert.ok(edge.to);
    assert.ok(edge.predicate);
  }
  assert.ok(parsed.edges.some(edge => edge.from === 'G' && edge.to === 'D' && edge.predicate === '必要とする'));
  assert.ok(parsed.edges.some(edge => edge.from === 'D' && edge.to === 'A1' && edge.predicate === '記録する'));
  assert.ok(parsed.edges.some(edge => edge.from === 'V' && edge.to === 'A1' && edge.predicate === '検証する'));
});

test('concept map nodeに実artifact provenanceがないとき artifact導線を付けるべきではない', () => {
  const parsed = model.parseSvgDiagramSpec(graphMap);

  assert.ok(parsed.nodes.every(node => node.artifact === ''));
});

test('graph-map snapshot takes over the first-screen tree while fallback remains available', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: { ...files, 'graph-map.md': graphMap }
  }), { nowMs });
  const tree = model.buildTreeViewModel(result);

  assert.equal(tree.explicitGraphMap, true);
  assert.equal(tree.nodes.length, 9);
  assert.equal(tree.edges.length, 8);
  assert.equal(tree.columns.task.length, 0);
  assert.equal(tree.columns.artifact.length, 0);
  assert.ok(tree.propositions.includes('判断を見落とさず決定 必要とする 判断通知の設計'));

  const path = new Set(['G']);
  for (let changed = true; changed;) {
    changed = false;
    for (const edge of tree.edges) {
      if (path.has(edge.from) && !path.has(edge.to)) {
        path.add(edge.to);
        changed = true;
      }
    }
  }
  assert.ok(path.has('A1'));
  assert.ok(path.has('A2'));
  assert.ok(path.has('A3'));

  const fallback = model.buildTreeViewModel(model.buildModel(model.normalizeSnapshot({ generatedAt, files }), { nowMs }));
  assert.notEqual(fallback.explicitGraphMap, true);
  assert.ok(fallback.columns.task.length > 0);
});

test('renders workflow markdown safely without an external parser', () => {
  const rendered = model.renderWorkflowMarkdown(`# 見出し

- [x] **完了**した作業
- [ ] 未完了の作業

| 項目 | 状態 |
| --- | --- |
| Parser | ready |

> 補足

\`inline\` and [OpenAI](https://openai.com)

\`\`\`html
<script>alert('xss')</script>
\`\`\`

<img src=x onerror=alert(1)>
[危険](javascript:alert(1))`);

  assert.match(rendered, /<h4 class="md-heading-1" data-md-heading="見出し" tabindex="-1">見出し<\/h4>/);
  assert.match(rendered, /type="checkbox" disabled checked/);
  assert.match(rendered, /<table>/);
  assert.match(rendered, /<blockquote>補足<\/blockquote>/);
  assert.match(rendered, /href="https:\/\/openai\.com"/);
  assert.match(rendered, /&lt;script&gt;alert\(&#039;xss&#039;\)&lt;\/script&gt;/);
  assert.match(rendered, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(rendered, /href="javascript:/);
  assert.doesNotMatch(rendered, /<img src=x/);
});

test('main plan本文だけはsourceの見出し階層をそのまま保ち、既定のdrawer offsetも維持する', () => {
  const mainDocument = model.renderWorkflowMarkdown('# Root\n\n## Section\n\n### Detail', 0);
  assert.match(mainDocument, /<h1 class="md-heading-1"/);
  assert.match(mainDocument, /<h2 class="md-heading-2"/);
  assert.match(mainDocument, /<h3 class="md-heading-3"/);

  const legacyDocument = model.renderWorkflowMarkdown('# Root');
  assert.match(legacyDocument, /<h4 class="md-heading-1"/);
});

test('keeps malformed markdown table input visible as escaped source text', () => {
  const rendered = model.renderWorkflowMarkdown('| A | B |\n| -- | broken |\n<script>x</script>');

  assert.match(rendered, /\| A \| B \|/);
  assert.match(rendered, /&lt;script&gt;x&lt;\/script&gt;/);
  assert.doesNotMatch(rendered, /<table>/);
});

test('計画書は正本本文を一度だけ描画しTaskへ補足を差し込む', () => {
  const template = html.slice(0, html.indexOf('<script id="embedded-snapshot"'));
  for (const id of ['main-content', 'plan-document', 'plan-source-document', 'plan-source-content', 'dependencies', 'verification', 'sources']) {
    assert.match(template, new RegExp("id=[\\\"']" + id + "[\\\"']"), id + ' is required');
  }
  assert.ok(template.indexOf('id="plan-source-document"') < template.indexOf('id="dependencies"'));
  assert.ok(template.indexOf('id="dependencies"') < template.indexOf('id="verification"'));
  assert.ok(template.indexOf('id="verification"') < template.indexOf('id="sources"'));
  assert.doesNotMatch(template, /id=["']before-after["']/);
  assert.doesNotMatch(template, /id=["']task-plan["']/);
  assert.doesNotMatch(template, /id=["']task-list["']/);
  assert.doesNotMatch(template, /<details\b/i);
  assert.doesNotMatch(template, /detail-drawer|data-detail-tab|role=["']tab["']/);
  assert.doesNotMatch(template, /id=["']plan-source-document-title["']/);
  assert.equal((template.match(/id=["']plan-source-content["']/g) || []).length, 1, 'plan body has one container');
  assert.match(html, /function renderPlanSource\(model\)/);
  assert.match(html, /host\.innerHTML = renderMarkdown\(displaySource, 0\)/);
  assert.match(html, /findTaskHeading\(headings, task\)/);
  assert.match(html, /renderTask\(record\.task, model\)/);
});

test('30_plan.mdの導入・背景・任意sectionを保持し投影用JSONブロックを重複表示しない', () => {
  assert.match(html, /function stripProjectedBlocks\(markdown\)/);
  assert.match(html, /label === 'ui-preview-json' \|\| label === 'diagram-json'/);
  assert.match(html, /function stripPlanMetadata\(markdown\)/);
  assert.match(html, /const metadata = stripPlanMetadata\(stripProjectedBlocks\(content\)\)/);
  assert.match(html, /const displaySource = stripFirstMarkdownH1\(metadata\.markdown\)/);
  assert.match(html, /const entries = \[\]/);
  assert.match(html, /required_sources\|write\[ _\]scope\|acceptance\|UI変更/);
  assert.match(html, /metadataEntries/);
  assert.match(html, /plan-source-content/);
  assert.match(html, /Plan source: /);
  assert.match(html, /計画本文から実コードを補作しません/);
  assert.match(html, /function firstMarkdownH1\(markdown\)/);
  assert.match(html, /function stripFirstMarkdownH1\(markdown\)/);
  assert.match(html, /function renderWorkflowMarkdown\(markdown, headingOffset = 3\)/);
  assert.match(html, /const offset = Number\.isFinite\(Number\(headingOffset\)\)/);
});

test('Task本文へBefore/After・source・diagram根拠を添え、本文項目を再出力しない', () => {
  const renderSource = html.match(/function renderTask\(task, model\) \{([\s\S]*?)\n    \}\n    function dependencyEdges/)?.[1] || '';
  assert.match(renderSource, /model\.snapshot\.uiPreviews\.filter/);
  assert.match(renderSource, /renderBeforeAfter/);
  assert.match(renderSource, /renderPlanDiagram/);
  assert.match(renderSource, /task\.source/);
  assert.match(renderSource, /sourcePreview/);
  assert.doesNotMatch(renderSource, /task\.purpose/);
  assert.doesNotMatch(renderSource, /task\.implementation/);
  assert.doesNotMatch(renderSource, /task\.targets/);
  assert.doesNotMatch(renderSource, /task\.outputs/);
  assert.doesNotMatch(renderSource, /task\.verification/);
  assert.match(html, /class="task-appendix"/);
  assert.match(html, /class="task-change"/);
  assert.match(html, /class="task-source"/);
  assert.match(html, /class="task-diagram"/);
  assert.match(html, /現在の実コード/);
  assert.match(html, /参照版の実装/);
  assert.match(renderSource, /sourcePreviews\.map/);
  assert.match(html, /Plan source anchor未記録/);
});

test('Before/Afterは各Taskの補足として640px以上2列、375px縦組みを保つ', () => {
  assert.match(html, /function renderBeforeAfter\(preview\)/);
  assert.match(html, /data-side="before"/);
  assert.match(html, /data-side="after"/);
  assert.match(html, /確認済みの観測/);
  assert.match(html, /計画上の案/);
  assert.match(html, /@media \(min-width: 640px\)[\s\S]*\.task-change\s*>\s*\.compare-grid/);
  assert.match(html, /@media \(max-width: 639px\)[\s\S]*\.compare-panel/);
  assert.match(html, /preview\.isNewScreen/);
  assert.match(html, /beforeIsUnverified/);
  assert.match(html, /hasExistingBefore/);
  for (const change of ['same', 'added', 'modified', 'removed']) {
    assert.match(html, new RegExp('change-' + change));
  }
});

test('依存とfresh Codemapは本文内SVG・evidence・unknown理由を持つ', () => {
  assert.match(html, /function dependencyEdges\(model\)/);
  assert.match(html, /function renderDependencyMap\(model\)/);
  assert.match(html, /id="task-dependency-svg"/);
  assert.match(html, /id="task-dependency-relations"/);
  assert.match(html, /marker-end="url\(#' \+ arrowId/);
  assert.match(html, /function renderCodemap\(model\)/);
  assert.match(html, /ROADMAP_MODEL\.buildCodemapViewModel\(codemap\)/);
  assert.match(html, /ROADMAP_MODEL\.codemapEvidenceLabel\(edge\)/);
  assert.match(html, /status !== 'fresh' \|\| !codemap/);
  assert.match(html, /arrowId = mobile \? 'codemap-arrow-narrow' : 'codemap-arrow'/);
  assert.match(html, /titleId = mobile \? 'dependency-svg-title-narrow' : 'dependency-svg-title'/);
  assert.match(html, /titleId = mobile \? 'codemap-svg-title-narrow' : 'codemap-svg-title'/);
  assert.match(html, /descId = mobile \? 'codemap-svg-desc-narrow' : 'codemap-svg-desc'/);
  assert.match(html, /verifiedはpath:line、unknownは理由/);
  assert.doesNotMatch(html, /detail-tab-impact/);
});

test('検証・レビュー・時系列は本文の末尾側に常時表示し欠落を未記録とする', () => {
  assert.match(html, /function renderVerification\(model\)/);
  for (const name of ['90_verification.md', '80_review.md', 'checkpoint.md']) {
    assert.match(html, new RegExp(name.replace('.', '\\.')));
  }
  assert.match(html, /この成果物は未記録です/);
  assert.match(html, /model\.timelineState/);
  assert.match(html, /Timeline error/);
  assert.match(html, /id="timeline-list"/);
});

test('Plan v2・legacy・source hash・invalid output境界をモデルと表示で維持する', () => {
  assert.match(html, /ROADMAP_MODEL\.normalizeSnapshot/);
  assert.match(html, /ROADMAP_MODEL\.snapshotSignature/);
  assert.match(html, /ROADMAP_MODEL\.buildModel/);
  assert.match(html, /model\.planState/);
  assert.match(html, /model\.plan \? 'v' \+ model\.plan\.schemaVersion/);
  assert.match(html, /plan\.sourceHash/);
  assert.match(html, /30_plan\.md · legacy source/);
  assert.match(html, /if \(model\.plan && model\.plan\.valid\)/);
  assert.match(html, /if \(!model\.plan\)/);
  assert.match(html, /return \[\];/);
});

test('user content・source・Markdownはescape/sanitizeを経由しCSPを維持する', () => {
  const template = html.slice(0, html.indexOf('<script id="embedded-snapshot"'));
  assert.match(template, /meta http-equiv="Content-Security-Policy"/);
  assert.match(template, /default-src 'none'/);
  assert.match(template, /script-src 'unsafe-inline'/);
  assert.match(template, /style-src 'unsafe-inline'/);
  assert.match(template, /img-src data:/);
  assert.match(template, /connect-src 'self'/);
  assert.match(html, /function escapeHtml\(value\)/);
  assert.match(html, /renderMarkdown\(value\)/);
  assert.match(html, /escapeHtml\(task\.title/);
  assert.match(html, /escapeHtml\(preview\.code\)/);
  assert.match(html, /ROADMAP_MODEL\.highlightSourceCode/);
  assert.doesNotMatch(html, /innerHTML\s*=\s*preview\.code/);
  assert.doesNotMatch(html, /innerHTML\s*=\s*task\.body/);
  assert.doesNotMatch(template, /<script[^>]+src=/i);
  assert.doesNotMatch(template, /\son[a-z]+\s*=/i);
});

test('Hubは明示されたsession modeだけで起動し通常表示にpopupや別serverを増やさない', () => {
  const template = html.slice(0, html.indexOf('<script id="embedded-snapshot"'));
  for (const id of ['task-hub', 'provider-status', 'task-sections', 'task-detail', 'hub-stale-minutes', 'hub-recent-hours']) {
    assert.match(template, new RegExp("id=[\\\"']" + id + "[\\\"']"));
  }
  assert.match(template, /<section class="hub-view"[^>]*hidden>/);
  assert.match(html, /function hubSessionKey\(\)/);
  assert.match(html, /if \(hubSessionKey\(\)\)/);
  assert.match(html, /function initializeTaskHub\(\)/);
  assert.match(html, /X-Roadmap-Session/);
  assert.match(html, /setInterval\(refresh, 2000\)/);
  assert.match(html, /setInterval\(heartbeat, 5000\)/);
  assert.doesNotMatch(template, /window\.open\(/);
  assert.doesNotMatch(template, /target=["']_blank["']/i);
  assert.match(template, /EXPLICIT MODE/);
});

test('selection・focus・scroll・live updateは一読UIのDOMへつながる', () => {
  assert.match(html, /function captureViewState\(\)/);
  assert.match(html, /function sourceIdPart\(value\)/);
  assert.match(html, /function sourcePreviewId\(task, preview\)/);
  assert.match(html, /data-source-task/);
  assert.match(html, /state\.key\) \|\| findViewTarget\(state\.fallback\)/);
  assert.match(html, /function restoreViewState\(state\)/);
  assert.match(html, /window\.scrollTo\(\{ top: state\.scrollTop/);
  assert.match(html, /target\.scrollIntoView\(\{ block: 'start', behavior: 'auto' \}\)/);
  assert.match(html, /data-plan-jump/);
  assert.match(html, /history\.replaceState/);
  assert.match(html, /function startLivePolling\(\)/);
  assert.match(html, /fetch\('roadmap-snapshot\.json\?ts=' \+ Date\.now\(\)/);
  assert.match(html, /generation !== pollGeneration/);
  assert.match(html, /lastSnapshotSignature/);
  assert.match(html, /function refreshFreshness\(\)[\s\S]*?captureViewState\(\)[\s\S]*?restoreViewState\(view\)/);
  assert.match(html, /renderPlanSource\(model\)/);
});

test('SVG・keyboard・responsive・forced colorsの安全な表示契約を持つ', () => {
  assert.match(html, /<a class="skip-link" id="skip-link" href="#main-content">/);
  assert.match(html, /\.skip-link:focus\s*\{[^}]*transform:\s*translateY\(0\)/);
  assert.match(html, /--quiet:\s*#5f6d64/);
  assert.ok(contrastRatio('#5f6d64', '#f4f6f2') >= 4.5);
  assert.ok(contrastRatio('#9aa99f', '#151b17') >= 4.5);
  assert.match(html, /<svg class="relationship-svg"/);
  assert.match(html, /role="img"/);
  assert.match(html, /<title/);
  assert.match(html, /<desc/);
  assert.match(html, /html[\s\S]*overflow-x: clip/);
  assert.match(html, /body[\s\S]*overflow-x: clip/);
  assert.match(html, /button:focus-visible, a:focus-visible/);
  assert.match(html, /@media \(forced-colors: active\)/);
  assert.match(html, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(html, /white-space: nowrap/);
  assert.doesNotMatch(html, /transition:\s*all/);
});

test('UI previewは5 layoutを同じ縦一覧へ潰さずprimitiveとstable IDを描画へ渡す', () => {
  assert.match(html, /data-layout="' \+ escapeHtml\(preview\.layout\) \+ '"/);
  assert.match(html, /data-item-id="' \+ escapeHtml\(pair\.id\) \+ '"/);
  assert.match(html, /data-kind="' \+ escapeHtml\(kind\) \+ '"/);
  assert.match(html, /class="change-primitive"/);
  for (const layout of ['topnav', 'sidebar', 'settings', 'list', 'form']) {
    assert.match(html, new RegExp('\\.compare-panel\\[data-layout="' + layout + '"\\]'));
  }
  assert.match(html, /data-layout="topnav"\][\s\S]*\.change-list\s*\{[\s\S]*display:\s*flex/);
  assert.match(html, /data-layout="sidebar"\][\s\S]*\.change-list\s*\{[\s\S]*border-left:/);
  assert.match(html, /data-layout="settings"\][\s\S]*data-kind="input"\][\s\S]*\.change-primitive/);
  assert.match(html, /data-layout="form"\][\s\S]*data-kind="input"\][\s\S]*\.change-primitive/);
});

test('browser: 5 layoutのUI模型はviewportごとに構造差を保つ', { skip: !chromium }, async () => {
  const browser = await launchChromium();
  try {
    const layouts = ['topnav', 'sidebar', 'settings', 'list', 'form'];
    const files = { '30_plan.md': '# UI模型\n\n' + layouts.map((layout, index) => `## Task ${index + 1}: ${layout}`).join('\n\n') };
    const uiPreviews = layouts.map((layout, index) => ({
      version: 1,
      taskNumber: String(index + 1),
      layout,
      title: layout,
      provenance: { before: { source: `repo:src/${layout}.tsx#root`, baseRef: 'a'.repeat(40) }, after: { source: `Task ${index + 1}` } },
      before: { items: [{ id: `${layout}-main`, label: 'Main', kind: layout === 'form' || layout === 'settings' ? 'input' : 'item', change: 'same' }] },
      after: { items: [
        { id: `${layout}-main`, label: 'Main', kind: layout === 'form' || layout === 'settings' ? 'input' : 'item', change: 'same' },
        { id: `${layout}-next`, label: 'Next', kind: layout === 'form' ? 'action' : 'item', change: 'added' }
      ] }
    }));
    for (const width of [375, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
      await page.evaluate(snapshot => window.__ROADMAP_VIEWER__.render(snapshot), { version: 1, title: 'UI模型', generatedAt: new Date().toISOString(), files, uiPreviews });
      await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
      await page.keyboard.press('Tab');
      const result = await page.evaluate(() => ({
        overflow: document.body.scrollWidth > window.innerWidth,
        focus: document.activeElement?.id || '',
        layouts: [...document.querySelectorAll('.compare-panel[data-side="after"]')].map(panel => {
          const list = panel.querySelector('.change-list');
          const primitive = panel.querySelector('.change-primitive');
          return {
            layout: panel.dataset.layout,
            display: getComputedStyle(list).display,
            leftBorder: parseFloat(getComputedStyle(list).borderLeftWidth),
            topBorder: parseFloat(getComputedStyle(list).borderTopWidth),
            primitive: primitive ? getComputedStyle(primitive).display : 'none'
          };
        })
      }));
      assert.deepEqual(errors, []);
      assert.equal(result.overflow, false, `${width}px must not overflow`);
      assert.equal(result.focus, 'skip-link');
      assert.deepEqual(result.layouts.map(item => item.layout), layouts);
      assert.equal(result.layouts[0].display, 'flex');
      assert.ok(result.layouts[1].leftBorder > 0);
      assert.equal(result.layouts[2].primitive, 'block');
      assert.ok(result.layouts[3].topBorder > 0);
      assert.equal(result.layouts[4].primitive, 'block');
      await page.close();
    }
    const zoomPage = await browser.newPage({ viewport: { width: 768, height: 900 } });
    await zoomPage.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    await zoomPage.evaluate(snapshot => window.__ROADMAP_VIEWER__.render(snapshot), { version: 1, title: 'UI模型', generatedAt: new Date().toISOString(), files, uiPreviews });
    const session = await zoomPage.context().newCDPSession(zoomPage);
    await session.send('Emulation.setPageScaleFactor', { pageScaleFactor: 2 });
    const zoomResult = await zoomPage.evaluate(() => ({
      scale: window.visualViewport?.scale || 1,
      overflow: document.body.scrollWidth > document.documentElement.clientWidth
    }));
    assert.equal(zoomResult.scale, 2);
    assert.equal(zoomResult.overflow, false, '200% zoom must not overflow');
    await zoomPage.close();
  } finally {
    await browser.close();
  }
});

test('browser: Task本文一度・任意section保持・比較layout・scroll復元', { skip: !chromium }, async () => {
  const browser = await launchChromium();
  try {
  const page = await browser.newPage({ viewport: { width: 768, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
  await page.keyboard.press('Tab');
  const firstFocus = await page.evaluate(() => ({ id: document.activeElement?.id || '', href: document.activeElement?.getAttribute('href') || '', outline: getComputedStyle(document.activeElement).outlineStyle }));
  assert.deepEqual(firstFocus, { id: 'skip-link', href: '#main-content', outline: 'solid' });
  const snapshot = {
    version: 1,
    title: '一読計画',
    generatedAt: new Date().toISOString(),
    files: {
      '30_plan.md': `# 人向けの計画書

required_sources: task:30_plan.md, workspace:tools/example.js

\`\`\`yaml
required_sources: example configuration
\`\`\`

導入の文章 ONCE

## Task 1: 本文のTask

### 目的
目的の文章 ONCE

### 実装
- 実装の文章 ONCE

### 変更対象
- src/example.js

#### 実装根拠
- repo:src/example.js#build

### 成果物
- 成果物の文章 ONCE

### 検証
- 検証の文章 ONCE

## 任意section

任意sectionの文章 ONCE
`
    },
    sourcePreviews: [{
      taskNumber: '1',
      path: 'src/example.js',
      anchor: 'function build',
      language: 'javascript',
      startLine: 1,
      endLine: 1,
      code: 'const actual = 1;',
      status: 'resolved',
      message: '',
      truncated: false,
      evidenceRevision: 'fixed-ref-revision'
    }],
    uiPreviews: [{
      version: 1,
      taskNumber: '1',
      layout: 'list',
      title: 'UI',
      provenance: { before: { source: 'repo:src/example.js#build', baseRef: 'a'.repeat(40), observedLabels: ['old'] }, after: { source: '30_plan.md#Task 1' } },
      before: { items: [{ id: 'old', label: 'Old', kind: 'item', change: 'same' }] },
      after: { items: [{ id: 'new', label: 'New', kind: 'item', change: 'added' }] }
    }]
  };
  await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
  const browserView = await page.evaluate(() => {
    const host = document.querySelector('#plan-source-content');
    const textContent = host.textContent;
    const panels = [...host.querySelectorAll('.task-appendix .compare-panel')].map(item => item.getBoundingClientRect());
    const taskHeading = document.querySelector('#task-1');
    const counts = value => (textContent.match(new RegExp(value, 'g')) || []).length;
    return {
      bodyScrollWidth: document.body.scrollWidth,
      innerWidth: window.innerWidth,
      taskId: taskHeading?.id || '',
      appendixCount: host.querySelectorAll('.task-appendix').length,
      counts: {
        task: counts('Task 1: 本文のTask'),
        purpose: counts('目的の文章 ONCE'),
        implementation: counts('実装の文章 ONCE'),
        optional: counts('任意sectionの文章 ONCE'),
        code: counts('const actual = 1;')
      },
      title: document.querySelector('#task-title')?.textContent || '',
      sourceH1Count: host.querySelectorAll('h1').length,
      taskHeadingTag: taskHeading?.tagName || '',
      purposeHeadingTag: host.querySelector('[data-md-heading="目的"]')?.tagName || '',
      rawRequiredSources: textContent.includes('required_sources: task:30_plan.md'),
      codeRequiredSources: textContent.includes('required_sources: example configuration'),
      sourceCodeLabels: [...host.querySelectorAll('.source-code')].map(node => node.getAttribute('aria-label') || ''),
      sourceLedger: document.querySelector('#source-ledger')?.textContent || '',
      panels: panels.map(rect => ({ left: rect.left, top: rect.top, width: rect.width }))
    };
  });
  assert.deepEqual(errors, []);
  assert.equal(browserView.bodyScrollWidth, 768);
  assert.equal(browserView.taskId, 'task-1');
  assert.equal(browserView.appendixCount, 1);
  assert.deepEqual(browserView.counts, { task: 1, purpose: 1, implementation: 1, optional: 1, code: 1 });
  assert.equal(browserView.title, '人向けの計画書');
  assert.equal(browserView.sourceH1Count, 0);
  assert.equal(browserView.taskHeadingTag, 'H2');
  assert.equal(browserView.purposeHeadingTag, 'H3');
  assert.equal(browserView.rawRequiredSources, false);
  assert.equal(browserView.codeRequiredSources, true);
  assert.deepEqual(browserView.sourceCodeLabels, ['参照版の実装 fixed-ref-revision']);
  assert.match(browserView.sourceLedger, /required_sources/);
  assert.match(browserView.sourceLedger, /workspace:tools\/example\.js/);
  assert.equal(browserView.panels.length, 2);
  assert.ok(Math.abs(browserView.panels[0].top - browserView.panels[1].top) < 1);
  const sourceExcerpt = page.locator('.source-code').first();
  const sourceExcerptId = await sourceExcerpt.getAttribute('id');
  assert.match(sourceExcerptId || '', /^source-excerpt-/);
  await sourceExcerpt.focus();
  const focusedBefore = await page.evaluate(() => ({ id: document.activeElement?.id || '', scrollY }));
  const reordered = {
    ...snapshot,
    sourcePreviews: [
      {
        taskNumber: '1', path: 'src/other.js', anchor: 'other', language: 'javascript',
        startLine: 1, endLine: 1, code: 'const other = 1;', status: 'resolved', message: '', truncated: false
      },
      snapshot.sourcePreviews[0]
    ]
  };
  await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), reordered);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const focusedAfter = await page.evaluate(() => ({ id: document.activeElement?.id || '', scrollY }));
  assert.equal(focusedAfter.id, focusedBefore.id);
  assert.equal(focusedAfter.scrollY, focusedBefore.scrollY);
  await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), { ...snapshot, sourcePreviews: [] });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.evaluate(() => document.activeElement?.id || ''), 'task-1');
  await page.setViewportSize({ width: 375, height: 812 });
  const mobilePanels = await page.evaluate(() => [...document.querySelectorAll('.task-appendix .compare-panel')].map(item => ({ left: item.getBoundingClientRect().left, top: item.getBoundingClientRect().top })));
  assert.ok(mobilePanels[1].top > mobilePanels[0].top);
  await page.locator('#plan-index-list a[data-plan-jump="1"]').click();
  const jumped = await page.evaluate(() => ({ focus: document.activeElement?.id || '', scrollY }));
  assert.equal(jumped.focus, 'task-1');
  await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
  await page.waitForTimeout(40);
  const restored = await page.evaluate(() => ({ focus: document.activeElement?.id || '', scrollY }));
  assert.equal(restored.focus, 'task-1');
  assert.equal(restored.scrollY, jumped.scrollY);
  } finally {
    await browser.close();
  }
});

test('browser: 375px Codemapは縦配置で図の横panを要求しない', { skip: !chromium }, async () => {
  const browser = await launchChromium();
  try {
    const page = await browser.newPage({ viewport: { width: 375, height: 812 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = {
      version: 1,
      kind: 'roadmap',
      title: 'Code Map narrow',
      generatedAt: new Date().toISOString(),
      files: { '30_plan.md': '# Plan\n' },
      codemapStatus: 'fresh',
      codemap: {
        kind: 'codemap',
        lanes: [
          { id: 'input', title: 'Input', order: 0 },
          { id: 'view', title: 'View', order: 1 },
          { id: 'test', title: 'Test', order: 2 }
        ],
        nodes: Array.from({ length: 7 }, (_, index) => ({
          id: 'node-' + index,
          title: 'Node ' + index,
          kind: 'module',
          lane: index < 2 ? 'input' : index < 5 ? 'view' : 'test',
          path: 'src/node-' + index + '.js'
        })),
        edges: Array.from({ length: 6 }, (_, index) => ({
          id: 'edge-' + index,
          from: 'node-' + index,
          to: 'node-' + (index + 1),
          relation: 'calls',
          status: index === 4 ? 'unknown' : 'verified',
          reason: index === 4 ? 'relation is not confirmed' : '',
          evidence: index === 4 ? [] : [{ path: 'src/node-' + index + '.js', line: index + 1 }]
        }))
      }
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const view = await page.evaluate(() => {
      const host = document.querySelector('#codemap-svg');
      const narrow = host.querySelector('.codemap-narrow');
      const wide = host.querySelector('.codemap-wide');
      const text = narrow.querySelector('text');
      return {
        bodyScrollWidth: document.body.scrollWidth,
        hostScrollWidth: host.scrollWidth,
        hostClientWidth: host.clientWidth,
        narrowDisplay: getComputedStyle(narrow).display,
        wideDisplay: getComputedStyle(wide).display,
        textSize: getComputedStyle(text).fontSize,
        relationCount: document.querySelectorAll('#codemap-relations li').length,
        unknownText: document.querySelector('#codemap-relations').textContent
      };
    });
    assert.equal(view.bodyScrollWidth, 375);
    assert.equal(view.hostScrollWidth, view.hostClientWidth);
    assert.equal(view.narrowDisplay, 'block');
    assert.equal(view.wideDisplay, 'none');
    assert.equal(view.textSize, '12px');
    assert.equal(view.relationCount, 6);
    assert.match(view.unknownText, /UNKNOWN/);
  } finally {
    await browser.close();
  }
});

test('browser: source付き空Beforeは未確認として表示し新規画面扱いにしない', { skip: !chromium }, async () => {
  const browser = await launchChromium();
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 812 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = {
      version: 1,
      title: '未確認Before fixture',
      generatedAt: new Date().toISOString(),
      files: {
        '30_plan.md': `# 未確認Before fixture

## Task 1: source付きUI

### 目的
既存sourceのBeforeを確認する。
`
      },
      uiPreviews: [{
        version: 1,
        taskNumber: '1',
        layout: 'list',
        title: 'source付きの未確認Before',
        status: 'unverified',
        isNewScreen: true,
        provenance: {
          before: { source: 'repo:src/old.js#render', baseRef: 'a'.repeat(40) },
          after: { source: '30_plan.md#Task 1' }
        },
        before: { items: [] },
        after: { items: [{ id: 'new', label: 'New section', kind: 'section', state: 'planned', change: 'added' }] }
      }]
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const before = await page.locator('.compare-panel[data-side="before"]').innerText();
    assert.match(before, /Before未確認/);
    assert.doesNotMatch(before, /新規画面/);
    assert.match(before, /old\.js#render/);
  } finally {
    await browser.close();
  }
});

test('browser: 末尾Taskの補足は本文の目的・実装の後ろへ置く', { skip: !chromium }, async () => {
  const browser = await launchChromium();
  try {
    const page = await browser.newPage({ viewport: { width: 768, height: 812 } });
    await page.goto(new URL('../tools/roadmap_viewer.html', import.meta.url).href);
    const snapshot = {
      version: 1,
      title: '末尾Task fixture',
      generatedAt: new Date().toISOString(),
      files: {
        '30_plan.md': `# 末尾Task fixture

## Task 1: 最後のTask

### 目的
末尾Taskの目的本文。

### 実装
末尾Taskの実装本文。
`
      },
      sourcePreviews: [{
        taskNumber: '1', path: 'src/last.js', anchor: 'build', language: 'javascript',
        startLine: 1, endLine: 1, code: 'const last = true;', status: 'resolved', message: '', truncated: false
      }]
    };
    await page.evaluate(value => window.__ROADMAP_VIEWER__.render(value), snapshot);
    const order = await page.evaluate(() => {
      const host = document.querySelector('#plan-source-content');
      const children = [...host.children];
      return {
        purpose: children.findIndex(node => node.textContent.includes('末尾Taskの目的本文')),
        implementation: children.findIndex(node => node.textContent.includes('末尾Taskの実装本文')),
        appendix: children.findIndex(node => node.classList.contains('task-appendix')),
        tags: children.map(node => node.tagName)
      };
    });
    assert.ok(order.purpose >= 0);
    assert.ok(order.implementation > order.purpose);
    assert.ok(order.appendix > order.implementation, JSON.stringify(order));
    assert.equal(await page.locator('#task-1').evaluate(node => node.tagName), 'H2');
  } finally {
    await browser.close();
  }
});
