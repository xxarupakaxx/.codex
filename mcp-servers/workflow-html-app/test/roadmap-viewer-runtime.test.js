import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const templatePath = fileURLToPath(new URL("../../../tools/roadmap_viewer.html", import.meta.url));
const latestRoadmapSnapshotPath = fileURLToPath(new URL("../../../../.local/memory/260827_effective-html-roadmap-overhaul/roadmap-snapshot.json", import.meta.url));
const graphMap = `# Concept Map

\`\`\`diagram-json
{
  "direction": "TB",
  "nodes": [
    {"id":"G","label":"理解できる計画"},
    {"id":"F","label":"snapshotに本文がある"},
    {"id":"D","label":"brief-firstを採用","shape":"decision"},
    {"id":"A","label":"実行計画"},
    {"id":"V","label":"browserで検証"}
  ],
  "edges": [
    {"from":"G","to":"D","label":"必要とする"},
    {"from":"F","to":"D","label":"判断材料にする"},
    {"from":"D","to":"A","label":"生み出す"},
    {"from":"V","to":"A","label":"検証する"}
  ]
}
\`\`\`
`;

function buildSnapshot() {
  return {
    version: 1,
    title: "Roadmap Viewerの読解可能性を再設計",
    generatedAt: new Date().toISOString(),
    files: {
      "00_spec.md": `# 機能要求

## 概要

実行Task、仕様、実装根拠、順序、事実、成果物を第一画面で理解できるようにする。

## 背景・目的

進捗だけでなく設計意図まで第一画面で理解できる必要がある。

## 必須要件

- Taskと仕様を同時に読める。

## 制約事項

- snapshot schema version 1を維持する。

## 現在の事実

- snapshotにはMarkdown本文が残っている。

## 採用判断

- 第一画面をbrief-firstにする。

## 未確定

- 古いtaskの見出し揺れ。
`,
      "20_survey.md": `## 現在の事実

- graph-first表示がTaskを隠していた。
`,
      "30_plan.md": `# 実装計画

## 実装方針

\`buildExecutionBrief()\` を \`.codex/tools/roadmap_viewer.html\` に追加する。

## Task 1: contractを固定する

### 目的

第一画面の読解要件をtestにする。

### 変更対象

- \`.codex/tests/roadmap-viewer.test.mjs\`

### 実装根拠

- \`repo:.codex/tests/roadmap-viewer.test.mjs#test('first screen')\`

### 実装

- contract testを追加する。
- source previewの境界を固定する。

### 実装図

\`\`\`diagram-json
{
  "direction": "LR",
  "nodes": [
    {"id":"T","label":"contract test"},
    {"id":"M","label":"Viewer model"},
    {"id":"U","label":"実装UI"}
  ],
  "edges": [
    {"from":"T","to":"M","label":"固定する"},
    {"from":"M","to":"U","label":"描画する"}
  ]
}
\`\`\`

### 成果物

- contract test

### 検証

\`node --test .codex/tests/roadmap-viewer.test.mjs\`

## Task 2: brief UIを実装する

### 目的

6項目を画面へ表示する。

### 変更対象

- \`.codex/tools/roadmap_viewer.html\`

### 実装根拠

- \`repo:.codex/tools/roadmap_viewer.html#function renderExecutionBrief(model)\`

### 実装

- compact indexと選択Task detailを描画する。
- 現在の実コードを計画と分けて表示する。
`,
      "40_progress.md": `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 進行中 | 1/2 |
| Task 2 | 未着手 | 0/1 |

## 実測

- Node contractはgreen。
`,
      "team-journal.md": `## Decisions

- primary briefとgraph inspectorを分離する。

## Open Questions

- code anchorがないtaskの表示。
`,
      "graph-map.md": graphMap,
    },
  };
}

function buildImplementationSnapshot() {
  const snapshot = buildSnapshot();
  snapshot.fingerprint = "source-preview-v1";
  snapshot.sourcePreviews = [
    {
      taskNumber: "1",
      status: "resolved",
      path: ".codex/tests/roadmap-viewer.test.mjs",
      anchor: "test('first screen')",
      startLine: 320,
      endLine: 322,
      language: "javascript",
      code: [
        "test('first screen', () => {",
        `  const boundedSourceLine = "${"implementation-workspace-".repeat(24)}";`,
        "});",
      ].join("\n"),
      message: "",
    },
    {
      taskNumber: "2",
      status: "resolved",
      path: ".codex/tools/roadmap_viewer.html",
      anchor: "function renderExecutionBrief(model)",
      startLine: 4030,
      endLine: 4032,
      language: "html",
      code: [
        "function renderExecutionBrief(model) {",
        "  const brief = ROADMAP_MODEL.buildExecutionBrief(model);",
        "}",
      ].join("\n"),
      message: "",
    },
  ];
  snapshot.uiPreviews = [
    {
      taskNumber: "1",
      version: 1,
      screen: "Detail drawer actions",
      title: "Evidence action wording",
      layout: "topnav",
      status: "unverified",
      message: "base refのanchor確認待ち",
      source: {
        path: ".codex/tools/roadmap_viewer.html",
        anchor: "data-detail-open=\"sources\"",
        status: "anchor-missing",
        message: "source anchor drift",
        evidenceRevision: "feed1234",
      },
      provenance: {
        before: {
          source: "repo:.codex/tools/roadmap_viewer.html#data-detail-open=\"sources\"",
          baseRef: "origin/main",
          observedLabels: ["Detailを開く", "Sources"],
        },
        after: {
          source: "30_plan.md#Task 1",
        },
      },
      before: {
        items: [
          { id: "detail", label: "Detailを開く", kind: "button", state: "primary", change: "same" },
          { id: "sources", label: "Sources", kind: "tab", state: "secondary", change: "modified" },
          { id: "legacy", label: "旧導線", kind: "link", state: "visible", change: "removed" },
          { id: "help", label: "Help", kind: "link", state: "secondary", change: "same" },
        ],
      },
      after: {
        status: "planned",
        items: [
          { id: "detail", label: "Detailを開く", kind: "button", state: "primary", change: "same" },
          { id: "help", label: "Help", kind: "link", state: "secondary", change: "same" },
          { id: "sources", label: "Evidence", kind: "tab", state: "secondary", change: "modified" },
          { id: "diff", label: "UI差分", kind: "section", state: "new", change: "added" },
        ],
      },
      uncertainty: ["hover stateは実ブラウザ確認で確定する。"],
    },
    {
      taskNumber: "2",
      version: 1,
      screen: "UI Preview panel",
      title: "新規UI差分panel",
      layout: "list",
      status: "planned",
      message: "new screen has no before source",
      before: { status: "source-unavailable", items: [] },
      after: {
        items: [
          { id: "summary", label: "要約", kind: "region", state: "visible", change: "added" },
          { id: "preview", label: "Before / After", kind: "region", state: "planned", change: "added" },
        ],
      },
      provenance: {
        before: { baseRef: "origin/main", observedLabels: [] },
        after: { source: "30_plan.md#Task 2" },
      },
      uncertainty: ["generator統合後にbase ref statusを再確認する。"],
    },
  ];
  return snapshot;
}

function buildLatestRoadmapSnapshot() {
  if (!existsSync(latestRoadmapSnapshotPath)) return buildSnapshot();
  return JSON.parse(readFileSync(latestRoadmapSnapshotPath, "utf8"));
}

function writeFixture(snapshotInput = buildSnapshot()) {
  const directory = mkdtempSync(join(tmpdir(), "roadmap-viewer-runtime-"));
  const template = readFileSync(templatePath, "utf8");
  const snapshot = JSON.stringify(snapshotInput).replaceAll("<", "\\u003c");
  const html = template.replace('{"__ROADMAP_SNAPSHOT_JSON__": true}', snapshot);
  const path = join(directory, "roadmap.html");
  writeFileSync(path, html);
  return { directory, path };
}

async function withPage(t, viewport, callback, snapshot = buildSnapshot()) {
  const fixture = writeFixture(snapshot);
  let browser;
  try {
    try {
      browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch (error) {
      t.diagnostic(`System Chrome launch failed; trying bundled Chromium. ${error.message}`);
      browser = await chromium.launch({ headless: true });
    }
    const page = await browser.newPage({ viewport });
    await page.goto(`file://${fixture.path}`);
    await page.waitForSelector("#current-focus");
    await callback(page);
    await page.close();
  } finally {
    await browser?.close();
    rmSync(fixture.directory, { recursive: true, force: true });
  }
}

async function withLivePage(t, viewport, callback, snapshotInput = buildSnapshot()) {
  const fixture = writeFixture(snapshotInput);
  let snapshot = snapshotInput;
  const server = createServer((request, response) => {
    if (request.url?.startsWith("/roadmap-snapshot.json")) {
      response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify(snapshot));
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(readFileSync(fixture.path));
  });
  let browser;
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    try {
      browser = await chromium.launch({ channel: "chrome", headless: true });
    } catch (error) {
      t.diagnostic(`System Chrome launch failed; trying bundled Chromium. ${error.message}`);
      browser = await chromium.launch({ headless: true });
    }
    const page = await browser.newPage({ viewport });
    const address = server.address();
    await page.goto(`http://127.0.0.1:${address.port}/roadmap.html`);
    await page.waitForSelector("#current-focus");
    await callback(page, (nextSnapshot) => { snapshot = nextSnapshot; });
    await page.close();
  } finally {
    await browser?.close();
    await new Promise((resolve) => server.close(resolve));
    rmSync(fixture.directory, { recursive: true, force: true });
  }
}

test("first screen exposes Project Map and Current Focus while evidence stays on-demand", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    const state = await page.evaluate(() => ({
      executionVisible: document.querySelector("#execution-brief")?.getBoundingClientRect().height > 0,
      planTitle: document.querySelector("#execution-brief-title")?.textContent,
      currentTitle: document.querySelector("#current-focus-task-title")?.textContent,
      currentPurpose: document.querySelector("#current-focus-purpose")?.textContent,
      primaryAction: document.querySelector("#current-primary-action")?.textContent,
      context: document.querySelector("#brief-design-context")?.textContent,
      requirements: document.querySelector("#brief-requirements")?.textContent,
      decisions: document.querySelector("#brief-design-decisions")?.textContent,
      boundaries: document.querySelector("#brief-boundaries")?.textContent,
      selectedMetric: document.querySelector("#brief-current-status")?.textContent,
      workspaceToggleCount: document.querySelectorAll("#workspace-view-plan, #workspace-view-code, .workspace-view-switch").length,
      headerCodemapVisible: Boolean(document.querySelector(".app-header #codemap-gate")?.getClientRects().length),
      impactCodemapStatusVisible: Boolean(document.querySelector("#detail-panel-impact #impact-code-map-status")?.getClientRects().length),
      evidenceVisible: Boolean(document.querySelector("#brief-claims")?.getClientRects().length || document.querySelector("#brief-artifacts")?.getClientRects().length),
      selectedDetailVisible: Boolean(document.querySelector("#implementation-workspace")?.getClientRects().length || document.querySelector("#brief-source-preview")?.getClientRects().length),
      graphOpen: document.querySelector("#concept-map-disclosure")?.open,
    }));

    assert.equal(state.executionVisible, true);
    assert.match(state.planTitle, /実行Task、仕様、実装根拠/);
    assert.equal(state.currentTitle, "contractを固定する");
    assert.match(state.currentPurpose, /第一画面の読解要件/);
    assert.match(state.primaryAction, /contract testを追加/);
    assert.match(state.context, /設計意図まで第一画面で理解/);
    assert.match(state.requirements, /Taskと仕様を同時に読める/);
    assert.match(state.decisions, /第一画面をbrief-firstにする/);
    assert.match(state.boundaries, /schema version 1を維持/);
    assert.match(state.selectedMetric, /1 \/ 2/);
    assert.equal(state.workspaceToggleCount, 0);
    assert.equal(state.headerCodemapVisible, false);
    assert.equal(state.impactCodemapStatusVisible, false);
    assert.equal(state.evidenceVisible, false);
    assert.equal(state.selectedDetailVisible, false);
    assert.equal(state.graphOpen, false);

    await page.locator('[data-detail-open="sources"]').click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    assert.deepEqual(await page.locator("#brief-claims h4").allTextContents(), ["事実", "判断", "未確定"]);
    assert.deepEqual(
      await page.locator("#brief-artifact-grid [data-artifact]").evaluateAll((nodes) => nodes.map((node) => node.dataset.artifact)),
      ["00_spec.md", "30_plan.md", "40_progress.md", "80_review.md"],
    );
    await page.keyboard.press("Escape");
    assert.equal(await page.evaluate(() => document.querySelector("#detail-drawer")?.hidden), true);
    assert.equal(await page.evaluate(() => document.activeElement?.dataset.detailOpen), "sources");
  });

  const completed = buildSnapshot();
  completed.files["40_progress.md"] = `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 完了 | 2/2 |
| Task 2 | 完了 | 1/1 |
`;
  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    assert.equal(await page.locator("#current-focus-task-title").textContent(), "brief UIを実装する");
    assert.equal(await page.locator("#current-primary-action").textContent(), "成果を確認");
    assert.match(await page.locator("#brief-current-status").textContent(), /2 \/ 2 · 完了/);

    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    await page.locator('[data-implementation-task="1"]').click();
    assert.equal(await page.locator("#implementation-task-title").textContent(), "contractを固定する");
    assert.equal(await page.locator("#current-focus-task-title").textContent(), "contractを固定する");
    assert.equal(await page.locator("#current-primary-action").textContent(), "成果を確認");
  }, completed);
});

test("motion system keeps transitions brief, stateful, and reduced-motion aware", async (t) => {
  const template = readFileSync(templatePath, "utf8");
  assert.match(template, /--duration-press:\s*120ms/);
  assert.match(template, /--duration-medium:\s*220ms/);
  assert.match(template, /@media \(prefers-reduced-motion: reduce\)[\s\S]*--motion-distance:\s*2px/);
  assert.match(template, /departing = previous\.cloneNode\(true\)/);
  assert.match(template, /typeof Element\.prototype\.animate === 'function'/);
  assert.match(template, /Keep the DOM update synchronous/);

  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    const initial = await page.evaluate(() => ({
      distance: getComputedStyle(document.documentElement).getPropertyValue("--motion-distance").trim(),
      canAnimate: typeof document.querySelector("#implementation-detail").animate === "function",
      entryName: (() => {
        document.body.classList.add("motion-entering");
        const name = getComputedStyle(document.querySelector("#execution-brief")).animationName;
        document.body.classList.remove("motion-entering");
        return name;
      })(),
    }));
    assert.equal(initial.distance, "8px");
    assert.equal(initial.canAnimate, true);
    assert.equal(initial.entryName, "motion-surface-enter");

    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--motion-distance").trim()), "2px");
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    const changed = await page.evaluate(() => {
      document.querySelector('[data-implementation-task="2"]').click();
      return {
        title: document.querySelector("#implementation-task-title")?.textContent,
        departing: document.querySelectorAll("body > .brief-task-detail[aria-hidden='true'][inert]").length,
      };
    });
    assert.equal(changed.title, "brief UIを実装する");
    assert.equal(changed.departing, 1);
    assert.equal(await page.locator('[data-implementation-task="2"]').getAttribute("aria-selected"), "true");
    await page.waitForFunction(() => document.querySelectorAll("body > .brief-task-detail[aria-hidden='true'][inert]").length === 0);

    const fallbackTitle = await page.evaluate(() => {
      const animate = Element.prototype.animate;
      Element.prototype.animate = undefined;
      try {
        document.querySelector('[data-implementation-task="1"]').click();
        return document.querySelector("#implementation-task-title")?.textContent;
      } finally {
        Element.prototype.animate = animate;
      }
    });
    assert.equal(fallbackTitle, "contractを固定する");
  });
});

test("concept map interaction does not overwrite the primary brief", async (t) => {
  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    const before = await page.locator("#execution-brief-title").textContent();
    const purposeBefore = await page.locator("#implementation-task-purpose").textContent();

    await page.locator("#concept-map-disclosure > summary").click();
    await page.waitForFunction(() => document.querySelectorAll("#graph-edges path").length > 0);
    const edgeBeforeResize = await page.locator("#graph-edges path").first().getAttribute("d");
    await page.locator('[data-graph-node="D"]').click();

    assert.equal(await page.locator("#execution-brief-title").textContent(), before);
    assert.equal(await page.locator("#implementation-task-purpose").textContent(), purposeBefore);
    assert.equal(await page.locator("#decision-evidence").isHidden(), true);
    assert.match(await page.locator("#inspector-title").textContent(), /brief-first/);

    await page.locator('[data-graph-node="D"]').focus();
    await page.keyboard.press("ArrowRight");
    await page.waitForFunction(() => document.activeElement?.dataset.graphNode === "A");
    assert.equal(await page.locator('[data-graph-node="A"]').getAttribute("aria-current"), "true");

    await page.setViewportSize({ width: 980, height: 900 });
    await page.waitForFunction((previous) => {
      const current = document.querySelector("#graph-edges path")?.getAttribute("d");
      return Boolean(current && current !== previous);
    }, edgeBeforeResize);
  });
});

test("desktop tablet and mobile preserve section order without horizontal overflow", async (t) => {
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 768, height: 900 },
    { width: 375, height: 812 },
  ]) {
    await withPage(t, viewport, async (page) => {
      const state = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        executionTop: document.querySelector("#execution-brief")?.getBoundingClientRect().top,
        conceptTop: document.querySelector("#concept-map-disclosure")?.getBoundingClientRect().top,
        evidenceVisible: Boolean(document.querySelector("#brief-claims")?.getClientRects().length || document.querySelector("#brief-artifacts")?.getClientRects().length),
        quickSpecInViewport: document.querySelector('#brief-quick-links [data-artifact="00_spec.md"]')?.getBoundingClientRect().bottom <= innerHeight,
      }));

      assert.ok(state.overflow <= 1, `${viewport.width}px has horizontal overflow ${state.overflow}px`);
      assert.ok(state.executionTop < state.conceptTop);
      assert.equal(state.quickSpecInViewport, true);
      assert.equal(state.evidenceVisible, false);
    });
  }
});

test("mobile Project Map keeps four readable stage representatives in 128px", async (t) => {
  await withPage(t, { width: 375, height: 812 }, async (page) => {
    const state = await page.evaluate(() => {
      const route = document.querySelector("#brief-route");
      const map = document.querySelector("#brief-route-map");
      const title = document.querySelector("#brief-route-title");
      const titleRect = title.getBoundingClientRect();
      const stages = [...document.querySelectorAll(".project-map-stage")].map((stage) => {
        const rect = stage.getBoundingClientRect();
        const node = stage.querySelector(".project-map-node");
        const nodeRect = node.getBoundingClientRect();
        return {
          stage: stage.querySelector("h4")?.textContent,
          text: node?.textContent || "",
          left: rect.left,
          right: rect.right,
          width: rect.width,
          nodeWidth: nodeRect.width,
          nodeHeight: nodeRect.height,
        };
      });
      const mapRect = map.getBoundingClientRect();
      return {
        title: title.textContent,
        titleWidth: titleRect.width,
        titleHeight: titleRect.height,
        routeHeight: route.getBoundingClientRect().height,
        horizontalOverflow: map.scrollWidth - map.clientWidth,
        mapLeft: mapRect.left,
        mapRight: mapRect.right,
        workspaceToggleCount: document.querySelectorAll("#workspace-view-plan, #workspace-view-code, .workspace-view-switch").length,
        evidenceVisible: Boolean(document.querySelector("#brief-claims")?.getClientRects().length || document.querySelector("#brief-artifacts")?.getClientRects().length),
        selectedDetailVisible: Boolean(document.querySelector("#implementation-workspace")?.getClientRects().length || document.querySelector("#brief-source-preview")?.getClientRects().length),
        currentFocus: document.querySelector("#current-focus-task-title")?.textContent || "",
        stages,
      };
    });

    assert.equal(state.title, "企画から検証まで");
    assert.ok(state.titleWidth > state.titleHeight * 3, "Project Map heading should read horizontally");
    assert.ok(state.routeHeight <= 128, `Project Map height ${state.routeHeight}px exceeds 128px`);
    assert.ok(state.horizontalOverflow <= 1, `Project Map overflow ${state.horizontalOverflow}px`);
    assert.deepEqual(state.stages.map((stage) => stage.stage), ["企画", "設計", "実装", "検証"]);
    assert.ok(state.stages.every((stage) => stage.left >= state.mapLeft - 1 && stage.right <= state.mapRight + 1 && stage.width > 0));
    assert.ok(state.stages.every((stage) => stage.nodeWidth > 0 && stage.nodeHeight > 0 && stage.text.trim().length >= 2));
    assert.ok(state.stages.some((stage) => /現在|進行中/.test(stage.text)));
    assert.equal(state.workspaceToggleCount, 0);
    assert.equal(state.evidenceVisible, false);
    assert.equal(state.selectedDetailVisible, false);
    assert.ok(state.currentFocus.trim().length > 0);

    const focusBefore = await page.locator("#current-focus-task-title").textContent();
    await page.locator('[data-detail-open="impact"]').click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    assert.equal(await page.locator("#detail-tab-impact").getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("#detail-panel-impact").isVisible(), true);
    assert.equal(await page.evaluate(() => document.body.classList.contains("codemap-mode")), false);
    assert.equal(await page.locator("#current-focus-task-title").textContent(), focusBefore);
    await page.keyboard.press("Escape");
    assert.equal(await page.evaluate(() => document.querySelector("#detail-drawer")?.hidden), true);
    assert.equal(await page.evaluate(() => document.activeElement?.id), "open-impact-map");
  }, buildLatestRoadmapSnapshot());
});

test("keyboard opens a source artifact and the concept disclosure on mobile", async (t) => {
  await withPage(t, { width: 375, height: 812 }, async (page) => {
    const specLink = page.locator('#brief-quick-links [data-artifact="00_spec.md"]');
    await specLink.focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.querySelector("#utility-disclosure")?.open);
    assert.match(await page.locator("#source-preview").textContent(), /実行Task/);
    assert.equal(await page.evaluate(() => document.activeElement?.id), "source-preview");

    const summary = page.locator("#concept-map-disclosure > summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("#concept-map-disclosure").getAttribute("open"), "");
  });
});

test("missing design decisions and done conditions stay explicit", async (t) => {
  const snapshot = buildSnapshot();
  snapshot.files["30_plan.md"] = `## Task 1: 古いTask

- [ ] 実行する
`;
  snapshot.files["00_spec.md"] = `## 目的

古いTaskを読む。

## 必須要件

- 記録済みの内容だけを表示する。

## 制約事項

- sourceにない内容を推論しない。
`;
  delete snapshot.files["20_survey.md"];
  delete snapshot.files["40_progress.md"];
  delete snapshot.files["team-journal.md"];

  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    assert.match(await page.locator("#brief-design-decisions").textContent(), /設計判断が未記録/);
    assert.match(await page.locator("#brief-done").textContent(), /完了条件が未記録/);
  }, snapshot);
});

test("live polling refreshes freshness and a changed snapshot updates the current task", async (t) => {
  await withLivePage(t, { width: 1280, height: 900 }, async (page, setSnapshot) => {
    await page.waitForFunction(() => document.querySelector("#live-status-text")?.textContent === "Live");
    const stale = buildSnapshot();
    stale.generatedAt = "2020-01-01T00:00:00.000Z";
    setSnapshot(stale);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.equal(await page.locator("#brief-status").textContent(), "更新待ち");

    const freshSameSignature = { ...stale, generatedAt: new Date().toISOString() };
    setSnapshot(freshSameSignature);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.equal(await page.locator("#brief-status").textContent(), "Task 1 進行中");
    assert.equal(await page.locator("#live-status-text").textContent(), "Live");

    const changed = structuredClone(freshSameSignature);
    changed.files["40_progress.md"] = `# 進捗

| Task | 状態 | 進捗 |
| --- | --- | --- |
| Task 1 | 完了 | 2/2 |
| Task 2 | 進行中 | 0/1 |

## 実測

- runtime snapshotを更新した。
`;
    setSnapshot(changed);
    await page.evaluate(() => pollSnapshot(pollGeneration));
    assert.match(await page.locator("#brief-current-task").textContent(), /Task 2/);
    assert.match(await page.locator("#implementation-task-meta").textContent(), /TASK 2/);
    assert.equal(await page.locator("#brief-progress").textContent(), "1 / 2 Task");
  });
});

test("implementation workspace keeps every task visible and binds selection to plan steps and real source", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    await page.waitForFunction(() => /contract test/.test(document.querySelector("#implementation-task-output")?.textContent || ""));
    const tasks = page.locator("[data-implementation-task]");
    assert.equal(await tasks.count(), 2);
    assert.deepEqual(await tasks.evaluateAll((nodes) => nodes.map((node) => ({
      task: node.dataset.implementationTask,
      selected: node.getAttribute("aria-selected"),
      visible: Boolean(node.getClientRects().length),
    }))), [
      { task: "1", selected: "true", visible: true },
      { task: "2", selected: "false", visible: true },
    ]);

    assert.match(await page.locator("#implementation-steps").textContent(), /contract testを追加する/);
    assert.match(await page.locator("#implementation-task-output").textContent(), /contract test/);
    assert.equal(
      await page.locator("#implementation-source-path").textContent(),
      ".codex/tests/roadmap-viewer.test.mjs",
    );
    assert.match(await page.locator("#implementation-source-range").textContent(), /320.*322/);
    assert.deepEqual(
      await page.locator("#implementation-code .implementation-code-line").evaluateAll(
        (nodes) => nodes.map((node) => node.dataset.line),
      ),
      ["320", "321", "322"],
    );

    await tasks.nth(0).focus();
    await page.keyboard.press("ArrowDown");
    assert.equal(await tasks.nth(1).getAttribute("aria-selected"), "true");
    assert.equal(
      await page.evaluate(() => document.activeElement?.dataset.implementationTask),
      "2",
    );
    assert.match(await page.locator("#implementation-steps").textContent(), /compact index/);
    assert.equal(
      await page.locator("#implementation-source-path").textContent(),
      ".codex/tools/roadmap_viewer.html",
    );
    assert.equal(await page.locator("#implementation-task-title").textContent(), "brief UIを実装する");

    await page.keyboard.press("ArrowUp");
    assert.equal(await tasks.nth(0).getAttribute("aria-selected"), "true");
    await page.keyboard.press("End");
    assert.equal(await tasks.nth(1).getAttribute("aria-selected"), "true");
    await page.keyboard.press("Home");
    assert.equal(await tasks.nth(0).getAttribute("aria-selected"), "true");
  }, buildImplementationSnapshot());
});

test("UI preview shows existing before after and new-screen after-only states", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);

    assert.equal(await page.locator("#brief-ui-preview").isVisible(), true);
    assert.equal(
      await page.locator('[data-ui-preview-layout="topnav"] .ui-preview-item').evaluateAll((nodes) => nodes.every((node) => node.getBoundingClientRect().width >= 150)),
      true,
    );
    assert.equal(await page.locator(".ui-preview-side.before h6").textContent(), "現状・base refから確認Before未確認");
    assert.equal(await page.locator(".ui-preview-side.after h6").textContent(), "計画案・未実装計画案");
    assert.doesNotMatch(await page.locator("#brief-ui-preview").textContent(), /anchor-missing|secondary|topnav/);
    assert.deepEqual(
      await page.locator(".ui-preview-item").evaluateAll((nodes) => nodes.map((node) => ({
        text: (node.textContent || "").replace(/\s+/g, " ").trim(),
        aria: node.getAttribute("aria-label"),
        className: node.className,
      })).filter((item) => /Sources|Evidence|UI差分|現状なし/.test(`${item.text} ${item.aria}`))),
      [
        {
          text: "~ Sourcesタブ · 補助 · 内容と順序を変更 順序変更",
          aria: "Before Sources: 変更、順序変更あり",
          className: "ui-preview-item change-modified",
        },
        {
          text: "+ 現状なしセクション · 計画側で追加",
          aria: "Before 現状なし: 追加",
          className: "ui-preview-item change-added placeholder",
        },
        {
          text: "~ Evidenceタブ · 補助 · 内容と順序を変更 順序変更",
          aria: "After Evidence: 変更、順序変更あり",
          className: "ui-preview-item change-modified",
        },
        {
          text: "+ UI差分セクション · 新規 · 追加予定",
          aria: "After UI差分: 追加",
          className: "ui-preview-item change-added",
        },
      ],
    );
    assert.equal(await page.locator(".ui-preview-item.change-added:not(.placeholder) .ui-preview-change-badge").count(), 0);

    const contrast = await page.evaluate(() => {
      const parse = (color) => color.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(Number);
      const linear = (value) => {
        const channel = value / 255;
        return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
      };
      const luminance = (color) => {
        const [r, g, b] = parse(color).map(linear);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const ratio = (a, b) => {
        const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
        return (light + 0.05) / (dark + 0.05);
      };
      const sample = () => ["added", "modified", "removed"].map((change) => {
        const symbol = document.querySelector(`.change-${change} .ui-preview-symbol`);
        const style = getComputedStyle(symbol);
        return { change, ratio: ratio(style.color, style.backgroundColor) };
      });
      const light = sample();
      document.body.dataset.theme = "dark";
      return { light, dark: sample() };
    });
    for (const item of [...contrast.light, ...contrast.dark]) {
      assert.ok(item.ratio >= 4.5, `${item.change} symbol contrast ${item.ratio}`);
    }

    await page.locator('[data-implementation-task="2"]').click();
    await page.waitForFunction(() => document.querySelector('[data-implementation-task="2"]')?.getAttribute("aria-selected") === "true");
    assert.equal(await page.locator(".ui-preview-new-badge").textContent(), "新規画面");
    assert.equal(
      await page.locator('[data-ui-preview-task="2"]').first().getAttribute("data-ui-preview-layout"),
      "list",
    );
    await page.waitForFunction(() => Array.from(document.querySelectorAll(".ui-preview-side.before")).filter((node) => node.getClientRects().length).length === 0);
    assert.match(await page.locator(".ui-preview-side.after").textContent(), /計画案・未実装/);
    assert.match(await page.locator(".ui-preview-side.after").textContent(), /Before \/ After/);
  }, buildImplementationSnapshot());
});

test("UI preview evidence opens on demand and restores focus when closed", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    assert.equal(await page.locator("#ui-preview-evidence").isHidden(), true);
    await page.locator("#ui-preview-evidence-toggle").click();
    await page.waitForFunction(() => !document.querySelector("#ui-preview-evidence")?.hidden);

    const evidence = (await page.locator("#ui-preview-evidence-list").textContent()).replace(/\s+/g, "");
    assert.match(evidence, /BeforesourceBefore未確認·feed1234/);
    assert.match(evidence, /sourceanchordrift/);
    assert.match(evidence, /\.codex\/tools\/roadmap_viewer\.html#data-detail-open="sources"/);
    assert.match(evidence, /Afterplansource30_plan\.md#Task1/);
    assert.match(evidence, /hoverstate/);

    await page.locator("#ui-preview-evidence-close").focus();
    await page.locator("#ui-preview-evidence-close").click();
    await page.waitForFunction(() => document.querySelector("#ui-preview-evidence")?.hidden);
    await page.waitForFunction(() => document.activeElement?.id === "ui-preview-evidence-toggle");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "ui-preview-evidence-toggle");
  }, buildImplementationSnapshot());
});

test("UI preview evidence controls keep 44px target and modal hides page background at 375px", async (t) => {
  await withPage(t, { width: 375, height: 812 }, async (page) => {
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);

    assert.deepEqual(await page.evaluate(() => ({
      headerInert: document.querySelector(".app-header")?.inert,
      headerHidden: document.querySelector(".app-header")?.getAttribute("aria-hidden"),
      mainInert: document.querySelector("#main-content")?.inert,
      mainHidden: document.querySelector("#main-content")?.getAttribute("aria-hidden"),
    })), {
      headerInert: true,
      headerHidden: "true",
      mainInert: true,
      mainHidden: "true",
    });

    const toggleBox = await page.locator("#ui-preview-evidence-toggle").boundingBox();
    assert.ok(toggleBox && toggleBox.height >= 44, `toggle height ${toggleBox?.height}`);
    await page.locator("#ui-preview-evidence-toggle").click();
    await page.waitForFunction(() => !document.querySelector("#ui-preview-evidence")?.hidden);
    const closeBox = await page.locator("#ui-preview-evidence-close").boundingBox();
    assert.ok(closeBox && closeBox.height >= 44, `close height ${closeBox?.height}`);

    await page.locator("#close-detail-drawer").click();
    await page.waitForFunction(() => document.querySelector("#detail-drawer")?.hidden);
    assert.deepEqual(await page.evaluate(() => ({
      headerInert: document.querySelector(".app-header")?.inert,
      headerHidden: document.querySelector(".app-header")?.getAttribute("aria-hidden"),
      mainInert: document.querySelector("#main-content")?.inert,
      mainHidden: document.querySelector("#main-content")?.getAttribute("aria-hidden"),
    })), {
      headerInert: false,
      headerHidden: null,
      mainInert: false,
      mainHidden: null,
    });
  }, buildImplementationSnapshot());
});

test("implementation workspace renders syntax color and only the selected task explicit diagram", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    assert.ok(await page.locator("#implementation-code .syntax-keyword").count() >= 1);
    assert.ok(await page.locator("#implementation-code .syntax-string").count() >= 1);
    assert.deepEqual(
      await page.locator("#implementation-diagram-flow [data-diagram-node]").allTextContents(),
      ["contract test", "Viewer model", "実装UI"],
    );
    assert.deepEqual(
      await page.locator("#implementation-diagram-relations li").allTextContents(),
      ["contract test → 固定する → Viewer model", "Viewer model → 描画する → 実装UI"],
    );

    await page.locator('[data-implementation-task="2"]').click();
    assert.equal(await page.locator("#implementation-diagram-flow [data-diagram-node]").count(), 0);
    assert.match(await page.locator("#implementation-diagram-message").textContent(), /未記録.*明示された関係だけ/);
  }, buildImplementationSnapshot());
});

test("implementation workspace splits on desktop and stacks without page overflow on tablet and mobile", async (t) => {
  for (const viewport of [
    { width: 1440, height: 1000, columns: 2 },
    { width: 768, height: 900, columns: 1 },
    { width: 375, height: 812, columns: 1 },
  ]) {
    await withPage(t, viewport, async (page) => {
      await page.locator("#open-detail-drawer").click();
      await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
      await page.locator("#ui-preview-evidence-toggle").click();
      await page.waitForFunction(() => !document.querySelector("#ui-preview-evidence")?.hidden);
      const state = await page.locator("#implementation-workspace").evaluate((workspace) => {
        const code = document.querySelector("#implementation-code");
        return {
          columns: getComputedStyle(workspace).gridTemplateColumns.split(/\s+/).filter(Boolean).length,
          pageOverflow: document.documentElement.scrollWidth - innerWidth,
          tabOrientation: document.querySelector("#brief-flow")?.getAttribute("aria-orientation"),
          taskIndexHeight: document.querySelector("#brief-task-index")?.getBoundingClientRect().height,
          taskDetailTop: document.querySelector("#implementation-detail")?.getBoundingClientRect().top,
          taskIndexTop: document.querySelector("#brief-task-index")?.getBoundingClientRect().top,
          codeTabIndex: code?.getAttribute("tabindex"),
          codeOverflowX: code ? getComputedStyle(code).overflowX : "",
          codeHasOwnOverflow: Boolean(code && code.scrollWidth > code.clientWidth),
        };
      });

      assert.equal(state.columns, viewport.columns, `${viewport.width}px workspace column count`);
      assert.ok(state.pageOverflow <= 1, `${viewport.width}px has page overflow ${state.pageOverflow}px`);
      assert.equal(state.codeTabIndex, "0");
      assert.match(state.codeOverflowX, /^(auto|scroll)$/);
      assert.equal(state.codeHasOwnOverflow, true, `${viewport.width}px code should own horizontal scroll`);
      assert.equal(state.tabOrientation, viewport.width <= 900 ? "horizontal" : "vertical");
      if (viewport.width <= 900) {
        assert.ok(state.taskIndexHeight > 0, `${viewport.width}px task rail should render`);
        assert.ok(
          state.taskDetailTop <= state.taskIndexTop + state.taskIndexHeight + 40,
          `${viewport.width}px detail should follow the task rail`,
        );
      }

      await page.locator("#implementation-code").focus();
      assert.equal(await page.evaluate(() => document.activeElement?.id), "implementation-code");
      if (viewport.width <= 900) {
        await page.locator('[data-implementation-task="1"]').focus();
        await page.keyboard.press("ArrowRight");
        assert.equal(
          await page.evaluate(() => document.activeElement?.dataset.implementationTask),
          "2",
        );
      }
    }, buildImplementationSnapshot());
  }
});

test("live source refresh replaces resolved code with an explicit missing-anchor state", async (t) => {
  const initial = buildImplementationSnapshot();
  await withLivePage(t, { width: 1280, height: 900 }, async (page, setSnapshot) => {
    await page.waitForFunction(() => document.querySelector("#live-status-text")?.textContent === "Live");
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    await page.locator("#ui-preview-evidence-toggle").click();
    await page.waitForFunction(() => !document.querySelector("#ui-preview-evidence")?.hidden);
    assert.match(await page.locator("#implementation-code").textContent(), /boundedSourceLine/);
    await page.locator("#implementation-code").focus();

    const changed = structuredClone(initial);
    changed.fingerprint = "source-preview-v2";
    changed.sourcePreviews[0] = {
      ...changed.sourcePreviews[0],
      status: "anchor-missing",
      startLine: null,
      endLine: null,
      code: "",
      message: "anchor not found",
    };
    setSnapshot(changed);
    await page.evaluate(() => pollSnapshot(pollGeneration));

    assert.equal(await page.locator("#implementation-code .implementation-code-line").count(), 0);
    assert.doesNotMatch(await page.locator("#implementation-detail").textContent(), /boundedSourceLine/);
    assert.match(await page.locator("#implementation-detail").textContent(), /anchor not found/);
    assert.match(await page.locator("#implementation-source-message").textContent(), /anchor not found/);
    await page.waitForFunction(() => document.activeElement?.id === "brief-source-preview");
    assert.equal(await page.evaluate(() => document.activeElement?.id), "brief-source-preview");
    assert.match(await page.locator("#state-announcer").textContent(), /実コード.*anchor not found/);
  }, initial);
});

test("live UI preview refresh keeps drawer tab task evidence scroll and focus", async (t) => {
  const initial = buildImplementationSnapshot();
  await withLivePage(t, { width: 1280, height: 900 }, async (page, setSnapshot) => {
    await page.waitForFunction(() => document.querySelector("#live-status-text")?.textContent === "Live");
    await page.locator("#open-detail-drawer").click();
    await page.waitForFunction(() => !document.querySelector("#detail-drawer")?.hidden);
    await page.locator("#ui-preview-evidence-toggle").click();
    await page.waitForFunction(() => !document.querySelector("#ui-preview-evidence")?.hidden);
    await page.evaluate(() => {
      document.querySelector(".detail-drawer-body").scrollTop = 90;
      document.querySelector("#ui-preview-evidence-close").focus();
    });

    const changed = structuredClone(initial);
    changed.fingerprint = "ui-preview-v2";
    changed.uiPreviews[0] = {
      ...changed.uiPreviews[0],
      after: {
        ...changed.uiPreviews[0].after,
        items: changed.uiPreviews[0].after.items.map((item) => item.id === "diff"
          ? { ...item, label: "UI差分詳細" }
          : item),
      },
    };
    setSnapshot(changed);
    await page.evaluate(() => pollSnapshot(pollGeneration));

    const state = await page.evaluate(() => ({
      drawerOpen: !document.querySelector("#detail-drawer")?.hidden,
      activeTab: document.querySelector('[data-detail-tab][aria-selected="true"]')?.dataset.detailTab,
      selectedTask: document.querySelector('[data-implementation-task][aria-selected="true"]')?.dataset.implementationTask,
      evidenceOpen: !document.querySelector("#ui-preview-evidence")?.hidden,
      focused: document.activeElement?.id,
      scrollTop: document.querySelector(".detail-drawer-body")?.scrollTop || 0,
      previewText: document.querySelector("#brief-ui-preview")?.textContent || "",
      announcement: document.querySelector("#state-announcer")?.textContent || "",
    }));

    assert.equal(state.drawerOpen, true);
    assert.equal(state.activeTab, "change");
    assert.equal(state.selectedTask, "1");
    assert.equal(state.evidenceOpen, true);
    assert.equal(state.focused, "ui-preview-evidence-close");
    assert.ok(state.scrollTop >= 40, `scroll should be preserved, got ${state.scrollTop}`);
    assert.match(state.previewText, /UI差分詳細/);
    assert.match(state.announcement, /UI差分プレビューを更新/);
  }, initial);
});

test("live connection badge changes are exposed through the shared status region", async (t) => {
  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    await page.evaluate(() => {
      document.querySelector("#state-announcer").textContent = "";
      setLiveStatus("error", "接続喪失");
    });
    assert.match(await page.locator("#state-announcer").textContent(), /接続状態: 接続喪失/);
  });
});
