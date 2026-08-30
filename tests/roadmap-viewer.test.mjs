import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

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
    truncated: false
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
    status: 'unverified',
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
  assert.match(html, /function timelineSourceLabel\(source\)/);
  assert.match(html, /出典: \$\{escapeHtml\(sourceLabel\)\}/);
  assert.match(html, /plan-timeline-event\$\{eventStatus\?\.className === 'error' \? ' error' : ''\}/);
  assert.match(html, /aria-live="polite" aria-atomic="false"/);
  assert.match(html, /計画timelineを読み込めません/);
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
  assert.match(html, /if \(planErrors\.length \|\| timelineErrors\.length\)/);
  assert.match(html, /構造化timelineエラー（legacy fallbackなし）/);
  assert.match(html, /role="alert"/);
});

test('first screen exposes structured plan status and human-readable timeline', () => {
  for (const id of ['plan-contract-status', 'plan-timeline', 'plan-timeline-meta', 'plan-timeline-list']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /function renderPlanTimeline\(model\)/);
  assert.match(html, /構造化Planエラー（legacy fallbackなし）/);
  assert.match(html, /snapshot\.timelineに時系列が未記録です/);
  assert.match(html, /model\.plan\.edges\.forEach/);
  assert.match(html, /if \(model\.plan && !model\.plan\.valid\)/);
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
  assert.match(html, /statusLabel\(currentTask\.status\)/);
});

test('first-screen roadmap routeは4stage Project Mapとして読めるべき', () => {
  for (const id of ['brief-route', 'brief-route-map', 'brief-route-summary']) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /function renderRoadmapRoute\(route\)/);
  assert.match(html, /PROJECT MAP/);
  assert.match(html, /企画から検証まで/);
  assert.match(html, /class="project-map-grid"/);
  assert.match(html, /role="list" aria-label="企画、設計、実装、検証のProject Map"/);
});

test('Project Map mobile layoutは128px内で4stageを横overflowなしに保つべき', () => {
  assert.match(html, /\.brief-route\s*\{[^}]*max-height:\s*180px[^}]*overflow:\s*auto/s);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.brief-route\s*\{[^}]*max-height:\s*128px/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.brief-route-head h3\s*\{[^}]*white-space:\s*nowrap/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.brief-route-map\s*\{[^}]*overflow-x:\s*hidden/);
  assert.match(html, /\.project-map-grid\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/);
});

test('Project Map nodeは代表識別とcurrent stateを短く表示すべき', () => {
  const renderSource = html.match(/function renderRoadmapRoute\(route\) \{([\s\S]*?)\n    \}\n    function centerRoadmapRoute/)?.[1] || '';
  assert.match(renderSource, /currentTask = route\.tasks\.find\(task => task\.isCurrent\)/);
  assert.match(renderSource, /stage: '企画'/);
  assert.match(renderSource, /stage: '設計'/);
  assert.match(renderSource, /stage: '実装'/);
  assert.match(renderSource, /stage: '検証'/);
  assert.match(renderSource, /現在・\$\{statusLabel\(currentTask\.status\)\}/);
  assert.match(renderSource, /project-map-glyph/);
  assert.match(renderSource, /project-map-state/);
});

test('Project Map compact化は旧SVG routeの横スクロールへ戻さないべき', () => {
  const renderSource = html.match(/function renderRoadmapRoute\(route\) \{([\s\S]*?)\n    \}\n    function centerRoadmapRoute/)?.[1] || '';
  assert.doesNotMatch(renderSource, /brief-route-svg/);
  assert.doesNotMatch(renderSource, /style="min-width:\$\{width\}px"/);
  assert.doesNotMatch(renderSource, /requestAnimationFrame\(centerRoadmapRoute\)/);
  assert.match(html, /\.project-map-node\.current/);
  assert.match(html, /\.project-map-node\.missing/);
});

test('Project Map desktop layoutは180px上限で既存brief順序を保つべき', () => {
  assert.match(html, /\.brief-route\s*\{[^}]*max-height:\s*180px[^}]*overflow:\s*auto/s);
  assert.ok(html.indexOf('id="brief-route"') < html.indexOf('id="brief-design-summary"'));
  assert.ok(html.indexOf('id="brief-route"') < html.indexOf('id="brief-flow"'));
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
  assert.match(html, /現在未確認/);
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

test('keeps malformed markdown table input visible as escaped source text', () => {
  const rendered = model.renderWorkflowMarkdown('| A | B |\n| -- | broken |\n<script>x</script>');

  assert.match(rendered, /\| A \| B \|/);
  assert.match(rendered, /&lt;script&gt;x&lt;\/script&gt;/);
  assert.doesNotMatch(rendered, /<table>/);
});

test('task hub shell exposes list detail status settings and responsive behavior', () => {
  for (const id of ['task-hub', 'provider-status', 'task-sections', 'task-detail', 'hub-stale-minutes', 'hub-recent-hours']) {
    assert.match(html, new RegExp(`id=["']${id}["']`));
  }
  assert.match(html, /@media \(max-width: 1023px\)/);
  assert.match(html, /setInterval\(refresh, 2000\)/);
  assert.match(html, /setInterval\(heartbeat, 5000\)/);
  assert.match(html, /response\.status === 409/);
  assert.match(html, /renderWorkflowMarkdown\(markdown\)/);
  for (const label of ['Live状況', '現在やっていること', '直近完了', '実行中command / tool', 'agent一覧', 'event timeline', 'blocker']) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /activeSubagentCount/);
  assert.match(html, /runningTools/);
  assert.match(html, /elapsedSeconds/);
  assert.match(html, /body\.task-hub-active\s*\{[^}]*overflow:\s*hidden/);
  assert.match(html, /\.task-sidebar\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(html, /\.task-detail\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(html, /overscroll-behavior:\s*contain/);
});

test('single-task HTMLは具体的な実行briefをConcept Mapより先に配置すべき', () => {
  const ids = [
    'execution-brief',
    'current-focus',
    'current-primary-action',
    'brief-design-summary',
    'brief-spec',
    'brief-approach',
    'brief-boundary',
    'brief-quick-links',
    'detail-drawer',
    'detail-tab-document',
    'detail-tab-change',
    'detail-tab-impact',
    'detail-tab-test',
    'detail-tab-sources',
    'concept-map-disclosure'
  ];
  for (const id of ids) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.doesNotMatch(html, /id=["']brief-summary["']/);
  assert.doesNotMatch(html, /id=["']source-line["']/);
  assert.doesNotMatch(html, /id=["']workspace-view-plan["']/);
  assert.doesNotMatch(html, /id=["']workspace-view-code["']/);
  assert.doesNotMatch(html.match(/<header class="app-header"[\s\S]*?<\/header>/)?.[0] || '', /codemap-gate/);
  assert.match(html, /id="detail-panel-impact"[\s\S]*id="codemap-gate"/);
  assert.ok(html.indexOf('id="brief-route"') < html.indexOf('id="brief-design-summary"'));
  assert.ok(html.indexOf('id="brief-route"') < html.indexOf('id="current-focus"'));
  assert.ok(html.indexOf('id="current-focus"') < html.indexOf('id="brief-design-summary"'));
  assert.ok(html.indexOf('id="execution-brief"') < html.indexOf('id="concept-map-disclosure"'));
});

test('execution briefは初期renderとfreshness更新の両方で再描画すべき', () => {
  assert.match(html, /function renderExecutionBrief\(model\)/);
  assert.match(html, /function render\(snapshotInput,[\s\S]*?renderExecutionBrief\(currentModel\)/);
  assert.match(html, /function refreshFreshness\(\)[\s\S]*?renderExecutionBrief\(next\)/);
  assert.match(html, /concept-map-disclosure[\s\S]*?addEventListener\('toggle'/);
});

test('Concept Mapのinspectorはprimary briefを上書きせずprovenanceがある時だけartifact CTAを出すべき', () => {
  const inspectorSource = html.match(/function renderGraphInspector\(node, tree\) \{([\s\S]*?)\n    \}\n    function drawGraphEdges/)?.[1] || '';

  assert.doesNotMatch(inspectorSource, /wayfinder-next-decision/);
  assert.doesNotMatch(inspectorSource, /decision-subject/);
  assert.match(inspectorSource, /decision-evidence'\)\.hidden = !node\.artifact/);
});

test('brief-first layoutはdesktopの情報階層とmobileの一列順序を維持すべき', () => {
  assert.match(html, /\.execution-brief\s*\{[^}]*order:\s*1/);
  assert.match(html, /\.concept-map-disclosure\s*\{[^}]*order:\s*2/);
  assert.match(html, /\.current-focus\s*\{/);
  assert.match(html, /<div class="detail-drawer" id="detail-drawer"[^>]*hidden>/);
  assert.match(html, /\.design-summary-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,/);
  assert.match(html, /\.claim-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.design-summary-grid,[\s\S]*\.claim-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
  assert.match(html, /id="brief-quick-links"[\s\S]*data-artifact="00_spec\.md"[\s\S]*data-artifact="30_plan\.md"/);
});

test('設計書の主見出しは選択Taskではなく計画全体の目的を表示すべき', () => {
  const renderSource = html.match(/function renderExecutionBrief\(model\) \{([\s\S]*?)\n    \}\n    function renderHeader/)?.[1] || '';

  assert.match(renderSource, /execution-brief-title'\)\.textContent = brief\.design\.goal\.text/);
  assert.match(renderSource, /brief-design-context'\)\.textContent = brief\.design\.context\.text/);
  assert.doesNotMatch(renderSource, /execution-brief-title'\)\.textContent = selectedTask/);
  assert.match(html, /function renderDesignSummary\(design\)/);
  assert.match(html, /設計の骨格/);
  assert.match(html, /境界と完了/);
  assert.match(html, /data-artifact-section=/);
  assert.match(html, /data-md-heading=/);
  assert.match(html, /function openArtifact\(name, section = ''\)/);
});

test('implementation workspaceはdrawer内でTask indexと選択detailを持つsplit viewであるべき', () => {
  for (const id of [
    'detail-panel-change',
    'brief-workspace',
    'brief-task-index',
    'brief-task-detail',
    'brief-implementation',
    'brief-source-preview',
    'brief-source-location',
    'brief-source-code'
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /id="detail-panel-change"[\s\S]*id="brief-workspace"/);
  assert.match(html, /\.brief-workspace\s*\{[^}]*display:\s*grid[^}]*grid-template-columns:/);
  assert.match(html, /@media \(max-width:\s*900px\)[\s\S]*\.brief-workspace\s*\{[^}]*grid-template-columns:\s*1fr/);
  assert.match(html, /\.brief-source-code\s*\{[^}]*overflow-x:\s*auto/);
});

test('Change detailは要約、UI差分、Evidenceの順でProgressiveに表示すべき', () => {
  for (const id of [
    'brief-ui-preview',
    'ui-preview-list',
    'brief-change-evidence',
    'ui-preview-evidence-toggle',
    'ui-preview-evidence',
    'ui-preview-evidence-close',
    'ui-preview-evidence-list'
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.ok(html.indexOf('id="brief-implementation"') < html.indexOf('id="brief-ui-preview"'));
  assert.ok(html.indexOf('id="brief-ui-preview"') < html.indexOf('id="brief-change-evidence"'));
  assert.match(html, /現状・base refから確認/);
  assert.match(html, /計画案・未実装/);
  assert.match(html, /新規画面/);
  assert.match(html, /\.ui-preview-sides\s*\{[^}]*grid-template-columns:\s*repeat\(2,/s);
  assert.match(html, /@media \(max-width:\s*720px\)[\s\S]*\.ui-preview-sides\s*\{[^}]*grid-template-columns:\s*1fr/s);
  for (const change of ['same', 'added', 'modified', 'removed']) {
    assert.match(html, new RegExp(`change-${change}`), `${change} state needs class coverage`);
  }
  assert.match(html, /aria-label="\$\{escapeHtml\(aria\)\}"/);
  assert.match(html, /setUiPreviewEvidenceExpanded/);
});

test('選択Taskは現在Taskと別stateで、EvidenceとImpactはdrawer内のon-demand surfaceであるべき', () => {
  assert.match(
    html,
    /\.brief-flow-item\.current:not\(\[aria-selected="true"\]\)\s*\{/,
    'current-but-not-selected needs a secondary visual state',
  );
  assert.match(
    html,
    /\.brief-flow-item\[aria-selected="true"\]\s*\{/,
    'selected task needs its own primary visual state',
  );
  assert.doesNotMatch(
    html,
    /\.brief-flow-item\.current,\s*\.brief-flow-item\[aria-selected="true"\]/,
    'current and selected must not share one visual rule',
  );
  assert.match(
    html,
    /\.brief-implementation\s*\{[^}]*border-left:[^;]+;[^}]*background:/s,
    'planned steps need a dedicated plan surface',
  );
  assert.match(
    html,
    /\.brief-source-preview\s*\{[^}]*border-top:[^;]+;/s,
    'current source fact needs a distinct source surface',
  );
  assert.match(html, /function renderCurrentFocus\(brief, model\)/);
  assert.match(html, /current-focus-task-title'\)\.textContent = current\?\.title/);
  assert.match(html, /function renderImpactCodeMap\(brief\)/);
  assert.match(html, /id="detail-panel-sources"[\s\S]*id="brief-claims"[\s\S]*id="brief-artifacts"/);
  assert.match(html, /data-detail-open="impact"/);
  assert.doesNotMatch(html, /workspace-view-switch/);
});

test('implementation workspaceはsourceのpath・anchor・codeをHTML escapeして描画すべき', () => {
  const renderSource = html.match(/function renderExecutionBrief\(model\) \{([\s\S]*?)\n    \}\n    function renderHeader/)?.[1] || '';

  assert.match(renderSource, /escapeHtml\([^)]*\.path\)/);
  assert.match(renderSource, /escapeHtml\([^)]*\.anchor\)/);
  assert.match(renderSource, /escapeHtml\([^)]*\.code\)/);
  assert.doesNotMatch(renderSource, /\.innerHTML\s*=\s*[^;\n]*\.code\b/);
  assert.match(html, /<pre[^>]*id=["']brief-source-code["'][^>]*>[\s\S]*?<code/);
});

test('source highlighterはtokenを色分けしつつscript breakoutを文字列として保持すべき', () => {
  const highlighted = model.highlightSourceCode(
    'const value = 42; // note\nconst payload = "</script><script>alert(1)</script>";',
    'javascript',
  );

  assert.match(highlighted, /class="syntax-token syntax-keyword">const<\/span>/);
  assert.match(highlighted, /class="syntax-token syntax-number">42<\/span>/);
  assert.match(highlighted, /class="syntax-token syntax-comment">\/\/ note<\/span>/);
  assert.match(highlighted, /class="syntax-token syntax-string">/);
  assert.match(highlighted, /&lt;\/script&gt;&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(highlighted, /<script>/);
});

test('source highlighterは主要なplan実装言語へ最低1つの意味tokenを付けるべき', () => {
  const examples = new Map([
    ['python', ['def build():\\n    return True', /syntax-keyword/]],
    ['typescript', ['const ready: boolean = true;', /syntax-(?:keyword|literal)/]],
    ['html', ['<section aria-label="plan">', /syntax-tag/]],
    ['css', ['.plan { opacity: 0.8; }', /syntax-number/]],
    ['json', ['{"ready": true}', /syntax-(?:string|literal)/]],
    ['shell', ['if test -f plan; then # ready', /syntax-(?:keyword|comment)/]],
    ['markdown', ['# 実装計画', /syntax-keyword/]],
  ]);

  for (const [language, [source, expected]] of examples) {
    assert.match(model.highlightSourceCode(source.replaceAll('\\n', '\n'), language), expected, language);
  }
  assert.equal(model.highlightSourceCode('<raw>', 'unknown'), '&lt;raw&gt;');
});

test('Task別実装図は明示diagram JSONだけを選択Taskへ結び付け、未記録Taskを補完しないべき', () => {
  const result = model.buildModel(model.normalizeSnapshot({
    generatedAt,
    files: {
      '30_plan.md': `## Task 1: 図あり

### 実装

- parserへ渡す。

### 実装図

\`\`\`diagram-json
{"direction":"LR","nodes":[{"id":"S","label":"source"},{"id":"P","label":"parser"},{"id":"V","label":"viewer"}],"edges":[{"from":"S","to":"P","label":"解析する"},{"from":"P","to":"V","label":"描画する"}]}
\`\`\`

## Task 2: 図なし

### 実装

- sourceから関係を推測しない。`
    }
  }), { nowMs });

  const explicit = model.buildExecutionBrief(result, '1');
  const absent = model.buildExecutionBrief(result, '2');
  assert.equal(explicit.selectedImplementationDiagram.direction, 'LR');
  assert.deepEqual(Array.from(explicit.selectedImplementationDiagram.nodes, node => node.title), ['source', 'parser', 'viewer']);
  assert.deepEqual(Array.from(explicit.selectedImplementationDiagram.edges, edge => edge.predicate), ['解析する', '描画する']);
  assert.equal(absent.selectedImplementationDiagram, null);
});

test('implementation workspaceは選択Taskの実装図と同値な関係一覧を持つべき', () => {
  const renderDiagramSource = html.match(/function renderImplementationDiagram\(diagram\) \{([\s\S]*?)\n    \}\n    function renderExecutionBrief/)?.[1] || '';
  for (const id of [
    'implementation-diagram',
    'implementation-diagram-flow',
    'implementation-diagram-relations',
    'implementation-diagram-message',
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /function renderImplementationDiagram\(diagram\)/);
  assert.match(html, /aria-label="実装図の関係"/);
  assert.match(html, /class="implementation-diagram-svg"/);
  assert.match(html, /<svg class="implementation-diagram-svg"/);
  assert.match(html, /<polygon class="diagram-node decision"/);
  assert.match(html, /<path class="diagram-edge"/);
  assert.match(renderDiagramSource, /escapeHtml\(node\.title\)/);
  assert.match(renderDiagramSource, /escapeHtml\(edge\.predicate\)/);
});

test('viewing-plansのauthoring contractは設計summaryとTask実行契約を要求すべき', () => {
  assert.match(viewingPlansSkill, /(?:実施Task|Current Task)/);
  for (const label of ['仕様', '実装根拠', '(?:実行順序|全体像)', '(?:事実・判断・未確定|Evidence)', '成果物']) {
    assert.match(viewingPlansSkill, new RegExp(label));
  }
  for (const contract of ['Project Map \\+ Focus', 'Current Task', 'primary action', 'NextまたはBlocker', 'Detail drawer', 'ImpactからCode Map']) {
    assert.match(viewingPlansSkill, new RegExp(contract));
  }
  for (const heading of ['#### 目的', '#### 変更対象', '#### 実装根拠', '#### 実装', '#### 実装図', '#### 成果物', '#### 検証']) {
    assert.match(memoryFileFormats, new RegExp(heading));
  }
  assert.match(memoryFileFormats, /repo:<relative-path>#<anchor-or-Lx-Ly>/);
  assert.match(viewingPlansSkill, /生成時点の実source/);
  assert.match(viewingPlansSkill, /bare pathや `変更対象` からsource参照を推測しない/);
  assert.match(viewingPlansSkill, /実装図.*planに明示されたnodeとedgeだけ/s);
});

test('viewing-plansは短い保守作業をRoadmapから除外し必要時だけ昇格すべき', () => {
  for (const route of ['explicit-roadmap', 'roadmap', 'log-only']) {
    assert.ok(viewingPlansSkill.includes(`\`${route}\``));
  }
  for (const maintenance of ['競合解消', '単発再実行', '形式修正', '誤字修正', '設定同期']) {
    assert.match(viewingPlansSkill, new RegExp(maintenance));
  }
  assert.match(viewingPlansSkill, /ファイル数だけを理由にRoadmapへ昇格させない/);
  assert.match(viewingPlansSkill, /表を上から順に評価し、最初に一致した結果/);
  assert.match(viewingPlansSkill, /仕様や振る舞いの選択.*複数の解消案.*依存する複数Task.*roadmap.*昇格/s);
  assert.match(viewingPlansSkill, /roadmap_route: <結果>：<理由>/);
  assert.match(viewingPlansSkill, /log-only.*30_plan\.md.*roadmap\.html.*作らない/s);
  assert.match(viewingPlansSkill, /Codemap preflightは省略しない/);
});

test('the tree-first roadmap information architecture remains in the HTML', () => {
  for (const id of [
    'task-title',
    'wayfinder',
    'graph-shell',
    'graph-edges',
    'graph-outcomes',
    'graph-tasks',
    'graph-artifacts',
    'node-inspector',
    'inspector-title',
    'inspector-facts',
    'inspector-relations'
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  assert.match(html, /id="state-announcer" role="status" aria-live="polite"/);
  assert.doesNotMatch(html, /id="live-status"[^>]*aria-live=/);
  assert.doesNotMatch(html, /id="implementation-source-message"[^>]*aria-live=/);
  assert.match(html, /byId\('state-announcer'\)\.textContent = `接続状態: \$\{text\}`/);
  assert.match(html, /prefers-reduced-motion/);
  assert.match(html, /Tabler Icons/);
  assert.match(html, /id="graph-shell" role="region"/);
  assert.match(html, /data-graph-column="outcome" role="group"/);
  assert.match(html, /data-graph-column="outcome"/);
  assert.match(html, /data-graph-column="task"/);
  assert.match(html, /data-graph-column="artifact"/);
  assert.match(html, /aria-describedby="\$\{relationId\}"/);
  assert.match(html, /成果の観点 \$\{outgoing\.length\}件/);
  assert.match(html, /data-outcome-cluster/);
  assert.match(html, /現状を知る/);
  assert.match(html, /仕組みを決める/);
  assert.match(html, /安全に守る/);
  assert.match(html, /requires/);
  assert.match(html, /implemented by/);
  assert.match(html, /waits for/);
  assert.match(html, /proves/);
  assert.match(html, /data-related-node/);
  assert.match(html, /node-inspector'\)\.hidden = tree\.explicitGraphMap \? node\.id === tree\.activeNodeId : node\.kind === 'goal'/);
  assert.match(html, /\.graph-inspector\[hidden\]\s*\{\s*display:\s*none/);
  assert.match(html, /\.inspector-facts\s*\{\s*display:\s*none/);
  assert.match(html, /function pathNodeIds\(tree, selectedId\)/);
  assert.match(html, /function visibleGraphNodeIds\(tree, selected\)/);
  assert.match(html, /function canReceiveRestoredFocus\(element\)/);
  assert.match(html, /function fallbackFocusTarget\(key, fallbackId = ''\)/);
  assert.match(html, /function selectedPathEdges\(tree, selectedId\)/);
  assert.match(html, /function buildTreeViewModel\(model\)/);
  assert.match(html, /function parseSvgDiagramSpec\(markdown\)/);
  assert.match(html, /firstDiagramJson/);
  assert.match(html, /graph-map\.md/);
  assert.match(html, /if \(tree\.explicitGraphMap\) \{\s*renderExplicitGraph\(tree\);\s*return;\s*\}/);
  assert.match(html, /className = 'explicit-node-layer'/);
  assert.match(html, /id="graph-propositions"/);
  assert.match(html, /tree\.propositions\.map/);
  assert.match(html, /tree\.explicitGraphMap \? tree\.edges : selectedPathEdges/);
  assert.match(html, /\.explicit-node-layer \.graph-node\.kind-decision/);
  assert.match(html, /\.explicit-node-layer \.graph-node\.kind-risk/);
  assert.match(html, /\.explicit-node-layer \.graph-node\.kind-verification/);
  assert.match(html, /\.explicit-node-layer \.graph-node\.kind-decision,[\s\S]*?clip-path:\s*none/);
  assert.match(html, /\.explicit-node-layer \.graph-node\[aria-current="true"\] \.node-glyph/);
  assert.doesNotMatch(html, /\.explicit-node-layer \.graph-node\.kind-decision,[\s\S]{0,360}clip-path:\s*polygon/);
  assert.match(html, /function renderGraph\(model\)/);
  assert.match(html, /function drawGraphEdges\(tree, selectedId, visibleIds\)/);
  assert.match(html, /data-graph-node/);
  assert.match(html, /ArrowDown/);
  assert.match(html, /ArrowUp/);
  assert.match(html, /ArrowLeft/);
  assert.match(html, /ArrowRight/);
  assert.match(html, /event\.key === 'Home'/);
  assert.match(html, /event\.key === 'End'/);
  assert.match(html, /event\.key === 'Enter'/);
  assert.match(html, /event\.key === 'Escape'/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.graph-shell\s*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.graph-edges\s*\{\s*display:\s*none/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.outcome-cluster-grid\s*\{\s*grid-template-columns:\s*1fr/);
  assert.match(html, /const visible = new Set\(allOutcomes\)/);
  assert.match(html, /document\.title = workspaceTitle/);
  assert.match(html, /--ease-out:\s*cubic-bezier/);
  assert.match(html, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.doesNotMatch(html, /transition:\s*all/);
  assert.doesNotMatch(html, /\*, \*::before, \*::after\s*\{[^}]*transition:\s*none/);
  assert.match(html, /missing-implementation/);
  assert.match(html, /\.graph-edge-label\s*\{/);
  assert.match(html, /body:not\(\.task-hub-active\) #open-utility,[\s\S]*\.inspector-actions/);
  assert.doesNotMatch(html, /id=["'](?:open-files|export-json|file-input|drop-zone|viewer-settings|review-stats|all-artifact-list|artifact-jump)["']/);
  assert.doesNotMatch(html, /function (?:loadFiles|exportJson)\(|手動ファイル読込|表示と読込|成果物metadataなし/);
  assert.match(html, /id=["']source-list["']/);
  assert.match(html, /id=["']source-preview["']/);
  assert.doesNotMatch(html, /body:not\(\.task-hub-active\) \.utility-disclosure\s*\{[^}]*display:\s*none !important/);
  assert.match(html, /body:not\(\.task-hub-active\) \.outcome-trace,[\s\S]*\.revision-panel,[\s\S]*\.implementation-strip,[\s\S]*\.evidence-shortcuts/);
  assert.match(html, /function stopLivePolling\(/);
  assert.match(html, /generation !== pollGeneration/);
  assert.match(html, /const current = model\.activeTask/);
  assert.match(html, /function refreshFreshness\(/);
  assert.match(html, /renderGraph\(next\)/);
  assert.doesNotMatch(html, /function brandData\(/);
});

test('decision beacon navigation exposes first-class artifacts and an accessible mobile drawer', () => {
  for (const id of [
    'viewer-layout',
    'viewer-sidebar',
    'open-viewer-nav',
    'close-viewer-nav',
    'nav-scrim',
    'nav-artifacts-meta',
    'nav-outcomes-meta',
    'nav-verification-meta',
    'nav-reports-meta'
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `${id} is required`);
  }
  for (const label of ['ダッシュボード', 'ロードマップ', '成果物', 'アウトカム', '検証', 'レポート']) {
    assert.match(html, new RegExp(`<span>${label}</span>`));
  }
  assert.match(html, /data-nav-target="implementation-strip"/);
  assert.match(html, /data-nav-target="evidence-shortcuts"/);
  assert.match(html, /data-nav-artifact="90_verification\.md"/);
  assert.match(html, /data-nav-artifact="80_review\.md"/);
  assert.match(html, /@media \(max-width: 1023px\)[\s\S]*body\.viewer-nav-open \.app-sidebar/);
  assert.match(html, /function openViewerNav\(/);
  assert.match(html, /function closeViewerNav\(/);
  assert.match(html, /function updateViewerNavFromScroll\(/);
  assert.match(html, /viewerNavScrollLockUntil/);
  assert.match(html, /event\.key === 'Escape'/);
  assert.match(html, /event\.key !== 'Tab'/);
  assert.match(html, /aria-modal/);
  assert.match(html, /byId\('main-content'\)\.inert = true/);
  assert.match(html, /prefers-reduced-motion:[\s\S]*\.app-sidebar, \.nav-scrim/);
});

test('warning tokens and missing artifacts have accessible contrast contracts', () => {
  assert.match(html, /--warn-text:\s*#6f4800/);
  assert.match(html, /\[data-theme="dark"\][\s\S]*--warn-text:\s*#f0c978/);
  assert.ok(contrastRatio('#6f4800', '#f3f4f0') >= 4.5);
  assert.ok(contrastRatio('#6f4800', '#ffffff') >= 4.5);
  assert.ok(contrastRatio('#f0c978', '#242a26') >= 4.5);
  assert.ok(contrastRatio('#f0c978', '#1c211e') >= 4.5);
  assert.ok(contrastRatio('#626a65', '#ffffff') >= 4.5);
  assert.ok(contrastRatio('#626a65', '#f3f4f0') >= 4.5);
  assert.match(html, /\.trace-token\.warn\s*\{[^}]*color:\s*var\(--warn-text\)/);
  assert.match(html, /\.artifact-warning\s*\{[^}]*color:\s*var\(--warn-text\)/);
  assert.match(html, /\.artifact-state\.missing\s*\{[^}]*color:\s*var\(--warn-text\)\s*!important/);
});

test('focused document workspace keeps markdown readable and responsive', () => {
  assert.match(html, /class="document-workspace" aria-label="Markdownワークスペース"/);
  assert.match(html, /class="document-sidebar" aria-label="Markdownソース"/);
  assert.match(html, /class="document-reader" aria-label="選択したMarkdown"/);
  assert.match(html, /\.document-workspace\s*\{[^}]*grid-template-columns:\s*minmax\(228px,\s*280px\)\s*minmax\(0,\s*1fr\)/);
  assert.match(html, /\.source-preview\s*\{[^}]*font-size:\s*16px/);
  assert.match(html, /\.source-preview\s*\{[^}]*line-height:\s*1\.75/);
  assert.doesNotMatch(html, /\.source-preview\s*\{[^}]*max-height/);
  assert.match(html, /--shadow:\s*none/);
  assert.match(html, /font-family:\s*ui-serif,\s*"Yu Mincho"/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.document-workspace\s*\{\s*grid-template-columns:\s*1fr/);
  assert.match(html, /@media \(max-width: 720px\)[\s\S]*\.document-sidebar\s*\{[^}]*border-bottom:\s*1px solid var\(--line\)/);
});
