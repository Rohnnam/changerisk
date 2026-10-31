import { h } from '../dom.js';
import { BANDS, GATE_SCORE, LEVEL_LABEL } from '../model.js';
import { levelShape } from '../icons.js';
import { clamp } from '../format.js';

const SWEEP_MS = 760;

/**
 * The risk ruler: a 0-100 scale cut into the four level bands, with the result marked on it
 * and the build gate marked underneath. The fill sweeps from the left once, in step with the marker.
 */
export function ruler({ score, level, failOn }) {
  const gateAt = failOn && failOn !== 'never' ? GATE_SCORE[failOn] : null;
  const value = clamp(score, 0, 100);

  const bands = BANDS.map((band) => {
    const filled = clamp(value - band.from, 0, band.to - band.from);
    const startsAt = value ? (Math.min(value, band.from) / value) * SWEEP_MS : 0;
    const lasts = value ? (filled / value) * SWEEP_MS : 0;
    return h(
      'div',
      { class: 'band', data: { level: band.id } },
      h('div', { class: 'band-track' }, h('i', {
        class: 'band-fill',
        vars: {
          '--fill': `${(filled / (band.to - band.from)) * 100}%`,
          '--delay': `${startsAt.toFixed(0)}ms`,
          '--dur': `${lasts.toFixed(0)}ms`,
        },
      })),
    );
  });

  const names = BANDS.map((band) =>
    h(
      'span',
      { class: 'scale-name', data: { level: band.id }, vars: { '--at': `${(band.from + band.to) / 2}%` } },
      levelShape(band.id, 10, { label: false }),
      LEVEL_LABEL[band.id],
    ),
  );
  const numbers = [0, 25, 50, 75, 100].map((n) =>
    h('span', { class: 'scale-num num', vars: { '--at': `${n}%` }, data: { edge: n === 0 ? 'start' : n === 100 ? 'end' : 'mid' } }, n),
  );

  const description =
    `Score ${score} out of 100, ${level}.` +
    (gateAt !== null ? ` The gate fails from ${failOn}, at ${gateAt}.` : ' The gate is off.');

  return h(
    'figure',
    { class: 'ruler', role: 'img', 'aria-label': description, data: { level } },
    h(
      'div',
      { class: 'ruler-flag', vars: { '--at': `${value}%`, '--sweep': `${SWEEP_MS}ms` } },
      h('span', { class: 'ruler-flag-label num' }, score),
    ),
    h('div', { class: 'ruler-bands' }, bands),
    h('div', { class: 'ruler-marker', vars: { '--at': `${value}%`, '--sweep': `${SWEEP_MS}ms` } }),
    h('div', { class: 'ruler-ticks' }),
    h('div', { class: 'ruler-scale' }, numbers, names),
    gateAt !== null
      ? h(
          'div',
          { class: 'ruler-gate', vars: { '--at': `${gateAt}%` }, data: { side: gateAt > 62 ? 'left' : 'right' } },
          h('span', { class: 'ruler-gate-notch' }),
          h('span', { class: 'ruler-gate-label' }, `Gate: fails from ${LEVEL_LABEL[failOn]} (${gateAt})`),
        )
      : h('div', { class: 'ruler-gate ruler-gate-off' }, h('span', { class: 'ruler-gate-label' }, 'Gate is off')),
  );
}
