import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  installVersionedBundle,
  publish,
  readCurrentBundleDir,
  resolveSafeTempDir,
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

function cleanup(paths) {
  for (const path of paths) {
    rmSync(path, { recursive: true, force: true });
  }
}

function managedTempEntries() {
  return readdirSync(root)
    .filter((entry) => entry.startsWith(".tmp-ui-"))
    .sort();
}

function runBuildUi() {
  const env = { ...process.env };
  delete env.WORKFLOW_HTML_APP_UI_OUT_DIR;
  const child = spawn(process.execPath, ["scripts/copy-static-ui.mjs", "--build"], {
    cwd: root,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  return {
    pid: child.pid,
    result: new Promise((resolve) => {
      child.on("close", (code, signal) => {
        resolve({ code, signal, stdout, stderr });
      });
    }),
  };
}

test("WORKFLOW_HTML_APP_UI_OUT_DIRはpackage root配下のmanaged tempだけを許可する", () => {
  assert.match(resolveSafeTempDir(".tmp-ui-custom"), /\/\.tmp-ui-custom$/);
  assert.throws(() => resolveSafeTempDir("."), /child directory/);
  assert.throws(() => resolveSafeTempDir("ui"), /source or published UI/);
  assert.throws(() => resolveSafeTempDir("dist"), /source or published UI/);
  assert.throws(() => resolveSafeTempDir("../outside"), /child directory/);
  assert.throws(() => resolveSafeTempDir("scratch"), /\.tmp-ui-\*/);
});

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
    cleanup([distRoot, oldBundle, newBundle]);
  }
});

test("publishはversioned pointerだけを更新しdist/ui mirrorを作らない", () => {
  const distRoot = mkdtempSync(join(root, ".tmp-ui-test-dist-"));
  const sourceDir = mkdtempSync(join(root, ".tmp-ui-test-source-"));

  try {
    makeBundle(sourceDir, "new");
    const result = publish({
      sourceDir,
      distRoot,
      version: "pointer-only-version",
      skipVerification: true,
    });

    assert.equal(result.version, "pointer-only-version");
    assert.equal(readCurrentBundleDir(distRoot), join(distRoot, "ui-versions", "pointer-only-version"));
    assert.equal(existsSync(join(distRoot, "ui")), false);
  } finally {
    cleanup([distRoot, sourceDir]);
  }
});

test("parallel build:uiはrun固有stagingを使い互いのtempを削除しない", async () => {
  const before = new Set(managedTempEntries());
  const first = runBuildUi();
  const second = runBuildUi();
  const pids = [first.pid, second.pid].filter(Boolean).map(String);

  try {
    const results = await Promise.all([first.result, second.result]);
    for (const result of results) {
      assert.equal(result.code, 0, result.stderr || result.stdout);
      assert.equal(result.signal, null);
      assert.doesNotMatch(result.stderr, /ENOENT/);
      assert.doesNotMatch(result.stdout, /ENOENT/);
    }

    const after = managedTempEntries().filter((entry) => !before.has(entry));
    assert.deepEqual(after, []);
  } finally {
    const leftovers = managedTempEntries()
      .filter((entry) => !before.has(entry))
      .filter((entry) => pids.some((pid) => entry.includes(pid)));
    cleanup(leftovers.map((entry) => join(root, entry)));
  }
});
