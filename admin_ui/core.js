/* Sentra by LGTM: ядро интерфейса модератора. Без сборки и зависимостей; модули делят объект window.Sentra. */
(() => {
'use strict';
const X = window.Sentra = {};

/* ---------- утилиты ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic = (n, cls = '') => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${n}"/></svg>`;
const nf = n => new Intl.NumberFormat('ru-RU').format(n);
const pc = (x, d = 0) => (x * 100).toFixed(d).replace('.', ',') + '%';
const dec = (x, d = 1) => Number(x).toFixed(d).replace('.', ',');
const rx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const clip = (s, n) => { s = String(s || ''); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
const ago = t => {
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 45) return 'только что';
  if (s < 3600) return Math.round(s / 60) + ' мин назад';
  if (s < 86400) return Math.round(s / 3600) + ' ч назад';
  return Math.round(s / 86400) + ' дн назад';
};
const fmtTime = iso => {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
};
const fmtDate = iso => {
  const d = new Date(iso);
  return isNaN(d) ? '—' : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
};
const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : 'k' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12));
Object.assign(X, { $, $$, esc, ic, nf, pc, dec, rx, clip, ago, fmtTime, fmtDate, uuid });

/* ---------- словари ---------- */
X.CAT = {
  'complaint.insult': 'Оскорбление', 'complaint.cheat': 'Читы и сторонний софт', 'complaint.dm': 'Убийство без причины',
  'complaint.scam': 'Мошенничество', 'complaint.rmt_ads': 'Реклама и продажа за реальные деньги',
  'complaint.admin': 'Жалоба на администратора', 'complaint.invalid': 'Некорректная жалоба', 'complaint.other': 'Другое',
  'report.account': 'Аккаунт и взлом', 'report.complaint': 'Жалоба в репорте', 'report.help': 'Просьба о помощи',
  'report.offtopic': 'Оффтоп', 'report.payment': 'Платёж и донат', 'report.question': 'Вопрос игрока',
};
X.CAT_SHORT = {
  'complaint.insult': 'Оскорбл.', 'complaint.cheat': 'Читы', 'complaint.dm': 'Убийства', 'complaint.scam': 'Скам',
  'complaint.rmt_ads': 'Реклама', 'complaint.admin': 'На админа', 'complaint.invalid': 'Некорр.', 'complaint.other': 'Другое',
  'report.account': 'Аккаунт', 'report.complaint': 'Жалоба', 'report.help': 'Помощь', 'report.offtopic': 'Оффтоп',
  'report.payment': 'Платёж', 'report.question': 'Вопрос',
};
X.INTENT = {
  approve: 'Подтвердить нарушение', need_evidence: 'Запросить доказательства', appeal_reject: 'Отклонить обжалование',
  not_complaint: 'Не жалоба', no_description: 'Нет описания', toxic: 'Оскорбления в жалобе', admin_complaint: 'Жалоба на администратора',
  duplicate: 'Дубль', help_ack: 'Принято, разберёмся', offtopic_flood: 'Оффтоп и флуд', question_unknown: 'Вопрос без ответа в базе',
  help_generic: 'Общая помощь', help_vehicle: 'Эвакуатор', clarify: 'Уточнить детали', report_watch: 'Слежу за игроком',
  help_service: 'Служба поддержки', report_need_id: 'Нужен ID игрока', report_rp: 'Термин из РП', question_kb: 'Ответ из базы знаний',
  event_tp: 'Телепорт на мероприятие', report_appeal: 'Обжалование в репорте', question_howto: 'Вопрос «как сделать»',
  question_tech: 'Технический вопрос', payment: 'Платёж: в техподдержку', account: 'Аккаунт и взлом: передать',
  appeal: 'Обжалование наказания', threat: 'Угроза вне игры: старшей администрации',
};
X.VERDICT = { approve: 'нарушение подтверждено', need_evidence: 'не хватает доказательств', reject: 'жалоба отклонена' };
X.LANG = { ru: 'Русский', uz: 'Узбекский', kk: 'Казахский', en: 'Английский', es: 'Испанский', pt: 'Португальский', uk: 'Украинский', und: 'Не определён' };
X.PRI = { p0: 'критичный', p1: 'высокий', p2: 'средний', p3: 'низкий' };
X.STATUS = { new: 'Ждёт решения', approved: 'Ответ утверждён', escalated: 'Эскалировано', closed: 'Закрыто' };
X.EVT = {
  'ticket.created': 'Обращение создано', 'ticket.triaged': 'Триаж выполнен', 'ticket.duplicate_linked': 'Связано с первым обращением',
  'decision.approve': 'Ответ утверждён и сохранён', 'decision.edit': 'Правка черновика сохранена', 'decision.escalate': 'Эскалировано',
  'decision.close': 'Обращение закрыто', 'decision.reopen': 'Возвращено в работу', 'decision.blocked': 'Текст не прошёл проверку, не сохранён',
};
X.catName = c => X.CAT[c] || c;
X.intentName = i => X.INTENT[i] || i || '—';
X.langName = l => X.LANG[l] || l;
X.isGuard = s => /удалены несуществующие|обещани|в тексте черновика пункт/i.test(s);
X.isDupReason = s => /менее часа/i.test(s);
X.isSpamReason = s => /спам|флуд/i.test(s);

/* ---------- состояние ---------- */
X.S = {
  health: null, stats: null, meta: null, metrics: null, tpl: null, dup: null, selfcheck: null,
  list: { items: [], total: 0 }, attention: [], detail: {}, rules: {}, ws: {},
  view: 'center', sel: null, version: -1, offline: false, busy: false, tplShown: 12,
  filter: { q: '', pri: 'all', tab: 'new' }, tplFilter: { cat: 'all', sort: 'size', status: 'all' },
};

/* ---------- обращения к серверу ---------- */
class ApiError extends Error {
  constructor(status, body) {
    const d = body && body.detail;
    const detail = Array.isArray(d) ? { message: 'Некорректный запрос' } : typeof d === 'string' ? { message: d } : (d || {});
    super(detail.message || (status ? 'Ошибка ' + status : 'Нет связи с сервисом'));
    this.status = status; this.code = detail.code || (status ? 'http_' + status : 'offline'); this.detail = detail;
  }
}
X.ApiError = ApiError;
X.api = async (url, opt) => {
  let r;
  try { r = await fetch(url, opt); } catch { throw new ApiError(0, null); }
  let body = null;
  try { body = await r.json(); } catch { /* тело не JSON */ }
  if (!r.ok) throw new ApiError(r.status, body);
  return body;
};
X.post = (url, body, headers = {}) => X.api(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body),
});

/* ---------- копирование в буфер: успех объявляется только после подтверждения браузера ---------- */
X.copyText = async text => {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* пробуем запасной путь */ }
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;left:-9999px;top:0';
  document.body.append(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
};

X.toast = (msg, kind = 'ok') => {
  const el = document.createElement('div');
  el.className = 'toast';
  el.innerHTML = `${ic(kind === 'risk' ? 'alert' : 'ok')}<span>${esc(msg)}</span>`;
  if (kind === 'risk') $('svg', el).style.color = 'var(--p0)';
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'risk' ? 7000 : 4200);
};

X.gauge = (k, v, h, extra = '', cls = '') =>
  `<div class="gauge ${cls}"><span class="k">${k}</span><span class="v">${v}</span><span class="h">${h}</span>${extra}</div>`;

/* подпись «откуда число и за какой период»: у каждой метрики на экране качества */
X.src = (text) => `<div class="src">${ic('db')}<span>${text}</span></div>`;

X.rulesFor = async cites => {
  const need = cites.filter(c => !(c in X.S.rules));
  if (!need.length) return;
  try {
    const d = await X.api('/rules?' + need.map(c => 'cite=' + encodeURIComponent(c)).join('&'));
    need.forEach(c => { X.S.rules[c] = d[c] || null; });
  } catch { need.forEach(c => { X.S.rules[c] = null; }); }
};
})();
