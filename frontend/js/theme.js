import { h } from './dom.js';
import { icon } from './icons.js';
import { recall, remember } from './store.js';

const KEY = 'changerisk.theme';
const CHOICES = [
  { id: 'system', label: 'Match system', icon: 'system' },
  { id: 'light', label: 'Light', icon: 'sun' },
  { id: 'dark', label: 'Dark', icon: 'moon' },
];

export function currentTheme() {
  const saved = recall(KEY, 'system');
  return CHOICES.some((c) => c.id === saved) ? saved : 'system';
}

export function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

export function themeSwitch() {
  const wrap = h('div', { class: 'theme-switch', role: 'group', 'aria-label': 'Colour theme' });
  const paint = () => {
    const now = currentTheme();
    for (const btn of wrap.querySelectorAll('button')) {
      btn.setAttribute('aria-pressed', String(btn.dataset.choice === now));
    }
  };
  for (const c of CHOICES) {
    wrap.append(
      h(
        'button',
        {
          type: 'button',
          class: 'theme-btn',
          title: c.label,
          'aria-label': c.label,
          data: { choice: c.id },
          onClick: () => {
            remember(KEY, c.id);
            applyTheme(c.id);
            paint();
          },
        },
        icon(c.icon, 15),
      ),
    );
  }
  paint();
  return wrap;
}
