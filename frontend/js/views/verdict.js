import { h, announce } from '../dom.js';
import { LEVEL_LABEL, rangeLabel } from '../model.js';
import { levelShape, icon } from '../icons.js';
import { ruler } from './ruler.js';
import { fmtInt, fmtPoints, fullDate, plural, relTime, shortRef } from '../format.js';
import { copyText } from '../clipboard.js';
import { api, fetchText } from '../api.js';

export function changeHeader(report, { onRerun, canExport }) {
  const range = rangeLabel(report.range);
  const sha = report.range.head_sha ? report.range.head_sha.slice(0, 8) : null;
  const meta = [
    plural(report.stats.files, 'file'),
    h('span', { class: 'delta' }, h('span', { class: 'add num' }, `+${fmtInt(report.stats.additions)}`), ' ', h('span', { class: 'del num' }, `−${fmtInt(report.stats.deletions)}`)),
    report.stats.commits ? plural(report.stats.commits, 'commit') : null,
    h('time', { datetime: report.generated_at, title: fullDate(report.generated_at) }, `analysed ${relTime(report.generated_at)}`),
  ].filter(Boolean);

  const actions = [];
  if (canExport && report.id) {
    actions.push(
      h('button', { type: 'button', class: 'btn', onClick: () => copyMarkdown(report) }, icon('copy', 15), 'Copy Markdown'),
      exportLinks(report),
    );
  }
  if (onRerun) {
    actions.push(h('button', { type: 'button', class: 'btn', onClick: onRerun }, icon('refresh', 15), 'Run again'));
  }

  return h(
    'section',
    { class: 'change', 'aria-label': 'Change under review' },
    h(
      'h1',
      { class: 'change-refs' },
      h('span', { class: `ref ${range.plain ? 'ref-plain' : ''}`, title: range.from }, shortRef(range.from)),
      h('span', { class: 'ref-join', 'aria-label': 'compared with' }, range.plain ? 'vs' : '…'),
      h('span', { class: 'ref', title: range.to }, shortRef(range.to)),
      sha ? h('span', { class: 'sha mono', title: 'Head commit' }, sha) : null,
    ),
    h(
      'div',
      { class: 'change-row' },
      h('p', { class: 'change-meta' }, meta.flatMap((m, i) => (i ? [h('span', { class: 'sep', 'aria-hidden': 'true' }, '·'), m] : [m]))),
      actions.length ? h('div', { class: 'change-actions' }, actions) : null,
    ),
  );
}

async function copyMarkdown(report) {
  try {
    const text = await fetchText(api.exportUrl(report.id, 'markdown'));
    await copyText(text, 'Markdown copied');
  } catch (error) {
    announce(error.message);
  }
}

function exportLinks(report) {
  const link = (format, label) =>
    h('a', { class: 'menu-item', href: api.exportUrl(report.id, format), download: '' }, label);
  return h(
    'details',
    { class: 'menu' },
    h('summary', { class: 'btn' }, icon('download', 15), 'Export', icon('chevron', 12)),
    h('div', { class: 'menu-pop' }, link('html', 'HTML report (one file)'), link('json', 'JSON'), link('sarif', 'SARIF for code scanning'), link('markdown', 'Markdown')),
  );
}

export function verdictPanel(report) {
  const level = report.level;
  const gate = report.gate;
  const gateChip =
    gate.fail_on === 'never'
      ? h('span', { class: 'gate-chip', data: { state: 'off' } }, 'Gate off')
      : h('span', { class: 'gate-chip', data: { state: gate.failed ? 'failed' : 'passed' } }, gate.failed ? 'Gate failed' : 'Gate passed');

  return h(
    'section',
    { class: 'verdict', data: { level }, 'aria-labelledby': 'verdict-heading' },
    h(
      'div',
      { class: 'verdict-score' },
      h('div', { class: 'score-num', 'aria-hidden': 'true' }, report.score),
      h('div', { class: 'score-of' }, 'out of 100'),
    ),
    h(
      'div',
      { class: 'verdict-body' },
      h(
        'h2',
        { class: 'verdict-level', id: 'verdict-heading' },
        levelShape(level, 22, { label: false }),
        h('span', null, `${LEVEL_LABEL[level]} risk`),
        gateChip,
      ),
      h('p', { class: 'verdict-text' }, report.verdict),
      h('p', { class: 'verdict-next' }, h('span', { class: 'eyebrow' }, 'Next'), report.recommendation),
    ),
    h('div', { class: 'verdict-ruler' }, ruler({ score: report.score, level, failOn: gate.fail_on })),
    scoreExplainer(report),
    report.notes.length
      ? h('ul', { class: 'notes' }, report.notes.map((n) => h('li', null, n)))
      : null,
  );
}

function scoreExplainer(report) {
  return h(
    'details',
    { class: 'how' },
    h('summary', null, 'How this score is built'),
    h(
      'div',
      { class: 'how-body' },
      h(
        'p',
        null,
        'Each finding is worth points by severity: low 3, medium 8, high 16, critical 30. A rule that fires again counts for half, then a quarter, so ten similar hits do not bury everything else.',
      ),
      h(
        'p',
        null,
        `The findings below add up to ${fmtPoints(report.points)} points. The score is `,
        h('code', null, '100 × (1 − e^(−points/40))'),
        `, which gives ${report.score}. It saturates smoothly and never passes 100.`,
      ),
      h('p', null, 'A critical finding makes the level at least High, and a high finding at least Moderate, however the points add up.'),
      report.floor_note ? h('p', { class: 'floor' }, report.floor_note) : null,
    ),
  );
}
