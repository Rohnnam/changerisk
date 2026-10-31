// Vocabulary shared by the views. The thresholds mirror src/changerisk/scoring.py.

export const LEVELS = ['low', 'moderate', 'high', 'critical'];

export const LEVEL_LABEL = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  critical: 'Critical',
};

export const BANDS = [
  { id: 'low', from: 0, to: 25 },
  { id: 'moderate', from: 25, to: 50 },
  { id: 'high', from: 50, to: 75 },
  { id: 'critical', from: 75, to: 100 },
];

export const GATE_SCORE = { moderate: 25, high: 50, critical: 75 };

export function levelForScore(score) {
  let level = 'low';
  for (const band of BANDS) if (score >= band.from) level = band.id;
  return level;
}

// A finding's severity picks the same four-way shape and colour as a report level.
export const SEVERITY_LEVEL = {
  info: 'low',
  low: 'low',
  medium: 'moderate',
  high: 'high',
  critical: 'critical',
};

export const SEVERITY_LABEL = {
  info: 'Info',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

export const STATUS_LETTER = {
  added: 'A',
  modified: 'M',
  deleted: 'D',
  renamed: 'R',
  copied: 'C',
  typechange: 'T',
};

export const STATUS_LABEL = {
  added: 'Added',
  modified: 'Modified',
  deleted: 'Deleted',
  renamed: 'Renamed',
  copied: 'Copied',
  typechange: 'Type changed',
};

export const PRIORITY_GROUPS = [
  { priority: 1, title: 'Before merging', hint: 'Tied to high and critical findings' },
  { priority: 2, title: 'Should do', hint: 'Tied to medium findings' },
  { priority: 3, title: 'If there is time', hint: 'Tied to low findings' },
];

export function groupPlan(steps) {
  return PRIORITY_GROUPS
    .map((g) => ({ ...g, steps: steps.filter((s) => s.priority === g.priority) }))
    .filter((g) => g.steps.length > 0);
}

/** Map "side:line" to the findings that quote that line of a file, for the diff view. */
export function flagIndex(report, path) {
  const index = new Map();
  for (const f of report.findings) {
    for (const ev of f.evidence) {
      if (ev.path !== path || !ev.line) continue;
      const key = `${ev.side === 'old' ? 'o' : 'n'}${ev.line}`;
      if (!index.has(key)) index.set(key, []);
      if (!index.get(key).includes(f)) index.get(key).push(f);
    }
  }
  return index;
}

export function topSeverity(findings) {
  const order = ['info', 'low', 'medium', 'high', 'critical'];
  return findings.reduce((best, f) => (order.indexOf(f.severity) > order.indexOf(best) ? f.severity : best), 'info');
}

export function rangeLabel(range) {
  if (range.mode === 'staged') return { from: 'HEAD', to: 'staged changes', plain: true };
  if (range.mode === 'worktree') return { from: 'HEAD', to: 'working tree', plain: true };
  if (range.mode === 'diff') return { from: '', to: 'pasted diff', plain: true, single: true };
  return { from: range.base, to: range.head, plain: false };
}
