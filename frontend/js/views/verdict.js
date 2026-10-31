import { h, announce } from '../dom.js';
import { LEVEL_LABEL, rangeLabel } from '../model.js';
import { levelShape, icon } from '../icons.js';
import { ruler } from './ruler.js';
import { fmtInt, fmtPoints, fullDate, plural, relTime, shortRef } from '../format.js';
import { EXPORT_TYPES } from '../download.js';

export function changeHeader(report, { onRerun, exporter }) {
  const range = rangeLabel(report.range);
  const sha = report.range.head_sha ? report.range.head_sha.slice(0, 8) : null;
  const meta = [
    plural(report.stats.files, 'file'),
    h('span', { class: 'delta' }, h('span', { class: 'add num' }, `+${fmtInt(report.stats.additions)}`), ' ', h('span', { class: 'del num' }, `−${fmtInt(report.stats.deletions)}`)),
    report.stats.commits ? plural(report.stats.commits, 'commit') : null,
    h('time', { datetime: report.generated_at, title: fullDate(report.generated_at) }, `analysed ${relTime(report.generated_at)}`),
  ].filter(Boolean);

  const actions = [];
  if (exporter) {
    actions.push(
      h('button', { type: 'button', class: 'btn', onClick: () => attempt(exporter.copyMarkdown) }, icon('copy', 15), 'Copy Markdown'),
      exportMenu(exporter),
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
      range.single
        ? h('span', { class: 'ref ref-plain' }, range.to)
        : [
            h('span', { class: `ref ${range.plain ? 'ref-plain' : ''}`, title: range.from }, shortRef(range.from)),
            h('span', { class: 'ref-join', 'aria-label': 'compared with' }, range.plain ? 'vs' : '…'),
            h('span', { class: 'ref', title: range.to }, shortRef(range.to)),
          ],
      sha ? h('span', { class: 'sha mono', title: 'Head commit' }, sha) : null,
    ),
    sourceLine(report.source),
    h(
      'div',
      { class: 'change-row' },
      h('p', { class: 'change-meta' }, meta.flatMap((m, i) => (i ? [h('span', { class: 'sep', 'aria-hidden': 'true' }, '·'), m] : [m]))),
      actions.length ? h('div', { class: 'change-actions' }, actions) : null,
    ),
  );
}

async function attempt(action) {
  try {
    await action();
  } catch (error) {
    announce(error.message);
  }
}

function exportMenu(exporter) {
  const menu = h('details', { class: 'menu' });
  const item = (format) =>
    h(
      'button',
      {
        type: 'button',
        class: 'menu-item',
        onClick: () => {
          menu.open = false;
          attempt(() => exporter.download(format));
        },
      },
      EXPORT_TYPES[format].label,
    );
  menu.append(
    h('summary', { class: 'btn' }, icon('download', 15), 'Export', icon('chevron', 12)),
    h('div', { class: 'menu-pop' }, ['html', 'json', 'sarif', 'markdown'].map(item)),
  );
  return menu;
}

/** For a pull request: its title and a link back to GitHub. Only https://github.com links are made links. */
function sourceLine(source) {
  if (!source || source.type !== 'github') return null;
  const safe = typeof source.url === 'string' && source.url.startsWith('https://github.com/');
  const label = source.label || source.url;
  return h(
    'p',
    { class: 'source-line' },
    safe ? h('a', { href: source.url, target: '_blank', rel: 'noopener noreferrer' }, label) : h('span', null, label),
    source.title ? h('span', { class: 'source-title' }, source.title) : null,
    source.author ? h('span', { class: 'dim' }, `by ${source.author}`) : null,
    source.state ? h('span', { class: 'sev-word' }, source.state) : null,
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
