import { h, mount } from '../dom.js';
import { SEVERITY_LABEL, SEVERITY_LEVEL } from '../model.js';
import { severityShape } from '../icons.js';
import { plural } from '../format.js';

/** The rule catalogue: what each rule looks for, why it matters, and how to tune it. */
export function rulesView(rules) {
  const state = { query: '', category: 'all' };
  const categories = [...new Map(rules.map((r) => [r.category, r.category_label])).entries()];
  const root = h('div', { class: 'stack' });

  function draw() {
    const q = state.query.trim().toLowerCase();
    const shown = rules.filter(
      (r) =>
        (state.category === 'all' || r.category === state.category) &&
        (!q || `${r.id} ${r.name} ${r.summary}`.toLowerCase().includes(q)),
    );
    const list = h('div', { class: 'rule-list' }, shown.map(ruleRow));
    const count = h('p', { class: 'panel-sub', role: 'status' }, `${plural(shown.length, 'rule')} of ${rules.length}.`);

    let table = root.querySelector('.rule-results');
    if (!table) {
      table = h('div', { class: 'rule-results' });
      mount(
        root,
        h(
          'section',
          { class: 'panel', 'aria-labelledby': 'rules-heading' },
          h('header', { class: 'panel-head' }, h('h1', { id: 'rules-heading', class: 'h2' }, 'Rules'), h('p', { class: 'panel-sub' }, 'Each rule has a stable id. Turn one off or tune it in changerisk.toml.')),
          h(
            'div',
            { class: 'filters' },
            h('div', { class: 'field' }, h('label', { for: 'rule-q' }, 'Search'), h('input', { id: 'rule-q', type: 'search', placeholder: 'id or words', autocomplete: 'off', onInput: (e) => { state.query = e.target.value; draw(); } })),
            h('div', { class: 'field' }, h('label', { for: 'rule-cat' }, 'Area'), h('select', { id: 'rule-cat', onChange: (e) => { state.category = e.target.value; draw(); } }, h('option', { value: 'all' }, 'All areas'), categories.map(([id, label]) => h('option', { value: id }, label)))),
          ),
          table,
        ),
      );
    }
    mount(table, count, list);
  }
  draw();
  return root;
}

function ruleRow(rule) {
  const level = SEVERITY_LEVEL[rule.severity];
  const options = Object.entries(rule.options);
  return h(
    'details',
    { class: 'rule-row', data: { enabled: String(rule.enabled) } },
    h(
      'summary',
      null,
      h('span', { class: 'rule-id mono' }, rule.id),
      h('span', { class: 'rule-name' }, rule.name),
      h('span', { class: 'rule-area dim' }, rule.category_label),
      h('span', { class: 'rule-sev' }, severityShape(rule.severity, 12), h('span', null, SEVERITY_LABEL[rule.severity]), h('span', { class: 'sr-level visually-hidden' }, level)),
      rule.enabled ? null : h('span', { class: 'rule-off' }, 'Off'),
    ),
    h(
      'div',
      { class: 'rule-body' },
      h('p', { class: 'rule-summary' }, rule.summary),
      h('p', { class: 'why' }, rule.why),
      h('h3', { class: 'eyebrow' }, 'What to test'),
      h('ul', { class: 'tests' }, rule.tests.map((t) => h('li', null, t))),
      options.length
        ? h('div', null, h('h3', { class: 'eyebrow' }, 'Options'), h('dl', { class: 'options' }, options.flatMap(([k, v]) => [h('dt', { class: 'mono' }, k), h('dd', { class: 'mono' }, JSON.stringify(v))])))
        : null,
    ),
  );
}
