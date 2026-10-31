import { h, mount } from '../dom.js';
import { icon } from '../icons.js';
import { recall, remember } from '../store.js';
import { SAMPLE_DIFF } from '../sample-diff.js';

const PREFS = 'changerisk.source-form';
const GATES = [
  ['high', 'High'],
  ['moderate', 'Moderate'],
  ['critical', 'Critical'],
  ['never', 'Never'],
];
const SOURCES = [
  { id: 'github', label: 'GitHub pull request' },
  { id: 'diff', label: 'Paste a diff' },
];

const kb = (text) => Math.ceil(new Blob([text]).size / 1024);

/**
 * The input for the hosted dashboard: a public GitHub pull request, or a diff pasted in.
 * The pasted diff is not remembered between visits; only the choice of tab and gate is.
 */
export function renderSourceForm(root, { busy, error, limits, onAnalyze }) {
  const saved = recall(PREFS, {});
  const state = {
    source: SOURCES.some((s) => s.id === saved.source) ? saved.source : 'github',
    failOn: GATES.some(([id]) => id === saved.failOn) ? saved.failOn : 'high',
    problem: null,
  };
  const maxKb = limits ? limits.max_diff_kb : 2048;

  const url = h('input', {
    id: 's-url',
    type: 'text',
    name: 'url',
    placeholder: 'https://github.com/owner/repo/pull/123',
    autocomplete: 'off',
    spellcheck: 'false',
    inputmode: 'url',
  });
  const diff = h('textarea', {
    id: 's-diff',
    name: 'diff',
    rows: 9,
    spellcheck: 'false',
    autocomplete: 'off',
    placeholder: 'Paste the output of git diff',
    onInput: () => sync(),
  });
  const size = h('span', { class: 'source-size dim small num' });
  const problem = h('p', { class: 'form-error', role: 'alert', hidden: true });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary', disabled: busy || null }, busy ? 'Analysing…' : 'Analyse');

  const gate = h(
    'select',
    {
      id: 's-gate',
      name: 'fail_on',
      onChange: (e) => {
        state.failOn = e.target.value;
        remember(PREFS, { source: state.source, failOn: state.failOn });
      },
    },
    GATES.map(([id, label]) => h('option', { value: id, selected: id === state.failOn || null }, label)),
  );

  const file = h('input', {
    type: 'file',
    id: 's-file',
    class: 'visually-hidden',
    accept: '.diff,.patch,.txt,text/plain',
    onChange: async (event) => {
      const chosen = event.target.files && event.target.files[0];
      if (!chosen) return;
      if (chosen.size > maxKb * 1024) return show(`That file is larger than ${maxKb} KB.`);
      diff.value = await chosen.text();
      choose('diff');
      sync();
    },
  });

  function show(message) {
    state.problem = message;
    problem.hidden = !message;
    problem.replaceChildren(...(message ? [icon('x', 14), message] : []));
  }

  function sync() {
    const length = kb(diff.value);
    size.textContent = diff.value ? `${length} KB of ${maxKb} KB` : '';
    size.dataset.over = String(length > maxKb);
    for (const pane of root.querySelectorAll('.source-pane')) pane.hidden = pane.dataset.pane !== state.source;
    for (const input of root.querySelectorAll('input[name="source"]')) input.checked = input.value === state.source;
  }

  function choose(id) {
    state.source = id;
    remember(PREFS, { source: id, failOn: state.failOn });
    sync();
  }

  const tabs = h(
    'div',
    { class: 'segmented', role: 'radiogroup', 'aria-label': 'Where the change comes from' },
    SOURCES.map((s) =>
      h(
        'label',
        { class: 'seg' },
        h('input', { type: 'radio', name: 'source', value: s.id, checked: state.source === s.id || null, onChange: () => choose(s.id) }),
        h('span', null, s.label),
      ),
    ),
  );

  const form = h(
    'form',
    {
      class: 'source-form',
      novalidate: true,
      onSubmit: (event) => {
        event.preventDefault();
        show(null);
        if (state.source === 'github') {
          const value = url.value.trim();
          if (!value) return show('Enter a public GitHub pull request, such as https://github.com/owner/repo/pull/123.');
          return onAnalyze({ source: { type: 'github', url: value }, fail_on: state.failOn });
        }
        if (!diff.value.trim()) return show('Paste a diff first, or load the example.');
        if (kb(diff.value) > maxKb) return show(`That diff is larger than ${maxKb} KB. Analyse a smaller change, or run ChangeRisk locally.`);
        return onAnalyze({ source: { type: 'diff', text: diff.value }, fail_on: state.failOn });
      },
    },
    h(
      'div',
      { class: 'source-head' },
      tabs,
      h('div', { class: 'field field-gate' }, h('label', { for: 's-gate' }, 'Fail the gate at'), gate),
    ),
    h(
      'div',
      { class: 'source-pane', data: { pane: 'github' } },
      h('div', { class: 'field' }, h('label', { for: 's-url' }, 'Pull request'), url),
      h('p', { class: 'source-hint' }, 'Public repositories only. A compare link or owner/repo#123 works too.'),
    ),
    h(
      'div',
      { class: 'source-pane', data: { pane: 'diff' } },
      h('div', { class: 'field' }, h('label', { for: 's-diff' }, 'Diff'), diff),
      h(
        'div',
        { class: 'source-tools' },
        h('label', { class: 'btn btn-quiet', for: 's-file' }, 'Choose a .diff or .patch file'),
        file,
        h('button', { type: 'button', class: 'btn btn-quiet', onClick: () => { diff.value = SAMPLE_DIFF; choose('diff'); sync(); diff.focus(); } }, 'Load an example'),
        size,
      ),
    ),
    h(
      'div',
      { class: 'source-foot' },
      h('p', { class: 'privacy' }, 'Diffs are analysed in memory and are not stored or logged. Reports stay in this browser.'),
      submit,
    ),
  );

  // On a phone the form folds away once there is a report to read.
  const narrow = window.matchMedia('(max-width: 700px)');
  const wrapper = h(
    'details',
    { class: 'toolbar-details', open: !narrow.matches || error || busy || null },
    h('summary', { class: 'toolbar-summary' }, h('span', null, 'Analyse a change'), icon('chevron', 14)),
    h('div', { class: 'toolbar-body' }, form),
  );
  narrow.addEventListener('change', (event) => { wrapper.open = !event.matches; });

  mount(root, wrapper, h('div', { class: 'source-problems' }, problem, error ? h('p', { class: 'form-error', role: 'alert' }, icon('x', 14), error) : null));
  sync();
}
