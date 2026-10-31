import test from 'node:test';
import assert from 'node:assert/strict';
import { EXAMPLES, SAMPLE_DIFF } from '../js/sample-diff.js';

test('three examples, each with what the first screen needs', () => {
  assert.deepEqual(EXAMPLES.map((e) => e.id), ['tidy', 'review', 'critical']);
  for (const e of EXAMPLES) {
    assert.ok(e.title && e.summary, e.id);
    assert.ok(`Example: ${e.label}`.length <= 30, `${e.id}: the history list shows 30 characters`);
    assert.ok(['low', 'moderate', 'high', 'critical'].includes(e.expect), e.id);
    assert.match(e.diff, /^diff --git /, e.id);
    assert.ok(e.diff.endsWith('\n'), e.id);
  }
});

test('the placeholder key is filled in at runtime and appears only where intended', () => {
  for (const e of EXAMPLES) assert.equal(e.diff.includes('__STRIPE_KEY__'), false, e.id);
  assert.ok(EXAMPLES.find((e) => e.id === 'critical').diff.includes('sk_live_'));
  assert.equal(EXAMPLES.find((e) => e.id === 'tidy').diff.includes('sk_live_'), false);
});

test('the form\'s "Load an example" still gets the one with the most to show', () => {
  assert.equal(SAMPLE_DIFF, EXAMPLES.find((e) => e.id === 'critical').diff);
});
