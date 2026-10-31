import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clamp, fmtInt, fmtPoints, plural, planAsChecklist, relTime, sentenceCase, shortDate, shortRef, splitPath,
} from '../js/format.js';

test('numbers are grouped and points keep one decimal', () => {
  assert.equal(fmtInt(1234567), '1,234,567');
  assert.equal(fmtInt(undefined), '0');
  assert.equal(fmtPoints(16), '16.0');
  assert.equal(fmtPoints(7.25), '7.3');
  assert.equal(fmtPoints('x'), '0.0');
});

test('plural picks the right form', () => {
  assert.equal(plural(1, 'file'), '1 file');
  assert.equal(plural(2, 'file'), '2 files');
  assert.equal(plural(1, 'analysis', 'analyses'), '1 analysis');
  assert.equal(plural(3, 'analysis', 'analyses'), '3 analyses');
  assert.equal(plural(1500, 'line'), '1,500 lines');
});

test('clamp stays inside its bounds', () => {
  assert.equal(clamp(5, 0, 3), 3);
  assert.equal(clamp(-1, 0, 3), 0);
  assert.equal(clamp(2, 0, 3), 2);
});

test('splitPath separates directory and name', () => {
  assert.deepEqual(splitPath('src/ledgerline/client.py'), { dir: 'src/ledgerline/', name: 'client.py' });
  assert.deepEqual(splitPath('README.md'), { dir: '', name: 'README.md' });
});

test('relative times read naturally', () => {
  const now = Date.parse('2026-10-31T12:00:00Z');
  const ago = (ms) => new Date(now - ms).toISOString();
  assert.equal(relTime(ago(10_000), now), 'just now');
  assert.equal(relTime(ago(5 * 60_000), now), '5 min ago');
  assert.equal(relTime(ago(3 * 3_600_000), now), '3 h ago');
  assert.equal(relTime(ago(26 * 3_600_000), now), 'yesterday');
  assert.equal(relTime(ago(4 * 86_400_000), now), '4 days ago');
  assert.equal(relTime(ago(40 * 86_400_000), now), 'Sep 21');
  assert.equal(relTime(new Date(now + 90_000).toISOString(), now), 'just now');
  assert.equal(relTime('not a date', now), '');
});

test('short dates drop the year only for the current one', () => {
  const now = new Date('2026-10-31T12:00:00Z');
  assert.equal(shortDate('2026-08-24T10:00:00Z', now), 'Aug 24');
  assert.equal(shortDate('2025-08-24T10:00:00Z', now), 'Aug 24, 2025');
  assert.equal(shortDate('nope', now), '');
});

test('long refs are shortened in the middle', () => {
  assert.equal(shortRef('main'), 'main');
  const long = 'feature/a-very-long-branch-name-that-goes-on-and-on';
  const short = shortRef(long, 20);
  assert.equal(short.length, 20);
  assert.ok(short.startsWith('feature/a-'));
  assert.ok(short.includes('…'));
  assert.equal(shortRef(''), '');
});

test('sentenceCase', () => {
  assert.equal(sentenceCase('critical'), 'Critical');
  assert.equal(sentenceCase(''), '');
});

test('the test plan copies as a Markdown checklist', () => {
  const plan = [{ text: 'Run the suite' }, { text: 'Rotate the key' }];
  assert.equal(planAsChecklist(plan), '- [ ] Run the suite\n- [ ] Rotate the key');
  assert.equal(planAsChecklist(plan, new Set(['Rotate the key'])), '- [ ] Run the suite\n- [x] Rotate the key');
});
