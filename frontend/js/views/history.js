import { h } from '../dom.js';
import { LEVEL_LABEL } from '../model.js';
import { levelShape } from '../icons.js';
import { fmtInt, fullDate, plural, relTime } from '../format.js';
import { trendChart } from './trend.js';

/** Every saved analysis: the full-width trend, then the list as a table. */
export function historyView({ reports, failOn, onSelect }) {
  if (!reports.length) {
    return h('section', { class: 'panel' }, h('header', { class: 'panel-head' }, h('h2', null, 'History')), h('p', { class: 'empty' }, 'Analyses you run are kept here, in .changerisk/ inside the repository. Nothing has been run yet.'));
  }
  const failed = reports.filter((r) => r.gate_failed).length;
  return h(
    'div',
    { class: 'stack' },
    h(
      'section',
      { class: 'panel chart-panel', 'aria-labelledby': 'hist-heading' },
      h(
        'header',
        { class: 'panel-head' },
        h('h1', { id: 'hist-heading', class: 'h2' }, 'History'),
        h('p', { class: 'panel-sub' }, `${plural(reports.length, 'analysis', 'analyses')}, ${failed} of them failed the gate. Newest on the right.`),
      ),
      trendChart({ reports, selectedId: null, failOn, onSelect, height: 240 }),
    ),
    h(
      'section',
      { class: 'panel', 'aria-label': 'All analyses' },
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'plain-table history-table' },
          h('thead', null, h('tr', null, ['When', 'Change', 'Level', 'Files', 'Findings', 'Main reasons'].map((t, i) => h('th', { scope: 'col', class: i === 3 || i === 4 ? 'r' : '' }, t)))),
          h(
            'tbody',
            null,
            reports.map((r) =>
              h(
                'tr',
                { data: { level: r.level } },
                h('td', { class: 'nowrap' }, h('time', { datetime: r.generated_at, title: fullDate(r.generated_at) }, relTime(r.generated_at))),
                h('th', { scope: 'row' }, h('a', { class: 'mono', href: `#/r/${r.id}` }, r.head), r.base && r.mode === 'range' ? h('div', { class: 'dim small' }, `into ${r.base}`) : null),
                h('td', { class: 'nowrap' }, h('span', { class: 'level-cell' }, levelShape(r.level, 13, { label: false }), h('span', { class: 'num' }, r.score), h('span', { class: 'dim' }, LEVEL_LABEL[r.level]))),
                h('td', { class: 'r num' }, fmtInt(r.files)),
                h('td', { class: 'r num' }, fmtInt(r.findings)),
                h('td', { class: 'dim' }, r.top.length ? r.top.join(', ') : 'Nothing flagged'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
