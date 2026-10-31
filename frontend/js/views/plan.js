import { h, mount } from '../dom.js';
import { groupPlan } from '../model.js';
import { icon } from '../icons.js';
import { recall, remember } from '../store.js';
import { copyText } from '../clipboard.js';
import { planAsChecklist } from '../format.js';

/** The test plan as a checklist. What you tick is remembered per report, in this browser only. */
export function planSection(report) {
  const key = `changerisk.plan.${report.id || report.generated_at}`;
  const done = new Set(recall(key, []));
  const steps = report.test_plan;
  const section = h('section', { class: 'panel plan', 'aria-labelledby': 'plan-heading' });

  function save() {
    remember(key, [...done]);
  }

  function draw() {
    const groups = groupPlan(steps);
    mount(
      section,
      h(
        'header',
        { class: 'panel-head' },
        h('h2', { id: 'plan-heading' }, 'Test plan'),
        h(
          'p',
          { class: 'panel-sub' },
          steps.length
            ? 'Collected from the findings above, most urgent first. Tick them off as you go.'
            : 'Nothing beyond the normal test run.',
        ),
        steps.length ? progress(done.size, steps.length) : null,
      ),
      groups.map((g) =>
        h(
          'div',
          { class: 'plan-group' },
          h('h3', { class: 'eyebrow plan-group-title' }, g.title, h('span', { class: 'plan-hint' }, g.hint)),
          h(
            'ul',
            { class: 'plan-list' },
            g.steps.map((step) => {
              const id = `step-${steps.indexOf(step)}`;
              return h(
                'li',
                { class: 'plan-item' },
                h('input', {
                  type: 'checkbox',
                  id,
                  checked: done.has(step.text) || null,
                  onChange: (event) => {
                    if (event.target.checked) done.add(step.text);
                    else done.delete(step.text);
                    save();
                    updateProgress();
                  },
                }),
                h('label', { for: id }, step.text, h('span', { class: 'plan-rules mono' }, step.rules.join(' '))),
              );
            }),
          ),
        ),
      ),
      steps.length
        ? h(
            'button',
            { type: 'button', class: 'btn btn-quiet', onClick: () => copyText(planAsChecklist(steps, done), 'Checklist copied') },
            icon('copy', 15),
            'Copy as checklist',
          )
        : null,
    );
  }

  function updateProgress() {
    const bar = section.querySelector('.progress');
    if (bar) bar.replaceWith(progress(done.size, steps.length));
  }

  draw();
  return section;
}

function progress(done, total) {
  return h(
    'p',
    { class: 'progress' },
    h('span', { class: 'progress-track', 'aria-hidden': 'true' }, h('i', { vars: { '--w': `${total ? (done / total) * 100 : 0}%` } })),
    h('span', { class: 'progress-text num' }, `${done} of ${total} done`),
  );
}
