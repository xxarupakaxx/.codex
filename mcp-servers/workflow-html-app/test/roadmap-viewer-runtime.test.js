import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const templatePath = fileURLToPath(new URL("../../../tools/roadmap_viewer.html", import.meta.url));
const graphMap = `# Concept Map

\`\`\`mermaid
flowchart TB
  G["理解できる計画"]
  F["snapshotに本文がある"]
  D{"brief-firstを採用"}
  A["実行計画"]
  V["browserで検証"]
  G -->|"必要とする"| D
  F -->|"判断材料にする"| D
  D -->|"生み出す"| A
  V -->|"検証する"| A
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

\`\`\`mermaid
flowchart LR
T["contract test"]
M["Viewer model"]
U["実装UI"]
T -->|"固定する"| M
M -->|"描画する"| U
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
  return snapshot;
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
    await page.waitForSelector("#brief-flow .brief-flow-item");
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
    await page.waitForSelector("#brief-flow .brief-flow-item");
    await callback(page, (nextSnapshot) => { snapshot = nextSnapshot; });
    await page.close();
  } finally {
    await browser?.close();
    await new Promise((resolve) => server.close(resolve));
    rmSync(fixture.directory, { recursive: true, force: true });
  }
}

test("first screen exposes the plan purpose roadmap design and selected task detail", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
    const state = await page.evaluate(() => ({
      executionVisible: document.querySelector("#execution-brief")?.getBoundingClientRect().height > 0,
      firstTask: document.querySelector("#brief-flow .brief-flow-item strong")?.textContent,
      planTitle: document.querySelector("#execution-brief-title")?.textContent,
      selectedTitle: document.querySelector("#implementation-task-title")?.textContent,
      selectedPurpose: document.querySelector("#implementation-task-purpose")?.textContent,
      context: document.querySelector("#brief-design-context")?.textContent,
      requirements: document.querySelector("#brief-requirements")?.textContent,
      decisions: document.querySelector("#brief-design-decisions")?.textContent,
      boundaries: document.querySelector("#brief-boundaries")?.textContent,
      selectedMetric: document.querySelector("#brief-current-status")?.textContent,
      claimHeadings: [...document.querySelectorAll("#brief-claims h4")].map((node) => node.textContent),
      artifacts: [...document.querySelectorAll("#brief-artifact-grid [data-artifact]")].map((node) => node.dataset.artifact),
      graphOpen: document.querySelector("#concept-map-disclosure")?.open,
    }));

    assert.equal(state.executionVisible, true);
    assert.equal(state.firstTask, "contractを固定する");
    assert.match(state.planTitle, /実行Task、仕様、実装根拠/);
    assert.equal(state.selectedTitle, "contractを固定する");
    assert.match(state.selectedPurpose, /第一画面の読解要件/);
    assert.match(state.context, /設計意図まで第一画面で理解/);
    assert.match(state.requirements, /Taskと仕様を同時に読める/);
    assert.match(state.decisions, /第一画面をbrief-firstにする/);
    assert.match(state.boundaries, /schema version 1を維持/);
    assert.match(state.selectedMetric, /1 \/ 2/);
    assert.deepEqual(state.claimHeadings, ["事実", "判断", "未確定"]);
    assert.deepEqual(state.artifacts, ["00_spec.md", "30_plan.md", "40_progress.md", "80_review.md"]);
    assert.equal(state.graphOpen, false);
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
        claimColumns: getComputedStyle(document.querySelector(".claim-grid")).gridTemplateColumns.split(" ").length,
        quickSpecInViewport: document.querySelector('#brief-quick-links [data-artifact="00_spec.md"]')?.getBoundingClientRect().bottom <= innerHeight,
      }));

      assert.ok(state.overflow <= 1, `${viewport.width}px has horizontal overflow ${state.overflow}px`);
      assert.ok(state.executionTop < state.conceptTop);
      assert.equal(state.quickSpecInViewport, true);
      if (viewport.width === 375) assert.equal(state.claimColumns, 1);
    });
  }
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

test("implementation workspace renders syntax color and only the selected task explicit diagram", async (t) => {
  await withPage(t, { width: 1440, height: 1000 }, async (page) => {
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

test("live connection badge changes are exposed through the shared status region", async (t) => {
  await withPage(t, { width: 1280, height: 900 }, async (page) => {
    await page.evaluate(() => {
      document.querySelector("#state-announcer").textContent = "";
      setLiveStatus("error", "接続喪失");
    });
    assert.match(await page.locator("#state-announcer").textContent(), /接続状態: 接続喪失/);
  });
});
