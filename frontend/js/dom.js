// Small DOM helpers. No templating, no virtual DOM: the views build real nodes.

const SVG_NS = 'http://www.w3.org/2000/svg';

function apply(el, attrs) {
  if (!attrs) return;
  for (const [key, value] of Object.entries(attrs)) {
    if (value === false || value === null || value === undefined) continue;
    if (key === 'class') {
      el.setAttribute('class', value);
    } else if (key === 'vars') {
      // CSS custom properties are the one place values reach the stylesheet. Setting them
      // through CSSOM keeps the page compatible with a CSP that forbids inline styles.
      for (const [name, v] of Object.entries(value)) el.style.setProperty(name, v);
    } else if (key === 'data') {
      for (const [name, v] of Object.entries(value)) el.dataset[name] = v;
    } else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      el.setAttribute(key, '');
    } else {
      el.setAttribute(key, String(value));
    }
  }
}

function append(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(el, child);
    else el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function mount(parent, ...nodes) {
  parent.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
}

export function announce(message) {
  const live = document.getElementById('live');
  if (!live) return;
  live.textContent = '';
  // A second tick makes screen readers repeat an identical message.
  setTimeout(() => { live.textContent = message; }, 30);
}
