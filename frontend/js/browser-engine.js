import { ApiError } from './api.js';

/**
 * The analysis engine for the browser build: the Python package running in a Web Worker through
 * Pyodide. This is the main-thread side; browser-worker.js is the other.
 *
 * The worker's source is fetched and started from a Blob. A page cannot start a worker from a
 * script on another origin, and the files may be served from a CDN.
 */
export function createEngine(config, onProgress = () => {}) {
  const pending = new Map();
  let worker = null;
  let counter = 0;
  let opening = null;

  const absolute = (path) => new URL(path, document.baseURI).href;

  function send(message) {
    return new Promise((resolve, reject) => {
      counter += 1;
      pending.set(counter, { resolve, reject });
      worker.postMessage({ ...message, id: counter });
    });
  }

  function failAll(error) {
    for (const { reject } of pending.values()) reject(error);
    pending.clear();
  }

  async function open() {
    let source;
    try {
      const response = await fetch(absolute(config.worker));
      if (!response.ok) throw new Error(`status ${response.status}`);
      source = await response.text();
    } catch {
      throw new ApiError('Could not load the analysis engine. Check your connection and reload the page.', 0);
    }
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    worker = new Worker(url);
    URL.revokeObjectURL(url);
    worker.onmessage = ({ data }) => {
      if (data.progress) return onProgress(data.progress);
      const entry = pending.get(data.id);
      if (!entry) return;
      pending.delete(data.id);
      if (data.ok) entry.resolve(data.result);
      else entry.reject(new ApiError(data.error, 0));
    };
    worker.onerror = (event) => {
      event.preventDefault();
      failAll(new ApiError('The analysis engine stopped unexpectedly. Reload the page to restart it.', 0));
    };
    return send({ op: 'init', config: { pyodide: absolute(config.pyodide), bundle: absolute(config.bundle) } });
  }

  /** Start loading (idempotent). Resolves with the bundled ChangeRisk version. */
  function ready() {
    if (!opening) {
      opening = open().catch((error) => {
        opening = null; // a later call may try again
        throw error;
      });
    }
    return opening;
  }

  async function call(message) {
    await ready();
    return send(message);
  }

  return {
    ready,
    /** Resolves with the report, or rejects with the reason the change could not be read. */
    async analyze(payload) {
      const result = JSON.parse(await call({ op: 'analyze', payload }));
      if (result.error) throw new ApiError(result.error, result.status || 0);
      return result;
    },
    async rules() {
      return JSON.parse(await call({ op: 'rules' })).rules;
    },
    /** Markdown, SARIF, JSON or plain text for a report the page holds. */
    render: (format, report) => call({ op: 'render', format, report }),
  };
}
