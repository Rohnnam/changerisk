import { h, mount, announce } from './dom.js';
import { api, ApiError } from './api.js';
import { createStore } from './store.js';
import { applyTheme, currentTheme, themeSwitch } from './theme.js';
import { LEVEL_LABEL } from './model.js';
import { renderToolbar } from './views/toolbar.js';
import { renderRail } from './views/rail.js';
import { changeHeader, verdictPanel } from './views/verdict.js';
import { reasonsSection } from './views/reasons.js';
import { planSection } from './views/plan.js';
import { breakdownPanel } from './views/breakdown.js';
import { trendPanel } from './views/trend.js';
import { filesSection } from './views/files.js';
import { commitsPanel } from './views/commits.js';
import { historyView } from './views/history.js';
import { rulesView } from './views/rules.js';

const boot = window.__CHANGERISK__ || {};
const STATIC = Boolean(boot.static);

const store = createStore({
  view: 'report',
  reportId: null,
  report: boot.report || null,
  reports: [],
  repo: null,
  rules: null,
  busy: false,
  loading: false,
  error: null,
  loadError: null,
});

const el = {
  nav: document.getElementById('nav'),
  barEnd: document.getElementById('bar-end'),
  toolbar: document.getElementById('toolbar'),
  rail: document.getElementById('rail'),
  main: document.getElementById('main'),
};

// --- routing -----------------------------------------------------------------

function parseHash() {
  const hash = location.hash;
  if (!hash || hash === '#' || hash === '#/') return { view: 'report', id: null };
  if (!hash.startsWith('#/')) return null; // an in-page anchor such as #f3
  const [, area, id] = hash.split('/');
  if (area === 'history') return { view: 'history', id: null };
  if (area === 'rules') return { view: 'rules', id: null };
  if (area === 'r' && id) return { view: 'report', id: decodeURIComponent(id) };
  return { view: 'report', id: null };
}

async function route(first = false) {
  const target = parseHash();
  if (!target) return;
  document.body.dataset.view = target.view;
  const state = store.get();
  let id = target.id;
  if (target.view === 'report' && !id && !STATIC) id = state.reports[0] ? state.reports[0].id : null;

  store.set({ view: target.view, reportId: id, loadError: null });
  renderNav();
  if (target.view === 'rules' && !state.rules) loadRules();
  if (target.view === 'report' && id && (!state.report || state.report.id !== id)) await loadReport(id);
  if (target.view === 'report' && !id && !STATIC) store.set({ report: null });
  renderAll();
  if (!first) {
    window.scrollTo({ top: 0 });
    el.main.focus({ preventScroll: true });
  }
}

async function loadReport(id) {
  store.set({ loading: true });
  renderAll();
  try {
    const report = await api.report(id);
    store.set({ report, loading: false });
  } catch (error) {
    store.set({ loading: false, report: null, loadError: error instanceof ApiError ? error.message : String(error) });
  }
}

async function loadRules() {
  try {
    store.set({ rules: (await api.rules()).rules });
  } catch (error) {
    store.set({ loadError: error.message });
  }
  renderAll();
}

// --- actions -----------------------------------------------------------------

async function refreshReports() {
  const { reports } = await api.reports();
  store.set({ reports });
  return reports;
}

async function analyze(payload) {
  store.set({ busy: true, error: null });
  renderToolbarOnly();
  announce('Analysing. This can take a few seconds on a large change.');
  try {
    const report = await api.analyze(payload);
    await refreshReports();
    store.set({ busy: false, report, reportId: report.id });
    announce(`Analysis finished: ${LEVEL_LABEL[report.level]} risk, score ${report.score}.`);
    if (location.hash === `#/r/${report.id}`) await route();
    else location.hash = `#/r/${report.id}`;
  } catch (error) {
    store.set({ busy: false, error: error.message });
    renderToolbarOnly();
    announce(`Analysis failed. ${error.message}`);
  }
}

async function remove(id) {
  try {
    await api.remove(id);
  } catch (error) {
    store.set({ error: error.message });
  }
  const reports = await refreshReports();
  if (store.get().reportId === id) {
    store.set({ report: null, reportId: null });
    location.hash = reports[0] ? `#/r/${reports[0].id}` : '#/';
    await route();
  } else {
    renderRailOnly();
  }
}

// --- rendering ---------------------------------------------------------------

function renderNav() {
  const { view } = store.get();
  const tabs = STATIC ? [['report', 'Report', '#/']] : [['report', 'Report', '#/'], ['history', 'History', '#/history'], ['rules', 'Rules', '#/rules']];
  mount(el.nav, tabs.map(([id, label, href]) => h('a', { class: 'tab', href, 'aria-current': view === id ? 'page' : null }, label)));
}

function renderBar() {
  const { repo, report } = store.get();
  const name = repo ? repo.name : report ? report.repo : '';
  mount(el.barEnd, name ? h('span', { class: 'bar-repo', title: repo ? repo.path : name }, name, repo && repo.branch ? ` @ ${repo.branch}` : '') : null, themeSwitch());
}

function renderToolbarOnly() {
  const { repo, busy, error } = store.get();
  if (!repo || STATIC) return;
  renderToolbar(el.toolbar, { repo, busy, error, onAnalyze: analyze });
}

function renderRailOnly() {
  if (STATIC) return;
  const { reports, reportId } = store.get();
  renderRail(el.rail, { reports, selectedId: reportId, onDelete: remove });
}

function emptyState() {
  const { repo } = store.get();
  const base = repo && repo.default_base;
  const head = repo && (repo.branch || 'HEAD');
  const can = repo && repo.has_commits && base && base !== head;
  return h(
    'section',
    { class: 'panel empty-state' },
    h('h1', { class: 'h2' }, 'Nothing analysed yet'),
    h('p', null, 'ChangeRisk compares a branch with the one it will merge into, scores the difference, and lists what to test because of it.'),
    can
      ? h('button', { type: 'button', class: 'btn btn-primary', onClick: () => analyze({ mode: 'range', base, head: 'HEAD', history: true }) }, `Analyse ${head} against ${base}`)
      : h('p', { class: 'dim' }, 'Pick two refs above and press Analyse, or analyse staged changes.'),
    h('p', { class: 'dim small' }, 'From a terminal: ', h('code', null, 'changerisk analyze --base main')),
  );
}

function reportView(report) {
  const { reports } = store.get();
  const failOn = report.gate.fail_on;
  const select = (id) => { location.hash = `#/r/${id}`; };
  return [
    changeHeader(report, { onRerun: STATIC ? null : () => analyze(report.range.mode === 'range' ? { mode: 'range', base: report.range.base, head: report.range.head, history: true } : { mode: report.range.mode, history: true }), canExport: !STATIC }),
    verdictPanel(report),
    reasonsSection(report),
    planSection(report),
    h('div', { class: 'duo' }, breakdownPanel(report), STATIC ? null : trendPanel({ reports, selectedId: report.id, failOn, onSelect: select })),
    filesSection(report),
    commitsPanel(report),
    h('footer', { class: 'colophon' }, `ChangeRisk ${report.tool_version}. Generated ${new Date(report.generated_at).toLocaleString()}.`),
  ];
}

function renderMain() {
  const s = store.get();
  el.main.classList.toggle('is-loading', s.loading);
  document.title = 'ChangeRisk';
  if (s.view === 'history') {
    mount(el.main, historyView({ reports: s.reports, failOn: s.repo && s.report ? s.report.gate.fail_on : 'high', onSelect: (id) => { location.hash = `#/r/${id}`; } }));
    return;
  }
  if (s.view === 'rules') {
    mount(el.main, s.rules ? rulesView(s.rules) : h('p', { class: 'empty' }, s.loadError || 'Loading rules…'));
    return;
  }
  if (s.loadError) {
    mount(el.main, h('section', { class: 'panel' }, h('h1', { class: 'h2' }, 'That analysis could not be opened'), h('p', null, s.loadError), h('a', { class: 'btn', href: '#/' }, 'Back to the latest')));
    return;
  }
  if (!s.report) {
    mount(el.main, s.loading ? h('p', { class: 'empty' }, 'Loading…') : emptyState());
    return;
  }
  document.title = `${LEVEL_LABEL[s.report.level]} risk (${s.report.score}) · ${s.report.range.head} · ChangeRisk`;
  mount(el.main, reportView(s.report));
}

function renderAll() {
  renderBar();
  renderToolbarOnly();
  renderRailOnly();
  renderMain();
}

// --- start -------------------------------------------------------------------

async function start() {
  applyTheme(currentTheme());
  if (STATIC) {
    document.body.dataset.static = '';
    store.set({ report: boot.report, reportId: boot.report.id || null });
    renderNav();
    renderAll();
    return;
  }
  try {
    const [repo, list] = await Promise.all([api.repo(), api.reports()]);
    store.set({ repo, reports: list.reports });
  } catch (error) {
    mount(el.main, h('section', { class: 'panel' }, h('h1', { class: 'h2' }, 'The dashboard cannot reach its server'), h('p', null, error.message)));
    return;
  }
  window.addEventListener('hashchange', () => route());
  await route(true);
}

start();
