import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { spawnSync } from "node:child_process";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const scriptsRoot = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(scriptsRoot, "..");
const repoRoot = resolve(packageRoot, "..", "..", "..");
const defaultDistRoot = join(packageRoot, "dist");
const stagingDir = process.env.WORKFLOW_HTML_APP_UI_OUT_DIR
  ? resolveSafeTempDir(process.env.WORKFLOW_HTML_APP_UI_OUT_DIR, "WORKFLOW_HTML_APP_UI_OUT_DIR")
  : uniqueManagedPath("build");
const publishLockDir = resolveSafeTempDir(".tmp-ui-publish-lock", "publish lock directory");
const versionRootName = "ui-versions";
const pointerFileName = "ui-current.json";
const expectedFiles = [
  "plan-viewer.html",
  "diagram-viewer.html",
  "verification-viewer.html",
];

function packageRelative(path) {
  return relative(packageRoot, path).split(sep).join("/");
}

export function resolveSafeTempDir(candidate, label = "temporary directory") {
  const resolved = resolve(packageRoot, candidate);
  const relativePath = packageRelative(resolved);
  if (!relativePath || relativePath === "." || relativePath.startsWith("../") || isAbsolute(relativePath)) {
    throw new Error(`${label} must resolve to a child directory under ${packageRoot}`);
  }
  if (relativePath === "ui" || relativePath.startsWith("ui/")
    || relativePath === "dist" || relativePath.startsWith("dist/")) {
    throw new Error(`${label} must not target source or published UI directories: ${relativePath}`);
  }
  const lastSegment = relativePath.split("/").at(-1) || "";
  if (!lastSegment.startsWith(".tmp-ui-")) {
    throw new Error(`${label} must be a managed temp directory named .tmp-ui-*`);
  }
  return resolved;
}

function assertManagedTempDir(path) {
  const resolved = resolve(path);
  const relativePath = packageRelative(resolved);
  if (!relativePath || relativePath === "." || relativePath.startsWith("../") || isAbsolute(relativePath)) {
    throw new Error(`managed temp directory must stay under ${packageRoot}`);
  }
  if (!basename(resolved).startsWith(".tmp-ui-")) {
    throw new Error("managed temp directory must be named .tmp-ui-*");
  }
  return resolved;
}

function removeManagedTempDir(path) {
  rmSync(assertManagedTempDir(path), { recursive: true, force: true });
}

function uniqueManagedPath(kind) {
  return resolveSafeTempDir(
    `.tmp-ui-${kind}-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    `${kind} directory`,
  );
}

function waitForLockRetry(milliseconds) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, milliseconds);
}

function acquirePublishLock(timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (true) {
    try {
      mkdirSync(publishLockDir);
      return () => removeManagedTempDir(publishLockDir);
    } catch (error) {
      if (error?.code !== "EEXIST") {
        throw error;
      }
      if (Date.now() >= deadline) {
        throw new Error(`timed out waiting for publish lock: ${publishLockDir}`);
      }
      waitForLockRetry(50);
    }
  }
}

export function prepareStaging(dir = stagingDir) {
  removeManagedTempDir(dir);
  mkdirSync(dir, { recursive: true });
}

function ensureFile(path, label) {
  if (!existsSync(path)) {
    throw new Error(`${label} missing: ${path}`);
  }
}

function ensureExpectedBundle(dir) {
  for (const fileName of expectedFiles) {
    ensureFile(join(dir, fileName), fileName);
  }
}

function validateVersion(version) {
  if (typeof version !== "string" || !/^[A-Za-z0-9._-]+$/.test(version)) {
    throw new Error(`invalid UI bundle version: ${version}`);
  }
  return version;
}

function distRoot(candidate = defaultDistRoot) {
  const resolved = resolve(packageRoot, candidate);
  const relativePath = packageRelative(resolved);
  if (!relativePath || relativePath === "." || relativePath.startsWith("../") || isAbsolute(relativePath)) {
    throw new Error(`dist root must stay under ${packageRoot}`);
  }
  if (relativePath === "ui" || relativePath.startsWith("ui/")) {
    throw new Error(`dist root must not target source UI: ${relativePath}`);
  }
  return resolved;
}

function distChild(root, childPath, label) {
  const resolvedRoot = distRoot(root);
  const resolved = resolve(resolvedRoot, childPath);
  const relativePath = relative(resolvedRoot, resolved).split(sep).join("/");
  if (!relativePath || relativePath === "." || relativePath.startsWith("../") || isAbsolute(relativePath)) {
    throw new Error(`${label} must stay under ${resolvedRoot}`);
  }
  return resolved;
}

function versionRoot(root = defaultDistRoot) {
  return distChild(root, versionRootName, "versioned UI root");
}

function pointerPath(root = defaultDistRoot) {
  return distChild(root, pointerFileName, "UI pointer");
}

function versionDir(root, version) {
  return distChild(versionRoot(root), validateVersion(version), "UI bundle version directory");
}

function newVersion() {
  return `${Date.now()}-${process.pid}-${Math.random().toString(36).slice(2)}`;
}

function copyExpectedFiles(sourceDir, targetDir) {
  mkdirSync(targetDir, { recursive: true });
  for (const fileName of expectedFiles) {
    copyFileSync(join(sourceDir, fileName), join(targetDir, fileName));
  }
}

export function syncVerificationAlias(dir) {
  ensureFile(join(dir, "plan-viewer.html"), "Plan viewer bundle");
  copyFileSync(join(dir, "plan-viewer.html"), join(dir, "verification-viewer.html"));
}

function runChecked(command, args, options, label) {
  const result = spawnSync(command, args, options);
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${label} failed with exit code ${result.status}`);
  }
}

export function runSharedSurfaceContract() {
  runChecked(
    "python3",
    [join(repoRoot, "scripts", "verify-html-surfaces.py")],
    { cwd: repoRoot, stdio: "inherit" },
    "shared HTML surface contract",
  );
}

export function verifyBundle(dir = stagingDir) {
  runSharedSurfaceContract();
  runChecked(
    process.execPath,
    [join(scriptsRoot, "verify-html-artifacts.mjs"), "--input-dir", dir],
    { cwd: packageRoot, stdio: "inherit" },
    "HTML artifact verification",
  );
}

export function runVite(entry, keepOutput, dir = stagingDir) {
  const viteBin = join(
    packageRoot,
    "node_modules",
    ".bin",
    process.platform === "win32" ? "vite.cmd" : "vite",
  );
  runChecked(
    viteBin,
    ["build"],
    {
      cwd: packageRoot,
      env: {
        ...process.env,
        WORKFLOW_HTML_APP_ENTRY: entry,
        WORKFLOW_HTML_APP_KEEP_OUT_DIR: keepOutput ? "1" : "0",
        WORKFLOW_HTML_APP_UI_OUT_DIR: dir,
      },
      stdio: "inherit",
    },
    `Vite build for ${entry}`,
  );
}

export function readCurrentBundleDir(root = defaultDistRoot) {
  const pointer = JSON.parse(readFileSync(pointerPath(root), "utf8"));
  const currentDir = versionDir(root, pointer.version);
  ensureExpectedBundle(currentDir);
  return currentDir;
}

export function installVersionedBundle(sourceDir, options = {}) {
  const root = distRoot(options.distRoot || defaultDistRoot);
  const version = validateVersion(options.version || newVersion());
  const targetDir = versionDir(root, version);
  if (existsSync(targetDir)) {
    throw new Error(`UI bundle version already exists: ${version}`);
  }

  mkdirSync(versionRoot(root), { recursive: true });
  renameSync(sourceDir, targetDir);

  const pointerTempPath = distChild(
    root,
    `.tmp-ui-pointer-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}.json`,
    "UI pointer temp",
  );
  const payload = {
    version,
    files: expectedFiles,
    createdAt: new Date().toISOString(),
  };
  writeFileSync(pointerTempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  if (options.failBeforePointerRename) {
    throw new Error("simulated crash before pointer rename");
  }
  renameSync(pointerTempPath, pointerPath(root));
  return { version, versionDir: targetDir, pointerPath: pointerPath(root) };
}

export function publish(options = {}) {
  const sourceDir = options.sourceDir || stagingDir;
  syncVerificationAlias(sourceDir);
  ensureExpectedBundle(sourceDir);
  if (!options.skipVerification) {
    verifyBundle(sourceDir);
  }
  let bundleStage = uniqueManagedPath("bundle");
  let releasePublishLock;
  try {
    copyExpectedFiles(sourceDir, bundleStage);
    ensureExpectedBundle(bundleStage);
    releasePublishLock = acquirePublishLock();
    const result = installVersionedBundle(bundleStage, options);
    bundleStage = undefined;
    return result;
  } finally {
    if (releasePublishLock) {
      releasePublishLock();
    }
    if (bundleStage) {
      removeManagedTempDir(bundleStage);
    }
    if (options.cleanupSource) {
      removeManagedTempDir(sourceDir);
    }
  }
}

export function build() {
  prepareStaging();
  runVite("plan-viewer", false);
  runVite("diagram-viewer", true);
  publish({ sourceDir: stagingDir, cleanupSource: true });
}

export function main(argv = process.argv.slice(2)) {
  const mode = argv[0] || "--publish";
  if (mode === "--build") {
    build();
  } else if (mode === "--publish") {
    publish();
  } else if (mode === "--list") {
    const files = existsSync(readCurrentBundleDir()) ? readdirSync(readCurrentBundleDir()).sort() : [];
    for (const fileName of files) {
      console.log(fileName);
    }
  } else {
    throw new Error(`unknown mode: ${mode}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
