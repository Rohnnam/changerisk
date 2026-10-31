import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BANDS, GATE_SCORE, LEVELS, SEVERITY_LEVEL, flagIndex, groupPlan, levelForScore, rangeLabel, topSeverity,
} from '../js/model.js';

test('score bands match the thresholds the backend uses', () => {
  const cases = [[0, 'low'], [24, 'low'], [25, 'moderate'], [49, 'moderate'], [50, 'high'], [74, 'high'], [75, 'critical'], [100, 'critical']];
  for (const [score, level] of cases) assert.equal(levelForScore(score), level, `score ${score}`);
  assert.deepEqual(BANDS.map((b) => b.id), LEVELS);
  assert.deepEqual(GATE_SCORE, { moderate: 25, high: 50, critical: 75 });
});

test('severities map onto the four level shapes', () => {
  assert.equal(SEVERITY_LEVEL.medium, 'moderate');
  assert.equal(SEVERITY_LEVEL.info, 'low');
  assert.equal(SEVERITY_LEVEL.critical, 'critical');
});

test('the test plan is grouped by priority and empty groups are dropped', () => {
  const groups = groupPlan([
    { text: 'a', priority: 2 },
    { text: 'b', priority: 1 },
    { text: 'c', priority: 1 },
  ]);
  assert.deepEqual(groups.map((g) => [g.priority, g.steps.map((s) => s.text)]), [[1, ['b', 'c']], [2, ['a']]]);
  assert.deepEqual(groupPlan([]), []);
});

test('flagIndex keys evidence by side and line, and merges findings on one line', () => {
  const f1 = { id: 'f1', evidence: [{ path: 'a.yml', line: 3, side: 'new' }, { path: 'b.yml', line: 1, side: 'new' }] };
  const f2 = { id: 'f2', evidence: [{ path: 'a.yml', line: 3, side: 'new' }, { path: 'a.yml', line: 7, side: 'old' }, { path: 'a.yml', line: null, side: 'new' }] };
  const index = flagIndex({ findings: [f1, f2] }, 'a.yml');
  assert.deepEqual([...index.keys()].sort(), ['n3', 'o7']);
  assert.deepEqual(index.get('n3').map((f) => f.id), ['f1', 'f2']);
  assert.equal(index.has('n1'), false);
});

test('topSeverity picks the worst', () => {
  assert.equal(topSeverity([{ severity: 'low' }, { severity: 'high' }, { severity: 'medium' }]), 'high');
  assert.equal(topSeverity([]), 'info');
});

test('range labels for each analysis mode', () => {
  assert.deepEqual(rangeLabel({ mode: 'range', base: 'main', head: 'x' }), { from: 'main', to: 'x', plain: false });
  assert.equal(rangeLabel({ mode: 'staged' }).to, 'staged changes');
  assert.equal(rangeLabel({ mode: 'worktree' }).to, 'working tree');
});
