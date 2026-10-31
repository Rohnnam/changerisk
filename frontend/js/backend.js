import { api, fetchText, renderReport, ApiError } from './api.js';
import { getLocal, listLocal, removeLocal, saveLocal } from './local-store.js';
import { downloadText, EXPORT_TYPES } from './download.js';
import { copyText } from './clipboard.js';

/**
 * Where reports come from. The local dashboard talks to a server that owns a repository and keeps
 * reports on disk. The hosted dashboard has no repository and keeps nothing: reports live in this
 * browser, and exports are rendered by the server from the report the browser sends back.
 */
export function serverBackend() {
  return {
    hosted: false,
    reports: async () => (await api.reports()).reports,
    report: (id) => api.report(id),
    remove: (id) => api.remove(id),
    analyze: (payload) => api.analyze(payload),
    exporter: (report) => ({
      copyMarkdown: async () => copyText(await fetchText(api.exportUrl(report.id, 'markdown')), 'Markdown copied'),
      download: async (format) => {
        const type = EXPORT_TYPES[format];
        downloadText(`changerisk-${report.id}.${type.ext}`, await fetchText(api.exportUrl(report.id, format)), type.mime);
      },
    }),
  };
}

export function hostedBackend() {
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
    analyze: async (payload) => saveLocal(await api.analyzeSource(payload)),
    exporter: (report) => ({
      copyMarkdown: async () => copyText(await renderReport('markdown', report), 'Markdown copied'),
      download: async (format) => {
        const type = EXPORT_TYPES[format];
        downloadText(`changerisk-report.${type.ext}`, await renderReport(format, report), type.mime);
      },
    }),
  };
}
