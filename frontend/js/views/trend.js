import { h, svg, mount } from '../dom.js';
import { GATE_SCORE, LEVEL_LABEL } from '../model.js';
import { clamp, fullDate, plural, shortDate } from '../format.js';
import { hideTip, showTip } from '../tooltip.js';
import { icon } from '../icons.js';

const MAX_POINTS = 30;

/**
 * Score over the most recent analyses: a thin line, a hairline grid, the gate drawn as a
 * solid rule, and the selected analysis marked. Hover or focus a point for details.
 */
export function trendChart({ reports, selectedId, failOn, onSelect, height = 188 }) {
  const series = [...reports].reverse().slice(-MAX_POINTS); // oldest first
  const wrap = h('div', { class: 'trend' });
  if (series.length < 2) {
    return h(
      'div',
      { class: 'trend trend-empty' },
      h('p', { class: 'empty' }, series.length ? 'One analysis so far. The trend appears after the second.' : 'No analyses yet.'),
    );
  }

  const gate = failOn && failOn !== 'never' ? GATE_SCORE[failOn] : null;
  let drawnWidth = 0;

  function draw(width) {
    drawnWidth = width;
    const m = { top: 14, right: 40, bottom: 26, left: 30 };
    const w = Math.max(240, width);
    const iw = w - m.left - m.right;
    const ih = height - m.top - m.bottom;
    const x = (i) => m.left + (series.length === 1 ? iw / 2 : (i / (series.length - 1)) * iw);
    const y = (v) => m.top + ih - (clamp(v, 0, 100) / 100) * ih;

    const line = series.map((r, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(r.score).toFixed(1)}`).join(' ');
    const area = `${line} L${x(series.length - 1).toFixed(1)} ${y(0)} L${x(0).toFixed(1)} ${y(0)} Z`;

    const grid = [0, 25, 50, 75, 100].map((v) =>
      svg('g', null,
        svg('line', { class: v === 0 ? 'axis' : 'grid', x1: m.left, x2: w - m.right, y1: y(v), y2: y(v) }),
        svg('text', { class: 'tick', x: m.left - 8, y: y(v) + 4, 'text-anchor': 'end' }, v),
      ),
    );

    const crosshair = svg('line', { class: 'crosshair', y1: m.top, y2: y(0), x1: 0, x2: 0, visibility: 'hidden' });
    const dots = series.map((r, i) => {
      const selected = r.id === selectedId;
      const dot = svg('g', { class: `pt ${selected ? 'is-selected' : ''}`, data: { level: r.level }, tabindex: '0', role: 'link', 'aria-label': `${shortDate(r.generated_at)}, ${r.head}, score ${r.score}, ${r.level}. Open this analysis.` },
        svg('circle', { class: 'hit', cx: x(i), cy: y(r.score), r: 13 }),
        svg('circle', { class: 'dot', cx: x(i), cy: y(r.score), r: selected ? 6 : 4.5 }),
      );
      const show = () => {
        crosshair.setAttribute('x1', x(i));
        crosshair.setAttribute('x2', x(i));
        crosshair.setAttribute('visibility', 'visible');
        const box = dot.getBoundingClientRect();
        showTip(box.left + box.width / 2, box.top + box.height / 2, [
          h('strong', null, r.head),
          h('div', null, `Score ${r.score}, ${LEVEL_LABEL[r.level].toLowerCase()} risk`),
          h('div', { class: 'tip-dim' }, `${fullDate(r.generated_at)} · ${plural(r.findings, 'finding')}`),
        ]);
      };
      const leave = () => {
        crosshair.setAttribute('visibility', 'hidden');
        hideTip();
      };
      dot.addEventListener('pointerenter', show);
      dot.addEventListener('pointerleave', leave);
      dot.addEventListener('focus', show);
      dot.addEventListener('blur', leave);
      dot.addEventListener('click', () => onSelect && onSelect(r.id));
      dot.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect && onSelect(r.id);
        }
      });
      return dot;
    });

    const last = series[series.length - 1];
    const picked = series.find((r) => r.id === selectedId) || last;
    const pickedIdx = series.indexOf(picked);
    const label = svg('text', { class: 'end-label', x: x(pickedIdx), y: y(picked.score) - 12, 'text-anchor': 'middle' }, picked.score);

    const chart = svg(
      'svg',
      { class: 'trend-svg', viewBox: `0 0 ${w} ${height}`, width: w, height, role: 'group', 'aria-label': 'Score of recent analyses, oldest to newest' },
      grid,
      gate !== null
        ? svg('g', null,
            svg('line', { class: 'gate-line', x1: m.left, x2: w - m.right, y1: y(gate), y2: y(gate) }),
            svg('text', { class: 'gate-text', x: w - m.right + 6, y: y(gate) + 4 }, 'gate'))
        : null,
      svg('path', { class: 'area', d: area }),
      svg('path', { class: 'line', d: line }),
      crosshair,
      dots,
      label,
      svg('text', { class: 'tick', x: m.left, y: height - 6, 'text-anchor': 'start' }, shortDate(series[0].generated_at)),
      svg('text', { class: 'tick', x: w - m.right, y: height - 6, 'text-anchor': 'end' }, shortDate(last.generated_at)),
    );
    mount(wrap, chart);
  }

  // Draw once the element has a width, and again whenever the container resizes.
  queueMicrotask(() => {
    draw(wrap.getBoundingClientRect().width || 640);
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver((entries) => {
        const width = Math.round(entries[0].contentRect.width);
        if (width && Math.abs(width - drawnWidth) > 1) draw(width);
      }).observe(wrap);
    }
  });
  return wrap;
}

export function trendPanel({ reports, selectedId, failOn, onSelect }) {
  return h(
    'section',
    { class: 'panel chart-panel', 'aria-labelledby': 'trend-heading' },
    h('header', { class: 'panel-head' }, h('h2', { id: 'trend-heading' }, 'Recent scores'), h('p', { class: 'panel-sub' }, 'Newest on the right. Select a point to open it.')),
    trendChart({ reports, selectedId, failOn, onSelect }),
    reports.length > 1 ? trendTable(reports, onSelect) : null,
  );
}

function trendTable(reports, onSelect) {
  return h(
    'details',
    { class: 'twin' },
    h('summary', null, icon('table', 14), 'View as table'),
    h(
      'table',
      { class: 'plain-table' },
      h('thead', null, h('tr', null, h('th', { scope: 'col' }, 'When'), h('th', { scope: 'col' }, 'Branch'), h('th', { scope: 'col', class: 'r' }, 'Score'), h('th', { scope: 'col' }, 'Level'))),
      h('tbody', null, reports.slice(0, 12).map((r) => h('tr', null, h('td', null, shortDate(r.generated_at)), h('th', { scope: 'row' }, h('a', { href: `#/r/${r.id}`, onClick: () => onSelect && onSelect(r.id) }, r.head)), h('td', { class: 'r num' }, r.score), h('td', null, LEVEL_LABEL[r.level])))),
    ),
  );
}
