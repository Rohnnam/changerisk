import { h } from '../dom.js';
import { SEVERITY_LEVEL, flagIndex } from '../model.js';
import { severityShape } from '../icons.js';

/**
 * A unified diff with the lines the rules quoted marked in the gutter, and the rule's note
 * under each, like a review comment would be.
 */
export function diffView(report, file) {
  if (!file.hunks || !file.hunks.length) {
    return h(
      'p',
      { class: 'diff-empty' },
      file.binary
        ? 'Binary file: no text diff.'
        : 'No diff is stored for this file. Reports keep diffs only for files with findings.',
    );
  }
  const flags = flagIndex(report, file.path);
  const rows = [];
  for (const hunk of file.hunks) {
    rows.push(
      h(
        'tr',
        { class: 'hunk' },
        h('td', { colspan: 5 }, `@@ -${hunk.old_start} +${hunk.new_start} @@`, hunk.header ? ` ${hunk.header}` : ''),
      ),
    );
    for (const [kind, oldNo, newNo, text] of hunk.lines) {
      const hits = (kind === '-' ? flags.get(`o${oldNo}`) : flags.get(`n${newNo}`)) || [];
      const top = hits.length ? hits.reduce((a, b) => (b.points > a.points ? b : a)) : null;
      rows.push(
        h(
          'tr',
          { class: `dl ${kind === '+' ? 'add' : kind === '-' ? 'del' : 'ctx'}`, data: { flagged: top ? SEVERITY_LEVEL[top.severity] : null } },
          h('td', { class: 'flag' }, top ? severityShape(top.severity, 11) : null),
          h('td', { class: 'ln num' }, oldNo ?? ''),
          h('td', { class: 'ln num' }, newNo ?? ''),
          h('td', { class: 'sign', 'aria-label': kind === '+' ? 'added' : kind === '-' ? 'removed' : 'unchanged' }, kind === ' ' ? '' : kind === '-' ? '−' : '+'),
          h('td', { class: 'code' }, h('code', null, text || ' ')),
        ),
      );
      for (const f of hits) {
        rows.push(
          h(
            'tr',
            { class: 'note', data: { level: SEVERITY_LEVEL[f.severity] } },
            h('td', { colspan: 5 }, h('span', { class: 'note-card' }, severityShape(f.severity, 12), h('span', { class: 'note-rule mono' }, f.rule), h('span', { class: 'note-title' }, f.title), h('span', { class: 'note-detail' }, f.detail))),
          ),
        );
      }
    }
  }
  return h(
    'div',
    { class: 'diff', role: 'region', 'aria-label': `Diff of ${file.path}`, tabindex: '0' },
    h('table', { class: 'diff-table' }, h('tbody', null, rows)),
    file.truncated ? h('p', { class: 'diff-trunc' }, 'The diff is cut here to keep reports small. Open the file in your editor for the rest.') : null,
  );
}
