// Pure formatting helpers. Nothing here touches the DOM, so they run under `node --test`.

const intFormat = new Intl.NumberFormat('en');

export function fmtInt(n) {
  return intFormat.format(Number(n) || 0);
}

export function fmtPoints(p) {
  const n = Number(p) || 0;
  return n.toFixed(1);
}

export function plural(n, one, many) {
  return `${fmtInt(n)} ${n === 1 ? one : (many || `${one}s`)}`;
}

export function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

export function splitPath(path) {
  const i = path.lastIndexOf('/');
  return i < 0 ? { dir: '', name: path } : { dir: path.slice(0, i + 1), name: path.slice(i + 1) };
}

export function shortDate(iso, now = new Date()) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const sameYear = d.getFullYear() === now.getFullYear();
  return new Intl.DateTimeFormat('en', {
    day: 'numeric',
    month: 'short',
    ...(sameYear ? {} : { year: 'numeric' }),
  }).format(d);
}

export function fullDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(d);
}

export function relTime(iso, now = Date.now()) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const seconds = Math.round((now - t) / 1000);
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  return shortDate(iso, new Date(now));
}

export function sentenceCase(text) {
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}

export function shortRef(ref, max = 34) {
  if (!ref || ref.length <= max) return ref || '';
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${ref.slice(0, head)}…${ref.slice(ref.length - tail)}`;
}

/** Turn a report's test plan into a Markdown checklist for pasting into a ticket. */
export function planAsChecklist(plan, done = new Set()) {
  const rows = plan.map((s) => `- [${done.has(s.text) ? 'x' : ' '}] ${s.text}`);
  return rows.join('\n');
}
