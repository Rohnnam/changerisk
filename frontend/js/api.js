export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  const options = { method, headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError('Could not reach the ChangeRisk server. Is it still running?', 0);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // an empty or non-JSON body is handled below by status
  }
  if (!response.ok) {
    throw new ApiError((data && data.error) || `The server answered ${response.status}.`, response.status);
  }
  return data;
}

export const api = {
  repo: () => request('GET', '/api/repo'),
  rules: () => request('GET', '/api/rules'),
  reports: () => request('GET', '/api/reports'),
  report: (id) => request('GET', `/api/reports/${encodeURIComponent(id)}`),
  analyze: (payload) => request('POST', '/api/analyze', payload),
  remove: (id) => request('DELETE', `/api/reports/${encodeURIComponent(id)}`),
  exportUrl: (id, format) => `/api/reports/${encodeURIComponent(id)}/export?format=${format}`,
  // hosted dashboard: the change arrives as a pasted diff or a GitHub URL, and nothing is stored server-side
  analyzeSource: (payload) => request('POST', '/api/analyze', payload),
};

/** Ask the hosted server to render a report the browser holds as Markdown, SARIF, HTML and so on. */
export async function renderReport(format, report) {
  let response;
  try {
    response = await fetch('/api/render', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, report }),
    });
  } catch {
    throw new ApiError('Could not reach the ChangeRisk server.', 0);
  }
  if (!response.ok) {
    let message = `The server answered ${response.status}.`;
    try {
      message = (await response.json()).error || message;
    } catch {
      // keep the status message
    }
    throw new ApiError(message, response.status);
  }
  return response.text();
}

export async function fetchText(url) {
  let response;
  try {
    response = await fetch(url);
  } catch {
    throw new ApiError('Could not reach the ChangeRisk server.', 0);
  }
  if (!response.ok) throw new ApiError(`The server answered ${response.status}.`, response.status);
  return response.text();
}
