import { api, fetchText, renderReport, ApiError } from './api.js';
import { getLocal, listLocal, removeLocal, saveLocal } from './local-store.js';
import { downloadText, EXPORT_TYPES } from './download.js';
import { copyText } from './clipboard.js';

/**
 * Where reports come from. The local dashboard talks to a server that owns a repository and keeps
 * reports on disk. The hosted dashboard has no repository and keeps nothing: reports live in this
 * browser, and exports are rendered by the server from the report the browser sends back. The
 * browser build has no server at all: the engine runs in a worker in this page.
 */
export function serverBackend() {
  return {
    hosted: false,
    reports: async () => (await api.reports()).reports,
    report: (id) => api.report(id),
    remove: (id) => api.remove(id),
    rules: async () => (await api.rules()).rules,
    analyze: (payload) => api.analyze(payload),
    exporter: (report) => ({
      formats: ['html', 'json', 'sarif', 'markdown'],
      copyMarkdown: async () => copyText(await fetchText(api.exportUrl(report.id, 'markdown')), 'Markdown copied'),
      download: async (format) => {
        const type = EXPORT_TYPES[format];
        downloadText(`changerisk-${report.id}.${type.ext}`, await fetchText(api.exportUrl(report.id, format)), type.mime);
      },
    }),
  };
}

/** Reports kept in this browser; the pieces that differ between the hosted and the browser build are passed in. */
function localBackend({ analyze, rules, render, formats }) {
  return {
    hosted: true,
    reports: async () => listLocal(),
    report: async (id) => {
      const report = getLocal(id);
      if (!report) {
        throw new ApiError('That analysis is not stored in this browser. Reports are kept only where they were made.', 404);
      }
      return report;
    },
    remove: async (id) => removeLocal(id),
    rules,
    analyze: async (payload) => saveLocal(await analyze(payload)),
    exporter: (report) => ({
      formats,
      copyMarkdown: async () => copyText(await render('markdown', report), 'Markdown copied'),
      download: async (format) => {
        const type = EXPORT_TYPES[format];
        downloadText(`changerisk-report.${type.ext}`, await render(format, report), type.mime);
      },
    }),
  };
}

export function hostedBackend() {
  return localBackend({
    analyze: (payload) => api.analyzeSource(payload),
    rules: async () => (await api.rules()).rules,
    render: renderReport,
    formats: ['html', 'json', 'sarif', 'markdown'],
  });
}

/** The same dashboard with no server behind it: analysis happens in the page. HTML export needs the server. */
export function browserBackend(engine) {
  return localBackend({
    analyze: (payload) => engine.analyze(payload),
    rules: () => engine.rules(),
    render: (format, report) => engine.render(format, report),
    formats: ['json', 'sarif', 'markdown'],
  });
}
