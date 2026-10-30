/* Sentra by LGTM: визуализации. Рисуют только агрегаты, которые посчитал сервер (/stats, /templates). */
(() => {
'use strict';
const X = window.Sentra;
const { esc, dec, nf, catName } = X;

const RAMP = {
  p0: ['#4A1B19', '#B8423C', '#FF5E57', '#FFD6D2'],
  p1: ['#4A3216', '#B97724', '#FFA24A', '#FFE3C2'],
  p2: ['#143D36', '#1F8E78', '#2FD9B5', '#C8FFF3'],
  p3: ['#27302E', '#4B5B57', '#82908B', '#DCE4E1'],
};
const rgb = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const ramp = (stops, t) => {
  const n = stops.length - 1, i = Math.min(n - 1, Math.floor(t * n)), f = t * n - i, a = rgb(stops[i]), b = rgb(stops[i + 1]);
  return 'rgb(' + a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(',') + ')';
};

/* Sankey: тип обращения → категория → решение. Ширина ленты равна числу обращений. flow считает сервер. */
X.sankey = flow => {
  const kind = flow.kind || {}, cat = flow.cat || {}, dec_ = flow.dec || {}, lk = flow.links || {}, risk = flow.risk || {};
  const T = Object.values(kind).reduce((a, b) => a + b, 0);
  const W = 1180, H = 300, padT = 12, gap = 10, nw = 12, XS = [132, 566, 968];
  const top = Object.keys(cat).sort((a, b) => cat[b] - cat[a]).slice(0, 8);
  const bucket = c => (top.includes(c) ? c : '*');
  const cat2 = {}, lk2 = {}, risk2 = {};
  Object.entries(cat).forEach(([c, n]) => { cat2[bucket(c)] = (cat2[bucket(c)] || 0) + n; risk2[bucket(c)] = Math.max(risk2[bucket(c)] || 0, risk[c] || 0); });
  Object.entries(lk).forEach(([key, n]) => {
    const [a, b] = key.split('>'), ka = a.includes('.') ? bucket(a) : a, kb = b.includes('.') ? bucket(b) : b;
    lk2[ka + '>' + kb] = (lk2[ka + '>' + kb] || 0) + n;
  });
  const kindNodes = ['complaint', 'report'].filter(k => kind[k]).map(k => ({ id: k, label: k === 'complaint' ? 'Жалобы' : 'Репорты', n: kind[k], col: '#9DB2AB' }));
  const catNodes = [...top, ...(cat2['*'] ? ['*'] : [])].map(c => ({
    id: c, label: c === '*' ? 'Остальные' : catName(c), n: cat2[c],
    col: risk2[c] === 2 ? '#FF5E57' : risk2[c] === 1 ? '#FFA24A' : '#8CF2DC',
  }));
  const decNodes = [{ id: 'h', label: 'Нужен человек', n: dec_.h || 0, col: '#FFA24A' }, { id: 'a', label: 'Можно без правок', n: dec_.a || 0, col: '#2FD9B5' }].filter(n => n.n);
  const cols = [kindNodes, catNodes, decNodes];
  const scale = Math.min(...cols.map(c => (H - gap * (c.length - 1)) / T));
  const byId = {};
  cols.forEach((nodes, ci) => {
    const total = nodes.reduce((a, n) => a + Math.max(4, n.n * scale), 0) + gap * (nodes.length - 1);
    let y = padT + (H - total) / 2;
    nodes.forEach(n => { n.x = XS[ci]; n.h = Math.max(4, n.n * scale); n.y = y; n.out = 0; n.in = 0; y += n.h + gap; byId[(ci === 0 ? 'k:' : ci === 1 ? 'c:' : 'd:') + n.id] = n; });
  });
  const links = [];
  Object.entries(lk2).forEach(([key, n]) => {
    const [a, b] = key.split('>');
    const s = byId['k:' + a] && byId['c:' + b] ? [byId['k:' + a], byId['c:' + b]] : [byId['c:' + a], byId['d:' + b]];
    if (s[0] && s[1]) links.push({ s: s[0], t: s[1], n, w: n * scale });
  });
  const order = n => n.y;
  [...kindNodes, ...catNodes].forEach(n => {
    links.filter(l => l.s === n).sort((a, b) => order(a.t) - order(b.t)).forEach(l => { l.sy = n.y + n.out; n.out += l.w; });
  });
  [...catNodes, ...decNodes].forEach(n => {
    links.filter(l => l.t === n).sort((a, b) => order(a.s) - order(b.s)).forEach(l => { l.ty = n.y + n.in; n.in += l.w; });
  });
  const defs = [], paths = [], flows = [];
  links.forEach((l, i) => {
    const x0 = l.s.x + nw, x1 = l.t.x, m = (x0 + x1) / 2;
    defs.push(`<linearGradient id="sk${i}" gradientUnits="userSpaceOnUse" x1="${x0}" x2="${x1}"><stop offset="0" stop-color="${l.s.col}"/><stop offset="1" stop-color="${l.t.col}"/></linearGradient>`);
    paths.push(`<path class="lk" fill="url(#sk${i})" d="M${x0},${l.sy}C${m},${l.sy} ${m},${l.ty} ${x1},${l.ty}L${x1},${l.ty + l.w}C${m},${l.ty + l.w} ${m},${l.sy + l.w} ${x0},${l.sy + l.w}Z"><title>${esc(l.s.label)} → ${esc(l.t.label)}: ${l.n}</title></path>`);
    if (l.w > 3) flows.push(`<path class="flow" d="M${x0},${l.sy + l.w / 2}C${m},${l.sy + l.w / 2} ${m},${l.ty + l.w / 2} ${x1},${l.ty + l.w / 2}" style="animation-delay:${-(i % 7) * .4}s"/>`);
  });
  const nodes = cols.map((c, ci) => c.map(n => {
    const cy = n.y + n.h / 2, share = Math.round(n.n / T * 100);
    const lab = ci === 0 ? `<text class="nl" x="${n.x - 14}" y="${cy + 4}" text-anchor="end">${esc(n.label)} <tspan class="nv">${n.n}</tspan></text>`
      : `<text class="nl" x="${n.x + nw + 12}" y="${cy + 4}">${esc(n.label)} <tspan class="nv">${n.n}${ci === 2 ? ` (${share}%)` : ''}</tspan></text>`;
    return `<g><rect x="${n.x}" y="${n.y}" width="${nw}" height="${n.h}" rx="3" fill="${n.col}"><title>${esc(n.label)}: ${n.n}</title></rect>${lab}</g>`;
  }).join('')).join('');
  return `<svg class="sankey" viewBox="0 0 ${W} ${H + padT * 2}" role="img" aria-label="Поток ${T} обращений: тип, категория, решение">
    <defs>${defs.join('')}</defs><g class="lks">${paths.join('')}</g><g>${flows.join('')}</g>${nodes}</svg>`;
};

/* Соты: категория × приоритет. Цвет ряда задаёт срочность, яркость соты задаёт число обращений. heat считает сервер. */
X.hexmap = heat => {
  const tot = {};
  const rows = ['p0', 'p1', 'p2', 'p3'];
  rows.forEach(p => Object.entries(heat[p] || {}).forEach(([c, n]) => { tot[c] = (tot[c] || 0) + n; }));
  const cats = Object.keys(tot).sort((a, b) => tot[b] - tot[a]).slice(0, 8);
  const max = Math.max(1, ...rows.flatMap(p => cats.map(c => (heat[p] || {})[c] || 0)));
  const R = 25, w = Math.sqrt(3) * R, x0 = 38, y0 = 30, W = x0 + cats.length * w + w / 2 + 8, H = y0 + 3 * 1.5 * R + R + 50;
  const pts = (cx, cy, r) => [0, 1, 2, 3, 4, 5].map(i => { const a = (Math.PI / 180) * (60 * i - 30); return (cx + r * Math.cos(a)).toFixed(1) + ',' + (cy + r * Math.sin(a)).toFixed(1); }).join(' ');
  let out = '';
  rows.forEach((p, ri) => {
    out += `<text class="hl" x="${x0 - 14}" y="${y0 + ri * 1.5 * R + 4}" text-anchor="end" fill="var(--${p})">${p}</text>`;
    cats.forEach((c, ci) => {
      const n = (heat[p] || {})[c] || 0, cx = x0 + ci * w + w / 2 + (ri % 2 ? w / 2 : 0), cy = y0 + ri * 1.5 * R;
      const t = n ? 0.22 + 0.78 * n / max : 0;
      const fill = n ? ramp(RAMP[p], t) : 'rgba(255,255,255,.035)';
      out += `<g class="hx${n ? ' on' : ''}"><polygon points="${pts(cx, cy, R - 2)}" fill="${fill}" stroke="${n ? 'rgba(255,255,255,.18)' : 'rgba(255,255,255,.07)'}" stroke-width="1"/>`
        + (n ? `<text x="${cx}" y="${cy + 5}" text-anchor="middle" fill="${t > .62 ? '#06100E' : '#fff'}">${n}</text>` : '')
        + `<title>${p}, ${esc(catName(c))}: ${n}</title></g>`;
    });
  });
  cats.forEach((c, ci) => { out += `<text class="hc" transform="translate(${(x0 + ci * w + w + 4).toFixed(1)} ${y0 + 3 * 1.5 * R + R + 16}) rotate(-38)" text-anchor="end">${esc(X.CAT_SHORT[c] || c)}</text>`; });
  return `<svg class="hexmap" viewBox="0 0 ${W.toFixed(0)} ${H.toFixed(0)}" role="img" aria-label="Тепловая карта обращений: категория и приоритет">${out}</svg>`;
};

/* Кольцо из 60 делений: доля от 0 до 1 */
X.ring = (p, num, unit, label, sub) => {
  const n = 60, lit = Math.round(Math.max(0, Math.min(1, p)) * n);
  let t = '';
  for (let i = 0; i < n; i++) {
    const a = (i / n) * 2 * Math.PI - Math.PI / 2, c = Math.cos(a), s = Math.sin(a);
    t += `<line x1="${(60 + c * 45).toFixed(1)}" y1="${(60 + s * 45).toFixed(1)}" x2="${(60 + c * 56).toFixed(1)}" y2="${(60 + s * 56).toFixed(1)}"${i < lit ? ' class="on"' : ''}/>`;
  }
  return `<div class="ringbox"><div class="rg"><svg viewBox="0 0 120 120" aria-hidden="true">${t}</svg>
    <div class="rn">${num}<small>${unit}</small></div></div><div class="rl">${label}</div><div class="rs">${sub}</div></div>`;
};

/* Карта кластеров: x — близость нашего черновика к ответам админов, y — как часто админы повторяют один ответ,
   радиус — число обращений. Данные: оффлайн-анализ scripts/suggest_templates.py. */
X.clusterMap = all => {
  const W = 1180, H = 360, L = 62, Rg = 24, Tp = 16, B = 46, pw = W - L - Rg, ph = H - Tp - B;
  const xmax = Math.ceil(Math.max(...all.map(c => c.draft_sim || 0)) * 20) / 20 + 0.02;
  const ymax = Math.ceil(Math.max(...all.map(c => c.top_reply_share || 0)) * 10) / 10;
  const smax = Math.max(...all.map(c => c.size));
  const XX = c => L + (c.draft_sim || 0) / xmax * pw, YY = c => Tp + ph - (c.top_reply_share || 0) / ymax * ph;
  const rad = c => 3.5 + Math.sqrt(c.size / smax) * 17;
  const pts = all.map((c, i) => ({ c, i })).sort((a, b) => b.c.size - a.c.size);
  let ax = '';
  for (let x = 0; x <= xmax + 1e-9; x += 0.1) ax += `<text class="ax" x="${L + x / xmax * pw}" y="${H - B + 22}" text-anchor="middle">${dec(x, 1)}</text>`;
  const ystep = ymax > 0.6 ? 0.2 : 0.1;
  for (let y = 0; y <= ymax + 1e-9; y += ystep) ax += `<text class="ax" x="${L - 12}" y="${Tp + ph - y / ymax * ph + 4}" text-anchor="end">${Math.round(y * 100)}%</text>`;
  return `<div class="cmap-wrap"><svg class="cmap" viewBox="0 0 ${W} ${H}" role="img" aria-label="Карта кластеров обращений">
    <defs>
      <pattern id="dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="rgba(200,240,230,.13)"/></pattern>
      <radialGradient id="cg"><stop offset="0" stop-color="#C8FFF3"/><stop offset=".45" stop-color="#2FD9B5"/><stop offset="1" stop-color="#2FD9B5" stop-opacity=".25"/></radialGradient>
    </defs>
    <rect x="${L}" y="${Tp}" width="${pw}" height="${ph}" fill="url(#dots)"/>
    <rect x="${L}" y="${Tp}" width="${pw}" height="${ph}" fill="none" stroke="rgba(255,255,255,.09)"/>
    ${ax}
    <text class="axl" x="${L + pw / 2}" y="${H - 6}" text-anchor="middle">наш черновик ближе к ответам админов →</text>
    <text class="axl" transform="translate(16 ${Tp + ph / 2}) rotate(-90)" text-anchor="middle">админы отвечают одинаково →</text>
    <g>${pts.map(({ c, i }) => `<circle data-i="${i}" cx="${XX(c).toFixed(1)}" cy="${YY(c).toFixed(1)}" r="${rad(c).toFixed(1)}" class="${c.gap ? 'cand' : 'rest'}"/>`).join('')}</g>
  </svg><div class="tip" id="tip" hidden></div>
  <div class="cmap-legend"><span><i class="cand"></i>кандидат в шаблон</span><span><i class="rest"></i>остальные кластеры</span><span class="muted">размер точки: число обращений</span></div></div>`;
};
void nf;
})();
