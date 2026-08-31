#!/usr/bin/env node

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BridgeError, runBridge } from './archify_render.mjs';

const PROTOCOL = 'archify-container-v1';
const RUN_DIR = '/tmp/run';
const SPEC_PATH = path.join(RUN_DIR, 'spec.json');
const RAW_PATH = path.join(RUN_DIR, 'raw.svg');
const INPUT_LIMIT = 1024 * 1024;
const SVG_LIMIT = 4 * 1024 * 1024;
const OUTPUT_LIMIT = 8 * 1024 * 1024;
const SHA256_RE = /^[a-f0-9]{64}$/;
const RUNTIME_KEYS = ['backend', 'image', 'baseImage', 'bridgeSha256', 'entrypointSha256', 'nodeSha256', 'nodeVersion', 'chromeSha256', 'chromeVersion'];

class EntryError extends Error {
  constructor(code, message, phase = 'container') {
    super(message);
    this.name = 'EntryError';
    this.code = code;
    this.phase = phase;
  }
}

const reject = (code, message, phase) => { throw new EntryError(code, message, phase); };
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const safeCode = (error) => error instanceof BridgeError || error instanceof EntryError ? error.code : 'internalFailure';
const statusFor = (code) => code === 'timeout' ? 'timeout' : ['invalidInput', 'invalidInvocation', 'sandboxRequired', 'sourceTamper', 'missingChrome', 'missingPlaywright'].includes(code) ? 'blocked' : 'error';
const safeMessage = (code) => ({
  invalidInput: 'Container input was rejected.',
  invalidInvocation: 'Container invocation was rejected.',
  sandboxRequired: 'Container sandbox attestation was rejected.',
  sourceTamper: 'Fixed container runtime integrity check failed.',
  missingChrome: 'Fixed container Chrome is unavailable.',
  missingPlaywright: 'Fixed container Playwright is unavailable.',
  timeout: 'Container export exceeded its deadline.',
  outputLimit: 'Container output exceeded its limit.',
  exportFailure: 'SVG export failed.',
})[code] || 'Container export failed.';

function privateDirectory(directory) {
  let stat;
  try { stat = fs.lstatSync(directory); } catch { reject('invalidInvocation', 'Container run directory is unavailable.', 'prepare'); }
  if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o077) !== 0) reject('invalidInvocation', 'Container run directory is not private.', 'prepare');
  try { return fs.realpathSync.native(directory); } catch { reject('invalidInvocation', 'Container run directory cannot be resolved.', 'prepare'); }
}

export async function readBounded(stream) {
  const chunks = []; let bytes = 0;
  for await (const chunk of stream) {
    const part = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += part.byteLength;
    if (bytes > INPUT_LIMIT) { stream.destroy?.(); reject('invalidInput', 'Container input exceeds 1 MiB.', 'input'); }
    chunks.push(part);
  }
  return Buffer.concat(chunks, bytes);
}

function regularFile(file, label, maxBytes) {
  let stat;
  try { stat = fs.lstatSync(file); } catch { reject('exportFailure', `${label} is missing.`, 'export'); }
  if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.size <= 0 || stat.size > maxBytes) reject('exportFailure', `${label} has an invalid identity or size.`, 'export');
  return stat;
}

function writeExclusive(file, data) {
  try { fs.writeFileSync(file, data, { flag: 'wx', mode: 0o600 }); } catch { reject('invalidInput', 'Container specification could not be staged.', 'input'); }
}

function removeOwned(file, expected) {
  if (!expected) return;
  try {
    const stat = fs.lstatSync(file);
    if (stat.isFile() && stat.nlink === 1 && `${stat.dev}:${stat.ino}` === expected) fs.unlinkSync(file);
  } catch {}
}

function validateReceipt(receipt, rawSvg) {
  if (!receipt || receipt.ok !== true || receipt.status !== 'verified' || receipt.schemaVersion !== 1) reject('exportFailure', 'Bridge receipt is not successful.', 'receipt');
  const runtime = receipt.runtime;
  if (!runtime || RUNTIME_KEYS.some((key) => typeof runtime[key] !== 'string' || (key.endsWith('Sha256') && !SHA256_RE.test(runtime[key])))) reject('exportFailure', 'Bridge runtime receipt is incomplete.', 'receipt');
  if (runtime.backend !== 'docker-colima-v1' || !/^sha256:[a-f0-9]{64}$/.test(runtime.image)) reject('exportFailure', 'Bridge runtime receipt is not fixed.', 'receipt');
  const digest = sha256(rawSvg);
  if (!receipt.browser || receipt.browser.sha256 !== digest || receipt.browser.bytes !== rawSvg.byteLength || receipt.rawSvg?.path !== 'raw.svg' || receipt.rawSvg.sha256 !== digest || receipt.rawSvg.bytes !== rawSvg.byteLength) reject('exportFailure', 'Bridge raw SVG receipt does not match.', 'receipt');
}

export function buildSuccessEnvelope(receipt, rawSvg) {
  const bytes = Buffer.isBuffer(rawSvg) ? rawSvg : Buffer.from(rawSvg);
  regularFileBuffer(bytes, 'raw SVG');
  validateReceipt(receipt, bytes);
  const envelope = { schemaVersion: 1, protocol: PROTOCOL, ok: true, receipt, rawSvg: { encoding: 'base64', bytes: bytes.byteLength, sha256: sha256(bytes), data: bytes.toString('base64') } };
  const encoded = JSON.stringify(envelope);
  if (Buffer.byteLength(encoded, 'utf8') > OUTPUT_LIMIT) reject('outputLimit', 'Container envelope exceeds 8 MiB.', 'output');
  return envelope;
}

function regularFileBuffer(bytes, label) {
  if (bytes.byteLength <= 0 || bytes.byteLength > SVG_LIMIT) reject('exportFailure', `${label} exceeds 4 MiB or is empty.`, 'export');
}

export function buildFailureEnvelope(error) {
  const code = safeCode(error);
  return { schemaVersion: 1, protocol: PROTOCOL, ok: false, status: statusFor(code), code, message: safeMessage(code) };
}

export async function runContainer({ input = process.stdin, output = process.stdout } = {}) {
  let specIdentity; let rawIdentity;
  try {
    const runRoot = privateDirectory(RUN_DIR);
    const inputBytes = await readBounded(input);
    writeExclusive(SPEC_PATH, inputBytes);
    specIdentity = (() => { const stat = regularFile(SPEC_PATH, 'specification', INPUT_LIMIT); return `${stat.dev}:${stat.ino}`; })();
    const receipt = await runBridge(SPEC_PATH, runRoot);
    const rawStat = regularFile(RAW_PATH, 'raw SVG', SVG_LIMIT);
    rawIdentity = `${rawStat.dev}:${rawStat.ino}`;
    const rawSvg = fs.readFileSync(RAW_PATH);
    const envelope = buildSuccessEnvelope(receipt, rawSvg);
    const text = `${JSON.stringify(envelope)}\n`;
    if (Buffer.byteLength(text, 'utf8') > OUTPUT_LIMIT) reject('outputLimit', 'Container envelope exceeds 8 MiB.', 'output');
    output.write(text);
    return envelope;
  } catch (error) {
    const envelope = buildFailureEnvelope(error);
    output.write(`${JSON.stringify(envelope)}\n`);
    process.exitCode = 1;
    return envelope;
  } finally {
    removeOwned(SPEC_PATH, specIdentity);
    removeOwned(RAW_PATH, rawIdentity);
  }
}

function isMain() { return process.argv[1] && path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1]); }
if (isMain()) {
  process.umask(0o077);
  if (process.argv.length !== 2) {
    process.stdout.write(`${JSON.stringify(buildFailureEnvelope(new EntryError('invalidInvocation', 'No container arguments are permitted.', 'prepare')))}\n`);
    process.exitCode = 2;
  } else await runContainer();
}
