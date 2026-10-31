import { h, mount } from '../dom.js';
import { icon } from '../icons.js';
import { recall, remember } from '../store.js';

const MODES = [
  { id: 'range', label: 'Branch' },
  { id: 'staged', label: 'Staged' },
  { id: 'worktree', label: 'Working tree' },
];
const PREFS = 'changerisk.form';

function refOptions(refs, selected) {
  const local = refs.filter((r) => r.kind === 'branch');
  const remote = refs.filter((r) => r.kind === 'remote');
  const tags = refs.filter((r) => r.kind === 'tag');
  const group = (label, items) =>
    items.length
      ? h('optgroup', { label }, items.map((r) => h('option', { value: r.name, selected: r.name === selected || null }, r.name)))
      : null;
  return [group('Branches', local), group('Remote branches', remote), group('Tags', tags)];
}

/** The strip at the top of the page where a new analysis is set up and started. */
export function renderToolbar(root, { repo, busy, error, onAnalyze }) {
  const saved = recall(PREFS, {});
  const refs = repo.refs;
  const names = new Set(refs.map((r) => r.name));
  const head0 = names.has(saved.head) ? saved.head : repo.branch && names.has(repo.branch) ? repo.branch : 'HEAD';
  const base0 = names.has(saved.base) ? saved.base : repo.default_base || (refs[0] && refs[0].name) || '';
  const state = { mode: saved.mode || 'range', history: saved.history !== false };

  const baseSel = h('select', { id: 'f-base', name: 'base', 'aria-describedby': 'f-hint' }, refOptions(refs, base0));
  const headSel = h(
    'select',
    { id: 'f-head', name: 'head' },
    h('option', { value: 'HEAD', selected: head0 === 'HEAD' || null }, repo.branch ? `HEAD (${repo.branch})` : 'HEAD'),
    refOptions(refs, head0),
  );
  const refsDisabled = () => state.mode !== 'range';

  const modeGroup = h(
    'div',
    { class: 'segmented', role: 'radiogroup', 'aria-label': 'What to analyse' },
    MODES.map((m) =>
      h(
        'label',
        { class: 'seg' },
        h('input', {
          type: 'radio',
          name: 'mode',
          value: m.id,
          checked: state.mode === m.id || null,
          onChange: () => {
            state.mode = m.id;
            sync();
          },
        }),
        h('span', null, m.label),
      ),
    ),
  );
  const history = h('input', {
    type: 'checkbox',
    id: 'f-history',
    checked: state.history || null,
    onChange: (e) => { state.history = e.target.checked; },
  });
  const hint = h('p', { class: 'toolbar-hint', id: 'f-hint' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', disabled: busy || null }, busy ? 'Analysing…' : 'Analyse');

  function sync() {
    const off = refsDisabled();
    baseSel.disabled = off;
    headSel.disabled = off;
    hint.textContent = {
      range: 'Compares the merge base of the two refs with the head, which is what a pull request shows.',
      staged: 'Looks at what is staged for the next commit, against HEAD.',
      worktree: 'Looks at every uncommitted change, including new files, against HEAD.',
    }[state.mode];
  }

  const form = h(
    'form',
    {
      class: 'toolbar-form',
      novalidate: true,
      onSubmit: (event) => {
        event.preventDefault();
        const values = { mode: state.mode, base: baseSel.value, head: headSel.value, history: state.history };
        remember(PREFS, values);
        onAnalyze(state.mode === 'range' ? values : { mode: state.mode, history: state.history });
      },
    },
    h('div', { class: 'field' }, h('label', { for: 'f-base' }, 'Merge into'), baseSel),
    h('span', { class: 'field-join', 'aria-hidden': 'true' }, '←'),
    h('div', { class: 'field' }, h('label', { for: 'f-head' }, 'Change'), headSel),
    h('div', { class: 'field field-mode' }, h('span', { class: 'label', id: 'f-mode-label' }, 'Analyse'), modeGroup),
    submit,
  );

  // On a phone the form folds away so the report is the first thing on screen.
  const narrow = window.matchMedia('(max-width: 700px)');
  const wrapper = h(
    'details',
    { class: 'toolbar-details', open: !narrow.matches || error || busy || null },
    h('summary', { class: 'toolbar-summary' }, h('span', null, 'Analyse a change'), icon('chevron', 14)),
    h('div', { class: 'toolbar-body' }, form, h('div', { class: 'toolbar-foot' }, hint, h('label', { class: 'check', for: 'f-history' }, history, 'Include history signals'))),
  );
  narrow.addEventListener('change', (event) => { wrapper.open = !event.matches; });

  mount(root, wrapper, error ? h('p', { class: 'form-error', role: 'alert' }, icon('x', 14), error) : null);
  sync();
}
