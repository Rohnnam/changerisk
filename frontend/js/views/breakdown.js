import { h } from '../dom.js';
import { fmtPoints, plural } from '../format.js';
import { attachTip } from '../tooltip.js';
import { icon } from '../icons.js';

/**
 * Points per area as horizontal bars. One series, so one colour; values sit at the bar tips.
 * The same numbers are available as a table for anyone who wants them that way.
 */
export function breakdownPanel(report) {
  const rows = report.categories;
  const max = Math.max(1, ...rows.map((r) => r.points));

  const body = rows.length
    ? h(
        'ul',
        { class: 'cats' },
        rows.map((row) => {
          const item = h(
            'li',
            { class: 'cat', tabindex: '0', 'aria-label': `${row.label}: ${fmtPoints(row.points)} points from ${plural(row.findings, 'finding')}` },
            h('span', { class: 'cat-label' }, row.label),
            h(
              'span',
              { class: 'cat-bar-area' },
              h('span', { class: 'cat-bar', vars: { '--p': String(row.points / max) } }),
              h('span', { class: 'cat-value num' }, fmtPoints(row.points)),
            ),
          );
          attachTip(item, () => [
            h('strong', null, row.label),
            h('div', null, `${fmtPoints(row.points)} points from ${plural(row.findings, 'finding')}`),
          ]);
          return item;
        }),
      )
    : h('p', { class: 'empty' }, 'No points scored in any area.');

  const table = h(
    'details',
    { class: 'twin' },
    h('summary', null, icon('table', 14), 'View as table'),
    h(
      'table',
      { class: 'plain-table' },
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'Area'), h('th', { scope: 'col', class: 'r' }, 'Findings'), h('th', { scope: 'col', class: 'r' }, 'Points'))),
      h('tbody', null, rows.map((r) => h('tr', null, h('th', { scope: 'row' }, r.label), h('td', { class: 'r num' }, r.findings), h('td', { class: 'r num' }, fmtPoints(r.points))))),
    ),
  );

  return h(
    'section',
    { class: 'panel chart-panel', 'aria-labelledby': 'cats-heading' },
    h('header', { class: 'panel-head' }, h('h2', { id: 'cats-heading' }, 'Where the points come from'), h('p', { class: 'panel-sub' }, 'Points per area of the change.')),
    body,
    rows.length ? table : null,
  );
}
