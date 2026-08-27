import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const serverSource = readFileSync(new URL("../server.ts", import.meta.url), "utf8");

test("Plan Viewer routeの後方互換性を維持する", () => {
  assert.match(serverSource, /"view-plan"/);
  assert.match(serverSource, /resourceUri: "ui:\/\/plan-viewer\/index\.html"/);
  assert.match(serverSource, /"plan-viewer-ui"/);
});

test("Log Viewerを独立toolとresource URIで公開する", () => {
  assert.match(serverSource, /"view-log"/);
  assert.match(serverSource, /resourceUri: "ui:\/\/log-viewer\/index\.html"/);
  assert.match(serverSource, /"log-viewer-ui"/);
  assert.match(serverSource, /new ResourceTemplate\("ui:\/\/log-viewer\/\{path\}"/);
});

test("PlanとLogは同じsanitized document viewer bundleを共有する", () => {
  const matches = serverSource.match(/join\(__dirname, "ui", "plan-viewer\.html"\)/g) || [];
  assert.equal(matches.length, 2);
});
