import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const serverSource = readFileSync(new URL("../server.ts", import.meta.url), "utf8");

test("Plan Viewer routeの後方互換性を維持する", () => {
  assert.match(serverSource, /"view-plan"/);
  assert.match(serverSource, /resourceUri: PLAN_VIEWER_URI/);
  assert.match(serverSource, /const PLAN_VIEWER_URI = "ui:\/\/plan-viewer\/index\.html"/);
  assert.match(serverSource, /"plan-viewer-ui"/);
});

test("Log Viewerを独立toolとresource URIで公開する", () => {
  assert.match(serverSource, /"view-log"/);
  assert.match(serverSource, /resourceUri: LOG_VIEWER_URI/);
  assert.match(serverSource, /const LOG_VIEWER_URI = "ui:\/\/log-viewer\/index\.html"/);
  assert.match(serverSource, /"log-viewer-ui"/);
});

test("PlanとLogは同じsanitized document viewer bundleを共有する", () => {
  const matches = serverSource.match(/safeHtmlResource\(uri\.href, "plan-viewer\.html"/g) || [];
  assert.equal(matches.length, 2);
});

test("UI resource loaderはatomic pointerのversioned bundleをserve正本にする", () => {
  assert.match(serverSource, /ui-current\.json/);
  assert.match(serverSource, /ui-versions/);
  assert.match(serverSource, /currentBundleFile\(fileName\)/);
  assert.match(serverSource, /readFileSync\(currentBundleFile\(fileName\), "utf-8"\)/);
  assert.match(serverSource, /Verified UI bundle is unavailable/);
  assert.doesNotMatch(serverSource, /join\(__dirname, "ui"/);
  assert.doesNotMatch(serverSource, /<html><body><h1>/);
});

test("MCP App helperと標準MIME/resource metadataでUIを公開する", () => {
  assert.match(serverSource, /registerAppTool/);
  assert.match(serverSource, /registerAppResource/);
  assert.match(serverSource, /RESOURCE_MIME_TYPE/);
  assert.match(serverSource, /mimeType: RESOURCE_MIME_TYPE/);
  assert.match(serverSource, /_meta: resourceUiMeta/);
});

test("Plan/Log/Verification route identityはtool structured dataとmetadataで渡す", () => {
  assert.match(serverSource, /const ROUTE_KIND_META_KEY = "workflow-html-app\/routeKind"/);
  assert.match(serverSource, /structuredContent:\s*\{\s*routeKind,\s*\}/s);
  assert.match(serverSource, /\[ROUTE_KIND_META_KEY\]: routeKind/);
  assert.match(serverSource, /documentToolResult\(content, "plan"\)/);
  assert.match(serverSource, /documentToolResult\(content, "log"\)/);
  assert.match(serverSource, /documentToolResult\(content, "verification"\)/);
});
