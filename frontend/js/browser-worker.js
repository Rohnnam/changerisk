// Runs ChangeRisk's Python engine inside the page, off the main thread, through Pyodide.
//
// This is a classic worker script (not an ES module), loaded by backend.js from a Blob so that
// it can be served from a CDN. Messages in:
//   { id, op: 'init', config: { pyodide, bundle } }
//   { id, op: 'analyze', payload }
//   { id, op: 'render', format, report }
//   { id, op: 'rules' }
// Messages out: { id, ok: true, result } or { id, ok: false, error }, plus { progress } while starting.

let engine = null;
let starting = null;

function progress(text) {
  postMessage({ progress: text });
}

async function start(config) {
  progress('Loading Python…');
  importScripts(`${config.pyodide}pyodide.js`);
  const py = await loadPyodide({ indexURL: config.pyodide });

  progress('Loading ChangeRisk…');
  const response = await fetch(config.bundle);
  if (!response.ok) throw new Error(`Could not load the analysis code (status ${response.status}).`);
  const bundle = await response.json();
  const root = '/changerisk-src';
  for (const [path, text] of Object.entries(bundle.files)) {
    const full = `${root}/${path}`;
    py.FS.mkdirTree(full.slice(0, full.lastIndexOf('/')));
    py.FS.writeFile(full, text);
  }
  py.runPython(`import sys\nsys.path.insert(0, "${root}")\nimport changerisk.browser as cb`);
  engine = py.globals.get('cb');
  return bundle.version;
}

// A Python exception arrives with a full traceback; the person only needs the last line.
function plain(error) {
  const text = String((error && error.message) || error);
  const lines = text.trim().split('\n');
  const last = lines[lines.length - 1] || text;
  return last.replace(/^\w*(Error|Exception):\s*/, '');
}

onmessage = async ({ data }) => {
  const { id, op } = data;
  try {
    if (op === 'init') {
      starting = starting || start(data.config);
      try {
        postMessage({ id, ok: true, result: await starting });
      } catch (error) {
        starting = null; // the page may ask again
        throw error;
      }
      return;
    }
    await starting;
    if (!engine) throw new Error('The analysis engine did not start.');
    let result;
    if (op === 'analyze') result = engine.analyze(JSON.stringify(data.payload));
    else if (op === 'render') result = engine.render(data.format, JSON.stringify(data.report));
    else if (op === 'rules') result = engine.rules();
    else throw new Error(`Unknown operation ${op}.`);
    postMessage({ id, ok: true, result });
  } catch (error) {
    postMessage({ id, ok: false, error: plain(error) });
  }
};
