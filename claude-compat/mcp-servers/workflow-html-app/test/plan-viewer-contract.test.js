import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

function read(relativePath) {
  return readFileSync(join(root, relativePath), "utf8");
}

test("Plan Viewerはoutline・document・reviewの読解領域を持つべき", () => {
  const html = read("ui/plan-viewer.html");

  assert.match(html, /id="plan-outline"/);
  assert.match(html, /id="plan-document"/);
  assert.match(html, /id="plan-review"/);
});

test("Plan Viewerはsanitized見出しからoutlineを作りMarkdown checkboxから進捗を数えるべき", () => {
  const html = read("ui/plan-viewer.html");

  assert.match(html, /id="outline-list"/);
  assert.match(html, /id="progress-complete"/);
  assert.match(html, /id="progress-total"/);
  assert.match(html, /function enhancePlanDocument/);
  assert.match(html, /querySelectorAll\('h2, h3'\)/);
  assert.match(html, /function countPlanTasks/);
  assert.match(html, /\[ xX\]/);
});

test("Plan Viewerは三領域をresponsiveかつkeyboard visibleなlayoutで表示すべき", () => {
  const html = read("ui/plan-viewer.html");

  assert.match(html, /grid-template-columns:\s*minmax\(180px,\s*240px\)\s+minmax\(0,\s*760px\)\s+minmax\(220px,\s*300px\)/);
  assert.match(html, /@media\s*\(max-width:\s*1100px\)/);
  assert.match(html, /@media\s*\(max-width:\s*720px\)/);
  assert.match(html, /:focus-visible/);
  assert.match(html, /min-height:\s*44px/);
  assert.match(html, /prefers-reduced-motion:\s*reduce/);
  assert.match(html, /@media\s*\(hover:\s*hover\)\s*and\s*\(pointer:\s*fine\)/);
});

test("共用Document ViewerはMCP payloadのroute kindでPlan/Log/Verificationを識別すべき", () => {
  const html = read("ui/plan-viewer.html");

  assert.match(html, /import \{ App, PostMessageTransport \} from '@modelcontextprotocol\/ext-apps'/);
  assert.match(html, /function detectDocumentKind\(markdown, routeKind, options = \{\}\)/);
  assert.match(html, /structuredContent\?\.routeKind/);
  assert.match(html, /\[ROUTE_KIND_META_KEY\]/);
  assert.match(html, /allowHeadingFallback/);
  assert.match(html, /作業ログ\|ログ\|log/);
  assert.match(html, /検証ガイド\|検証\|verification/);
  assert.match(html, /実装計画\|計画\|plan/);
  assert.match(html, /commentPrefix: 'Log Comment'/);
  assert.match(html, /commentPrefix: 'Verification Comment'/);
  assert.match(html, /commentPrefix: 'Plan Comment'/);
  assert.match(html, /return DEFAULT_DOCUMENT_KIND/);
  assert.match(html, /name: 'Document Viewer'/);
  assert.match(html, /app\.onContentReceived = \(\{ text: markdown, routeKind \}\)/);
  assert.match(html, /applyDocumentKind\(markdown, routeKind\)/);
  assert.match(html, /progressLabel: '計画タスクの進捗'/);
  assert.match(html, /progressLabel: '検証チェックリストの進捗'/);
  assert.match(html, /getElementById\('progress-grid'\)\.setAttribute\('aria-label', activeDocumentKind\.progressLabel\)/);
  assert.match(html, /getElementById\('progress-meter'\)\.setAttribute\('aria-label', activeDocumentKind\.progressLabel\)/);
  assert.doesNotMatch(html, /aria-label="計画の完了率"/);
  assert.match(html, /DOMPurify\.sanitize/);
});
