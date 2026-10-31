import { recall, remember } from './store.js';

// The hosted dashboard keeps nothing on the server. Each visitor's reports live in their own
// browser, so a pasted diff never leaves the analysis request and cannot be read by anyone else.

const KEY = 'changerisk.reports.v1';
export const MAX_KEPT = 12;

/** The list-row view of a report. Mirrors summarize() in src/changerisk/store.py. */
export function summarize(report) {
  const range = report.range || {};
  const stats = report.stats || {};
  const findings = report.findings || [];
  return {
    id: report.id,
    generated_at: report.generated_at,
    repo: report.repo,
    mode: range.mode,
    base: range.base,
    head: range.mode === 'diff' && report.source && report.source.label ? report.source.label : range.head,
    head_sha: (range.head_sha || '').slice(0, 8),
    score: report.score,
    level: report.level,
    gate_failed: report.gate ? report.gate.failed : null,
    files: stats.files,
    additions: stats.additions,
    deletions: stats.deletions,
    findings: findings.length,
    top: findings.slice(0, 3).map((f) => f.title),
  };
}

function readAll() {
  const items = recall(KEY, []);
  return Array.isArray(items) ? items.filter((r) => r && typeof r.id === 'string') : [];
}

/** Reports kept in this browser, newest first. */
export function listLocal() {
  return readAll().map(summarize);
}

export function getLocal(id) {
  return readAll().find((r) => r.id === id) || null;
}

function newId(now = Date.now(), random = Math.random()) {
  return `${now.toString(36)}-${Math.floor(random * 36 ** 4).toString(36).padStart(4, '0')}`;
}

/** Give the report an id and keep it, dropping the oldest if the browser's storage is full. */
export function saveLocal(report) {
  const saved = { ...report, id: newId() };
  let items = [saved, ...readAll()].slice(0, MAX_KEPT);
  while (!remember(KEY, items) && items.length > 1) items = items.slice(0, -1);
  return saved;
}

export function removeLocal(id) {
  remember(KEY, readAll().filter((r) => r.id !== id));
}

export function clearLocal() {
  remember(KEY, undefined);
}
