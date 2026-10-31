import { h, mount } from '../dom.js';
import { levelShape, icon } from '../icons.js';
import { fmtInt, relTime, fullDate, shortRef } from '../format.js';

/** The list of past analyses, newest first. */
export function renderRail(root, { reports, selectedId, onDelete }) {
  const confirming = new Set();

  function draw() {
    mount(
      root,
      h(
        'div',
        { class: 'rail-head' },
        h('h2', { class: 'eyebrow' }, 'Recent analyses'),
        h('span', { class: 'rail-count num dim' }, reports.length),
      ),
      reports.length
        ? h('ul', { class: 'rail-list' }, reports.map((r) => item(r)))
        : h('p', { class: 'rail-empty' }, 'Nothing analysed yet. Pick two refs above and press Analyse.'),
    );
  }

  function item(r) {
    const selected = r.id === selectedId;
    const asking = confirming.has(r.id);
    return h(
      'li',
      { class: 'rail-li', data: { selected: String(selected) } },
      h(
        'a',
        { class: 'rail-item', href: `#/r/${r.id}`, 'aria-current': selected ? 'true' : null, data: { level: r.level } },
        h('span', { class: 'rail-score' }, levelShape(r.level, 13), h('span', { class: 'rail-num num' }, r.score)),
        h(
          'span',
          { class: 'rail-meta' },
          h('span', { class: 'rail-ref mono', title: r.head }, shortRef(r.head, 30)),
          h(
            'span',
            { class: 'rail-sub' },
            h('time', { datetime: r.generated_at, title: fullDate(r.generated_at) }, relTime(r.generated_at)),
            ` · ${fmtInt(r.files)} files`,
            r.gate_failed ? h('span', { class: 'rail-failed' }, ' · gate failed') : null,
          ),
        ),
      ),
      asking
        ? h(
            'span',
            { class: 'rail-confirm' },
            h('button', { type: 'button', class: 'mini danger', onClick: () => onDelete(r.id) }, 'Delete'),
            h('button', { type: 'button', class: 'mini', onClick: () => { confirming.delete(r.id); draw(); } }, 'Keep'),
          )
        : h(
            'button',
            {
              type: 'button',
              class: 'rail-del',
              title: 'Delete this analysis',
              'aria-label': `Delete the analysis of ${r.head}`,
              onClick: () => {
                confirming.add(r.id);
                draw();
              },
            },
            icon('x', 12),
          ),
    );
  }

  draw();
}
