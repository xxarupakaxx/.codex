import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  installVersionedBundle,
  readCurrentBundleDir,
} from "../scripts/copy-static-ui.mjs";

const root = fileURLToPath(new URL("..", import.meta.url));
const expectedFiles = [
  "plan-viewer.html",
  "diagram-viewer.html",
  "verification-viewer.html",
];

function makeBundle(dir, label) {
  for (const fileName of expectedFiles) {
    writeFileSync(join(dir, fileName), `${label}:${fileName}`, "utf8");
  }
}

test("versioned pointer publishはpointer rename前crashでprevious served bundleを保持する", () => {
  const distRoot = mkdtempSync(join(root, ".tmp-ui-test-dist-"));
  const oldBundle = mkdtempSync(join(root, ".tmp-ui-test-old-"));
  const newBundle = mkdtempSync(join(root, ".tmp-ui-test-new-"));

  try {
    makeBundle(oldBundle, "old");
    makeBundle(newBundle, "new");
    installVersionedBundle(oldBundle, {
      distRoot,
      version: "old-version",
    });
    const oldServedDir = readCurrentBundleDir(distRoot);

    assert.throws(
      () => installVersionedBundle(newBundle, {
        distRoot,
        version: "new-version",
        failBeforePointerRename: true,
      }),
      /simulated crash before pointer rename/,
    );

    assert.equal(readCurrentBundleDir(distRoot), oldServedDir);
    assert.equal(existsSync(join(distRoot, "ui-versions", "new-version")), true);
    for (const fileName of expectedFiles) {
      assert.equal(readFileSync(join(oldServedDir, fileName), "utf8"), `old:${fileName}`);
    }
  } finally {
    rmSync(distRoot, { recursive: true, force: true });
    rmSync(oldBundle, { recursive: true, force: true });
    rmSync(newBundle, { recursive: true, force: true });
  }
});
