import { announce } from './dom.js';

/** Hand the visitor a file made in the page. Used for exports in the hosted dashboard. */
export function downloadText(filename, text, mime = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type: `${mime};charset=utf-8` }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  announce(`Downloaded ${filename}.`);
}

export const EXPORT_TYPES = {
  html: { label: 'HTML report (one file)', ext: 'html', mime: 'text/html' },
  json: { label: 'JSON', ext: 'json', mime: 'application/json' },
  sarif: { label: 'SARIF for code scanning', ext: 'sarif', mime: 'application/sarif+json' },
  markdown: { label: 'Markdown', ext: 'md', mime: 'text/markdown' },
};
