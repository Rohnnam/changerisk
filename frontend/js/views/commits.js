import { h } from '../dom.js';
import { plural, relTime, fullDate } from '../format.js';

export function commitsPanel(report) {
  if (!report.commits.length) return null;
  return h(
    'details',
    { class: 'panel commits' },
    h('summary', null, h('h2', null, plural(report.commits.length, 'commit'), ' in this change')),
    h(
      'ol',
      { class: 'commit-list' },
      report.commits.map((c) =>
        h(
          'li',
          { class: 'commit' },
          h('span', { class: 'sha mono' }, c.sha.slice(0, 8)),
          h('span', { class: 'commit-subject' }, c.subject),
          h('span', { class: 'commit-meta dim' }, c.author, ' · ', h('time', { datetime: c.date, title: fullDate(c.date) }, relTime(c.date))),
        ),
      ),
    ),
  );
}
