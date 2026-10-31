import test from 'node:test';
import assert from 'node:assert/strict';

// Just enough of a browser for the engine's main-thread half: fetch, Worker, Blob URLs, a base URI.
globalThis.document = { baseURI: 'https://space.example/app/' };
const created = [];
globalThis.URL.createObjectURL = () => 'blob:fake';
globalThis.URL.revokeObjectURL = () => {};

class FakeWorker {
  constructor(url) {
    this.url = url;
    this.sent = [];
    created.push(this);
  }
  postMessage(message) {
    this.sent.push(message);
    queueMicrotask(() => this.reply(message));
  }
  reply(message) {
    const handler = FakeWorker.handler;
    for (const out of handler(message)) this.onmessage({ data: { id: message.id, ...out } });
  }
}
globalThis.Worker = FakeWorker;

const { createEngine } = await import('../js/browser-engine.js');

const config = { worker: 'js/browser-worker.js', bundle: 'py/changerisk-py.json', pyodide: 'https://cdn.example/pyodide/' };
const answer = (result) => [{ ok: true, result }];

function setup(handler, { workerOk = true } = {}) {
  created.length = 0;
  FakeWorker.handler = handler;
  globalThis.fetch = async () => ({ ok: workerOk, status: workerOk ? 200 : 404, text: async () => '/* worker */' });
}

test('the worker is started once, with every address made absolute', async () => {
  setup((m) => answer(m.op === 'init' ? '0.2.0' : '{}'));
  const engine = createEngine(config);
  const [a, b] = await Promise.all([engine.ready(), engine.ready()]);
  assert.equal(a, '0.2.0');
  assert.equal(b, '0.2.0');
  assert.equal(created.length, 1);
  assert.deepEqual(created[0].sent[0].config, {
    pyodide: 'https://cdn.example/pyodide/',
    bundle: 'https://space.example/app/py/changerisk-py.json',
  });
});

test('progress messages from the worker reach the page', async () => {
  const seen = [];
  setup((m) => (m.op === 'init' ? [{ ok: true, result: '0.2.0' }] : answer('{}')));
  const engine = createEngine(config, (text) => seen.push(text));
  await engine.ready();
  created[0].onmessage({ data: { progress: 'Loading Python…' } });
  assert.deepEqual(seen, ['Loading Python…']);
});

test('a report comes back parsed; an error comes back as an ApiError with its status', async () => {
  const report = { score: 12, level: 'low' };
  setup((m) => {
    if (m.op === 'init') return answer('0.2.0');
    if (m.payload.source.type === 'diff') return answer(JSON.stringify(report));
    return answer(JSON.stringify({ error: 'GitHub could not find that.', status: 404 }));
  });
  const engine = createEngine(config);
  assert.deepEqual(await engine.analyze({ source: { type: 'diff', text: 'x' } }), report);
  await assert.rejects(engine.analyze({ source: { type: 'github', url: 'a/b#1' } }), (e) => e.status === 404 && /could not find/.test(e.message));
});

test('a failure inside the engine is reported in plain words', async () => {
  setup((m) => (m.op === 'init' ? answer('0.2.0') : [{ ok: false, error: 'format must be one of: json' }]));
  const engine = createEngine(config);
  await assert.rejects(engine.render('html', {}), /format must be one of/);
});

test('rules and exports go through the same channel', async () => {
  setup((m) => {
    if (m.op === 'init') return answer('0.2.0');
    if (m.op === 'rules') return answer(JSON.stringify({ rules: [{ id: 'CFG001' }] }));
    return answer(`# ${m.format}`);
  });
  const engine = createEngine(config);
  assert.deepEqual(await engine.rules(), [{ id: 'CFG001' }]);
  assert.equal(await engine.render('markdown', { score: 1 }), '# markdown');
});

test('if the worker file cannot be loaded the page is told how to recover, and may try again', async () => {
  setup(() => answer('0.2.0'), { workerOk: false });
  const engine = createEngine(config);
  await assert.rejects(engine.ready(), /Could not load the analysis engine/);
  globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => '/* worker */' });
  assert.equal(await engine.ready(), '0.2.0');
});

test('a worker that dies fails what was waiting on it', async () => {
  setup((m) => (m.op === 'init' ? answer('0.2.0') : []));
  const engine = createEngine(config);
  await engine.ready();
  const waiting = engine.rules();
  await new Promise((r) => setTimeout(r, 5));
  created[0].onerror({ preventDefault() {} });
  await assert.rejects(waiting, /stopped unexpectedly/);
});
