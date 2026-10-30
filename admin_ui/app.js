/* Sentra by LGTM: интерфейс модератора Grand Mobile. Точка входа: маршруты, обновление, диалоги. Без сборки и зависимостей. */
(() => {
'use strict';
const X = window.Sentra;
const { S, $, $$, esc, ic, nf, dec } = X;

const VIEWS = {
  center: { title: 'Командный центр', sub: () => S.stats && S.stats.tickets.total ? `${nf(S.stats.tickets.total)} обращений в базе Sentra, показатели обновляются сами` : 'Обращений пока нет' },
  queue: { title: 'Очередь', sub: () => S.stats ? `${S.stats.tickets.awaiting} ждут решения администратора, ${S.stats.tickets.in_progress} в работе` : '' },
  duplicates: { title: 'Дубли и спам', sub: () => 'Что сервис отсеял и почему' },
  quality: { title: 'Качество и безопасность', sub: () => 'Что гарантирует код, что измерено сейчас и что измерено оффлайн' },
  templates: { title: 'Шаблоны', sub: () => 'Кандидаты в шаблоны ответов из оффлайн-кластеризации и решения по ним' },
};
const BANNER = {
  rules_synthetic: 'Тестовая база правил (synthetic): номера пунктов в ответах не относятся к правилам Grand Mobile.',
  no_category_model: 'ML-моделей нет: категория определяется только правилами, качество ниже.',
  llm_external: 'LLM включена: тексты обращений уходят во внешний API.',
};
const MODE = { full: 'полный', limited: 'ограниченный', rules_only: 'только правила', unavailable: 'триаж недоступен' };

/* ---------- загрузка ---------- */
const loadHealth = async () => { try { S.health = await X.api('/health'); S.offline = false; } catch { S.health = null; S.offline = true; } };
const loadStats = async () => { try { S.stats = await X.api('/stats'); } catch { S.stats = null; } };
async function loadTemplates() {
  try { S.tpl = await X.api('/templates?only_candidates=false'); } catch { S.tpl = { available: false, hint: 'сервис недоступен' }; }
  const c = $('#c-tpl');
  if (c && S.tpl.available) c.textContent = S.tpl.totals.candidates;
}

/* данные для текущего экрана */
async function loadView() {
  const jobs = [];
  if (S.view === 'center') jobs.push(X.api('/tickets?status=new&limit=6').then(r => { S.attention = r.items; }).catch(() => { S.attention = []; }));
  if (S.view === 'queue') jobs.push(X.loadList().catch(() => { S.list = { items: [], total: 0 }; }));
  if (S.view === 'duplicates') jobs.push(X.api('/duplicates').then(r => { S.dup = r; }).catch(() => { S.dup = { groups: [], spam: [], repeat_reporters: [] }; }));
  if (S.view === 'quality') jobs.push(X.api('/metrics').then(r => { S.metrics = r; }).catch(() => { S.metrics = { available: false }; }));
  if (S.view === 'templates') jobs.push(loadTemplates());
  await Promise.all(jobs);
}

X.refresh = async () => {
  await Promise.all([loadHealth(), loadStats()]);
  await loadView();
  S.version = S.stats ? S.stats.version : -1;
  updateChrome();
  X.render();
};

X.render = full => {
  if (S.view === 'queue') {
    if (full || !$('#ql')) X.renderQueue(); else { X.updateQueueList(); X.syncSelected(); }
    return;
  }
  const fn = { center: X.renderCenter, duplicates: X.renderDuplicates, quality: X.renderQuality, templates: X.renderTemplates }[S.view];
  fn();
};

/* ---------- каркас: навигация, статус, предупреждения ---------- */
function updateChrome() {
  const s = S.stats, h = S.health;
  $('#c-queue').textContent = s ? s.tickets.awaiting : '0';
  $('#c-queue').classList.toggle('hot', !!(s && s.priority.open.p0));
  $('#c-dupes').textContent = s ? s.duplicates.flagged : '0';
  const live = $('#live');
  let label = 'Нет связи', off = true;
  if (h) {
    if (!h.ready) label = 'Триаж недоступен';
    else if (h.mode !== 'full') label = 'Режим: ' + MODE[h.mode];
    else { label = 'Сервис в работе'; off = false; }
  }
  live.classList.toggle('off', off);
  $('span', live).textContent = label;
  live.title = h ? h.problems.map(p => p.text).join('\n') : 'Сервер не отвечает';
  const L = s && s.latency;
  $('#sys').innerHTML = h ? `
    <div class="sys-row"><span>Режим</span><b>${esc(MODE[h.mode] || h.mode)}</b></div>
    <div class="sys-row"><span>Классификатор</span><b>${h.model_loaded ? 'ML и правила' : 'только правила'}</b></div>
    <div class="sys-row"><span>Правила</span><b class="num">${nf(h.rules)}${h.rules_synthetic ? ' · тест' : ''}</b></div>
    <div class="sys-row"><span>LLM</span><b>${h.llm ? 'включена' : 'выключена'}</b></div>
    <div class="sys-row"><span>База</span><b>${h.storage.ok ? nf(h.storage.tickets) + ' обращ.' : 'недоступна'}</b></div>
    <div class="sys-row"><span>Задержка p50</span><b class="num">${L && L.p50 != null ? dec(L.p50) + ' мс' : '—'}</b></div>` :
    '<div class="sys-row"><span>Нет связи с сервисом</span></div>';
  const v = VIEWS[S.view];
  $('#subtitle').textContent = v.sub();
  const bn = $('#banner');
  const probs = h ? h.problems.filter(p => p.level === 'error' || p.code === 'rules_synthetic' || p.code === 'llm_external' || p.code === 'no_category_model') : [];
  const show = !h ? [{ level: 'error', text: 'Нет связи с сервисом: интерфейс не получает данные.' }] : probs;
  bn.hidden = !show.length;
  bn.className = 'banner' + (show.some(p => p.level === 'error') ? ' err' : '');
  bn.innerHTML = show.length ? `${ic('alert')}<div>${show.map(p => `<div>${esc(BANNER[p.code] || p.text)}</div>`).join('')}</div><a class="btn sm" href="#/quality">Диагностика</a>` : '';
  document.documentElement.style.setProperty('--banner-h', show.length ? bn.offsetHeight + 'px' : '0px');
}

/* ---------- маршрутизация ---------- */
async function route(userNav = true) {
  const [name = 'center', id] = location.hash.replace(/^#\/?/, '').split('/');
  const view = VIEWS[name] ? name : 'center';
  const prev = S.view, inQueue = prev === 'queue' && view === 'queue' && $('#ql');
  S.view = view; S.sel = view === 'queue' ? (id ? decodeURIComponent(id) : null) : null;
  $$('#nav a').forEach(a => a.dataset.v === view ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  $('#title').textContent = VIEWS[view].title;
  document.title = VIEWS[view].title + ' · Sentra by LGTM';
  if (view === 'queue' && S.sel) {
    delete S.detail[S.sel];
    const d = await X.loadDetail(S.sel).catch(() => null);      // вкладка списка подстраивается под статус открытой карточки
    if (d && S.filter.tab !== 'all' && S.filter.tab !== X.tabFor(d.status)) {
      S.filter.tab = X.tabFor(d.status);
      if (inQueue) await X.loadList().catch(() => {});
    }
  }
  if (inQueue) {
    $('#ql').dataset.mode = S.sel ? 'detail' : 'list';
    X.updateQueueList(true); X.renderWorkspace();
    return;
  }
  await Promise.all([loadHealth(), loadStats()]);
  await loadView();
  S.version = S.stats ? S.stats.version : -1;
  updateChrome();
  X.render(true);
  if (userNav) $('#view').focus({ preventScroll: true });
}

/* ---------- диалог нового обращения ---------- */
let intakeKey = X.uuid(), intakeBusy = false;
function openIntake() {
  const d = $('#intake');
  if (!d.open) { $('#in-err').hidden = true; d.showModal(); $('#in-text').focus(); }
}
function intakeBody() {
  const v = id => $(id).value.trim();
  const body = { kind: $('#in-kind').value, text: $('#in-text').value, attachments: +$('#in-att').value || 0 };
  [['server', '#in-server'], ['server_lang', '#in-lang'], ['reporter', '#in-rep'], ['reported_nick', '#in-nick'], ['reported_id', '#in-rid']]
    .forEach(([k, id]) => { if (v(id)) body[k] = v(id); });
  const urls = $('#in-urls').value.split(/\s+/).map(s => s.trim()).filter(Boolean);
  if (urls.length) body.evidence_urls = urls;
  return body;
}
async function submitIntake(e) {
  e.preventDefault();
  if (intakeBusy) return;                       // повторное нажатие не создаёт второе обращение
  if (!$('#in-text').value.trim()) { $('#in-text').focus(); return; }
  intakeBusy = true; $('#in-go').disabled = true; $('#in-err').hidden = true;
  try {
    const r = await X.post('/tickets', intakeBody(), { 'Idempotency-Key': intakeKey });
    const t = r.ticket;
    $('#intake').close();
    $('#intake-form').reset(); $('#in-att').value = 0;
    intakeKey = X.uuid();
    S.filter.tab = 'new'; S.filter.pri = 'all'; S.filter.q = '';
    await Promise.all([loadHealth(), loadStats()]);
    location.hash = '#/queue/' + t.id;
    if (S.view === 'queue') route(false);
    X.toast(`Обращение ${t.id} создано и разобрано за ${dec((t.response._meta || {}).latency_ms ?? 0)} мс`);
  } catch (err) {
    const f = err.detail && err.detail.field ? ` (поле: ${err.detail.field})` : '';
    const el = $('#in-err');
    el.hidden = false;
    el.innerHTML = `${ic('stop')}<div><div class="t">Обращение не создано</div><div class="d">${esc(err.message)}${esc(f)}</div></div>`;
  } finally { intakeBusy = false; $('#in-go').disabled = false; }
}

/* ---------- диалог импорта JSONL ---------- */
function openImport() {
  const d = $('#import');
  if (!d.open) { $('#im-res').innerHTML = ''; d.showModal(); }
}
async function submitImport(e) {
  e.preventDefault();
  const f = $('#im-file').files[0];
  const text = f ? await f.text() : $('#im-text').value;
  if (!text.trim()) { $('#im-res').innerHTML = `<div class="check risk">${ic('stop')}<div><div class="t">Нечего импортировать</div><div class="d">Выберите файл или вставьте строки JSONL.</div></div></div>`; return; }
  $('#im-go').disabled = true;
  try {
    const r = await X.api('/tickets/import', { method: 'POST', headers: { 'Content-Type': 'application/x-ndjson' }, body: text });
    const bad = r.errors.length ? `<div class="checks" style="margin-top:10px">${r.errors.map(x => `<div class="check risk">${ic('stop')}<div><div class="t">Строка ${x.line}</div><div class="d">${esc(x.error)}</div></div></div>`).join('')}</div>${r.errors_total > r.errors.length ? `<div class="muted">…и ещё ${r.errors_total - r.errors.length}</div>` : ''}` : '';
    $('#im-res').innerHTML = `<div class="notice ${r.errors_total ? 'warn' : 'ok'}">${ic(r.errors_total ? 'alert' : 'ok')}<span>Строк: ${r.lines}. Импортировано: <b>${r.imported}</b>, уже было: ${r.skipped_existing}, ошибок: ${r.errors_total}. Битые строки пропущены, остальные обработаны.</span></div>${bad}`;
    S.filter.tab = 'new';
    await X.refresh();
  } catch (err) {
    $('#im-res').innerHTML = `<div class="check risk">${ic('stop')}<div><div class="t">Импорт не выполнен</div><div class="d">${esc(err.message)}</div></div></div>`;
  } finally { $('#im-go').disabled = false; }
}

/* ---------- запуск ---------- */
async function poll() {
  const before = S.version;
  await Promise.all([loadHealth(), loadStats()]);
  updateChrome();
  const v = S.stats ? S.stats.version : -1;
  if (v === before) return;
  S.version = v;
  await loadView();
  X.render();
}

function init() {
  document.addEventListener('click', e => {
    if (e.target.closest('[data-new]')) openIntake();
    if (e.target.closest('[data-import]')) openImport();
  });
  $('#new-btn').onclick = openIntake;
  $('#imp-btn').onclick = openImport;
  $('#in-cancel').onclick = () => $('#intake').close();
  $('#im-cancel').onclick = () => $('#import').close();
  $('#intake-form').addEventListener('submit', submitIntake);
  $('#import-form').addEventListener('submit', submitImport);
  [$('#intake'), $('#import')].forEach(d => d.addEventListener('click', e => { if (e.target === e.currentTarget) e.currentTarget.close(); }));
  window.addEventListener('hashchange', () => route(true));
  document.addEventListener('keydown', e => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      if ($('#intake').open) { $('#intake-form').requestSubmit(); e.preventDefault(); }
      else { const b = $('#b-approve'); if (b && !b.disabled) { b.click(); e.preventDefault(); } }
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || $('#intake').open || $('#import').open) return;
    if (e.key === 'n' || e.key === 'т') { e.preventDefault(); openIntake(); }
    if ((e.key === 'j' || e.key === 'k' || e.key === 'о' || e.key === 'л') && S.view === 'queue') {
      const ids = S.list.items.map(q => q.id), i = ids.indexOf(S.sel);
      const nxt = ids[Math.min(ids.length - 1, Math.max(0, i + (e.key === 'j' || e.key === 'о' ? 1 : -1)))];
      if (nxt && nxt !== S.sel) location.hash = '#/queue/' + nxt;
    }
  });
  X.api('/meta').then(m => { S.meta = m; }).catch(() => {}).then(async () => {
    await route(false);
    loadTemplates();
    setInterval(poll, 5000);
  });
}

init();
})();
