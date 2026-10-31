import test from 'node:test';
import assert from 'node:assert/strict';

// A stand-in for the browser's storage, with an optional size limit to exercise the "full" path.
function installStorage(limit = Infinity) {
  const data = new Map();
  globalThis.localStorage = {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => {
      const total = [...data.entries()].filter(([key]) => key !== k).reduce((n, [, val]) => n + val.length, 0) + v.length;
      if (total > limit) throw new DOMException('full', 'QuotaExceededError');
      data.set(k, v);
    },
    removeItem: (k) => data.delete(k),
  };
  return data;
}

installStorage();
const { summarize, listLocal, getLocal, saveLocal, removeLocal, clearLocal, MAX_KEPT } = await import('../js/local-store.js');

const report = (n, overrides = {}) => ({
  generated_at: `2026-10-0${(n % 9) + 1}T10:00:00+00:00`,
  repo: 'acme/ledger',
  range: { mode: 'pr', base: 'main', head: `topic-${n}`, head_sha: 'abcdef0123456789' },
  stats: { files: 3, additions: 10, deletions: 2 },
  score: n,
  level: 'moderate',
  gate: { fail_on: 'high', failed: false },
  findings: [{ title: 'A' }, { title: 'B' }, { title: 'C' }, { title: 'D' }],
  ...overrides,
});

test('summaries carry what the list needs and nothing heavy', () => {
  const s = summarize({ ...report(7), id: 'x' });
  assert.deepEqual(s.top, ['A', 'B', 'C']);
  assert.equal(s.findings, 4);
  assert.equal(s.head_sha, 'abcdef01');
  assert.equal(s.gate_failed, false);
  assert.equal(s.files, 3);
  assert.equal('hunks' in s, false);
});

test('a named diff is listed under its name, an unnamed one under what the range says', () => {
  const diff = (source) => ({ ...report(1), range: { mode: 'diff', base: '(pasted)', head: 'diff' }, source });
  assert.equal(summarize({ ...diff({ type: 'diff', label: 'Example: tidy' }), id: 'a' }).head, 'Example: tidy');
  assert.equal(summarize({ ...diff(null), id: 'b' }).head, 'diff');
  assert.equal(summarize({ ...report(2), source: { type: 'github', label: 'o/r#1' }, id: 'c' }).head, 'topic-2');
});

test('summaries tolerate a sparse report', () => {
  const s = summarize({ id: 'y' });
  assert.equal(s.findings, 0);
  assert.deepEqual(s.top, []);
  assert.equal(s.gate_failed, null);
});

test('a saved report gets an id, comes back whole, and is listed newest first', () => {
  clearLocal();
  const first = saveLocal(report(1));
  const second = saveLocal(report(2));
  assert.notEqual(first.id, second.id);
  assert.match(first.id, /^[0-9a-z]+-[0-9a-z]{4}$/);
  assert.equal(getLocal(first.id).score, 1);
  assert.deepEqual(listLocal().map((r) => r.id), [second.id, first.id]);
  assert.equal(getLocal('nope'), null);
});

test('only the most recent reports are kept', () => {
  clearLocal();
  for (let i = 0; i < MAX_KEPT + 5; i += 1) saveLocal(report(i));
  assert.equal(listLocal().length, MAX_KEPT);
  assert.equal(listLocal()[0].score, MAX_KEPT + 4);
});

test('removing and clearing', () => {
  clearLocal();
  const a = saveLocal(report(1));
  saveLocal(report(2));
  removeLocal(a.id);
  assert.equal(listLocal().length, 1);
  clearLocal();
  assert.deepEqual(listLocal(), []);
});

test('when storage fills up the oldest reports make room for the new one', () => {
  installStorage(3000);
  const big = (n) => report(n, { filler: 'x'.repeat(1200) });
  const a = saveLocal(big(1));
  saveLocal(big(2));
  const c = saveLocal(big(3));
  const ids = listLocal().map((r) => r.id);
  assert.equal(ids[0], c.id);
  assert.ok(!ids.includes(a.id));
  assert.ok(ids.length >= 1);
});

test('corrupt or foreign data in storage is ignored', () => {
  installStorage();
  globalThis.localStorage.setItem('changerisk.reports.v1', '{"not":"a list"}');
  assert.deepEqual(listLocal(), []);
  globalThis.localStorage.setItem('changerisk.reports.v1', '[1,null,{"id":5},{"id":"ok","score":1}]');
  assert.deepEqual(listLocal().map((r) => r.id), ['ok']);
  globalThis.localStorage.setItem('changerisk.reports.v1', '{broken');
  assert.deepEqual(listLocal(), []);
});

test('a browser without storage still analyses: saving just does not persist', () => {
  delete globalThis.localStorage;
  const saved = saveLocal(report(1));
  assert.ok(saved.id);
  assert.deepEqual(listLocal(), []);
});
