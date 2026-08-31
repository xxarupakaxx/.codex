#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { TextDecoder } from 'node:util';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKSPACE_ROOT = path.resolve(HERE, '..');
const SOURCE_CONFIG_PATH = path.join(WORKSPACE_ROOT, 'config', 'archify-source.json');
const PACKAGE_ROOT = path.join(WORKSPACE_ROOT, 'skills', 'archify');
const FIXED_CLI = path.join(PACKAGE_ROOT, 'bin', 'archify.mjs');
const PACKAGE_JSON = path.join(WORKSPACE_ROOT, 'mcp-servers', 'workflow-html-app', 'package.json');
const EXPECTED_NODE_EXECUTABLE = '/usr/bin/node';
const EXPECTED_NODE_VERSION = 'v24.17.0';
const EXPECTED_NODE_SHA256 = '4adeeca28663521e926659041cf26dbe5bded9d104316373c364a8b65ed17f03';
const EXPECTED_CHROME_EXECUTABLE = '/ms-playwright/chromium-1228/chrome-linux/chrome';
const EXPECTED_CHROME_VERSION = '149.0.7827.0';
const EXPECTED_CHROME_SHA256 = 'c1aa0fb5b6c60eb093df69d9e40dd50ab2039d3ccba8836ef21880340a77af64';
const EXPECTED_BASE_IMAGE = 'mcr.microsoft.com/playwright@sha256:824f1a789072e648c62541c2cfa4479c4061a290d5c27766d67dc1dcbc19b321';
const EXPECTED_SECCOMP_SHA256 = '05e4588202a0950e17465aff9831b04f6e196dcd5b31941515a6db4d0a3ee45d';
const EXPECTED_PLAYWRIGHT_VERSION = '1.61.1';
const EXPECTED_PLAYWRIGHT_LOCK_SHA256 = 'f39a5523505682275900e15483f080e04537917107686743f047edfe5b8a3ba3';
const EXPECTED_PLAYWRIGHT_PACKAGE_SHA256 = '6b840268612656f0639fb7d68782e8353bdf11518589d30ddf66f283c2670ed5';
const EXPECTED_PLAYWRIGHT_CORE_SHA256 = '759e376f995bf39edd4810d699b99469bab1d7428b6fbc78d41912f367df7ba9';
const SANDBOX_MARKER = 'ARCHIFY_REVIEW_SANDBOX';
const SANDBOX_POLICY_ID = 'archify-plan-container-v1';
const SANDBOX_PROFILE_HASH_MARKER = 'ARCHIFY_REVIEW_SANDBOX_PROFILE_SHA256';
const CONTAINER_IMAGE_MARKER = 'ARCHIFY_CONTAINER_IMAGE';
const BROWSER_TMPDIR = '/tmp/browser';
const ENTRYPOINT_PATH = path.join(HERE, 'archify_container.mjs');

// This digest covers the fixed revision, executable paths, and all 190 manifest
// entries. A changed config is a review-stage integrity failure.
const EXPECTED_CONFIG_SHA256 = '8f3b1e38ff92ed0a589169686322123d676837fb9ce0716a27ebf28087e04810';
const EXPECTED_REVISION = '5de7275fe87a66a19d52a4d9b0b3a4f2a5a90115';
const LIMITS = Object.freeze({
  inputBytes: 1024 * 1024,
  htmlBytes: 8 * 1024 * 1024,
  svgBytes: 4 * 1024 * 1024,
  streamBytes: 512 * 1024,
  timeoutMs: 60_000,
  stepMs: 30_000,
  exportMs: 15_000,
  maxDepth: 32,
  maxTokens: 50_000,
});
const FORBIDDEN_KEYS = new Set([
  'brand', 'repository', 'source', 'sources', 'evidence', 'url', 'urls', 'href',
  'src', 'xlink:href', 'output', 'command', 'argv', 'env', 'executable', 'path',
  '__proto__', 'prototype', 'constructor',
]);
const ID_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;
const TYPE_VALUES = new Set(['frontend', 'backend', 'database', 'cloud', 'security', 'messagebus', 'external']);
const VARIANT_VALUES = new Set(['default', 'emphasis', 'security', 'dashed']);
const SIDE_VALUES = new Set(['left', 'right', 'top', 'bottom']);

export class BridgeError extends Error {
  constructor(code, message, phase = 'prepare') {
    super(message);
    this.name = 'BridgeError';
    this.code = code;
    this.phase = phase;
  }
}

const reject = (code, message, phase) => { throw new BridgeError(code, message, phase); };
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const safeMessage = (error) => String(error?.message || error).replace(/[\r\n]+/g, ' ').slice(0, 240);
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const own = (value, key) => value !== null && value !== undefined && Object.prototype.hasOwnProperty.call(value, key);

const THEME_ICON_RULE_HASHES = new Map([
  ['b984068804a5f904ab7e210293a29d0744457034ac1ff63baf4f96ef35188092', 'light'],
  ['32bf193b027458e157518fb73b3755b1fcd2a0ca71e849c9580d057f8207c53f', 'dark'],
]);

function parseJsonShape(text) {
  let index = 0;
  let tokens = 0;
  const whitespace = () => { while (/\s/.test(text[index] || '')) index += 1; };
  const token = () => {
    tokens += 1;
    if (tokens > LIMITS.maxTokens) reject('invalidInput', 'JSON token limit exceeded.', 'input');
  };
  const string = () => {
    const start = index;
    if (text[index++] !== '"') reject('invalidInput', 'Invalid JSON string.', 'input');
    let escaped = false;
    while (index < text.length) {
      const char = text[index++];
      if (escaped) { escaped = false; continue; }
      if (char === '\\') { escaped = true; continue; }
      if (char === '"') {
        try { return JSON.parse(text.slice(start, index)); } catch { reject('invalidInput', 'Invalid JSON string.', 'input'); }
      }
      if (char < ' ') reject('invalidInput', 'Control character in JSON string.', 'input');
    }
    reject('invalidInput', 'Unterminated JSON string.', 'input');
  };
  const value = (depth) => {
    whitespace();
    if (depth > LIMITS.maxDepth) reject('invalidInput', 'JSON nesting limit exceeded.', 'input');
    token();
    const char = text[index];
    if (char === '"') { string(); return; }
    if (char === '{') {
      index += 1; whitespace(); const keys = new Set();
      if (text[index] === '}') { index += 1; return; }
      while (index < text.length) {
        whitespace();
        if (text[index] !== '"') reject('invalidInput', 'JSON object key expected.', 'input');
        const key = string(); token();
        if (keys.has(key)) reject('invalidInput', `Duplicate JSON key: ${key}.`, 'input');
        keys.add(key); whitespace();
        if (text[index++] !== ':') reject('invalidInput', 'JSON colon expected.', 'input');
        value(depth + 1); whitespace();
        if (text[index] === '}') { index += 1; return; }
        if (text[index++] !== ',') reject('invalidInput', 'JSON comma expected.', 'input');
      }
      reject('invalidInput', 'Unterminated JSON object.', 'input');
    }
    if (char === '[') {
      index += 1; whitespace();
      if (text[index] === ']') { index += 1; return; }
      while (index < text.length) {
        value(depth + 1); whitespace();
        if (text[index] === ']') { index += 1; return; }
        if (text[index++] !== ',') reject('invalidInput', 'JSON comma expected.', 'input');
      }
      reject('invalidInput', 'Unterminated JSON array.', 'input');
    }
    if (text.startsWith('true', index)) { index += 4; return; }
    if (text.startsWith('false', index)) { index += 5; return; }
    if (text.startsWith('null', index)) { index += 4; return; }
    const number = text.slice(index).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (number) { index += number[0].length; return; }
    reject('invalidInput', 'Invalid JSON value.', 'input');
  };
  value(0); whitespace();
  if (index !== text.length) reject('invalidInput', 'Trailing JSON data.', 'input');
}

export function parseWorkflowJson(buffer) {
  if (!Buffer.isBuffer(buffer)) buffer = Buffer.from(buffer);
  if (buffer.byteLength > LIMITS.inputBytes) reject('invalidInput', 'Specification exceeds 1 MiB.', 'input');
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(buffer); }
  catch { reject('invalidInput', 'Specification is not valid UTF-8.', 'input'); }
  parseJsonShape(text);
  try { return JSON.parse(text); }
  catch { reject('invalidInput', 'Specification JSON could not be parsed.', 'input'); }
}

function fields(object, allowed, name) {
  if (!isRecord(object)) reject('invalidInput', `${name} must be an object.`, 'input');
  for (const key of Object.keys(object)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) reject('invalidInput', `${name}.${key} is prohibited.`, 'input');
    if (!allowed.has(key)) reject('invalidInput', `${name}.${key} is not allowlisted.`, 'input');
  }
}
function textValue(value, name, { min = 0, max = 512 } = {}) {
  const points = typeof value === 'string' ? [...value] : [];
  if (typeof value !== 'string' || points.length < min || points.length > max || points.some((point) => point.length === 1 && point.charCodeAt(0) >= 0xd800 && point.charCodeAt(0) <= 0xdfff) || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value)) {
    reject('invalidInput', `${name} must be a bounded text value.`, 'input');
  }
}
function idValue(value, name) {
  textValue(value, name, { min: 1, max: 128 });
  if (!ID_RE.test(value)) reject('invalidInput', `${name} is not a safe identifier.`, 'input');
}
function finiteNumber(value, name, { integer = false, min, max } = {}) {
  if (typeof value !== 'number' || !Number.isFinite(value) || (integer && !Number.isInteger(value))) reject('invalidInput', `${name} must be finite.`, 'input');
  if (min !== undefined && value < min) reject('invalidInput', `${name} is below its minimum.`, 'input');
  if (max !== undefined && value > max) reject('invalidInput', `${name} is above its maximum.`, 'input');
}
function optionalNumber(object, key, name, options) { if (own(object, key)) finiteNumber(object[key], `${name}.${key}`, options); }
function boundedArray(value, name, max, min = 0) {
  if (!Array.isArray(value) || value.length < min || value.length > max) reject('invalidInput', `${name} has an invalid element count.`, 'input');
}
function point(value, name) {
  boundedArray(value, name, 2, 2); finiteNumber(value[0], `${name}[0]`); finiteNumber(value[1], `${name}[1]`);
}
function listOfIds(value, name, max = 256, min = 0) {
  boundedArray(value, name, max, min); value.forEach((item, i) => idValue(item, `${name}[${i}]`));
}

function validateMeta(meta) {
  fields(meta, new Set(['title', 'locale', 'subtitle', 'animation', 'visual_preset', 'quality_profile', 'views', 'legend', 'viewBox']), 'meta');
  if (!own(meta, 'title')) reject('invalidInput', 'meta.title is required.', 'input');
  textValue(meta.title, 'meta.title', { min: 1 });
  if (own(meta, 'locale') && !new Set(['en', 'zh-CN']).has(meta.locale)) reject('invalidInput', 'meta.locale is invalid.', 'input');
  if (own(meta, 'subtitle')) textValue(meta.subtitle, 'meta.subtitle');
  if (own(meta, 'animation') && meta.animation !== 'none') reject('invalidInput', 'Only animation=none is permitted.', 'input');
  if (own(meta, 'visual_preset') && !new Set(['classic', 'signal-flow', 'blueprint', 'editorial']).has(meta.visual_preset)) reject('invalidInput', 'meta.visual_preset is invalid.', 'input');
  if (own(meta, 'quality_profile') && meta.quality_profile !== 'standard') reject('invalidInput', 'Only quality_profile=standard is permitted.', 'input');
  if (own(meta, 'viewBox')) { boundedArray(meta.viewBox, 'meta.viewBox', 2, 2); finiteNumber(meta.viewBox[0], 'meta.viewBox[0]', { min: 700 }); finiteNumber(meta.viewBox[1], 'meta.viewBox[1]', { min: 240 }); }
  if (own(meta, 'views')) {
    boundedArray(meta.views, 'meta.views', 5);
    meta.views.forEach((view, i) => {
      fields(view, new Set(['id', 'label', 'focus', 'note']), `meta.views[${i}]`);
      for (const key of ['id']) if (!own(view, key)) reject('invalidInput', `meta.views[${i}].${key} is required.`, 'input');
      idValue(view.id, `meta.views[${i}].id`); textValue(view.label, `meta.views[${i}].label`, { min: 1, max: 48 }); listOfIds(view.focus, `meta.views[${i}].focus`, 128, 1);
      if (own(view, 'note')) textValue(view.note, `meta.views[${i}].note`, { max: 140 });
    });
  }
  if (own(meta, 'legend')) {
    fields(meta.legend, new Set(['mode', 'entries']), 'meta.legend');
    if (own(meta.legend, 'mode') && !new Set(['auto', 'all', 'hidden']).has(meta.legend.mode)) reject('invalidInput', 'meta.legend.mode is invalid.', 'input');
    if (own(meta.legend, 'entries')) {
      const kinds = new Set(['frontend', 'backend', 'database', 'cloud', 'security', 'messagebus', 'external']); fields(meta.legend.entries, kinds, 'meta.legend.entries');
      for (const key of Object.keys(meta.legend.entries)) { const entry = meta.legend.entries[key]; fields(entry, new Set(['label', 'visible']), `meta.legend.entries.${key}`); if (own(entry, 'label')) textValue(entry.label, `meta.legend.entries.${key}.label`, { min: 1 }); if (own(entry, 'visible') && typeof entry.visible !== 'boolean') reject('invalidInput', 'legend.visible must be boolean.', 'input'); }
    }
  }
}

function validateWorkflowObject(workflow) {
  fields(workflow, new Set(['schema_version', 'diagram_type', 'meta', 'lanes', 'phases', 'groups', 'mainPath', 'semanticChecks', 'nodes', 'edges', 'cards']), 'workflow');
  if (![1, 2].includes(workflow.schema_version) || workflow.diagram_type !== 'workflow') reject('invalidInput', 'Only workflow schema version 1 or 2 is permitted.', 'input');
  validateMeta(workflow.meta);
  boundedArray(workflow.lanes, 'lanes', 32, 1);
  workflow.lanes.forEach((lane, i) => { fields(lane, new Set(['id', 'label', 'variant']), `lanes[${i}]`); if (!own(lane, 'id') || !own(lane, 'label')) reject('invalidInput', `lanes[${i}] requires id and label.`, 'input'); idValue(lane.id, `lanes[${i}].id`); textValue(lane.label, `lanes[${i}].label`, { min: 1 }); if (own(lane, 'variant') && !new Set(['normal', 'exception']).has(lane.variant)) reject('invalidInput', 'lane.variant is invalid.', 'input'); });
  if (own(workflow, 'phases')) { boundedArray(workflow.phases, 'phases', 32); workflow.phases.forEach((item, i) => { fields(item, new Set(['id', 'label', 'fromCol', 'toCol', 'variant']), `phases[${i}]`); idValue(item.id, `phases[${i}].id`); textValue(item.label, `phases[${i}].label`, { min: 1 }); finiteNumber(item.fromCol, `phases[${i}].fromCol`, { integer: true, min: 0, max: 5 }); finiteNumber(item.toCol, `phases[${i}].toCol`, { integer: true, min: 0, max: 5 }); }); }
  if (own(workflow, 'groups')) { boundedArray(workflow.groups, 'groups', 32); workflow.groups.forEach((item, i) => { fields(item, new Set(['id', 'label', 'lane', 'fromCol', 'toCol', 'variant']), `groups[${i}]`); idValue(item.id, `groups[${i}].id`); textValue(item.label, `groups[${i}].label`, { min: 1 }); idValue(item.lane, `groups[${i}].lane`); finiteNumber(item.fromCol, `groups[${i}].fromCol`, { integer: true, min: 0, max: 5 }); finiteNumber(item.toCol, `groups[${i}].toCol`, { integer: true, min: 0, max: 5 }); }); }
  if (own(workflow, 'mainPath')) listOfIds(workflow.mainPath, 'mainPath', 256, 2);
  if (own(workflow, 'nodes')) {
    boundedArray(workflow.nodes, 'nodes', 128, 1);
    workflow.nodes.forEach((node, i) => { fields(node, new Set(['id', 'lane', 'col', 'type', 'label', 'sublabel', 'tag', 'width', 'height', 'yOffset']), `nodes[${i}]`); for (const key of ['id', 'lane', 'type', 'label', 'col']) if (!own(node, key)) reject('invalidInput', `nodes[${i}].${key} is required.`, 'input'); idValue(node.id, `nodes[${i}].id`); idValue(node.lane, `nodes[${i}].lane`); finiteNumber(node.col, `nodes[${i}].col`, { integer: true, min: 0, max: 5 }); if (!TYPE_VALUES.has(node.type)) reject('invalidInput', `nodes[${i}].type is invalid.`, 'input'); textValue(node.label, `nodes[${i}].label`, { min: 1 }); for (const key of ['sublabel', 'tag']) if (own(node, key)) textValue(node[key], `nodes[${i}].${key}`); optionalNumber(node, 'width', `nodes[${i}]`, { min: 32 }); optionalNumber(node, 'height', `nodes[${i}]`, { min: 32 }); optionalNumber(node, 'yOffset', `nodes[${i}]`); });
  } else reject('invalidInput', 'nodes is required.', 'input');
  if (own(workflow, 'edges')) {
    boundedArray(workflow.edges, 'edges', 256);
    workflow.edges.forEach((edge, i) => { fields(edge, new Set(['id', 'from', 'to', 'label', 'variant', 'role', 'fromSide', 'toSide', 'route', 'via', 'labelAt', 'labelDx', 'labelDy', 'labelSegment', 'channelX', 'channelY', 'bias', 'width']), `edges[${i}]`); for (const key of ['from', 'to']) if (!own(edge, key)) reject('invalidInput', `edges[${i}].${key} is required.`, 'input'); for (const key of ['id', 'from', 'to']) if (own(edge, key)) idValue(edge[key], `edges[${i}].${key}`); if (own(edge, 'label')) textValue(edge.label, `edges[${i}].label`); if (own(edge, 'variant') && !VARIANT_VALUES.has(edge.variant)) reject('invalidInput', 'edge.variant is invalid.', 'input'); if (own(edge, 'role') && !new Set(['main', 'branch', 'async', 'return', 'error']).has(edge.role)) reject('invalidInput', 'edge.role is invalid.', 'input'); for (const key of ['fromSide', 'toSide']) if (own(edge, key) && !SIDE_VALUES.has(edge[key])) reject('invalidInput', `edge.${key} is invalid.`, 'input'); if (own(edge, 'route') && !new Set(['auto', 'straight', 'drop', 'outside-right', 'return-left', 'bottom-channel', 'up-channel']).has(edge.route)) reject('invalidInput', 'edge.route is invalid.', 'input'); if (own(edge, 'via')) { boundedArray(edge.via, `edges[${i}].via`, 16); edge.via.forEach((item, j) => point(item, `edges[${i}].via[${j}]`)); } if (own(edge, 'labelAt')) point(edge.labelAt, `edges[${i}].labelAt`); optionalNumber(edge, 'labelDx', `edges[${i}]`); optionalNumber(edge, 'labelDy', `edges[${i}]`); optionalNumber(edge, 'labelSegment', `edges[${i}]`, { integer: true, min: 0 }); optionalNumber(edge, 'channelX', `edges[${i}]`); optionalNumber(edge, 'channelY', `edges[${i}]`); optionalNumber(edge, 'bias', `edges[${i}]`, { min: 0, max: 1 }); optionalNumber(edge, 'width', `edges[${i}]`, { min: 0.5 }); });
  } else reject('invalidInput', 'edges is required.', 'input');
  if (own(workflow, 'semanticChecks')) { fields(workflow.semanticChecks, new Set(['allowedRoots', 'allowedTerminals', 'requiredEdges', 'requiredPaths']), 'semanticChecks'); for (const key of ['allowedRoots', 'allowedTerminals']) if (own(workflow.semanticChecks, key)) listOfIds(workflow.semanticChecks[key], `semanticChecks.${key}`); for (const key of ['requiredEdges', 'requiredPaths']) if (own(workflow.semanticChecks, key)) { boundedArray(workflow.semanticChecks[key], `semanticChecks.${key}`, 256); workflow.semanticChecks[key].forEach((item, i) => { fields(item, new Set(['from', 'to']), `semanticChecks.${key}[${i}]`); idValue(item.from, `semanticChecks.${key}[${i}].from`); idValue(item.to, `semanticChecks.${key}[${i}].to`); }); } }
  if (own(workflow, 'cards')) { boundedArray(workflow.cards, 'cards', 16); workflow.cards.forEach((card, i) => { fields(card, new Set(['dot', 'title', 'items']), `cards[${i}]`); if (!new Set(['cyan', 'emerald', 'violet', 'amber', 'rose', 'orange', 'slate']).has(card.dot)) reject('invalidInput', 'card.dot is invalid.', 'input'); textValue(card.title, `cards[${i}].title`, { min: 1 }); boundedArray(card.items, `cards[${i}].items`, 32); card.items.forEach((item, j) => textValue(item, `cards[${i}].items[${j}]`)); }); }
  return workflow;
}

export function validateWorkflowInput(value) { return validateWorkflowObject(value); }

function modeBits(mode) {
  if (typeof mode !== 'string' || !/^0o[0-7]+$/.test(mode)) reject('sourceTamper', 'Source manifest mode is invalid.', 'source');
  return Number.parseInt(mode.slice(2), 8);
}
function fixedPath(value, expected, name) {
  if (value !== expected) reject('sourceTamper', `${name} is not the fixed review executable.`, 'source');
}

function requireSandboxAttestation() {
  const policy = process.env[SANDBOX_MARKER];
  const profileSha256 = process.env[SANDBOX_PROFILE_HASH_MARKER];
  const image = process.env[CONTAINER_IMAGE_MARKER];
  if (policy !== SANDBOX_POLICY_ID || profileSha256 !== EXPECTED_SECCOMP_SHA256 || typeof image !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(image)) {
    reject('sandboxRequired', 'This bridge must be launched by the reviewed container launcher.', 'prepare');
  }
  return { policy, profileSha256, image };
}

function fixedFileDigest(file, label, executable = false) {
  let stat;
  try {
    stat = fs.lstatSync(file);
    if (stat.isSymbolicLink() || !stat.isFile() || stat.nlink !== 1 || fs.realpathSync.native(file) !== path.resolve(file)) throw new Error('not a fixed regular file');
    if (executable) fs.accessSync(file, fs.constants.X_OK);
  } catch (error) {
    reject('sourceTamper', `${label} is unavailable: ${safeMessage(error)}.`, 'runtime');
  }
  let descriptor;
  try {
    descriptor = fs.openSync(file, 'r');
    const digest = createHash('sha256'); const chunk = Buffer.allocUnsafe(1024 * 1024); let bytes = 0;
    for (;;) { const count = fs.readSync(descriptor, chunk, 0, chunk.length, null); if (count === 0) break; bytes += count; digest.update(chunk.subarray(0, count)); }
    return { sha256: digest.digest('hex'), bytes, mode: stat.mode & 0o7777 };
  } catch (error) {
    reject('sourceTamper', `${label} could not be hashed: ${safeMessage(error)}.`, 'runtime');
  } finally { try { if (descriptor !== undefined) fs.closeSync(descriptor); } catch {} }
}

function collectRuntime(sandbox, config) {
  fixedPath(config.nodeExecutable, EXPECTED_NODE_EXECUTABLE, 'Node');
  fixedPath(config.chromeExecutable, EXPECTED_CHROME_EXECUTABLE, 'Chrome');
  if (path.resolve(process.execPath) !== EXPECTED_NODE_EXECUTABLE || process.version !== EXPECTED_NODE_VERSION) reject('sourceTamper', 'Running Node runtime is not the fixed container binary.', 'runtime');
  const bridge = fixedFileDigest(fileURLToPath(import.meta.url), 'bridge');
  const entrypoint = fixedFileDigest(ENTRYPOINT_PATH, 'container entrypoint');
  const node = fixedFileDigest(config.nodeExecutable, 'Node', true);
  const chrome = fixedFileDigest(config.chromeExecutable, 'Chrome', true);
  if (node.sha256 !== EXPECTED_NODE_SHA256 || chrome.sha256 !== EXPECTED_CHROME_SHA256) reject('sourceTamper', 'Fixed container runtime digest mismatch.', 'runtime');
  return { backend: 'docker-colima-v1', image: sandbox.image, baseImage: EXPECTED_BASE_IMAGE, bridgeSha256: bridge.sha256, entrypointSha256: entrypoint.sha256, nodeSha256: node.sha256, nodeVersion: process.version, chromeSha256: chrome.sha256, chromeVersion: EXPECTED_CHROME_VERSION };
}

export function loadSourceConfig() {
  let bytes;
  try { bytes = fs.readFileSync(SOURCE_CONFIG_PATH); } catch (error) { reject('sourceTamper', `Fixed source config is unavailable: ${safeMessage(error)}.`, 'source'); }
  if (sha256(bytes) !== EXPECTED_CONFIG_SHA256) reject('sourceTamper', 'Fixed source config digest mismatch.', 'source');
  let config;
  try { config = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { reject('sourceTamper', 'Fixed source config is not valid JSON.', 'source'); }
  const keys = new Set(['revision', 'packagePath', 'nodeExecutable', 'chromeExecutable', 'files', 'pythonExecutable']);
  if (!isRecord(config) || Object.keys(config).some((key) => !keys.has(key)) || config.revision !== EXPECTED_REVISION || config.packagePath !== 'skills/archify' || !Array.isArray(config.files) || config.files.length !== 190) reject('sourceTamper', 'Fixed source config does not match the review baseline.', 'source');
  fixedPath(config.nodeExecutable, EXPECTED_NODE_EXECUTABLE, 'Node');
  fixedPath(config.chromeExecutable, EXPECTED_CHROME_EXECUTABLE, 'Chrome');
  const paths = new Set();
  for (const entry of config.files) {
    if (!isRecord(entry) || typeof entry.path !== 'string' || paths.has(entry.path) || entry.path.startsWith('/') || entry.path.includes('..') || typeof entry.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(entry.sha256) || !Number.isInteger(entry.bytes) || entry.bytes < 0) reject('sourceTamper', 'Fixed source manifest entry is invalid.', 'source');
    modeBits(entry.mode); paths.add(entry.path);
  }
  return config;
}

function walkFiles(root, current = root, out = new Map()) {
  for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
    const file = path.join(current, entry.name);
    if (entry.isSymbolicLink()) reject('sourceTamper', 'Symbolic links are not allowed in the fixed source package.', 'source');
    if (entry.isDirectory()) walkFiles(root, file, out);
    else if (entry.isFile()) out.set(path.relative(root, file).split(path.sep).join('/'), file);
    else reject('sourceTamper', 'Non-regular source package entry found.', 'source');
  }
  return out;
}

export function verifySourceManifest(config = loadSourceConfig()) {
  let root;
  try { root = fs.realpathSync.native(PACKAGE_ROOT); } catch (error) { reject('sourceTamper', `Fixed source package is unavailable: ${safeMessage(error)}.`, 'source'); }
  if (root !== PACKAGE_ROOT || path.resolve(WORKSPACE_ROOT, config.packagePath) !== PACKAGE_ROOT) reject('sourceTamper', 'Fixed source package path changed.', 'source');
  const files = walkFiles(PACKAGE_ROOT);
  const manifest = new Map(config.files.map((entry) => [entry.path, entry]));
  if (files.size !== manifest.size || [...files.keys()].some((name) => !manifest.has(name))) reject('sourceTamper', 'Fixed source file set changed.', 'source');
  for (const [name, entry] of manifest) {
    const file = files.get(name); let stat; let data;
    try { stat = fs.statSync(file); data = fs.readFileSync(file); } catch (error) { reject('sourceTamper', `Fixed source file is unreadable: ${safeMessage(error)}.`, 'source'); }
    if (!stat.isFile() || stat.nlink !== 1 || data.byteLength !== entry.bytes || sha256(data) !== entry.sha256 || (stat.mode & 0o7777) !== modeBits(entry.mode)) reject('sourceTamper', `Fixed source file digest mismatch: ${name}.`, 'source');
  }
  return { revision: config.revision, fileCount: manifest.size, manifestSha256: sha256(JSON.stringify(config.files)) };
}

function privateDirectory(directory) {
  let stat;
  try { stat = fs.lstatSync(directory); } catch (error) { reject('invalidInvocation', `Run directory is unavailable: ${safeMessage(error)}.`, 'prepare'); }
  if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o077) !== 0) reject('invalidInvocation', 'Run directory must be a private regular directory.', 'prepare');
  try { return fs.realpathSync.native(directory); } catch (error) { reject('invalidInvocation', `Run directory cannot be resolved: ${safeMessage(error)}.`, 'prepare'); }
}
function inside(root, target) { const relative = path.relative(root, target); return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`)); }
function absent(pathname, label) {
  try { fs.lstatSync(pathname); reject('invalidInvocation', `${label} already exists in the run directory.`, 'prepare'); }
  catch (error) { if (error.code !== 'ENOENT') reject('invalidInvocation', `${label} cannot be inspected: ${safeMessage(error)}.`, 'prepare'); }
}

export function prepareRun({ inputPath, runDirectory }) {
  const runRoot = privateDirectory(path.resolve(runDirectory));
  const inputCandidate = path.resolve(inputPath);
  let inputReal; let stat;
  try { stat = fs.lstatSync(inputCandidate); inputReal = fs.realpathSync.native(inputCandidate); } catch (error) { reject('invalidInput', `Specification file is unavailable: ${safeMessage(error)}.`, 'input'); }
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || !inside(runRoot, inputReal) || path.extname(inputReal).toLowerCase() !== '.json') reject('invalidInput', 'Specification must be a private regular JSON file inside the run directory.', 'input');
  for (const [name, label] of [['raw.svg', 'raw SVG'], ['.raw.svg.tmp', 'raw SVG temporary'], ['.archify-delivered.html', 'delivered HTML'], ['.archify-transient.html', 'transient HTML'], ['.specification.snapshot.json', 'specification snapshot']]) absent(path.join(runRoot, name), label);
  const inputBytes = fs.readFileSync(inputReal); const workflow = parseJsonShapeAndValidate(inputBytes);
  return { runRoot, inputPath: inputReal, inputBytes, workflow };
}
function parseJsonShapeAndValidate(bytes) { const value = parseWorkflowJson(bytes); return validateWorkflowObject(value); }

export function cleanEnvironment(tmpdir) { return { HOME: tmpdir, TMPDIR: tmpdir, MAC_CHROMIUM_TMPDIR: tmpdir, LANG: 'C', LC_ALL: 'C', TZ: 'UTC' }; }

export function buildDeliverInvocation({ nodeExecutable, inputPath, htmlPath, runRoot, tmpdir }) {
  fixedPath(nodeExecutable, EXPECTED_NODE_EXECUTABLE, 'Node');
  // Keep the renderer in the caller's process group so the Python sandbox can
  // terminate the complete Node/renderer tree at its deadline.
  return { executable: nodeExecutable, args: [FIXED_CLI, 'deliver', 'workflow', inputPath, htmlPath, '--json', '--quality', 'standard'], options: { cwd: runRoot, shell: false, detached: false, stdio: ['ignore', 'pipe', 'pipe'], env: cleanEnvironment(tmpdir) } };
}

function terminateChild(child) {
  if (!child?.pid) return;
  try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGTERM'); } catch { try { child.kill('SIGTERM'); } catch {} }
  setTimeout(() => { try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGKILL'); } catch {} }, 500).unref();
}
function remaining(deadline, ceiling) {
  const value = Math.min(ceiling, deadline - Date.now());
  if (value <= 0) reject('timeout', 'SVG export bridge exceeded its deadline.', 'bridge');
  return value;
}

function stripFixedThemeIconRules(css) {
  const seen = new Set();
  const rulePattern = /(^[ \t]*)(\[data-theme="(?:light|dark)"\][ \t]+#theme-icon[ \t]*\{[^{}]*^[ \t]*\})/gim;
  return css.replace(rulePattern, (whole) => {
    const theme = THEME_ICON_RULE_HASHES.get(sha256(whole));
    if (!theme) reject('exportFailure', 'Delivered CSS contains an unexpected theme icon rule.', 'sanitize');
    if (seen.has(theme)) reject('exportFailure', 'Delivered CSS contains a duplicate theme icon rule.', 'sanitize');
    seen.add(theme);
    return '';
  });
}

function runFixedChild(invocation, deadline) {
  return new Promise((resolve, rejectPromise) => {
    let child; let settled = false; let timer;
    const stdout = []; const stderr = []; let outBytes = 0; let errBytes = 0;
    const finishError = (error) => { if (settled) return; settled = true; clearTimeout(timer); terminateChild(child); rejectPromise(error); };
    const available = deadline - Date.now();
    if (available <= 0) { finishError(new BridgeError('timeout', 'Renderer delivery exceeded its deadline.', 'renderer')); return; }
    try { child = spawn(invocation.executable, invocation.args, invocation.options); } catch (error) { finishError(new BridgeError('exportFailure', 'Renderer process could not start.', 'renderer')); return; }
    const read = (chunks, kind) => (chunk) => {
      const bytes = Buffer.byteLength(chunk); if (kind === 'stdout') outBytes += bytes; else errBytes += bytes;
      if ((kind === 'stdout' ? outBytes : errBytes) > LIMITS.streamBytes) { finishError(new BridgeError('outputLimit', `Renderer ${kind} exceeded 512 KiB.`, 'renderer')); return; }
      chunks.push(Buffer.from(chunk));
    };
    child.stdout.on('data', read(stdout, 'stdout')); child.stderr.on('data', read(stderr, 'stderr'));
    child.on('error', (error) => finishError(new BridgeError('exportFailure', 'Renderer process failed to start.', 'renderer')));
    child.on('close', (code, signal) => {
      if (settled) return; settled = true; clearTimeout(timer);
      if (code !== 0) { rejectPromise(new BridgeError('exportFailure', `Renderer delivery failed (${signal || code}).`, 'renderer')); return; }
      resolve({ stdout: Buffer.concat(stdout).toString('utf8'), stderr: Buffer.concat(stderr).toString('utf8') });
    });
    timer = setTimeout(() => finishError(new BridgeError('timeout', 'Renderer delivery exceeded its deadline.', 'renderer')), Math.min(available, LIMITS.timeoutMs));
  });
}

export function sanitizeTransientHtml(input) {
  const source = Buffer.isBuffer(input) ? input : Buffer.from(input);
  if (source.byteLength > LIMITS.htmlBytes) reject('exportFailure', 'Delivered HTML exceeds 8 MiB.', 'sanitize');
  let html;
  try { html = new TextDecoder('utf-8', { fatal: true }).decode(source); } catch { reject('exportFailure', 'Delivered HTML is not valid UTF-8.', 'sanitize'); }
  const scriptBodies = (value) => [...value.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)].map((match) => sha256(match[1]));
  const scriptsBefore = scriptBodies(html);
  const stripEvents = (tag) => tag.replace(/\s+on[a-z0-9_-]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
  const tagEnd = (source, start) => { let quote = ''; for (let i = start; i < source.length; i += 1) { const char = source[i]; if (quote) { if (char === quote) quote = ''; } else if (char === '"' || char === "'") quote = char; else if (char === '>') return i; } return -1; };
  const rewriteMarkup = (source) => {
    let output = ''; let cursor = 0;
    while (cursor < source.length) {
      const start = source.indexOf('<', cursor); if (start < 0) { output += source.slice(cursor); break; }
      output += source.slice(cursor, start);
      if (source.startsWith('<!--', start)) { const end = source.indexOf('-->', start + 4); if (end < 0) reject('exportFailure', 'Delivered HTML contains an unterminated comment.', 'sanitize'); output += source.slice(start, end + 3); cursor = end + 3; continue; }
      const opening = source.slice(start).match(/^<([A-Za-z][A-Za-z0-9:-]*)\b/i);
      const closing = source.slice(start).match(/^<\/\s*[A-Za-z][A-Za-z0-9:-]*\s*>/);
      if (!opening && !closing && !source.startsWith('<!', start) && !source.startsWith('<?', start)) { output += '<'; cursor = start + 1; continue; }
      const end = tagEnd(source, start); if (end < 0) reject('exportFailure', 'Delivered HTML contains an unterminated tag.', 'sanitize');
      if (!opening) { output += source.slice(start, end + 1); cursor = end + 1; continue; }
      const name = opening[1].toLowerCase();
      if (name === 'link') { cursor = end + 1; continue; }
      if (name === 'noscript') {
        const close = new RegExp(`<\\/\\s*${name}\\s*>`, 'ig'); close.lastIndex = end + 1; const match = close.exec(source); if (!match) reject('exportFailure', 'Delivered noscript element is unterminated.', 'sanitize');
        cursor = match.index + match[0].length; continue;
      }
      const tag = stripEvents(source.slice(start, end + 1));
      if (new Set(['base', 'iframe', 'frame', 'object', 'embed']).has(name)) reject('exportFailure', 'Delivered HTML contains a prohibited resource element.', 'sanitize');
      if (name === 'script' && /\bsrc\s*=/i.test(tag)) reject('exportFailure', 'Delivered HTML contains an external script.', 'sanitize');
      if (/\b(?:src|href)\s*=\s*["']?(?:https?:|\/\/)/i.test(tag)) reject('exportFailure', 'Delivered HTML contains an external resource.', 'sanitize');
      output += tag; cursor = end + 1;
      if (name === 'script' || name === 'style') {
        const close = new RegExp(`<\\/\\s*${name}\\s*>`, 'ig'); close.lastIndex = cursor; const match = close.exec(source); if (!match) reject('exportFailure', `Delivered ${name} element is unterminated.`, 'sanitize');
        let body = source.slice(cursor, match.index); if (name === 'style') body = stripFixedThemeIconRules(body); if (name === 'style' && /@import\s+|url\(\s*["']?(?:https?:|\/\/)/i.test(body)) reject('exportFailure', 'Delivered CSS contains an external resource.', 'sanitize');
        output += body + match[0]; cursor = match.index + match[0].length;
      }
    }
    return output;
  };
  html = rewriteMarkup(html);
  html = html.replace(/<meta\b[^>]*content-security-policy[^>]*>/gi, '');
  const root = html.match(/<html\b[^>]*>/i); const head = html.match(/<head\b[^>]*>/i);
  if (!root || !head) reject('exportFailure', 'Delivered HTML has no HTML/head root.', 'sanitize');
  let rootTag = stripEvents(root[0]).replace(/\s+(?:lang|data-theme)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '');
  rootTag = rootTag.replace(/>$/, ' lang="ja" data-theme="light">'); html = html.replace(root[0], rootTag);
  const scriptSources = scriptsBefore.map((digest) => `'sha256-${Buffer.from(digest, 'hex').toString('base64')}'`).join(' ') || "'none'";
  const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src ${scriptSources}; style-src 'unsafe-inline'; img-src data: blob:; font-src 'none'; connect-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">`;
  html = html.replace(head[0], `${head[0]}${csp}`);
  if (JSON.stringify(scriptBodies(html)) !== JSON.stringify(scriptsBefore)) reject('exportFailure', 'Transient HTML sanitizer changed an inline script body.', 'sanitize');
  if (Buffer.byteLength(html, 'utf8') > LIMITS.htmlBytes) reject('exportFailure', 'Transient HTML sanitization did not reach its safe form.', 'sanitize');
  return Buffer.from(html, 'utf8');
}

function writeExclusive(file, data) { fs.writeFileSync(file, data, { flag: 'wx', mode: 0o600 }); }
function identity(stat) { return stat && `${stat.dev}:${stat.ino}`; }
function fileIdentity(file) { try { return identity(fs.lstatSync(file)); } catch { return null; } }
function removeOwned(file, expected) { if (!expected || fileIdentity(file) !== expected) return; try { fs.unlinkSync(file); } catch {} }
function statPrivateFile(file, label, maxBytes) {
  let stat;
  try { stat = fs.lstatSync(file); } catch (error) { reject('exportFailure', `${label} is missing.`, 'export'); }
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size <= 0 || stat.size > maxBytes) reject('exportFailure', `${label} has an invalid size or file identity.`, 'export');
  return stat;
}
function looksLikeSvg(data) {
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(data); } catch { return false; }
  const body = text.replace(/^\uFEFF/, '').trim();
  return /^<svg(?:\s|>)/i.test(body) && /<\/svg>\s*$/i.test(body);
}

async function loadChromium() {
  try {
    const require = createRequire(PACKAGE_JSON); const modulePath = require.resolve('playwright/package.json'); const corePath = require.resolve('playwright-core/package.json');
    const packageBytes = fs.readFileSync(modulePath); const coreBytes = fs.readFileSync(corePath); const packageInfo = JSON.parse(packageBytes); const coreInfo = JSON.parse(coreBytes);
    const lockPath = path.join(path.dirname(PACKAGE_JSON), 'package-lock.json'); const lockBytes = fs.readFileSync(lockPath); const lock = JSON.parse(lockBytes);
    const locked = lock.packages?.['node_modules/playwright']?.version; const lockedCore = lock.packages?.['node_modules/playwright-core']?.version;
    if (packageInfo.name !== 'playwright' || packageInfo.version !== EXPECTED_PLAYWRIGHT_VERSION || coreInfo.version !== EXPECTED_PLAYWRIGHT_VERSION || locked !== EXPECTED_PLAYWRIGHT_VERSION || lockedCore !== EXPECTED_PLAYWRIGHT_VERSION || sha256(packageBytes) !== EXPECTED_PLAYWRIGHT_PACKAGE_SHA256 || sha256(coreBytes) !== EXPECTED_PLAYWRIGHT_CORE_SHA256 || sha256(lockBytes) !== EXPECTED_PLAYWRIGHT_LOCK_SHA256) throw new Error('fixed Playwright 1.61.1 is not installed');
    return { chromium: require('playwright').chromium, info: { version: packageInfo.version, coreVersion: coreInfo.version, packageSha256: sha256(packageBytes), coreSha256: sha256(coreBytes), lockSha256: sha256(lockBytes) } };
  } catch (error) { reject('missingPlaywright', `Fixed Playwright runtime is unavailable: ${safeMessage(error)}.`, 'browser'); }
}

async function exportSvg({ htmlPath, rawPath, config, runRoot, tmpdir, deadline, sandbox }) {
  fixedPath(config.chromeExecutable, EXPECTED_CHROME_EXECUTABLE, 'Chrome');
  if (!fs.existsSync(config.chromeExecutable)) reject('missingChrome', 'Fixed system Chrome is unavailable.', 'browser');
  try { const link = fs.lstatSync(config.chromeExecutable); const stat = fs.statSync(config.chromeExecutable); if (link.isSymbolicLink() || !stat.isFile()) throw new Error('not a fixed regular file'); fs.accessSync(config.chromeExecutable, fs.constants.X_OK); }
  catch { reject('missingChrome', 'Fixed system Chrome is unavailable or not executable.', 'browser'); }
  const playwright = await loadChromium(); const chromium = playwright.chromium; let browser; let context; let page; const blocked = []; const allowed = [];
  try {
    try { browser = await chromium.launch({ executablePath: config.chromeExecutable, headless: true, pipe: true, chromiumSandbox: true, timeout: remaining(deadline, LIMITS.stepMs), env: cleanEnvironment(tmpdir) }); }
    catch (error) { reject('browserLaunchFailure', `Fixed system Chrome could not launch: ${safeMessage(error)}.`, 'browser'); }
    context = await browser.newContext({ acceptDownloads: true, serviceWorkers: 'block', permissions: [], viewport: { width: 1440, height: 900 } });
    context.setDefaultTimeout(remaining(deadline, LIMITS.stepMs));
    page = await context.newPage();
    const pageUrl = `${pathToFileURL(htmlPath).href}?theme=light`;
    await context.route('**/*', async (route) => {
      const requestUrl = route.request().url();
      if (requestUrl === pageUrl) { allowed.push(requestUrl); await route.continue(); return; }
      if (blocked.length < 16) blocked.push(requestUrl.slice(0, 200));
      await route.abort('blockedbyclient');
    });
    const pageErrors = []; const consoleErrors = [];
    page.on('pageerror', (error) => { if (pageErrors.length < 8) pageErrors.push(safeMessage(error)); });
    page.on('console', (message) => { if (message.type() === 'error' && consoleErrors.length < 8) consoleErrors.push(message.text().slice(0, 200)); });
    await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: remaining(deadline, LIMITS.stepMs) });
    await page.waitForFunction(() => document.documentElement?.dataset.theme === 'light', { timeout: remaining(deadline, LIMITS.stepMs) });
    await page.waitForSelector('#btn-export', { state: 'visible', timeout: remaining(deadline, LIMITS.stepMs) });
    const exportButton = page.locator('#btn-export'); const svgButton = page.locator('#export-menu button[data-format="svg"]');
    if (await exportButton.count() !== 1 || await svgButton.count() !== 1) reject('exportFailure', 'Official SVG export selectors are unavailable.', 'export');
    const downloadPromise = page.waitForEvent('download', { timeout: remaining(deadline, LIMITS.exportMs) });
    await exportButton.click(); await svgButton.click();
    const download = await downloadPromise; const failure = await download.failure();
    if (failure) reject('exportFailure', `SVG download failed: ${String(failure).slice(0, 160)}.`, 'export');
    await page.waitForFunction(() => document.documentElement?.dataset.lastExportFormat === 'svg', { timeout: remaining(deadline, LIMITS.exportMs) });
    const receipt = await page.evaluate(() => ({ format: document.documentElement.dataset.lastExportFormat, bytes: Number(document.documentElement.dataset.lastExportBytes), canonical: document.documentElement.dataset.lastExportCanonical, error: document.documentElement.dataset.lastExportError }));
    if (receipt.format !== 'svg' || !Number.isInteger(receipt.bytes) || receipt.bytes <= 0 || receipt.bytes > LIMITS.svgBytes || receipt.canonical !== 'true' || receipt.error) reject('exportFailure', 'Official SVG export receipt is invalid.', 'export');
    if (blocked.length || pageErrors.length || consoleErrors.length) reject('exportFailure', 'Browser requested a blocked resource or reported an export error.', 'browser');
    const downloadedPath = await download.path();
    if (!downloadedPath) reject('exportFailure', 'SVG download has no local file.', 'export');
    const raw = fs.readFileSync(downloadedPath);
    if (raw.byteLength > LIMITS.svgBytes) reject('exportFailure', 'Downloaded SVG exceeds 4 MiB.', 'export');
    writeExclusive(rawPath, raw); statPrivateFile(rawPath, 'raw SVG', LIMITS.svgBytes);
    if (raw.byteLength !== receipt.bytes || !looksLikeSvg(raw)) reject('exportFailure', 'Downloaded SVG failed the raw-file checks.', 'export');
    const chromeVersion = await browser.version(); if (chromeVersion !== EXPECTED_CHROME_VERSION) reject('exportFailure', 'Fixed Chrome did not return the pinned version.', 'browser');
    return { format: receipt.format, bytes: raw.byteLength, canonical: true, selector: '#btn-export', itemSelector: '#export-menu button[data-format="svg"]', allowedRequests: allowed.length, blockedRequests: blocked.length, pageErrors, consoleErrors, theme: 'light', serviceWorkers: 'block', chromiumSandbox: true, pipe: true, freshContext: true, sandboxPolicy: sandbox.policy, sandboxProfileSha256: sandbox.profileSha256, chromeExecutable: config.chromeExecutable, chromeVersion, playwright: playwright.info, sha256: sha256(raw) };
  } finally { try { await context?.close(); } catch {} try { await browser?.close(); } catch {} }
}

export async function runBridge(inputArg, runArg) {
  const sandbox = requireSandboxAttestation(); const deadline = Date.now() + LIMITS.timeoutMs; const config = loadSourceConfig(); const source = verifySourceManifest(config); const runtime = collectRuntime(sandbox, config); const prepared = prepareRun({ inputPath: inputArg, runDirectory: runArg });
  const tmpdir = privateDirectory(BROWSER_TMPDIR);
  const snapshot = path.join(prepared.runRoot, '.specification.snapshot.json'); const delivered = path.join(prepared.runRoot, '.archify-delivered.html'); const transient = path.join(prepared.runRoot, '.archify-transient.html'); const rawPath = path.join(prepared.runRoot, 'raw.svg');
  const owned = new Map(); let keepRaw = false;
  try {
    writeExclusive(snapshot, prepared.inputBytes); owned.set(snapshot, fileIdentity(snapshot)); const invocation = buildDeliverInvocation({ nodeExecutable: config.nodeExecutable, inputPath: snapshot, htmlPath: delivered, runRoot: prepared.runRoot, tmpdir });
    const child = await runFixedChild(invocation, deadline); let rendererReceipt;
    try { rendererReceipt = JSON.parse(child.stdout.trim()); } catch { reject('exportFailure', 'Renderer did not emit a JSON delivery receipt.', 'renderer'); }
    if (!rendererReceipt?.ok || rendererReceipt.command !== 'deliver' || rendererReceipt.type !== 'workflow' || rendererReceipt.specification?.sha256 !== sha256(prepared.inputBytes)) reject('exportFailure', 'Renderer delivery receipt failed its contract.', 'renderer');
    const deliveredStat = statPrivateFile(delivered, 'delivered HTML', LIMITS.htmlBytes); owned.set(delivered, identity(deliveredStat)); const deliveredBytes = fs.readFileSync(delivered); if (deliveredBytes.byteLength !== rendererReceipt.artifact?.bytes || sha256(deliveredBytes) !== rendererReceipt.artifact?.sha256) reject('exportFailure', 'Renderer artifact receipt does not match delivered HTML.', 'renderer');
    const sanitized = sanitizeTransientHtml(deliveredBytes); writeExclusive(transient, sanitized); owned.set(transient, fileIdentity(transient));
    const rawTemp = path.join(prepared.runRoot, '.raw.svg.tmp'); const browser = await exportSvg({ htmlPath: transient, rawPath: rawTemp, config, runRoot: prepared.runRoot, tmpdir, deadline, sandbox }); owned.set(rawTemp, fileIdentity(rawTemp));
    if (browser.chromeVersion !== runtime.chromeVersion) reject('sourceTamper', 'Observed Chrome version changed during export.', 'runtime');
    fs.linkSync(rawTemp, rawPath); owned.set(rawPath, fileIdentity(rawPath)); removeOwned(rawTemp, owned.get(rawTemp)); keepRaw = true;
    return { schemaVersion: 1, ok: true, status: 'verified', command: 'archify-render', diagramType: 'workflow', revision: source.revision, source, runtime, renderer: { command: 'deliver', quality: 'standard', artifact: { sha256: rendererReceipt.artifact.sha256, bytes: deliveredStat.size } }, html: { rawSha256: sha256(deliveredBytes), rawBytes: deliveredBytes.byteLength, sanitizedSha256: sha256(sanitized), sanitizedBytes: sanitized.byteLength }, browser, rawSvg: { path: 'raw.svg', sha256: browser.sha256, bytes: browser.bytes } };
  } finally {
    for (const file of [snapshot, delivered, transient, path.join(prepared.runRoot, '.raw.svg.tmp')]) removeOwned(file, owned.get(file));
    if (!keepRaw) removeOwned(rawPath, owned.get(rawPath));
  }
}

function failureReceipt(error) {
  const known = error instanceof BridgeError ? error : new BridgeError('internalFailure', 'SVG export bridge failed.', 'internal');
  const status = known.code === 'timeout' ? 'timeout' : (['invalidInput', 'sourceTamper', 'missingChrome', 'missingPlaywright', 'invalidInvocation', 'sandboxRequired'].includes(known.code) ? 'blocked' : 'error');
  return { schemaVersion: 1, ok: false, status, command: 'archify-render', code: known.code, phase: known.phase, message: safeMessage(known) };
}

export async function runCli(argv = process.argv.slice(2)) {
  if (argv.length !== 2 || argv.some((arg) => typeof arg !== 'string' || arg.startsWith('-'))) {
    const receipt = failureReceipt(new BridgeError('invalidInvocation', 'Usage: archify_render.mjs <spec.json> <dedicated-run-dir>.', 'prepare')); process.stdout.write(`${JSON.stringify(receipt)}\n`); process.exitCode = 2; return receipt;
  }
  try { const receipt = await runBridge(argv[0], argv[1]); process.stdout.write(`${JSON.stringify(receipt)}\n`); return receipt; }
  catch (error) { const receipt = failureReceipt(error); process.stdout.write(`${JSON.stringify(receipt)}\n`); process.exitCode = receipt.code === 'invalidInvocation' ? 2 : 1; return receipt; }
}

function isMain() { return process.argv[1] && path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1]); }
if (isMain()) await runCli();
