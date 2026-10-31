/* Sentra by LGTM: экраны «Командный центр», «Дубли и спам», «Качество и безопасность», «Шаблоны». */
(() => {
'use strict';
const X = window.Sentra;
const { S, $, $$, esc, ic, nf, pc, dec, clip, ago, fmtTime, fmtDate, catName, intentName, gauge, src } = X;

const num = x => (x == null ? '—' : nf(x));
const ms = x => (x == null ? '—' : dec(x) + ' мс');
const span = s => s && s.range && s.range.first ? `${fmtDate(s.range.first)}–${fmtDate(s.range.last)}` : 'нет данных';

/* ---------- диагностика: что загружено, чего нет ---------- */
X.diagList = h => {
  if (!h) return `<div class="muted">Нет связи с сервисом.</div>`;
  const lvl = { error: 'risk', warn: 'warn', info: 'idle' };
  const ico = { error: 'stop', warn: 'alert', info: 'dot' };
  return `<div class="checks">${h.problems.map(p => `<div class="check ${lvl[p.level] || 'idle'}">${ic(ico[p.level] || 'dot')}<div><div class="t">${esc(p.text)}</div></div></div>`).join('')
    || `<div class="check ok">${ic('ok')}<div><div class="t">Все файлы и модели на месте</div></div></div>`}</div>`;
};
X.filesTable = h => {
  if (!h) return '';
  return `<table class="tbl"><thead><tr><th>Файл</th><th>Роль</th><th>Для чего</th><th class="r">Состояние</th></tr></thead><tbody>${h.files.map(f => `
    <tr><td class="mono">${esc(f.path)}</td><td>${esc(f.role)}</td><td class="soft">${esc(f.purpose)}</td>
    <td class="r">${f.present ? '<span class="chip auto">есть</span>' : '<span class="chip risk">нет</span>'}</td></tr>`).join('')}</tbody></table>`;
};

/* ---------- командный центр ---------- */
function emptyCenter() {
  const h = S.health;
  if (h && !h.ready) {
    return `<div class="empty big">${ic('alert')}<h3>Триаж недоступен</h3>
      <p>Sentra не подставляет вымышленные результаты. Причины:</p>
      <div style="max-width:640px;text-align:left;width:100%">${X.diagList(h)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center"><a class="btn primary" href="#/quality">Диагностика и недостающие файлы</a></div></div>`;
  }
  return `<div class="empty big">${ic('inbox')}
    <h3>Обращений пока нет</h3>
    <p>Sentra показывает только реальные обращения: ничего не подставляется само. Создайте обращение вручную или загрузите выгрузку в формате JSONL, как в tickets.jsonl.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center">
      <button class="btn primary" data-new type="button">${ic('plus')}Новое обращение</button>
      <button class="btn" data-import type="button">${ic('inbox')}Импортировать JSONL</button>
    </div></div>`;
}

function routeStrip(s) {
  const T = s.tickets.total, ql = s.quality_live, pctOf = n => T ? Math.round(n / T * 100) : 0;
  const guarded = ql.guard_removed_missing + ql.guard_promise + ql.guard_text_ref;
  const st = [
    { t: 'Поступило', n: T, d: `дублей и спама: ${s.duplicates.flagged}` },
    { t: 'Классификация', n: T, d: `моделью ${pctOf(ql.by_model)}%, правилами ${100 - pctOf(ql.by_model)}%` },
    { t: 'Пункты правил', n: ql.with_cites, d: 'цитату выбирает код' },
    { t: 'Черновик', n: T, d: ql.llm ? `LLM вызывалась для ${ql.llm}` : 'шаблон на языке игрока' },
    { t: 'Guard', n: guarded, d: guarded ? 'остановлено проверкой' : 'ничего не остановлено', cls: guarded ? 'warn' : '' },
    { t: 'Решение', n: s.needs_human.total, d: `человеку; без правок допустимо: ${s.needs_human.auto_ok}`, cls: 'human' },
  ];
  return `<div class="route-wrap"><div class="route">${st.map(x => `
    <div class="stage ${x.cls || ''}"><span class="node"></span><span class="t">${x.t}</span><span class="n">${x.n}</span><span class="d">${x.d}</span></div>`).join('')}</div></div>`;
}

function attRow(q) {
  return `<a class="dupe" href="#/queue/${esc(q.id)}" style="grid-template-columns:auto minmax(0,1fr) auto;text-decoration:none;color:inherit;padding:11px 4px">
    <span class="pri ${q.priority}">${q.priority}</span>
    <span class="txt"><span style="font-weight:500">${esc(catName(q.category))}</span> <span class="muted">${esc(clip(q.text, 70))}</span></span>
    <span class="chip ${q.needs_human ? 'human' : 'auto'}">${q.needs_human ? 'нужен человек' : 'можно без правок'}</span></a>`;
}

X.renderCenter = () => {
  const v = $('#view'); v.classList.remove('flush');
  const s = S.stats;
  if (!s) { v.innerHTML = S.health && !S.health.ready ? emptyCenter() : '<div class="panel skel" style="height:96px"></div><div class="panel skel" style="height:300px"></div>'; return; }
  if (!s.tickets.total) { v.innerHTML = emptyCenter(); return; }
  const T = s.tickets, P = s.priority.open, L = s.latency;
  const mx = Math.max(1, ...Object.values(P));
  const spark = `<div class="spark" aria-hidden="true" title="открытые по приоритету">${['p0', 'p1', 'p2', 'p3'].map(p =>
    `<i style="height:${Math.max(10, P[p] / mx * 100)}%;background:var(--${p})"></i>`).join('')}</div>`;
  const crit = P.p0 + P.p1;
  v.innerHTML = `
  <section class="panel" aria-label="Ключевые показатели"><div class="strip">
    ${gauge('Ждут решения', T.awaiting, `в работе: ${T.in_progress}, закрыто: ${T.closed}, всего: ${T.total}`, spark)}
    ${gauge('Критичные p0 и p1', crit, `открытых; p0: ${P.p0}, p1: ${P.p1}`, '', P.p0 ? 'crit' : '')}
    ${gauge('Нужен человек', `${Math.round(s.needs_human.total / T.total * 100)}<small>%</small>`, `${s.needs_human.total} из ${T.total}; без правок допустимо: ${s.needs_human.auto_ok}`)}
    ${gauge('Дубли и спам', s.duplicates.flagged, `дублей: ${s.duplicates.tickets}, спама: ${s.duplicates.spam}`)}
    ${gauge('Задержка p50', L.p50 == null ? '—' : `${dec(L.p50)}<small>мс</small>`, `p95: ${ms(L.p95)}, вызовов: ${L.n}`)}
  </div></section>

  <section class="panel hero">
    <div class="panel-h"><h2>Поток обращений</h2><span class="aside">ширина ленты равна числу обращений, период ${span(s)}</span></div>
    <div class="sk-wrap">${X.sankey(s.flow)}</div>
    ${routeStrip(s)}
  </section>

  <div class="cols">
    <section class="panel">
      <div class="panel-h"><h2>Что требует внимания</h2><a class="aside" href="#/queue">Вся очередь</a></div>
      <div class="panel-b" style="padding-top:6px">${S.attention.length ? S.attention.map(attRow).join('') : `<div class="empty" style="padding:30px">${ic('ok')}<h3>Все обращения разобраны</h3></div>`}</div>
    </section>
    <section class="panel">
      <div class="panel-h"><h2>Нагрузка</h2><span class="aside">категория и приоритет</span></div>
      <div class="panel-b">${X.hexmap(s.heat)}
        <p class="muted" style="font-size:12.5px;margin-top:6px">Чем ярче сота, тем больше обращений. Цвет ряда показывает срочность: красный p0, оранжевый p1.</p></div>
    </section>
  </div>
  <p class="muted" style="font-size:12.5px;max-width:92ch">Все цифры на этом экране посчитаны сервером по базе Sentra (${nf(T.total)} обращений) и совпадают со списком в очереди. Метрики оффлайн-валидации не смешиваются с ними: они на экране «Качество и безопасность».</p>`;
};

/* ---------- дубли и спам ---------- */
const sigChips = d => {
  if (!d) return '';
  const c = [];
  c.push(d.same_reporter ? '<span class="chip sig">тот же заявитель</span>' : '');
  c.push(d.same_reported ? '<span class="chip sig">тот же нарушитель</span>' : '<span class="chip">нарушитель не совпал или не указан</span>');
  c.push(`<span class="chip mono" title="Коэффициент Жаккара по 4-граммам текста, считает dedup.py">сходство текста ${dec(d.text_overlap, 2)}</span>`);
  c.push(d.category_equal ? '<span class="chip">та же категория</span>' : '');
  c.push(`<span class="chip">через ${d.delta_seconds < 90 ? Math.round(d.delta_seconds) + ' с' : Math.round(d.delta_seconds / 60) + ' мин'}</span>`);
  return c.join('');
};
X.sigChips = sigChips;

X.renderDuplicates = () => {
  const v = $('#view'); v.classList.remove('flush');
  const s = S.stats, D = S.dup;
  if (!s || !D) { v.innerHTML = '<div class="panel skel" style="height:96px"></div><div class="panel skel" style="height:260px"></div>'; return; }
  const total = s.tickets.total;
  const row = (q, extra = '') => `<a class="dupe" href="#/queue/${esc(q.id)}" style="text-decoration:none;color:inherit">
      <span class="pri ${q.priority}">${q.priority}</span>
      <span style="min-width:0"><span class="txt" style="display:block">${esc(clip(q.text, 110))}</span>
        <small>${esc(X.short(q))} · ${ago(q.received)}${extra}</small></span>
      <span class="chip">${esc(X.STATUS[q.status])}</span></a>`;
  const groups = D.groups.map(g => {
    const o = g.original;
    return `<div class="dgroup"><div class="dgroup-h"><span class="chip sig">первое обращение</span>${row(o)}</div>
      ${g.repeats.map(r => `<div class="drep"><div class="sigs">${sigChips(r.duplicate)}</div>${row(r, r.duplicate && r.duplicate.original_id !== o.id ? ` · ближайшее совпадение ${esc(r.duplicate.original_id)}` : '')}
        <div class="muted" style="font-size:12px;padding:0 16px 10px">${esc((r.duplicate || {}).reason || 'помечено как дубль')}. Автозакрытия нет: решает администратор.</div></div>`).join('')}</div>`;
  }).join('');
  v.innerHTML = `
  <section class="panel"><div class="strip" style="grid-template-columns:repeat(4,minmax(0,1fr))">
    ${gauge('Дубли', s.duplicates.tickets, 'тот же заявитель, меньше часа')}
    ${gauge('Спам и флуд', s.duplicates.spam, 'повторы слов, бессвязный текст')}
    ${gauge('Доля потока', total ? pc(s.duplicates.flagged / total, 1) : '—', `${s.duplicates.flagged} из ${total} обращений`)}
    ${gauge('Повторные заявители', D.repeat_reporters.length, 'больше одного обращения')}
  </div></section>

  <section class="panel"><div class="rule-tile">
    <div><b>Тот же заявитель и нарушитель</b><p>Окно в 1 час. Если ник или ID нарушителя совпал, обращение помечается дублем.</p></div>
    <div><b>Тот же заявитель и текст</b><p>Сравнение по 4-граммам: сходство от 0,7, а при той же категории от 0,4. Число сходства в карточке считает сервер.</p></div>
    <div><b>Спам и флуд</b><p>Повторы одного слова, длинные строки без пробелов, текст почти без гласных.</p></div>
  </div></section>

  <div class="cols">
    <section class="panel"><div class="panel-h"><h2>Повторные обращения</h2><span class="aside">групп: ${D.groups.length}</span></div>
      <div class="panel-b" style="padding:10px 0 0">${groups || `<div class="empty" style="padding:44px 24px">${ic('dupe')}<h3>Дублей пока нет</h3><p>Проверка идёт по каждому новому обращению. Если заявитель повторит жалобу в течение часа, она появится здесь вместе с первым обращением. Без ID заявителя дубли не проверяются.</p></div>`}</div></section>
    <div class="stack">
      <section class="panel"><div class="panel-h"><h2>Спам и флуд</h2><span class="aside">${D.spam.length}</span></div>
        <div class="panel-b" style="padding:6px 0 0">${D.spam.map(q => row(q)).join('') || '<div class="muted" style="padding:10px 16px 16px">Спама не найдено.</div>'}</div></section>
      <section class="panel"><div class="panel-h"><h2>Повторные заявители</h2></div>
        <div class="panel-b">${D.repeat_reporters.length ? `<div class="bars">${D.repeat_reporters.map(r =>
          `<div class="bar-row" style="grid-template-columns:minmax(80px,120px) 1fr 30px"><span class="mono">${esc(r.reporter_id)}</span><div class="track"><i style="width:${r.n / D.repeat_reporters[0].n * 100}%"></i></div><span class="n num">${r.n}</span></div>`).join('')}</div>` :
          '<div class="muted">Заявителей с несколькими обращениями нет.</div>'}</div></section>
    </div>
  </div>
  <p class="muted" style="font-size:12.5px;max-width:92ch">Связи повторных обращений с первым хранятся в базе и переживают перезапуск. Точность поиска дублей на реальных данных не измерена: в выданной валидации исходных жалоб нет (REPORT.md).</p>`;
};

/* ---------- качество и безопасность ---------- */
const probeRow = r => `<details class="probe ${r.passed ? 'ok' : 'bad'}"><summary>${ic(r.passed ? 'ok' : 'stop')}<span>${esc(r.title)}</span>
  <span class="chip ${r.passed ? 'auto' : 'risk'}">${r.passed ? 'пройдена' : 'провалена'}</span></summary>
  <div class="probe-b"><div class="muted">Вход:</div><div class="msg">${esc(r.input)}</div>
  <div class="checks" style="margin-top:8px">${r.checks.map(c => `<div class="check ${c.ok ? 'ok' : 'risk'}">${ic(c.ok ? 'ok' : 'stop')}<div><div class="t">${esc(c.name)}</div><div class="d">${esc(c.detail)}</div></div></div>`).join('')}</div>
  <div class="muted" style="margin-top:8px">Ответ сервиса: ${esc(r.output.category)}, ${esc(r.output.priority)}, ${r.output.needs_human ? 'нужен человек' : 'без человека'}, язык ${esc(r.output.draft_lang)}</div>
  <div class="proposal" style="margin-top:6px">${esc(r.output.draft)}</div></div></details>`;

const envPanel = h => `<section class="panel"><div class="panel-h"><h2>Окружение</h2><span class="aside">${h ? `режим: ${esc({ full: 'полный', limited: 'ограниченный', rules_only: 'только правила', unavailable: 'триаж недоступен' }[h.mode] || h.mode)}` : 'нет связи'}</span></div>
    <div class="panel-b">${X.diagList(h)}
      ${h && h.missing_files.length ? `<div class="notice warn" style="margin-top:12px">${ic('alert')}<span>Недостающие файлы: <span class="mono">${h.missing_files.map(esc).join(', ')}</span>. Данные кейса приватные и в репозиторий не входят; Sentra их не придумывает.</span></div>` : ''}
      <details style="margin-top:12px"><summary class="muted" style="cursor:pointer">Все файлы, которые нужны сервису</summary>${X.filesTable(h)}</details></div></section>`;

X.renderQuality = () => {
  const v = $('#view'); v.classList.remove('flush');
  const s = S.stats, h = S.health, M = S.metrics && S.metrics.available ? S.metrics : null;
  if (!s) { v.innerHTML = h ? envPanel(h) + `<div class="notice warn">${ic('alert')}<span>Статистика недоступна: хранилище не отвечает. Живые показатели появятся после восстановления базы.</span></div>` : '<div class="panel skel" style="height:200px"></div>'; return; }
  const q = s.quality_live, T = s.tickets.total, chk = s.live_citation_check || {};
  const live = `live: база Sentra, ${nf(T)} обращений, период ${span(s)}`;
  const guardN = q.guard_removed_missing + q.guard_promise + q.guard_text_ref;
  const P = M && M.provenance;
  const metricsBlock = M ? `
  <section class="panel hero">
    <div class="panel-h"><h2>Оффлайн-валидация</h2><span class="aside">исторический отчёт, не живой поток</span></div>
    <div class="panel-b" style="padding-bottom:0">${src(`${esc(P.file)}, изменён ${fmtDate(P.file_modified)}. ${esc(P.population)}`)}
      <div class="notice warn">${ic('alert')}<span>${esc(P.note)}${P.models_now ? '' : ' Сейчас ML-моделей нет, текущие результаты могут отличаться от этих цифр.'}</span></div></div>
    <div class="rings">
      ${X.ring(M.category_accuracy, dec(M.category_accuracy * 100, 1), '%', 'Категория', `accuracy; macro-F1 ${pc(M.category_macro_f1, 1)}`)}
      ${X.ring(M.priority_macro_f1, dec(M.priority_macro_f1 * 100, 1), '%', 'Приоритет', `macro-F1; accuracy ${pc(M.priority_accuracy, 1)}`)}
      ${X.ring(1 - M.citations_nonexistent / M.citations_total, dec((1 - M.citations_nonexistent / M.citations_total) * 100, 1), '%', 'Верные цитаты', `${M.citations_nonexistent} несуществующих из ${nf(M.citations_total)} на валидации`)}
      ${X.ring(M.draft_lang_equals_admin_reply_lang, dec(M.draft_lang_equals_admin_reply_lang * 100, 1), '%', 'Язык ответа', 'совпал с языком ответа админов')}
    </div>
  </section>
  <div class="cols even">
    <section class="panel"><div class="panel-h"><h2>Совпадение с админами</h2><span class="aside">оффлайн</span></div>
      <div class="panel-b">${[
        ['Сценарий совпал с решением админа', `Жалобы с распознанным вердиктом: ${M.draft_scenario_n}`, M.draft_scenario_matches_admin_verdict],
        ['Черновики с цитатой пункта', 'Доля черновиков со ссылкой на правило', M.drafts_with_citation_share],
        ['Доля «нужен человек»', `Жалобы ${pc(M.needs_human_share_by_kind.complaint)}, репорты ${pc(M.needs_human_share_by_kind.report)}`, M.needs_human_share],
      ].map(([l, sub, x]) => `<div class="metric-row"><div class="l">${l}<small>${sub}</small></div><div class="track"><i style="width:${x * 100}%"></i></div><div class="val">${pc(x, 1)}</div></div>`).join('')}
        <div class="stats3" style="margin-top:16px;gap:34px">
          <div><b>${dec(M.latency_ms_p50)} мс</b><span>задержка p50, оффлайн</span></div>
          <div><b>${dec(M.latency_ms_p95)} мс</b><span>задержка p95, оффлайн</span></div>
          <div><b>$${M.cost_usd_per_ticket}</b><span>за обращение, без LLM</span></div></div></div></section>
    <section class="panel"><div class="panel-h"><h2>Какие сценарии выбирал сервис</h2><span class="aside">оффлайн</span></div>
      <div class="panel-b"><div class="bars">${Object.entries(M.intents).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, n], _, a) => `
        <div class="bar-row"><span>${esc(intentName(k))}</span><div class="track"><i style="width:${n / a[0][1] * 100}%"></i></div><span class="n num">${n}</span></div>`).join('')}</div></div></section>
  </div>` : `<section class="panel"><div class="empty">${ic('shield')}<h3>Метрик оффлайн-валидации нет</h3><p>Файл reports/metrics.json появляется после <span class="mono">make eval</span>. Живые показатели ниже от него не зависят.</p></div></section>`;

  const sc = S.selfcheck;
  v.innerHTML = `
  ${envPanel(h)}

  <section class="panel" aria-label="Живое состояние">
    <div class="panel-h"><h2>Живое состояние</h2><span class="aside">${live}</span></div>
    <div class="strip">
      ${gauge('Остановлено guard', guardN, 'несуществующий пункт, обещание, номер в тексте', '', guardN ? 'crit' : '')}
      ${gauge('Нужен человек', T ? `${Math.round(s.needs_human.total / T * 100)}<small>%</small>` : '—', `${s.needs_human.total} из ${T}`)}
      ${gauge('Низкая уверенность', q.low_confidence, 'меньше 0,5, ушло человеку')}
      ${gauge('Средняя уверенность', q.avg_confidence == null ? '—' : dec(q.avg_confidence, 2), 'по классификации')}
      ${gauge('Правки админов', s.overrides.text_edited, `категорий исправлено: ${s.overrides.category}, приоритетов: ${s.overrides.priority}`)}
    </div></section>

  <section class="panel">
    <div class="panel-h"><h2>Цепочка проверок</h2><span class="aside">каждый ответ проходит все пять</span></div>
    <div class="panel-b">${src(live)}<div class="route five">${[
      { t: 'Цитаты', n: chk.available ? `${chk.failed} из ${nf(chk.checked)}` : '—', sm: 1, d: 'Пункты выбирает код. Несуществующий пункт удаляется, обращение уходит человеку.', s: 'сверено сейчас с rules.json', cls: chk.failed ? 'warn' : '' },
      { t: 'Обещания', n: q.guard_promise, d: 'Разбан, возврат, компенсация на 6 языках блокируют автоответ.', s: 'остановлено в черновиках', cls: q.guard_promise ? 'warn' : '' },
      { t: 'Номер в тексте', n: q.guard_text_ref + q.guard_removed_missing, d: 'Номер пункта в тексте сверяется с rules.json и подтверждёнными цитатами.', s: 'остановлено', cls: (q.guard_text_ref + q.guard_removed_missing) ? 'warn' : '' },
      { t: 'Правки текста', n: q.approvals_blocked, d: 'Текст администратора проверяется заново; с несуществующим пунктом или обещанием не сохраняется.', s: 'попыток отклонено', cls: 'human' },
      { t: 'Чувствительное', n: q.sensitive_to_human, d: 'Платежи, взлом, жалобы на админов и p0 всегда идут человеку.', s: `всегда к человеку; повторов к человеку по политике: ${q.policy_to_human}`, cls: 'human' },
    ].map(x => `
      <div class="stage ${x.cls || ''}"><span class="node"></span><span class="t">${x.t}</span><span class="n${x.sm ? ' sm' : ''}">${x.n}</span><span class="s">${x.s}</span><span class="d">${x.d}</span></div>`).join('')}</div>
      ${chk.available ? `<p class="muted" style="font-size:12.5px;margin-top:10px">Проверка цитат: ${esc(chk.scope)}. Проверено ${nf(chk.checked)}, ошибок ${chk.failed}.${chk.failed ? ' ' + chk.failures.map(f => esc(f.id)).join(', ') : ''}</p>` : ''}</div>
  </section>

  <section class="panel">
    <div class="panel-h"><h2>Самопроверка безопасности</h2>
      <span class="aside"><button class="btn sm" id="run-selfcheck" type="button">${ic('shield')}${sc ? 'Запустить снова' : 'Запустить'}</button></span></div>
    <div class="panel-b">
      <p class="muted" style="font-size:12.5px;margin-bottom:10px">Встроенные пробы идут через настоящий пайплайн на текущих правилах и моделях: просьба пообещать разбан, выдуманный пункт, HTML в тексте, платёж, взлом, языки. Пробы не сохраняются как обращения.</p>
      ${sc ? `<div class="notice ${sc.failed ? 'warn' : 'ok'}">${ic(sc.failed ? 'alert' : 'ok')}<span>Пройдено ${sc.passed} из ${sc.ran} за ${dec(sc.duration_ms)} мс. ${sc.rules_synthetic ? 'Правила тестовые (synthetic). ' : ''}${sc.models_loaded ? '' : 'ML-моделей нет, работают только правила. '}${esc(sc.note)}</span></div>
        <div class="probes">${sc.results.map(probeRow).join('')}</div>` : '<div class="muted">Самопроверка ещё не запускалась в этой сессии.</div>'}
    </div></section>

  ${metricsBlock}`;
  const btn = $('#run-selfcheck');
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    try { S.selfcheck = await X.api('/quality/selfcheck', { method: 'POST' }); }
    catch (e) { X.toast('Самопроверка не выполнена: ' + e.message, 'risk'); }
    X.renderQuality();
  };
};

/* ---------- шаблоны ---------- */
const TPL_STATUS = { pending: ['Не рассмотрен', ''], approved: ['Утверждён', 'auto'], rejected: ['Отклонён', 'risk'] };
const tkey = k => k.replace(/[^\w:-]/g, '_');

function safetyBlock(r) {
  const sf = r.safety;
  if (!sf) return '';
  const c = sf.compat || {};
  return `<div class="checks" style="margin-top:2px">
    <div class="check ${sf.ok ? 'ok' : 'risk'}">${ic(sf.ok ? 'ok' : 'stop')}<div><div class="t">${sf.ok ? 'Проверка безопасности пройдена' : 'Проверка безопасности не пройдена'}</div>
      <div class="d">${sf.ok ? `Обещаний нет, пункты правил из rules.json${sf.cited.length ? ': ' + sf.cited.map(esc).join(', ') : ' не упомянуты'}.` : sf.problems.map(esc).join('; ')}</div></div></div>
    <div class="check idle">${ic('dot')}<div><div class="t">Совместимость с пайплайном</div>
      <div class="d">Язык: ${esc(X.langName(c.detected_lang))}${c.known_placeholders && c.known_placeholders.length ? `; поля: ${c.known_placeholders.map(p => '{' + esc(p) + '}').join(', ')}` : ''}. В генерацию ответов не подключён.</div></div></div></div>`;
}

X.renderTemplates = () => {
  const v = $('#view'); v.classList.remove('flush');
  const T = S.tpl;
  if (!T) { v.innerHTML = '<div class="panel skel" style="height:96px"></div><div class="panel skel" style="height:260px"></div>'; return; }
  if (!T.available) { v.innerHTML = `<section class="panel"><div class="empty">${ic('tpl')}<h3>Сводки по шаблонам нет</h3><p>${esc(T.hint || 'нет данных')}. Запуск: <span class="mono">make suggest-templates</span>.</p></div></section>`; return; }
  const t = T.totals || {}, f = S.tplFilter, all = T.clusters, P = T.provenance;
  const cand = all.filter(c => c.gap), cats = [...new Set(cand.map(c => c.category))];
  let list = cand.filter(c => (f.cat === 'all' || c.category === f.cat) && (f.status === 'all' || c.review.status === f.status));
  list = [...list].sort((a, b) => f.sort === 'share' ? b.top_reply_share - a.top_reply_share : b.size - a.size);
  const shown = list.slice(0, S.tplShown);
  const rc = T.review_counts || { pending: 0, approved: 0, rejected: 0 };

  v.innerHTML = `
  <section class="panel"><div class="strip" style="grid-template-columns:repeat(5,minmax(0,1fr))">
    ${gauge('Кластеров обращений', nf(t.clusters), `из ${nf((T.meta || {}).tickets || 0)} обращений train`)}
    ${gauge('Кандидатов в шаблоны', t.candidates, 'черновик покрывает их плохо')}
    ${gauge('Утверждено', rc.approved, 'решение модератора')}
    ${gauge('Отклонено', rc.rejected, 'решение модератора')}
    ${gauge('Не рассмотрено', cand.filter(c => c.review.status === 'pending').length, 'среди кандидатов')}
  </div></section>

  <div class="notice">${ic('db')}<span><b>Оффлайн-анализ.</b> ${esc(P.population)}. Файл ${esc(P.file)}, изменён ${fmtDate(P.file_modified)}. Это не живой поток: кластеры построены по обучающей выгрузке, а не по обращениям из очереди. ${esc(P.live_note)}</span></div>

  <section class="panel hero">
    <div class="panel-h"><h2>Карта кластеров</h2><span class="aside">точка — группа похожих обращений, нажмите на яркую, чтобы открыть шаблон</span></div>
    ${X.clusterMap(all)}
  </section>

  <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
    <div style="min-width:200px"><select id="tf-cat" aria-label="Категория"><option value="all">Все категории</option>${cats.map(c => `<option value="${esc(c)}" ${c === f.cat ? 'selected' : ''}>${esc(catName(c))}</option>`).join('')}</select></div>
    <div class="tabs" id="tf-status" role="group" aria-label="Решение" style="min-width:330px">
      ${[['all', 'Все'], ['pending', 'Не рассмотрены'], ['approved', 'Утверждены'], ['rejected', 'Отклонены']].map(([k, l]) => `<button type="button" data-v="${k}" aria-pressed="${f.status === k}">${l}</button>`).join('')}</div>
    <div class="tabs" id="tf-sort" role="group" aria-label="Сортировка" style="min-width:300px">
      <button type="button" data-v="size" aria-pressed="${f.sort === 'size'}">По размеру кластера</button>
      <button type="button" data-v="share" aria-pressed="${f.sort === 'share'}">По повторяемости ответа</button></div>
  </div>
  <p class="muted" style="font-size:12.5px;max-width:100ch">Утверждённый шаблон только сохраняется для разработчиков. В автоответы он не подключается: сначала нужна доработка пайплайна и повторная оценка. Любой текст проходит те же проверки, что и ответы: пункты правил по rules.json, обещания, поля подстановки.</p>

  ${shown.map(c => {
    const r = c.review, st = TPL_STATUS[r.status], err = (S.tplErr || {})[c.key];
    return `<section class="panel cluster" id="cl-${esc(tkey(c.key))}" data-key="${esc(c.key)}">
    <div class="cluster-h"><h3>${esc(catName(c.category))}</h3><span class="chip mono">кластер ${c.cluster}</span>
      <span class="chip ${st[1]}">${st[0]}${r.rev ? ' · ревизия ' + r.rev : ''}</span>
      <span class="chip">сценарий: ${esc(intentName(c.intent))}, ${Math.round(c.intent_share * 100)}%</span>
      <span class="aside muted" style="margin-left:auto">${(c.refs || []).length ? 'пункты: ' + esc(c.refs.join(', ')) : 'без ссылок на пункты'}</span></div>
    <div class="stats3">
      <div><b>${nf(c.size)}</b><span>обращений в кластере (оффлайн)</span></div>
      <div><b>${Math.round(c.top_reply_share * 100)}%</b><span>одинаковый ответ админов</span></div>
      <div><b>${c.draft_sim == null ? '—' : dec(c.draft_sim, 3)}</b><span>близость нашего черновика</span></div>
      <div><b>${nf(c.live_matches)}</b><span>живых обращений с тем же сценарием</span></div>
    </div>
    <div><label class="lbl" for="tx-${esc(tkey(c.key))}">Текст шаблона (можно править)</label>
      <textarea class="draft" id="tx-${esc(tkey(c.key))}" data-tx rows="3" style="min-height:84px">${esc(r.template_final || c.template)}</textarea></div>
    ${err ? `<div class="check risk">${ic('stop')}<div><div class="t">Не сохранено</div><div class="d">${err.map(esc).join('; ')}</div></div></div>` : safetyBlock(r)}
    <div class="actions-bar" style="margin-top:0">
      <button class="btn primary sm" data-tact="approve" type="button">${ic('check')}Проверить и утвердить</button>
      <button class="btn sm" data-tact="edit" type="button">Сохранить правку</button>
      <button class="btn danger sm" data-tact="reject" type="button">Отклонить</button>
      ${r.rev ? '<button class="btn ghost sm" data-tact="reset" type="button">Вернуть исходный</button>' : ''}
      <span class="sp"></span>${r.reviewer ? `<span class="muted" style="font-size:12px">${esc(fmtTime(r.updated_at))}</span>` : ''}</div>
    <div class="chips">${(c.terms || []).map(w => `<span class="chip mono">${esc(w)}</span>`).join('')}</div>
    <div class="muted" style="font-size:12.5px">Почему кандидат: ${esc((c.gap_reasons || []).join('; ') || '—')}${(c.guard || []).length ? '. Guard: ' + esc(c.guard.join('; ')) : ''}</div>
    ${c.examples ? `<details><summary class="muted" style="cursor:pointer">Примеры обращений (${c.examples.length})</summary>${c.examples.map(e => `<div class="rule"><div class="tx">${esc(e.player_text || '')}</div>${e.reply ? `<div class="muted">Ответ админа: ${esc(e.reply)}</div>` : ''}</div>`).join('')}</details>`
      : `<div class="muted" style="font-size:12.5px">Примеров обращений нет: ${esc(P.examples_note || '')}</div>`}
  </section>`;
  }).join('') || `<section class="panel"><div class="empty"><h3>Кандидатов нет при текущем фильтре</h3></div></section>`}
  ${list.length > shown.length ? `<div style="text-align:center"><button class="btn" id="tf-more" type="button">Показать ещё ${Math.min(12, list.length - shown.length)}</button></div>` : ''}`;

  $('#tf-cat').onchange = e => { f.cat = e.target.value; S.tplShown = 12; X.renderTemplates(); };
  $('#tf-sort').onclick = e => { const b = e.target.closest('button'); if (b) { f.sort = b.dataset.v; X.renderTemplates(); } };
  $('#tf-status').onclick = e => { const b = e.target.closest('button'); if (b) { f.status = b.dataset.v; S.tplShown = 12; X.renderTemplates(); } };
  const more = $('#tf-more'); if (more) more.onclick = () => { S.tplShown += 12; X.renderTemplates(); };
  $$('[data-tact]').forEach(b => b.onclick = () => reviewTemplate(b));

  const svg = $('.cmap'), tip = $('#tip');
  svg.addEventListener('mousemove', e => {
    const el = e.target.closest('circle[data-i]');
    if (!el) { tip.hidden = true; return; }
    const c = all[+el.dataset.i], box = svg.parentElement.getBoundingClientRect();
    tip.hidden = false;
    tip.innerHTML = `<b>${esc(catName(c.category))}</b><span>${nf(c.size)} обращений, ответ повторяется в ${Math.round(c.top_reply_share * 100)}%</span><span>близость черновика ${c.draft_sim == null ? '—' : dec(c.draft_sim, 3)}</span>${c.gap ? '<span class="sig">кандидат в шаблон</span>' : ''}`;
    tip.style.left = Math.min(box.width - 250, e.clientX - box.left + 14) + 'px';
    tip.style.top = Math.max(0, e.clientY - box.top - 8) + 'px';
  });
  svg.addEventListener('mouseleave', () => { tip.hidden = true; });
  svg.addEventListener('click', e => {
    const el = e.target.closest('circle.cand'); if (!el) return;
    const c = all[+el.dataset.i], idx = list.indexOf(c);
    if (idx < 0) { f.cat = 'all'; f.status = 'all'; X.renderTemplates(); return; }
    if (idx >= S.tplShown) { S.tplShown = idx + 1; X.renderTemplates(); }
    const card = $('#cl-' + tkey(c.key));
    if (card) { card.scrollIntoView({ block: 'center', behavior: 'smooth' }); card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash'); }
  });
};

async function reviewTemplate(btn) {
  if (S.busy) return;
  const card = btn.closest('[data-key]'), key = card.dataset.key, action = btn.dataset.tact;
  const text = $('[data-tx]', card).value;
  const cur = S.tpl.clusters.find(c => c.key === key);
  S.busy = true; $$('[data-tact]').forEach(b => { b.disabled = true; });
  S.tplErr = S.tplErr || {};
  try {
    await X.post(`/templates/${encodeURIComponent(key)}/review`, { action, template: action === 'reject' || action === 'reset' ? undefined : text, expected_rev: cur.review.rev || undefined });
    delete S.tplErr[key];
    S.tpl = await X.api('/templates?only_candidates=false');
    X.toast({ approve: 'Шаблон утверждён и сохранён (в генерацию ответов не подключён)', edit: 'Правка шаблона сохранена', reject: 'Шаблон отклонён', reset: 'Возвращён исходный текст' }[action]);
  } catch (e) {
    if (e.code === 'template_rejected') { S.tplErr[key] = e.detail.problems || [e.message]; X.toast('Шаблон не прошёл проверку: не утверждён', 'risk'); }
    else if (e.code === 'conflict') { S.tpl = await X.api('/templates?only_candidates=false').catch(() => S.tpl); X.toast('Решение по шаблону уже изменилось, страница обновлена', 'risk'); }
    else X.toast('Не сохранено: ' + e.message, 'risk');
  } finally { S.busy = false; }
  X.renderTemplates();
}
})();
