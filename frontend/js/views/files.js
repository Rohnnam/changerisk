import { h, mount } from '../dom.js';
import { STATUS_LABEL, STATUS_LETTER, topSeverity } from '../model.js';
import { icon, severityShape } from '../icons.js';
import { fmtInt, fmtPoints, plural, splitPath } from '../format.js';
import { diffView } from './diff.js';

const COLLAPSED_LIMIT = 12;

export function filesSection(report) {
  const files = report.files;
  const flagged = files.filter((f) => f.findings.length);
  const state = {
    flaggedOnly: flagged.length > 0 && files.length > 6,
    open: new Set(flagged.length ? [flagged[0].path] : []),
    showAll: false,
  };
  const maxLines = Math.max(1, ...files.map((f) => f.additions + f.deletions));
  const section = h('section', { class: 'panel files', 'aria-labelledby': 'files-heading' });
  const findingsById = new Map(report.findings.map((f) => [f.id, f]));

  function draw() {
    const pool = state.flaggedOnly ? flagged : files;
    const rows = state.showAll ? pool : pool.slice(0, COLLAPSED_LIMIT);
    mount(
      section,
      h(
        'header',
        { class: 'panel-head panel-head-split' },
        h(
          'div',
          null,
          h('h2', { id: 'files-heading' }, 'Changed files'),
          h('p', { class: 'panel-sub' }, `${plural(files.length, 'file')}, ${flagged.length} with findings. Riskiest first.`),
        ),
        flagged.length && flagged.length < files.length
          ? h(
              'label',
              { class: 'check' },
              h('input', {
                type: 'checkbox',
                checked: state.flaggedOnly || null,
                onChange: (e) => {
                  state.flaggedOnly = e.target.checked;
                  state.showAll = false;
                  draw();
                },
              }),
              'Only files with findings',
            )
          : null,
      ),
      h(
        'div',
        { class: 'table-wrap' },
        h(
          'table',
          { class: 'file-table' },
          h(
            'thead',
            null,
            h('tr', null, h('th', { scope: 'col', class: 'col-status' }, h('span', { class: 'visually-hidden' }, 'Status')), h('th', { scope: 'col' }, 'File'), h('th', { scope: 'col', class: 'col-size' }, 'Change'), h('th', { scope: 'col', class: 'col-risk' }, 'Risk points')),
          ),
          rows.map((f) => fileRows(f)),
        ),
      ),
      pool.length > COLLAPSED_LIMIT
        ? h('button', { type: 'button', class: 'btn btn-quiet more-btn', onClick: () => { state.showAll = !state.showAll; draw(); } }, state.showAll ? 'Show fewer' : `Show all ${fmtInt(pool.length)}`)
        : null,
    );
  }

  function fileRows(f) {
    const { dir, name } = splitPath(f.path);
    const isOpen = state.open.has(f.path);
    const mine = f.findings.map((id) => findingsById.get(id)).filter(Boolean);
    const top = mine.length ? topSeverity(mine) : null;
    const change = f.additions + f.deletions;
    const rowId = `file-${f.path.replace(/[^a-z0-9]+/gi, '-')}`;

    const main = h(
      'tbody',
      { class: 'file-group', data: { open: String(isOpen) } },
      h(
        'tr',
        { class: 'file-row' },
        h('td', { class: 'col-status' }, h('span', { class: 'status', data: { status: f.status }, title: STATUS_LABEL[f.status] }, STATUS_LETTER[f.status] || '?')),
        h(
          'th',
          { scope: 'row', class: 'col-path' },
          h(
            'button',
            {
              type: 'button',
              class: 'path-btn',
              'aria-expanded': String(isOpen),
              'aria-controls': rowId,
              onClick: () => {
                if (state.open.has(f.path)) state.open.delete(f.path);
                else state.open.add(f.path);
                draw();
              },
            },
            icon('chevron', 12),
            h('span', { class: 'path' }, dir ? h('span', { class: 'path-dir' }, dir) : null, h('span', { class: 'path-name' }, name)),
            f.old_path && f.status === 'renamed' ? h('span', { class: 'was dim' }, `from ${f.old_path}`) : null,
          ),
        ),
        h(
          'td',
          { class: 'col-size' },
          h('div', { class: 'size' }, h('span', { class: 'sizebar', 'aria-hidden': 'true', vars: { '--add': `${(f.additions / maxLines) * 100}%`, '--del': `${(f.deletions / maxLines) * 100}%` } }, h('i', { class: 'a' }), h('i', { class: 'd' })), h('span', { class: 'delta num' }, h('span', { class: 'add' }, `+${fmtInt(f.additions)}`), ' ', h('span', { class: 'del' }, `−${fmtInt(f.deletions)}`))),
        ),
        h(
          'td',
          { class: 'col-risk' },
          top ? h('span', { class: 'risk-cell' }, severityShape(top, 13), h('span', { class: 'num' }, fmtPoints(f.points))) : h('span', { class: 'dim', 'aria-label': 'no findings' }, '—'),
        ),
      ),
    );
    if (isOpen) {
      main.append(
        h(
          'tr',
          { class: 'file-detail', id: rowId },
          h(
            'td',
            { colspan: 4 },
            mine.length
              ? h('ul', { class: 'file-findings' }, mine.map((m) => h('li', null, severityShape(m.severity, 12), h('a', { href: `#${m.id}`, class: 'file-finding-link' }, m.title))))
              : null,
            diffView(report, f),
            change === 0 && !f.hunks ? h('p', { class: 'diff-empty' }, 'No line changes (rename or mode change only).') : null,
          ),
        ),
      );
    }
    return main;
  }

  draw();
  return section;
}

