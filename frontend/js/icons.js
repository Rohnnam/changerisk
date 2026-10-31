import { svg } from './dom.js';
import { SEVERITY_LEVEL, LEVEL_LABEL } from './model.js';

// Four shapes, one per level, so the level never depends on colour alone.
const SHAPES = {
  low: () => svg('circle', { cx: 8, cy: 8, r: 6.4 }),
  moderate: () => svg('polygon', { points: '8,1.6 15.2,14.2 0.8,14.2' }),
  high: () => svg('polygon', { points: '8,0.9 15.1,8 8,15.1 0.9,8' }),
  critical: () => svg('polygon', { points: '5.1,1 10.9,1 15,5.1 15,10.9 10.9,15 5.1,15 1,10.9 1,5.1' }),
};

export function levelShape(level, size = 14, { label = true } = {}) {
  const node = svg(
    'svg',
    {
      class: 'shape',
      viewBox: '0 0 16 16',
      width: size,
      height: size,
      data: { level },
      role: label ? 'img' : null,
      'aria-label': label ? `${LEVEL_LABEL[level]} risk` : null,
      'aria-hidden': label ? null : 'true',
      focusable: 'false',
    },
    SHAPES[level](),
  );
  return node;
}

export function severityShape(severity, size = 14) {
  return levelShape(SEVERITY_LEVEL[severity] || 'low', size, { label: false });
}

const PATHS = {
  chevron: ['M4 6l4 4 4-4'],
  copy: ['M5.5 5.5h7.5v8H5.5z', 'M3 10.5V2.5h7.5'],
  download: ['M8 2.5v8', 'M4.7 7.4L8 10.7l3.3-3.3', 'M3 13.5h10'],
  refresh: ['M13.2 8A5.2 5.2 0 1 1 11.7 4.3', 'M13.4 2.4v2.9h-2.9'],
  check: ['M3.5 8.6l3.1 3.1 6-7.2'],
  x: ['M4 4l8 8', 'M12 4l-8 8'],
  sun: ['M8 5.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6z', 'M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1'],
  moon: ['M13 9.4A5.6 5.6 0 0 1 6.6 3 5.6 5.6 0 1 0 13 9.4z'],
  system: ['M2 3h12v7.6H2z', 'M5.5 13.5h5', 'M8 10.6v2.9'],
  trash: ['M3 4.5h10', 'M6.2 4.5V2.8h3.6v1.7', 'M4.4 4.5l.6 8.7h6l.6-8.7'],
  table: ['M2 3h12v10H2z', 'M2 6.5h12', 'M6 6.5V13'],
  chart: ['M2 13V3', 'M2 13h12', 'M4.5 10l3-3 2.4 2 3.6-4.5'],
};

export function icon(name, size = 16) {
  return svg(
    'svg',
    {
      class: 'icon',
      viewBox: '0 0 16 16',
      width: size,
      height: size,
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': 1.5,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
      focusable: 'false',
    },
    PATHS[name].map((d) => svg('path', { d })),
  );
}
