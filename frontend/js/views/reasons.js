import { h, mount } from '../dom.js';
import { SEVERITY_LABEL, SEVERITY_LEVEL } from '../model.js';
import { levelShape } from '../icons.js';
import { fmtInt, fmtPoints, plural } from '../format.js';

const FIRST_PAGE = 8;
const EVIDENCE_INLINE = 3;

/** The ranked list of reasons: the heart of the report. */
export function reasonsSection(report) {
  const state = { category: 'all', expanded: false };
  const section = h('section', { class: 'panel reasons', 'aria-labelledby': 'reasons-heading' });

  function draw() {
    const all = report.findings;
    const visible = all.filter((f) => state.category === 'all' || f.category === state.category);
    const shown = state.expanded ? visible : visible.slice(0, FIRST_PAGE);
    const total = report.points || 1;

    mount(
      section,
      h(
        'header',
        { class: 'panel-head' },
        h('h2', { id: 'reasons-heading' }, 'Why this needs extra testing'),
        h(
          'p',
          { class: 'panel-sub' },
          all.length
            ? `${plural(all.length, 'finding')}, ranked by points. They add up to ${fmtPoints(report.points)}.`
            : 'No rule found anything worth flagging in this change.',
        ),
      ),
      all.length ? categoryFilter(report, state, draw) : emptyState(),
      h(
        'ol',
        { class: 'reason-list' },
        shown.map((f, i) => reason(f, all.indexOf(f) + 1, total, i === 0 && state.category === 'all')),
      ),
      visible.length > FIRST_PAGE
        ? h(
            'button',
            {
              type: 'button',
              class: 'btn btn-quiet more-btn',
              'aria-expanded': String(state.expanded),
              onClick: () => {
                state.expanded = !state.expanded;
                draw();
              },
            },
            state.expanded ? 'Show fewer' : `Show all ${fmtInt(visible.length)}`,
          )
        : null,
    );
  }
  draw();
  return section;
}

function emptyState() {
  return h(
    'p',
    { class: 'empty' },
    'Normal review and the usual test run are enough. Nothing here touches configuration, tests, dependencies, secrets, pipelines or the database in a risky way.',
  );
}

function categoryFilter(report, state, redraw) {
  const cats = [{ id: 'all', label: 'All', findings: report.findings.length }, ...report.categories];
  if (cats.length <= 2) return null;
  return h(
    'div',
    { class: 'chips', role: 'group', 'aria-label': 'Filter reasons by area' },
    cats.map((c) =>
      h(
        'button',
        {
          type: 'button',
          class: 'chip',
          'aria-pressed': String(state.category === c.id),
          onClick: () => {
            state.category = c.id;
            state.expanded = false;
            redraw();
          },
        },
        c.label,
        h('span', { class: 'chip-n num' }, c.findings),
      ),
    ),
  );
}

function reason(f, rank, total, open) {
  const level = SEVERITY_LEVEL[f.severity];
  const inline = f.evidence.slice(0, EVIDENCE_INLINE);
  const rest = f.evidence.slice(EVIDENCE_INLINE);
  const share = Math.max(2, Math.round((f.points / total) * 100));

  return h(
    'li',
    { class: 'reason', id: f.id, data: { level } },
    h('div', { class: 'reason-rank num', 'aria-label': `Rank ${rank}` }, rank),
    h(
      'div',
      { class: 'reason-main' },
      h(
        'div',
        { class: 'reason-head' },
        h(
          'h3',
          { class: 'reason-title' },
          levelShape(level, 15, { label: false }),
          h('span', { class: 'reason-name' }, f.title),
          h('span', { class: 'sev-word' }, SEVERITY_LABEL[f.severity]),
        ),
        h(
          'div',
          { class: 'reason-pts', title: `${fmtPoints(f.points)} of ${fmtPoints(total)} points` },
          h('span', { class: 'pts num' }, `+${fmtPoints(f.points)}`),
          h('span', { class: 'share', 'aria-hidden': 'true' }, h('i', { vars: { '--w': `${share}%` } })),
        ),
      ),
      h('p', { class: 'reason-detail' }, f.detail),
      inline.length ? h('ul', { class: 'evidence' }, inline.map(evidenceRow)) : null,
      h(
        'details',
        { class: 'more', open: open || null },
        h('summary', null, 'Why it matters, and what to test'),
        h(
          'div',
          { class: 'more-body' },
          h('p', { class: 'why' }, f.why),
          f.test_focus.length
            ? h('ul', { class: 'tests' }, f.test_focus.map((t) => h('li', null, t)))
            : null,
          rest.length
            ? h('ul', { class: 'evidence evidence-rest' }, rest.map(evidenceRow))
            : null,
          h('p', { class: 'rule-id mono' }, f.rule, ' · ', f.scope === 'change' ? 'about the whole change' : plural(f.paths.length, 'file')),
        ),
      ),
    ),
  );
}

function evidenceRow(ev) {
  const where = ev.line ? `${ev.path}:${ev.line}` : ev.path;
  return h(
    'li',
    { class: 'ev', data: { side: ev.side } },
    h('span', { class: 'ev-loc mono', title: where }, where),
    h('span', { class: 'ev-sign', 'aria-label': ev.side === 'old' ? 'removed' : 'added' }, ev.side === 'old' ? '−' : '+'),
    h('code', { class: 'ev-text' }, ev.text),
  );
}
