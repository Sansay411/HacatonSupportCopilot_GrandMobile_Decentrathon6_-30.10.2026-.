/* Sentra by LGTM: очередь и рабочее место модератора. Каждое действие подтверждает сервер; без ответа сервера успех не показывается. */
(() => {
'use strict';
const X = window.Sentra;
const { S, $, $$, esc, ic, dec, rx, clip, ago, fmtTime, catName, intentName, langName } = X;

X.short = q => (typeof q === 'string' ? q : q.id);
X.tabFor = status => (status === 'new' ? 'new' : status === 'closed' ? 'closed' : 'work');

/* ---------- загрузка ---------- */
const TAB_QUERY = { new: 'status=new', work: 'status=approved,escalated', closed: 'status=closed', all: '' };
X.loadList = async () => {
  const f = S.filter, p = [TAB_QUERY[f.tab], f.pri !== 'all' ? 'priority=' + f.pri : '', f.q.trim() ? 'q=' + encodeURIComponent(f.q.trim()) : '', 'limit=200']
    .filter(Boolean).join('&');
  S.list = await X.api('/tickets?' + p);
};
X.loadDetail = async id => {
  try { S.detail[id] = await X.api('/tickets/' + encodeURIComponent(id)); }
  catch (e) { if (e.status === 404) S.detail[id] = null; else throw e; }
  return S.detail[id];
};

/* ---------- список ---------- */
X.renderQueue = () => {
  const v = $('#view'); v.classList.add('flush');
  if (!S.sel && matchMedia('(min-width:761px)').matches && S.list.items.length) {
    S.sel = S.list.items[0].id; history.replaceState(null, '', '#/queue/' + S.sel);
  }
  v.innerHTML = `<div class="q-layout" id="ql" data-mode="${S.sel ? 'detail' : 'list'}">
    <section class="q-list" aria-label="Список обращений">
      <div class="q-tools">
        <div class="field">${ic('search')}<input id="q-search" type="search" placeholder="Поиск по тексту, нику, номеру" value="${esc(S.filter.q)}" aria-label="Поиск"></div>
        <div class="tabs" id="q-tabs" role="group" aria-label="Статус"></div>
        <div class="tabs" id="q-pri" role="group" aria-label="Приоритет"></div>
      </div>
      <div class="q-scroll" id="q-scroll"></div>
    </section>
    <section class="ws" id="ws" aria-live="polite"></section></div>`;
  let timer;
  $('#q-search').addEventListener('input', e => {
    S.filter.q = e.target.value; clearTimeout(timer);
    timer = setTimeout(async () => { await X.loadList(); X.updateQueueList(); }, 250);
  });
  $('#q-tabs').addEventListener('click', async e => { const b = e.target.closest('button'); if (b) { S.filter.tab = b.dataset.v; await X.loadList(); X.updateQueueList(); } });
  $('#q-pri').addEventListener('click', async e => { const b = e.target.closest('button'); if (b) { S.filter.pri = b.dataset.v; await X.loadList(); X.updateQueueList(); } });
  $('#q-scroll').addEventListener('click', e => { const b = e.target.closest('.tk'); if (b) location.hash = '#/queue/' + b.dataset.id; });
  X.updateQueueList(true);
  X.renderWorkspace();
};

X.updateQueueList = (reveal = false) => {
  const box = $('#q-scroll'); if (!box) return;
  const list = S.list.items, T = (S.stats || {}).tickets || { awaiting: 0, in_progress: 0, closed: 0, total: 0 };
  const cnt = { new: T.awaiting, work: T.in_progress, closed: T.closed, all: T.total };
  $('#q-tabs').innerHTML = [['new', 'Ждут'], ['work', 'В работе'], ['closed', 'Закрыты'], ['all', 'Все']].map(([k, l]) =>
    `<button type="button" data-v="${k}" aria-pressed="${S.filter.tab === k}">${l}<span class="c">${cnt[k]}</span></button>`).join('');
  $('#q-pri').innerHTML = ['all', 'p0', 'p1', 'p2', 'p3'].map(k =>
    `<button type="button" data-v="${k}" aria-pressed="${S.filter.pri === k}">${k === 'all' ? 'Все' : k}</button>`).join('');
  box.innerHTML = list.map(q => `
    <button type="button" class="tk ${q.priority} ${q.status === 'closed' ? 'done' : ''}" data-id="${esc(q.id)}" ${q.id === S.sel ? 'aria-current="true"' : ''}>
      <div class="tk-top"><span class="pri ${q.priority}">${q.priority}</span><span class="cat">${esc(catName(q.category))}${q.overridden.category || q.overridden.priority ? ' *' : ''}</span><span class="when">${ago(q.received)}</span></div>
      <div class="tk-txt">${esc(clip(q.text, 160))}</div>
      <div class="tk-bot">
        <span class="chip ${q.needs_human ? 'human' : 'auto'}">${q.needs_human ? 'нужен человек' : 'можно без правок'}</span>
        ${q.is_duplicate ? '<span class="chip risk">дубль</span>' : ''}${q.is_spam ? '<span class="chip risk">спам</span>' : ''}
        ${q.status === 'new' ? '' : `<span class="chip">${esc(X.STATUS[q.status])}</span>`}
        <span class="chip">${esc(q.lang || '—')}</span><span class="chip mono">${esc(q.id)}</span>
      </div></button>`).join('')
    || `<div class="empty" style="padding:36px 12px">${ic('inbox')}<h3>Ничего не найдено</h3><p>${T.total ? 'В этом разделе пусто. Смените вкладку, фильтр или поиск.' : 'Обращений пока нет: создайте обращение или импортируйте JSONL.'}</p></div>`;
  if (list.length < S.list.total) box.insertAdjacentHTML('beforeend', `<div class="muted" style="padding:10px 12px;font-size:12.5px">Показано ${list.length} из ${S.list.total}. Уточните поиск.</div>`);
  if (reveal) { const cur = $('.tk[aria-current]', box); if (cur) cur.scrollIntoView({ block: 'nearest' }); }
};

/* ---------- рабочее место ---------- */
const hilite = (text, nick, refs) => {
  const parts = [];
  if (nick) parts.push(rx(nick));
  (refs || []).forEach(r => parts.push(rx(r)));
  parts.push('https?:\\/\\/\\S+');
  return String(text).split(new RegExp('(' + parts.join('|') + ')', 'g')).map((p, i) => i % 2 ? `<mark>${esc(p)}</mark>` : esc(p)).join('');
};

function wsState(t) {
  const st = (S.ws[t.id] ||= {});
  if (st.rev !== t.rev) {   // обращение изменилось на сервере: локальные правки сбрасываются
    Object.assign(st, { rev: t.rev, alt: 0, text: t.draft.text, cat: null, pri: null, form: null, reason: '', comment: '', vfy: null, vfyErr: null });
  }
  return st;
}
const altsOf = t => {
  const m = t.response._meta || {};
  return [{ intent: m.intent, text: t.response.draft_reply.text, cited: t.response.draft_reply.cited }, ...(m.alternatives || [])];
};
const reasonLabel = (kind, code) => ((S.meta || {})[kind + '_reasons'] || {})[code] || code || '';
const isEdited = (t, st) => st.text.trim() !== t.draft.text.trim();

function suggestReason(t, kind) {
  if (kind === 'close') return t.status === 'approved' ? 'answered' : t.is_duplicate ? 'duplicate' : t.is_spam ? 'spam' : '';
  if (t.category === 'report.payment') return 'payment';
  if (t.category === 'report.account') return 'account';
  if (t.category === 'complaint.admin') return 'admin_complaint';
  if ((t.response._meta || {}).intent === 'threat') return 'threat';
  return '';
}

function vfyHtml(st) {
  if (st.vfyErr) return `<div class="check idle">${ic('dot')}<div><div class="t">Проверка текста недоступна</div><div class="d">${esc(st.vfyErr)}. Сервер проверит текст при сохранении.</div></div></div>`;
  const v = st.vfy;
  if (!v) return `<div class="muted" style="font-size:12.5px">Проверка текста…</div>`;
  const rows = v.violations.map(x => `<div class="check risk">${ic('stop')}<div><div class="t">${esc(x.message)}</div></div></div>`);
  if (v.ok) rows.push(`<div class="check ok">${ic('ok')}<div><div class="t">${v.cited.length ? 'Пункты есть в rules.json: ' + v.cited.map(esc).join(', ') : 'Номеров пунктов в тексте нет'}</div><div class="d">Обещаний разбана, возврата, компенсации и наказания не найдено.</div></div></div>`);
  (v.warnings || []).forEach(w => rows.push(`<div class="check warn">${ic('alert')}<div><div class="t">${esc(w)}</div></div></div>`));
  return `<div class="checks">${rows.join('')}</div>`;
}

let vfyTimer;
function scheduleVerify(t, st) {
  clearTimeout(vfyTimer);
  const text = st.text;
  vfyTimer = setTimeout(async () => {
    try { st.vfy = await X.post('/verify', { text }); st.vfyErr = null; }
    catch (e) { st.vfy = null; st.vfyErr = e.message; }
    if (st.text !== text) return;       // текст уже изменился, придёт следующий ответ
    const box = $('#vfy'); if (box) box.innerHTML = vfyHtml(st);
    syncButtons(t, st);
  }, 280);
}

function syncButtons(t, st) {
  const edited = isEdited(t, st), bad = st.vfy && !st.vfy.ok;
  const a = $('#b-approve'), e = $('#b-edit'), r = $('#b-reset');
  if (a) { a.disabled = S.busy || !!bad; a.title = bad ? 'Исправьте текст: проверка не пройдена' : ''; }
  if (e) e.disabled = S.busy || !edited || !!bad;
  if (r) r.hidden = !edited;
  const ch = $('#chars'); if (ch) ch.textContent = st.text.length + ' симв.';
  const tag = $('#edited-tag'); if (tag) tag.hidden = !edited;
}

X.renderWorkspace = async () => {
  const box = $('#ws'); if (!box) return;
  const id = S.sel;
  if (!id) { box.dataset.id = ''; box.innerHTML = `<div class="empty big">${ic('queue')}<h3>Выберите обращение</h3><p>Слева очередь по приоритету. Здесь появится черновик ответа, пункты правил, трасса решения и история.</p></div>`; return; }
  let t = S.detail[id];
  if (t === undefined) { box.innerHTML = '<div class="panel skel" style="height:200px"></div>'; t = await X.loadDetail(id).catch(() => undefined); }
  if (S.sel !== id || !$('#ws')) return;
  if (!t) { box.dataset.id = id; box.innerHTML = `<div class="empty big">${ic('alert')}<h3>Обращение не найдено</h3><p>Номер ${esc(id)} отсутствует в базе Sentra.</p><a class="btn" href="#/queue">К очереди</a></div>`; return; }
  const alts = altsOf(t);
  await X.rulesFor([...new Set([...alts.flatMap(a => a.cited || []), ...(t.draft.cited || [])])]);
  if (S.sel !== id || !$('#ws')) return;
  const st = wsState(t);
  if (st.alt >= alts.length) st.alt = 0;
  draw(box, t, st, alts);
  box.dataset.id = id; box.dataset.rev = t.rev;
  if (!st.vfy && !st.vfyErr) scheduleVerify(t, st);
};

function draw(box, t, st, alts) {
  const r = t.response, m = r._meta || {}, req = t.request;
  const open = t.status !== 'closed';
  const edited = isEdited(t, st);
  const pri = st.pri || t.priority, cat = st.cat || t.category;
  const guardHits = r.reasons.filter(X.isGuard), dupHits = r.reasons.filter(x => X.isDupReason(x) || X.isSpamReason(x));
  const other = r.reasons.filter(x => !X.isGuard(x) && !X.isDupReason(x) && !X.isSpamReason(x));
  const ex = r.extracted, sameLang = r.lang === r.draft_reply.lang;
  const urls = req.evidence_urls || [];
  const cites = t.draft.cited || [];
  const catOptions = (((S.meta || {}).categories || {})[t.kind] || Object.keys(X.CAT).filter(c => c.startsWith(t.kind + '.')))
    .map(c => `<option value="${esc(c)}" ${c === cat ? 'selected' : ''}>${esc(catName(c))}</option>`).join('');
  const vfy = t.draft.verification;
  const checks = [
    guardHits.some(x => /несуществующие/.test(x)) ? ['risk', 'stop', 'Цитата не из rules.json удалена', guardHits.find(x => /несуществующие/.test(x))]
      : guardHits.some(x => /в тексте черновика пункт/.test(x)) ? ['risk', 'stop', 'Номер пункта в тексте не подтверждён', guardHits.find(x => /в тексте черновика пункт/.test(x))]
      : cites.length ? ['ok', 'ok', 'Все пункты есть в rules.json', `Цитат в сохранённом тексте: ${cites.length}. Пункты подставляет код, не модель.`]
        : ['idle', 'dot', 'Цитат нет', 'Для этого сценария пункт правил не требуется.'],
    guardHits.some(x => /обещани/.test(x)) ? ['risk', 'stop', 'Найдено обещание', 'Разбан, возврат или компенсация без подтверждения: нужен человек.']
      : ['ok', 'ok', 'Нет обещаний разбана и возврата', 'Исходный черновик проверен кодом на 6 языках.'],
    r.reasons.some(x => /предлагает наказание/.test(x)) ? ['warn', 'alert', 'В черновике указано наказание', 'Срок взят из текста пункта. Решает администратор.']
      : ['ok', 'ok', 'Наказание не назначается', 'Черновик не называет срок или меру.'],
    sameLang ? ['ok', 'ok', 'Язык ответа совпадает с языком игрока', `${langName(r.lang)}.`]
      : ['warn', 'alert', 'Язык ответа отличается', `Игрок: ${langName(r.lang)}, ответ: ${langName(r.draft_reply.lang)}.`],
    dupHits.length ? ['warn', 'alert', X.isSpamReason(dupHits[0]) && !X.isDupReason(dupHits[0]) ? 'Признаки спама' : 'Возможный дубль', dupHits[0]]
      : ['ok', 'ok', 'Дубль и спам не найдены', 'Окно проверки: 1 час, нужен ID заявителя.'],
  ];
  if (m.intent === 'approve' && !ex.has_evidence) checks.push(['warn', 'alert', 'Нарушение подтверждается без доказательств', 'В черновике сказано «по приложенным материалам», а вложений и ссылок в обращении нет. Проверьте или выберите «Запросить доказательства».']);
  if (t.draft_rev > 0 && vfy) checks.push(vfy.ok ? ['ok', 'ok', 'Утверждённый текст проверен сервером', `Цитаты: ${vfy.cited.join(', ') || 'нет'}. Проверка по rules.json при сохранении.`]
    : ['risk', 'stop', 'Текст не прошёл проверку', 'Такой текст не сохраняется.']);

  const trace = [
    { c: sameLang ? '' : 'warn', k: 'Язык', v: `${langName(r.lang)}${sameLang ? '' : ' → ответ: ' + langName(r.draft_reply.lang)}` },
    { c: r.confidence < .5 ? 'warn' : '', k: 'Категория', v: esc(catName(r.category)), n: `${esc(r.category)}, ${m.category_source === 'model' ? 'модель' : 'правила'}, уверенность ${dec(r.confidence, 2)}` },
    { c: r.priority === 'p0' ? 'risk' : '', k: 'Приоритет', v: `<span class="pri ${r.priority}">${r.priority}</span> <span class="soft">${X.PRI[r.priority] || ''}</span>` },
    { c: '', k: 'Пункты правил', v: r.draft_reply.cited.length ? r.draft_reply.cited.map(c => `<span class="cite">${esc(c)}</span>`).join(' ') : '<span class="muted">без цитат</span>', n: 'Выбирает код по тексту и категории' },
    { c: '', k: 'Сценарий ответа', v: esc(intentName(m.intent)), n: m.verdict_pred ? `Прогноз исхода: ${esc(X.VERDICT[m.verdict_pred] || m.verdict_pred)}` : '' },
    ...(dupHits.length ? [{ c: 'warn', k: 'Дубль и спам', v: esc(dupHits[0]) }] : []),
    guardHits.length ? { c: 'risk', k: 'Guard', v: 'Остановил черновик', n: esc(guardHits.join('; ')) } : { c: 'ok', k: 'Guard', v: 'Проверка пройдена' },
    { c: r.needs_human ? 'human' : 'ok', k: 'Рекомендация модели', v: r.needs_human ? 'Нужен человек' : 'Черновик годится без правок', n: esc(other.join('. ')) },
    ...((m.policy || []).map(p => ({ c: 'human', k: 'Политика Sentra', v: 'Нужен человек', n: esc(p) }))),
  ];
  const conf = Math.round(r.confidence * 100);
  const lastDec = t.last_decision;
  const stateNote = {
    new: '',
    approved: `${ic('ok')}<span>Ответ утверждён и сохранён ${esc(fmtTime(t.updated_at))}. <b>Sentra не отправляет сообщения игрокам</b>: канала доставки нет. Скопируйте ответ и отправьте его вручную.</span>`,
    escalated: `${ic('up')}<span>Эскалировано ${esc(fmtTime(t.updated_at))}: ${esc(reasonLabel('escalation', lastDec && lastDec.reason_code))}${lastDec && lastDec.comment ? '. ' + esc(lastDec.comment) : ''}.</span>`,
    closed: `${ic('ok')}<span>Закрыто ${esc(fmtTime(t.closed_at))}: ${esc(reasonLabel('close', lastDec && lastDec.reason_code))}${lastDec && lastDec.comment ? '. ' + esc(lastDec.comment) : ''}.</span>`,
  }[t.status];
  const canEsc = ['new', 'approved'].includes(t.status), canReopen = t.status !== 'new';
  const canApprove = open && !(t.status === 'approved' && !edited);

  const form = st.form ? (() => {
    const kind = st.form === 'escalate' ? 'escalation' : 'close';
    const reasons = (S.meta || {})[kind + '_reasons'] || {};
    if (st.reason === '' && !st.reasonTouched) st.reason = suggestReason(t, st.form);
    return `<div class="inline-form" id="act-form">
      <div><label class="lbl" for="f-reason">${st.form === 'escalate' ? 'Причина эскалации' : 'Как решено'} (обязательно)</label>
        <select id="f-reason"><option value="" ${st.reason ? '' : 'selected'} disabled>— выберите —</option>${Object.entries(reasons).map(([k, l]) => `<option value="${esc(k)}" ${k === st.reason ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
      <div><label class="lbl" for="f-comment">Комментарий${st.reason === 'other' ? ' (обязательно)' : ''}</label>
        <textarea id="f-comment" rows="2" maxlength="1000" placeholder="Для старшей администрации и журнала">${esc(st.comment)}</textarea></div>
      <div class="actions-bar" style="margin-top:0"><button class="btn ${st.form === 'escalate' ? 'danger' : 'primary'}" id="f-ok" type="button">${st.form === 'escalate' ? 'Эскалировать' : 'Закрыть обращение'}</button>
        <button class="btn ghost" id="f-cancel" type="button">Отмена</button></div></div>`;
  })() : '';

  const dup = t.duplicate;
  const dupPanel = t.is_duplicate ? `<section class="panel dup-panel"><div class="panel-h"><h3>${ic('dupe')} Повтор обращения</h3><span class="aside">автозакрытия нет</span></div>
    <div class="panel-b">${dup && dup.original_id ? `
      <div>Первое обращение: <a class="mono" href="#/queue/${esc(dup.root_id)}">${esc(dup.root_id)}</a>${dup.original_id !== dup.root_id ? `, ближайшее совпадение: <a class="mono" href="#/queue/${esc(dup.original_id)}">${esc(dup.original_id)}</a>` : ''}</div>
      <div class="sigs" style="margin-top:8px">${X.sigChips(dup)}</div>
      <div class="muted" style="margin-top:8px;font-size:12.5px">${esc(dup.reason)}. Окно проверки ${Math.round(dup.window_seconds / 60)} мин. Сходство текста посчитано сервисом, оценки «на глаз» нет. Решает администратор: повтор может быть новым нарушением.</div>`
      : `<div>${esc(dupHits[0] || 'Помечено как повтор')}.</div><div class="muted" style="margin-top:6px;font-size:12.5px">Первое обращение не сохранено в Sentra (оно пришло через POST /triage без enqueue), перейти к нему нельзя.</div>`}</div></section>` : '';
  const repeatsPanel = t.repeats.length ? `<section class="panel"><div class="panel-h"><h3>Повторные обращения (${t.repeats.length})</h3><span class="aside">после этого</span></div>
    <div class="panel-b" style="padding-top:6px">${t.repeats.map(x => `<a class="dupe" href="#/queue/${esc(x.id)}" style="text-decoration:none;color:inherit;grid-template-columns:1fr auto;padding:9px 0"><span class="txt"><span class="mono">${esc(x.id)}</span> <span class="muted">${esc(clip(x.text, 80))}</span><small>${esc(x.reason)}, сходство ${dec(x.text_overlap, 2)}, ${ago(x.received)}</small></span><span class="chip">${esc(X.STATUS[x.status])}</span></a>`).join('')}</div></section>` : '';

  const evLabel = e => {
    const d = e.data || {};
    let extra = '';
    if (e.event === 'decision.escalate') extra = reasonLabel('escalation', d.reason) + (d.comment ? ': ' + d.comment : '');
    else if (e.event === 'decision.close') extra = reasonLabel('close', d.reason) + (d.comment ? ': ' + d.comment : '');
    else if (e.event === 'ticket.triaged') extra = `${catName(d.category)}, ${d.priority}, ${dec(d.latency_ms || 0)} мс`;
    else if (e.event === 'decision.blocked') extra = (d.violations || []).map(v => v.message).join('; ');
    else if (e.event === 'ticket.created' && d.redactions && Object.keys(d.redactions).length) extra = 'секреты в тексте скрыты: ' + Object.entries(d.redactions).map(([k, n]) => k + ' ' + n).join(', ');
    else if (e.event === 'decision.approve' || e.event === 'decision.edit') extra = d.final_category || d.final_priority ? `поправка: ${[d.final_category && catName(d.final_category), d.final_priority].filter(Boolean).join(', ')}` : '';
    return { t: X.EVT[e.event] || e.event, extra };
  };

  box.innerHTML = `
  <div class="ws-head">
    <a class="btn ghost sm back" href="#/queue" aria-label="К списку">${ic('back')}</a>
    <h2>Обращение ${esc(t.id)}</h2>
    <span class="chip">${t.kind === 'complaint' ? 'Жалоба' : 'Репорт'}</span>
    <span class="pri ${t.priority}">${t.priority}</span>
    <span class="chip ${open ? 'sig' : ''}">${esc(X.STATUS[t.status])}</span>
    <span class="muted" title="${esc(fmtTime(t.created_at))}">${esc(fmtTime(t.created_at))}</span>
    <span class="chip mono" style="margin-left:auto" title="Время работы пайплайна при создании">${m.latency_ms != null ? dec(m.latency_ms) + ' мс' : '—'}</span>
  </div>
  ${dupPanel}
  <div class="ws-grid">
    <div class="stack">
      <section class="panel">
        <div class="panel-h"><h3>Сообщение игрока</h3><span class="aside">${t.source === 'import' ? 'импорт' : t.source === 'api' ? 'POST /triage' : 'создано вручную'}</span></div>
        <div class="panel-b">
          <div class="msg">${hilite(t.text, ex.nickname, ex.rule_refs)}</div>
          <div class="facts">
            <div class="fact"><div class="k">Ник нарушителя</div><div class="v ${ex.nickname ? 'mono' : 'muted'}">${esc(ex.nickname || 'не указан')}</div></div>
            <div class="fact"><div class="k">Заявитель</div><div class="v ${t.reporter_id ? 'mono' : 'muted'}">${esc(t.reporter_id || 'не указан, дубли не проверяются')}</div></div>
            <div class="fact"><div class="k">Пункты игрока</div><div class="v ${ex.rule_refs.length ? 'mono' : 'muted'}">${esc(ex.rule_refs.join(', ') || 'нет')}</div></div>
            <div class="fact"><div class="k">Доказательства</div><div class="v">${ex.has_evidence ? 'есть' : '<span class="muted">не найдены</span>'}${t.attachments ? `, файлов: ${t.attachments}` : ''}${urls.length ? `, ссылок: ${urls.length}` : ''}</div><div class="muted" style="font-size:11.5px">содержимое файлов и ссылок не анализируется</div></div>
            <div class="fact"><div class="k">Сервер</div><div class="v ${t.server || ex.server ? '' : 'muted'}">${esc(t.server || ex.server || 'не указан')}${t.server ? ' <span class="muted">(указан при создании)</span>' : ex.server ? ' <span class="muted">(из текста)</span>' : ''}</div></div>
          </div>
          ${urls.length ? `<div class="chips" style="margin-top:10px">${urls.map(u => `<span class="chip mono" title="${esc(u)}">${esc(clip(u, 48))}</span>`).join('')}</div>` : ''}
        </div>
      </section>

      <section class="panel ai">
        <div class="panel-h"><h3><span class="ai-mark">${ic('spark')}Черновик ответа</span></h3>
          <span class="aside">${m.llm ? 'LLM вызывалась, ' : ''}язык ответа: ${esc(langName(t.draft.lang || r.draft_reply.lang))}</span></div>
        <div class="panel-b">
          ${open && alts.length > 1 ? `<div class="scn" role="group" aria-label="Сценарий ответа">${alts.map((a, i) =>
            `<button type="button" data-alt="${i}" aria-pressed="${i === st.alt && st.text.trim() === a.text.trim()}">${esc(intentName(a.intent))}</button>`).join('')}</div>` : ''}
          <textarea class="draft" id="draft" rows="7" aria-label="Текст ответа игроку" ${open ? '' : 'readonly'}>${esc(st.text)}</textarea>
          <div class="draft-foot"><span class="num" id="chars">${st.text.length} симв.</span>
            ${cites.map(c => `<span class="cite" title="${esc((S.rules[c] || {}).text || '')}">${esc(c)}</span>`).join('')}
            <span class="chip" id="edited-tag" ${edited ? '' : 'hidden'}>есть несохранённая правка</span>
            ${t.draft_rev > 0 ? `<span class="chip sig">версия ${t.draft_rev}: ${t.draft.kind === 'approved' ? 'утверждена' : 'правка администратора'}</span>` : '<span class="chip">исходный черновик модели</span>'}</div>
          ${open ? `<div id="vfy" style="margin-top:10px">${vfyHtml(st)}</div>` : ''}
          ${stateNote ? `<div class="closed-note">${stateNote}</div>` : ''}
          <div class="actions-bar">
            ${canApprove ? `<button class="btn primary" id="b-approve" type="button">${ic('check')}<span>Утвердить и сохранить</span><span class="kbd">Ctrl ⏎</span></button>` : ''}
            ${open ? `<button class="btn" id="b-edit" type="button" ${edited ? '' : 'disabled'}>Сохранить правку</button>` : ''}
            <button class="btn" id="b-copy" type="button">${ic('copy')}Скопировать ответ</button>
            ${canEsc ? '<button class="btn danger" id="b-esc" type="button">' + ic('up') + 'Эскалировать</button>' : ''}
            ${open ? '<button class="btn" id="b-close" type="button">Закрыть обращение</button>' : ''}
            ${canReopen ? '<button class="btn ghost" id="b-reopen" type="button">Вернуть в работу</button>' : ''}
            <span class="sp"></span>
            <button class="btn ghost sm" id="b-reset" type="button" ${edited ? '' : 'hidden'}>Сбросить правку</button>
          </div>
          ${form}
        </div>
      </section>
      ${repeatsPanel}
    </div>

    <div class="stack">
      <section class="panel">
        <div class="panel-h"><h3>Решение</h3><span class="aside"><span class="ai-mark">${ic('spark')}ИИ предлагает, вы решаете</span></span></div>
        <div class="panel-b kv">
          <div class="r"><span>Рекомендация</span><span class="chip ${t.needs_human ? 'human' : 'auto'}">${t.needs_human ? 'Нужен человек' : 'Можно без правок'}</span></div>
          <div class="r"><span>Уверенность</span><span class="conf"><span class="ring" style="--v:${conf}"><b>${conf}</b></span></span></div>
          <div><div class="lbl">Категория${t.overridden.category ? ' (исправлена админом)' : ''}</div><select id="s-cat" ${open ? '' : 'disabled'} aria-label="Категория">${catOptions}</select>
            ${cat !== t.original.category ? `<div class="muted" style="font-size:12px;margin-top:4px">Модель предложила: ${esc(catName(t.original.category))}</div>` : ''}</div>
          <div><div class="lbl">Приоритет${t.overridden.priority ? ' (исправлен админом)' : ''}</div><div class="segpri" id="s-pri" role="group" aria-label="Приоритет">${['p0', 'p1', 'p2', 'p3'].map(p =>
            `<button type="button" class="${p} ${p === t.original.priority && pri !== t.original.priority ? 'was' : ''}" data-p="${p}" aria-pressed="${p === pri}" ${open ? '' : 'disabled'}>${p}</button>`).join('')}</div></div>
          ${(st.cat && st.cat !== t.category) || (st.pri && st.pri !== t.priority) ? '<div class="muted" style="font-size:12.5px">Поправка сохранится вместе со следующим действием. Исходный результат модели остаётся в журнале.</div>' : ''}
        </div>
      </section>

      <section class="panel">
        <div class="panel-h"><h3>Трасса решения</h3><span class="aside">исходный результат триажа</span></div>
        <div class="panel-b"><div class="trace">${trace.map(s => `
          <div class="step ${s.c}"><span class="nd"></span><div><div class="k">${s.k}</div><div class="v">${s.v}</div>${s.n ? `<div class="note">${s.n}</div>` : ''}</div></div>`).join('')}</div></div>
      </section>

      <section class="panel">
        <div class="panel-h"><h3>Качество и безопасность</h3></div>
        <div class="panel-b"><div class="checks">${checks.map(([c, i, tt, d]) =>
          `<div class="check ${c}">${ic(i)}<div><div class="t">${esc(tt)}</div><div class="d">${esc(d)}</div></div></div>`).join('')}</div></div>
      </section>

      <section class="panel">
        <div class="panel-h"><h3>Цитируемые пункты</h3><span class="aside">из rules.json</span></div>
        <div class="panel-b">${cites.map(c => {
          const p = S.rules[c];
          return `<div class="rule"><div class="h"><b>${esc(c)}</b><span class="muted">${esc(p ? p.section : 'пункт не найден')}</span></div>${p ? `<div class="tx">${esc(p.text)}</div>` : ''}</div>`;
        }).join('') || '<div class="muted">В сохранённом тексте цитат нет.</div>'}</div>
      </section>

      <section class="panel">
        <div class="panel-h"><h3>История изменений</h3><span class="aside">${t.history.length} событий</span></div>
        <div class="panel-b"><div class="trace">${t.history.map(e => { const l = evLabel(e); return `
          <div class="step ${e.event === 'decision.blocked' ? 'risk' : e.event.startsWith('decision.') ? 'human' : 'quiet'}"><span class="nd"></span><div>
            <div class="k">${esc(fmtTime(e.ts))} · ${esc(e.actor)}</div><div class="v">${esc(l.t)}</div>${l.extra ? `<div class="note">${esc(l.extra)}</div>` : ''}</div></div>`; }).join('')}</div>
          <details style="margin-top:12px"><summary class="muted" style="cursor:pointer">Версии текста ответа (${t.revisions.length})</summary>
            ${t.revisions.map(rv => `<div class="rev"><div class="muted" style="font-size:12px">версия ${rv.rev}: ${rv.kind === 'original' ? 'исходный черновик модели' : rv.kind === 'edit' ? 'правка админа' : 'утверждено'} · ${esc(fmtTime(rv.created_at))} · ${esc(rv.author)}</div><div class="proposal">${esc(rv.text)}</div></div>`).join('')}</details></div>
      </section>
    </div>
  </div>`;
  bind(t, st, alts);
  syncButtons(t, st);
}

/* ---------- действия ---------- */
function bind(t, st, alts) {
  const rerender = () => draw($('#ws'), t, st, alts);
  $$('.scn button').forEach(b => b.onclick = () => { st.alt = +b.dataset.alt; st.text = alts[st.alt].text; st.vfy = null; rerender(); scheduleVerify(t, st); });
  $$('#s-pri button').forEach(b => b.onclick = () => { st.pri = b.dataset.p === t.priority ? null : b.dataset.p; rerender(); });
  const cat = $('#s-cat'); if (cat) cat.onchange = () => { st.cat = cat.value === t.category ? null : cat.value; rerender(); };
  const draft = $('#draft');
  if (draft && !draft.readOnly) draft.oninput = () => { st.text = draft.value; st.vfy = null; syncButtons(t, st); scheduleVerify(t, st); const b = $('#vfy'); if (b) b.innerHTML = vfyHtml(st); };
  const on = (id, fn) => { const el = $('#' + id); if (el) el.onclick = fn; };
  on('b-reset', () => { st.text = t.draft.text; st.alt = 0; st.vfy = null; rerender(); scheduleVerify(t, st); });
  on('b-copy', async () => {
    if (await X.copyText(st.text)) X.toast('Ответ скопирован в буфер обмена');
    else X.toast('Браузер не разрешил копирование: выделите текст и скопируйте вручную', 'risk');
  });
  on('b-approve', () => act(t, st, alts, 'approve'));
  on('b-edit', () => act(t, st, alts, 'edit'));
  on('b-reopen', () => act(t, st, alts, 'reopen'));
  on('b-esc', () => { st.form = 'escalate'; st.reason = ''; st.reasonTouched = false; st.comment = ''; rerender(); const s = $('#f-reason'); if (s) s.focus(); });
  on('b-close', () => { st.form = 'close'; st.reason = ''; st.reasonTouched = false; st.comment = ''; rerender(); const s = $('#f-reason'); if (s) s.focus(); });
  on('f-cancel', () => { st.form = null; rerender(); });
  on('f-ok', () => {
    if (!st.reason) { X.toast('Выберите причину из списка', 'risk'); const s = $('#f-reason'); if (s) s.focus(); return; }
    if (st.reason === 'other' && !st.comment.trim()) { X.toast('Для причины «другая» опишите её в комментарии', 'risk'); const s = $('#f-comment'); if (s) s.focus(); return; }
    act(t, st, alts, st.form);
  });
  const fr = $('#f-reason'); if (fr) fr.onchange = () => { st.reason = fr.value; st.reasonTouched = true; rerender(); };
  const fc = $('#f-comment'); if (fc) fc.oninput = () => { st.comment = fc.value; };
}

const DONE = {
  approve: 'Ответ утверждён и сохранён. Игроку ничего не отправлено: скопируйте текст и отправьте вручную',
  edit: 'Правка сохранена, исходный черновик остался в истории', escalate: 'Эскалировано, причина записана',
  close: 'Обращение закрыто', reopen: 'Возвращено в работу',
};

async function act(t, st, alts, action) {
  if (S.busy) return;
  S.busy = true;
  $$('#ws .actions-bar button, #ws .inline-form button').forEach(b => { b.disabled = true; });
  const body = { action, expected_rev: t.rev };
  if (action === 'approve' || action === 'edit') {
    body.text = st.text;
    const same = alts.find(a => a.text.trim() === st.text.trim());
    if (same && same.intent) body.intent = same.intent;
  }
  if (action === 'escalate' || action === 'close') { body.reason = st.reason; body.comment = st.comment.trim() || undefined; }
  if (st.cat && st.cat !== t.category) body.category = st.cat;
  if (st.pri && st.pri !== t.priority) body.priority = st.pri;
  try {
    const nt = await X.post(`/tickets/${encodeURIComponent(t.id)}/decision`, body);
    S.detail[t.id] = nt;
    X.toast(DONE[action]);
    const oldTab = S.filter.tab, here = X.tabFor(nt.status), before = S.list.items.map(x => x.id);
    let next = null;
    if (oldTab !== 'all' && oldTab !== here) {
      if (action === 'escalate' || action === 'close') {      // как в очереди: к следующему обращению
        await X.refresh();
        next = S.list.items.find(x => before.includes(x.id) && x.id !== t.id);
      }
      if (!next) S.filter.tab = here;                          // иначе остаёмся на карточке и открываем её вкладку
    }
    if (next) location.hash = '#/queue/' + next.id; else await X.refresh();
  } catch (e) {
    if (e.code === 'draft_rejected') {
      st.vfy = { ok: false, violations: e.detail.violations || [], cited: [], warnings: [] };
      X.toast('Текст не сохранён: он не прошёл проверку', 'risk');
    } else if (e.code === 'conflict' || e.code === 'invalid_transition') {
      X.toast('Обращение уже изменилось (возможно, повторное нажатие). Карточка обновлена', 'risk');
      delete S.detail[t.id]; await X.refresh();
    } else if (e.code === 'no_change') {
      X.toast('Текст не изменился: сохранять нечего', 'risk');
    } else {
      X.toast('Не удалось сохранить: ' + e.message, 'risk');
    }
  } finally {
    S.busy = false;
    if (S.view === 'queue' && S.sel === t.id) { const nt = S.detail[t.id]; if (nt && $('#ws') && nt.rev === t.rev) draw($('#ws'), nt, wsState(nt), altsOf(nt)); else X.renderWorkspace(); }
  }
}

/* обновление открытой карточки после изменений на сервере */
X.syncSelected = async () => {
  const box = $('#ws'); if (!box || !S.sel || S.busy) return;
  const prev = S.detail[S.sel];
  const t = await X.loadDetail(S.sel).catch(() => prev);
  if (!t || (prev && prev.rev === t.rev && box.dataset.id === S.sel)) return;
  const typing = document.activeElement && document.activeElement.id === 'draft';
  if (typing && box.dataset.id === S.sel) { X.toast('Обращение изменилось на сервере: сохраните правку или обновите страницу', 'risk'); return; }
  X.renderWorkspace();
};
})();
