import { h } from '../dom.js';
import { levelShape } from '../icons.js';
import { LEVEL_LABEL } from '../model.js';
import { EXAMPLES } from '../sample-diff.js';

// A real, public pull request that edits release workflows. It is here so there is something to
// paste into the GitHub field, not as a recommendation about the project.
export const REAL_PULL = { url: 'https://github.com/pallets/flask/pull/5000', label: 'pallets/flask#5000' };

/** What to try when there is no change to hand: three built-in diffs and one real pull request. */
export function examplesPanel({ busy, onDiff, onPull }) {
  return h(
    'section',
    { class: 'examples', 'aria-labelledby': 'examples-head' },
    h('h2', { id: 'examples-head', class: 'examples-head' }, 'No change to hand? Try one'),
    h(
      'ul',
      { class: 'example-list' },
      EXAMPLES.map((example) =>
        h(
          'li',
          null,
          h(
            'button',
            { type: 'button', class: 'example', data: { level: example.expect }, disabled: busy || null, onClick: () => onDiff(example) },
            h('span', { class: 'example-level' }, levelShape(example.expect, 12, { label: false }), `${LEVEL_LABEL[example.expect]} risk`),
            h('span', { class: 'example-title' }, example.title),
            h('span', { class: 'example-summary' }, example.summary),
          ),
        ),
      ),
    ),
    h(
      'p',
      { class: 'dim small' },
      'These three are built in and need no network. For a real one, ',
      h('button', { type: 'button', class: 'link-button', disabled: busy || null, onClick: onPull }, `analyse ${REAL_PULL.label}`),
      ', which edits release workflows. It is fetched from GitHub, so it counts against GitHub\u2019s limit for anonymous requests.',
    ),
  );
}
