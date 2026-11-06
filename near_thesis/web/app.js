/* Dashboard renderer: reads the inline JSON spec and draws every chart as SVG. No dependencies. */
(function () {
  const DATA = JSON.parse(document.getElementById('spec').textContent);
  const COLORS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)', 'var(--series-6)'];
  const SVGNS = 'http://www.w3.org/2000/svg';
  const W = 760, H = 320, M = { t: 18, r: 110, b: 34, l: 56 };
  let range = { start: null };

  const el = (tag, attrs, parent) => { const e = document.createElementNS(SVGNS, tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
  const h = (tag, cls, parent, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; if (parent) parent.appendChild(e); return e; };
  const fmt = (v, unit) => {
    if (v === null || v === undefined || Number.isNaN(v)) return 'n/a';
    const a = Math.abs(v);
    const money = unit === 'USD';
    if (a === 0) return (money ? '$' : '') + '0';
    const s = a >= 1e9 ? (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B' : a >= 1e6 ? (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M' : a >= 1e4 ? (v / 1e3).toFixed(0) + 'K' : a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(2) : v.toFixed(3);
    return (money ? '$' : '') + s + (unit === 'x' ? 'x' : '');
  };
  const parseDate = (s) => new Date(s + (s.length === 10 ? 'T00:00:00Z' : s.length === 7 ? '-01T00:00:00Z' : '-01-01T00:00:00Z'));
  const niceTicks = (lo, hi, n) => { const span = hi - lo || 1; const step0 = Math.pow(10, Math.floor(Math.log10(span / n))); const e = span / n / step0; const step = step0 * (e >= 5 ? 10 : e >= 2 ? 5 : e >= 1 ? 2 : 1); const t = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) t.push(+v.toFixed(10)); return t; };
  const logTicks = (lo, hi) => { const t = []; for (let p = Math.floor(Math.log10(lo)); p <= Math.ceil(Math.log10(hi)); p++) { for (const m of [1, 2, 5]) { const v = m * Math.pow(10, p); if (v >= lo && v <= hi) t.push(v); } } return t.length > 8 ? t.filter((_, i) => i % 2 === 0) : t; };

  function filtered(spec) {
    if (!range.start || !['line', 'column', 'stacked'].includes(spec.type)) return spec.series;
    return spec.series.map(s => ({ name: s.name, points: s.points.filter(p => parseDate(p[0]) >= range.start) }));
  }

  function timeChart(spec, host) {
    const series = filtered(spec).filter(s => s.points.length);
    if (!series.length) { h('div', 'empty', host, 'No data in the selected range.'); return; }
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': spec.title }, host);
    const isCol = spec.type === 'column' || spec.type === 'stacked';
    const right = series.length > 1 && series.length <= 4 && !isCol ? M.r : 24;
    const pw = W - M.l - right, ph = H - M.t - M.b;
    const dates = [...new Set(series.flatMap(s => s.points.map(p => p[0])))].sort();
    const x0 = parseDate(dates[0]).getTime(), x1 = parseDate(dates[dates.length - 1]).getTime();
    const xs = (d) => M.l + (x1 === x0 ? pw / 2 : (parseDate(d).getTime() - x0) / (x1 - x0) * pw);
    let vals;
    if (spec.type === 'stacked') { const tot = {}; series.forEach(s => s.points.forEach(p => tot[p[0]] = (tot[p[0]] || 0) + p[1])); vals = Object.values(tot).concat([0]); }
    else vals = series.flatMap(s => s.points.map(p => p[1]));
    if (spec.y_log) vals = vals.filter(v => v > 0);
    vals = vals.filter(Number.isFinite);
    if (!vals.length) { svg.remove(); h('div', 'empty', host, 'No finite values available for this scale.'); return; }
    let lo = spec.y_domain ? spec.y_domain[0] : Math.min(...vals), hi = spec.y_domain ? spec.y_domain[1] : Math.max(...vals);
    if (!spec.y_log && !spec.y_domain) { lo = Math.min(0, lo); hi = hi + (hi - lo) * 0.08; }
    if (spec.y_log) { lo = Math.pow(10, Math.floor(Math.log10(lo))); hi = Math.pow(10, Math.ceil(Math.log10(hi))); if (lo === hi) hi *= 10; }
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || (spec.y_log && lo <= 0)) { svg.remove(); h('div', 'empty', host, 'No finite values available for this scale.'); return; }
    if (hi < lo) { svg.remove(); h('div', 'empty', host, 'Invalid scale domain.'); return; }
    if (hi === lo) { const pad = Math.abs(lo) * 0.05 || 1; hi = lo + pad; lo -= pad; }
    const ys = (v) => spec.y_log ? M.t + ph - (Math.log10(Math.max(v, lo)) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * ph : M.t + ph - (v - lo) / (hi - lo) * ph;
    const g = el('g', { class: 'grid' }, svg), ax = el('g', { class: 'axis' }, svg);
    const ticks = spec.y_log ? logTicks(lo, hi) : niceTicks(lo, hi, 5);
    ticks.forEach(t => { el('line', { x1: M.l, x2: W - right, y1: ys(t), y2: ys(t) }, g); const tx = el('text', { x: M.l - 8, y: ys(t) + 4, 'text-anchor': 'end' }, ax); tx.textContent = fmt(t, spec.unit); });
    el('line', { x1: M.l, x2: W - right, y1: M.t + ph, y2: M.t + ph }, ax);
    const years = [...new Set(dates.map(d => d.slice(0, 4)))];
    const step = Math.ceil(years.length / 8);
    if (years.length > 2) years.forEach((y, i) => { if (i % step) return; const d = `${y}-01-01`; if (parseDate(d) < parseDate(dates[0])) return; const tx = el('text', { x: xs(d), y: M.t + ph + 18, 'text-anchor': 'middle' }, ax); tx.textContent = y; });
    if (years.length <= 2) { const seen = new Set(); const months = dates.filter((d, i) => i % Math.ceil(dates.length / 8) === 0).map(d => d.slice(0, 7)).filter(mo => !seen.has(mo) && seen.add(mo)); months.forEach(mo => { const d = mo + '-01'; const tx = el('text', { x: xs(d), y: M.t + ph + 18, 'text-anchor': 'middle' }, ax); tx.textContent = d.slice(0, 7); }); }
    let annI = 0; (spec.annotations || []).forEach(a => { if (parseDate(a.date) < parseDate(dates[0]) || parseDate(a.date) > parseDate(dates[dates.length - 1])) return; const ga = el('g', { class: 'ann' }, svg); el('line', { x1: xs(a.date), x2: xs(a.date), y1: M.t, y2: M.t + ph, 'stroke-dasharray': '0' }, ga); const t = el('text', { x: xs(a.date) + 3, y: M.t + 9 + 11 * (annI++ % 2) }, ga); t.textContent = a.date.slice(0, 7); });
    const byDate = series.map(s => Object.fromEntries(s.points));
    if (isCol) {
      const slot = pw / Math.max(1, dates.length); const bw = Math.max(1, Math.min(24, slot - 2));
      const stackTop = {};
      series.forEach((s, si) => { const gs = el('g', { class: 'series', fill: COLORS[si] }, svg); s.points.forEach(p => { const v = p[1]; if (!(v > 0) && spec.y_log) return; const base = spec.type === 'stacked' ? (stackTop[p[0]] || 0) : 0; const yTop = ys(base + v), yBase = ys(base); const hh = Math.max(0, yBase - yTop - (spec.type === 'stacked' && base ? 2 : 0)); const x = xs(p[0]) - bw / 2; const r = Math.min(4, bw / 2, hh); const path = `M${x},${yBase - (spec.type === 'stacked' && base ? 2 : 0)} v${-(hh - r)} q0,${-r} ${r},${-r} h${bw - 2 * r} q${r},0 ${r},${r} v${hh - r} z`; const b = el('path', { d: path, class: 'bar', 'data-date': p[0] }, gs); b.addEventListener('pointerenter', () => b.classList.add('lift')); b.addEventListener('pointerleave', () => b.classList.remove('lift')); stackTop[p[0]] = base + v; }); });
    } else {
      series.forEach((s, si) => { const gs = el('g', { class: 'series' }, svg); const pts = s.points.filter(p => !(spec.y_log && !(p[1] > 0))); const d = pts.map((p, i) => (i ? 'L' : 'M') + xs(p[0]).toFixed(1) + ',' + ys(p[1]).toFixed(1)).join(''); el('path', { d, class: 'line', stroke: COLORS[si] }, gs); const last = pts[pts.length - 1]; if (last) { el('circle', { cx: xs(last[0]), cy: ys(last[1]), r: 4, fill: COLORS[si] }, gs);  } });
    }
    // hover layer: crosshair + one tooltip for every series at the nearest date
    const cross = el('line', { class: 'crosshair', y1: M.t, y2: M.t + ph, style: 'display:none' }, svg);
    const tip = h('div', 'tooltip', host);
    const rectHit = el('rect', { x: M.l, y: M.t, width: pw, height: ph, fill: 'transparent' }, svg);
    const dateMs = dates.map(d => parseDate(d).getTime());
    const nearest = (ms) => { let lo2 = 0, hi2 = dateMs.length - 1; while (lo2 < hi2) { const mid = (lo2 + hi2) >> 1; if (dateMs[mid] < ms) lo2 = mid + 1; else hi2 = mid; } if (lo2 > 0 && Math.abs(dateMs[lo2 - 1] - ms) < Math.abs(dateMs[lo2] - ms)) lo2--; return lo2; };
    const show = (ev) => { const r = svg.getBoundingClientRect(); const px = (ev.clientX - r.left) / r.width * W; const ms = x0 + (px - M.l) / pw * (x1 - x0); const i = nearest(ms); const d = dates[i]; cross.setAttribute('x1', xs(d)); cross.setAttribute('x2', xs(d)); cross.style.display = ''; tip.textContent = ''; h('div', 't-date', tip, d); series.forEach((s, si) => { const v = byDate[si][d]; const row = h('div', 't-row', tip); const b = h('b', null, row, fmt(v, spec.unit)); const sp = h('span', null, row); const i2 = h('i', null, sp); i2.style.borderColor = COLORS[si]; sp.appendChild(document.createTextNode(s.name)); }); tip.style.display = 'block'; const hr = host.getBoundingClientRect(); let left = ev.clientX - hr.left + 14; if (left + tip.offsetWidth > hr.width) left = ev.clientX - hr.left - tip.offsetWidth - 14; tip.style.left = left + 'px'; tip.style.top = Math.max(0, ev.clientY - hr.top - 20) + 'px'; };
    const hide = () => { cross.style.display = 'none'; tip.style.display = 'none'; };
    [rectHit, ...svg.querySelectorAll('.bar')].forEach(n => { n.addEventListener('pointermove', show); n.addEventListener('pointerleave', hide); });
    svg.setAttribute('tabindex', '0');
    if (series.length > 1) legend(series, host, isCol);
    tableView(host, ['date', ...series.map(s => s.name)], dates.map(d => [d, ...series.map((s, si) => byDate[si][d])]), spec.unit);
  }

  function rankedChart(spec, host) {
    const series = spec.series; const cats = series[0].points.map(p => p[0]);
    const rowH = series.length > 1 ? 14 * series.length + 10 : 26; const top = 8, left = 150, right = 70;
    const height = top + cats.length * rowH + 8; const svg = el('svg', { viewBox: `0 0 ${W} ${height}`, role: 'img', 'aria-label': spec.title }, host);
    const vals = series.flatMap(s => s.points.map(p => p[1]));
    let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals); if (spec.y_domain) { lo = Math.min(lo, spec.y_domain[0] < 0 ? spec.y_domain[0] : 0); }
    hi = hi || 1; const pw = W - left - right; const xs = (v) => left + (v - lo) / (hi - lo) * pw;
    const emph = (spec.note || '').startsWith('emphasis:') ? spec.note.slice(9) : null;
    const ax = el('g', { class: 'axis' }, svg); el('line', { x1: xs(0), x2: xs(0), y1: top, y2: height - 8 }, ax);
    const tip = h('div', 'tooltip', host);
    cats.forEach((c, i) => { const y = top + i * rowH; const t = el('text', { x: left - 10, y: y + rowH / 2 + 4, 'text-anchor': 'end' }, el('g', { class: 'cat' }, svg)); t.textContent = c; series.forEach((s, si) => { const p = s.points.find(q => q[0] === c); if (!p) return; const v = p[1]; const bh = Math.min(24, series.length > 1 ? 12 : rowH - 8); const by = y + (series.length > 1 ? 5 + si * 14 : (rowH - bh) / 2); const x0 = xs(Math.min(0, v)), x1 = xs(Math.max(0, v)); const w = Math.max(0, x1 - x0); const r = Math.min(4, w / 2, bh / 2); const dir = v >= 0 ? 1 : -1; const path = v >= 0 ? `M${x0},${by} h${w - r} q${r},0 ${r},${r} v${bh - 2 * r} q0,${r} ${-r},${r} h${-(w - r)} z` : `M${x1},${by} h${-(w - r)} q${-r},0 ${-r},${r} v${bh - 2 * r} q0,${r} ${r},${r} h${w - r} z`; const color = series.length > 1 ? COLORS[si] : (emph ? (c === emph ? COLORS[0] : 'var(--deemph)') : COLORS[0]); const b = el('path', { d: path, class: 'bar', fill: color }, svg); const vt = el('text', { x: v >= 0 ? x1 + 6 : x0 - 6, y: by + bh / 2 + 4, 'text-anchor': v >= 0 ? 'start' : 'end' }, el('g', { class: 'val' }, svg)); vt.textContent = fmt(v, spec.unit); b.addEventListener('pointermove', (ev) => { tip.textContent = ''; h('div', 't-date', tip, c); const row = h('div', 't-row', tip); h('b', null, row, fmt(v, spec.unit)); h('span', null, row, s.name); tip.style.display = 'block'; const hr = host.getBoundingClientRect(); tip.style.left = (ev.clientX - hr.left + 14) + 'px'; tip.style.top = (ev.clientY - hr.top - 20) + 'px'; b.classList.add('lift'); }); b.addEventListener('pointerleave', () => { tip.style.display = 'none'; b.classList.remove('lift'); }); }); });
    if (series.length > 1) legend(series, host, true);
    tableView(host, ['category', ...series.map(s => s.name)], cats.map(c => [c, ...series.map(s => (s.points.find(q => q[0] === c) || [c, null])[1])]), spec.unit);
  }

  function divergingChart(spec, host) {
    const series = spec.series; const cats = [...new Set(series.flatMap(s => s.points.map(p => p[0])))].sort();
    const pw = W - M.l - 24, ph = H - M.t - M.b; const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': spec.title }, host);
    const lo = spec.y_domain ? spec.y_domain[0] : -1, hi = spec.y_domain ? spec.y_domain[1] : 1; const ys = (v) => M.t + ph - (v - lo) / (hi - lo) * ph;
    const g = el('g', { class: 'grid' }, svg), ax = el('g', { class: 'axis' }, svg);
    niceTicks(lo, hi, 4).forEach(t => { el('line', { x1: M.l, x2: W - 24, y1: ys(t), y2: ys(t) }, g); const tx = el('text', { x: M.l - 8, y: ys(t) + 4, 'text-anchor': 'end' }, ax); tx.textContent = t.toFixed(2); });
    el('line', { x1: M.l, x2: W - 24, y1: ys(0), y2: ys(0) }, ax);
    const slot = pw / cats.length; const bw = Math.min(24, (slot - 8) / series.length - 2); const tip = h('div', 'tooltip', host);
    cats.forEach((c, ci) => { const cx = M.l + slot * (ci + 0.5); const tx = el('text', { x: cx, y: M.t + ph + 18, 'text-anchor': 'middle' }, ax); tx.textContent = c; series.forEach((s, si) => { const p = s.points.find(q => q[0] === c); if (!p) return; const v = p[1]; const x = cx - (series.length * (bw + 2)) / 2 + si * (bw + 2); const y0 = ys(0), y1 = ys(v); const hh = Math.abs(y1 - y0); const r = Math.min(4, bw / 2, hh); const path = v >= 0 ? `M${x},${y0} v${-(hh - r)} q0,${-r} ${r},${-r} h${bw - 2 * r} q${r},0 ${r},${r} v${hh - r} z` : `M${x},${y0} v${hh - r} q0,${r} ${r},${r} h${bw - 2 * r} q${r},0 ${r},${-r} v${-(hh - r)} z`; const b = el('path', { d: path, class: 'bar', fill: COLORS[si] }, svg); b.addEventListener('pointermove', (ev) => { tip.textContent = ''; h('div', 't-date', tip, c); const row = h('div', 't-row', tip); h('b', null, row, v.toFixed(2)); h('span', null, row, s.name); tip.style.display = 'block'; const hr = host.getBoundingClientRect(); tip.style.left = (ev.clientX - hr.left + 14) + 'px'; tip.style.top = (ev.clientY - hr.top - 20) + 'px'; b.classList.add('lift'); }); b.addEventListener('pointerleave', () => { tip.style.display = 'none'; b.classList.remove('lift'); }); }); });
    legend(series, host, true);
    tableView(host, ['year', ...series.map(s => s.name)], cats.map(c => [c, ...series.map(s => (s.points.find(q => q[0] === c) || [c, null])[1])]), spec.unit);
  }

  function legend(series, host, rect) { const lg = h('div', 'legend', host); series.forEach((s, i) => { const item = h('span', null, lg); const key = h('span', 'key' + (rect ? ' rect' : ''), item); key.style.borderColor = COLORS[i]; if (rect) key.style.background = COLORS[i]; item.appendChild(document.createTextNode(s.name)); }); }

  function tableView(host, header, rows, unit) { const det = h('details', null, host); h('summary', null, det, `Table view (${rows.length} rows)`); det.addEventListener('toggle', () => { if (!det.open || det.dataset.built) return; det.dataset.built = '1'; const t = h('table', null, det); const tr = h('tr', null, h('thead', null, t)); header.forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t); rows.forEach(r => { const row = h('tr', null, tb); r.forEach((v, i) => h('td', null, row, i ? fmt(v, unit) : String(v))); }); }); }

  function card(spec, parent) {
    const c = h('section', 'card', parent); c.id = 'chart-' + spec.id; h('h3', null, c, spec.title); h('p', 'sentence', c, spec.sentence);
    const chart = h('div', 'chart', c); chart.dataset.id = spec.id;
    draw(spec, chart);
    const det = h('details', null, c); h('summary', null, det, 'Source and query'); const pre = h('pre', null, det); pre.textContent = `source: ${spec.source}\nquery: ${spec.query}` + (spec.note && !spec.note.startsWith('emphasis:') ? `\nnote: ${spec.note}` : '');
    return c;
  }
  function draw(spec, chart) { chart.textContent = ''; if (spec.type === 'empty' || !spec.series.length) { h('div', 'empty', chart, spec.type === 'empty' ? 'No chart: see the sentence above.' : 'No data in the selected range.'); return; } if (spec.type === 'ranked') rankedChart(spec, chart); else if (spec.type === 'diverging') divergingChart(spec, chart); else timeChart(spec, chart); }

  function render() {
    const root = document.getElementById('charts'); root.textContent = '';
    const sections = [...new Set(DATA.charts.map(s => s.section))];
    sections.forEach((sec, i) => { const meta = (DATA.sections || {})[sec]; const head = h('div', 'sec-head', root); head.id = secId(sec); h('span', 'num', head, String(i + 1).padStart(2, '0')); h('h2', null, head, secLabel(sec)); if (meta) { h('p', 'sec-q', head, meta.question); h('p', 'sec-intro', head, meta.intro); h('p', 'sec-limit', head, meta.limit); } DATA.charts.filter(s => s.section === sec).forEach(s => card(s, root)); });
  }
  function kpis() {
    const hero = DATA.kpis[0]; const hv = document.getElementById('hero');
    h('div', 'label', hv, `${hero.label} (${hero.month})`); h('div', 'value', hv, fmt(hero.value, hero.unit));
    const d = h('div', 'delta', hv, hero.delta_pct_yoy == null ? '' : `${hero.delta_pct_yoy >= 0 ? '+' : ''}${hero.delta_pct_yoy.toFixed(0)}% vs the same month a year earlier`);
    const row = document.getElementById('kpis');
    DATA.kpis.slice(1).forEach(k => { const c = h('div', 'kpi' + (k.state ? ' state-' + k.state : ''), row); h('div', 'label', c, k.label); h('div', 'value', c, k.unit === 'ratio' ? (k.value == null ? 'n/a' : k.value.toFixed(2)) : fmt(k.value, k.unit)); if (k.delta_pct_yoy == null) { h('div', 'delta note', c, k.note || ''); return; } const up = k.delta_pct_yoy >= 0; const good = k.up_is_good ? up : !up; h('div', 'delta ' + (good ? 'up' : 'down'), c, `${up ? '▲' : '▼'} ${Math.abs(k.delta_pct_yoy).toFixed(0)}% YoY`); });
  }
  const STATE_WORD = { pass: 'supported', fail: 'failing', open: 'open' };
  const byId = Object.fromEntries(DATA.charts.map(c => [c.id, c]));
  const secId = (sec) => { const meta = (DATA.sections || {})[sec]; return 'sec-' + (meta ? meta.id : sec.replace(/\W+/g, '-').toLowerCase()); };
  const secLabel = (sec) => sec.replace(/^\d+\.\s*/, '');
  function story() {
    const v = DATA.verdict; const vh = document.getElementById('verdict'); const strip = document.getElementById('strip');
    if (v) {
      (v.checks || []).forEach(c => { const chip = h('a', 'chip', strip); chip.href = '#verdict'; h('span', 'pill ' + c.state, chip, STATE_WORD[c.state] || c.state); chip.appendChild(document.createTextNode(c.label)); });
      const top = h('div', 'v-top', vh); h('h2', null, top, 'Claim and current verdict').id = 'verdict-h'; h('span', 'pill ' + (v.status === 'supported' ? 'pass' : 'open'), top, v.status === 'supported' ? 'Supported' : 'Unresolved');
      h('p', 'v-claim', vh, v.claim);
      const list = h('div', 'checks', vh);
      (v.checks || []).forEach(c => { const row = h('div', 'check', list); const head = h('div', 'c-head', row); h('span', 'pill ' + c.state, head, STATE_WORD[c.state] || c.state); h('span', 'c-label', head, c.label); h('p', null, row, c.text); });
      h('p', 'v-statement', vh, v.statement);
      const det = h('details', null, vh); h('summary', null, det, 'What would change the verdict'); const ul = h('ul', null, det); (v.changes || []).forEach(t => h('li', null, ul, t));
    } else { vh.remove(); strip.remove(); }
    const a = DATA.argument; const ah = document.getElementById('argument');
    if (a && a.length) {
      h('h2', null, ah, 'The argument in ' + a.length + ' steps').id = 'argument-h';
      h('p', 'sec-q', ah, 'Scroll the steps; the chart on the right follows. Each step links to its evidence below.');
      const wrap = h('div', 'scrolly', ah); const ol = h('ol', 'steps', wrap);
      const pin = h('div', 'pinned', wrap); const pt = h('h3', null, pin); const ps = h('p', 'p-sentence', pin); const pc = h('div', 'schart', pin); const pl = h('p', 'p-link', pin); const plink = h('a', null, pl, 'Open the full chart');
      const items = a.map(st => { const li = h('li', null, ol); li.dataset.step = st.step; const link = h('a', 's-title', li, st.title); link.href = st.href; h('p', null, li, st.text); const spec = byId[st.chart]; if (spec) { const mini = h('div', 's-chart', li); draw(spec, mini); } return li; });
      let current = -1;
      const showStep = (i) => { if (i === current) return; current = i; items.forEach((li, j) => li.classList.toggle('active', j === i)); const spec = byId[a[i].chart]; if (!spec) return; pt.textContent = spec.title; ps.textContent = spec.sentence; plink.href = '#chart-' + spec.id; draw(spec, pc); };
      showStep(0);
      if ('IntersectionObserver' in window) {
        const io = new IntersectionObserver(entries => { entries.forEach(e => { if (e.isIntersecting) showStep(+e.target.dataset.step - 1); }); }, { rootMargin: '-35% 0px -45% 0px', threshold: 0 });
        items.forEach(li => io.observe(li));
      }
      items.forEach((li, i) => { li.addEventListener('mouseenter', () => showStep(i)); li.addEventListener('focusin', () => showStep(i)); });
    } else ah.remove();
    const g = DATA.against; const gh = document.getElementById('against');
    if (g && g.length) { h('h2', null, gh, 'Evidence against and unresolved tests').id = 'against-h'; h('p', 'sec-q', gh, 'What counts against the claim, in the open rather than in a footnote.'); const ul = h('ul', null, gh); g.forEach(x => { const li = h('li', null, ul); li.appendChild(document.createTextNode(x.text + ' ')); const link = h('a', 'see', li, 'See chart'); link.href = x.href; }); } else gh.remove();
  }
  function nav() {
    const toc = document.getElementById('toc'); const entries = [];
    const add = (id, label, n) => { const el = document.getElementById(id); if (!el) return; const link = h('a', null, toc); link.href = '#' + id; if (n !== undefined) h('span', 'n', link, String(n)); link.appendChild(document.createTextNode(label)); entries.push({ id, link, el }); };
    add('verdict', 'Verdict', '◆'); add('argument', 'Argument', '→');
    [...new Set(DATA.charts.map(s => s.section))].forEach((sec, i) => add(secId(sec), secLabel(sec), i + 1));
    add('against', 'Evidence against', '!'); add('repro', 'Reproduce it', '$');
    const setCurrent = (id) => entries.forEach(e => { if (e.id === id) e.link.setAttribute('aria-current', 'true'); else e.link.removeAttribute('aria-current'); });
    const spy = () => { const y = window.scrollY + Math.min(160, window.innerHeight * 0.25); let cur = entries[0] && entries[0].id; for (const e of entries) { if (e.el.offsetTop <= y) cur = e.id; } setCurrent(cur); };
    const bar = document.querySelector('#progress span'); const prog = document.getElementById('progress'); const totop = document.getElementById('totop');
    const progress = () => { const max = document.documentElement.scrollHeight - window.innerHeight; const pct = max > 0 ? Math.min(100, Math.max(0, window.scrollY / max * 100)) : 0; bar.style.width = pct + '%'; prog.setAttribute('aria-valuenow', pct.toFixed(0)); totop.hidden = window.scrollY < 600; };
    let ticking = false; const onScroll = () => { if (ticking) return; ticking = true; requestAnimationFrame(() => { spy(); progress(); ticking = false; }); };
    window.addEventListener('scroll', onScroll, { passive: true }); window.addEventListener('resize', onScroll); onScroll();
    totop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }));
  }
  function toolbar() {
    const presets = [['All', null], ['Since 2023', '2023-01-01'], ['Since 2024', '2024-01-01'], ['Since Intents', '2024-12-01'], ['Last 12 months', new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10)]];
    const grp = document.getElementById('range');
    presets.forEach(([label, start], i) => { const b = h('button', null, grp, label); b.setAttribute('aria-pressed', i === 0 ? 'true' : 'false'); b.addEventListener('click', () => { range.start = start ? parseDate(start) : null; grp.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); DATA.charts.forEach(s => { const chart = document.querySelector(`.chart[data-id="${s.id}"]`); if (chart) draw(s, chart); }); }); });
    const th = document.getElementById('theme');
    [['Auto', ''], ['Light', 'light'], ['Dark', 'dark']].forEach(([label, v], i) => { const b = h('button', null, th, label); b.setAttribute('aria-pressed', i === 0 ? 'true' : 'false'); b.addEventListener('click', () => { if (v) document.documentElement.setAttribute('data-theme', v); else document.documentElement.removeAttribute('data-theme'); th.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', 'false')); b.setAttribute('aria-pressed', 'true'); try { localStorage.setItem('theme', v); } catch (e) {} }); });
    try { const qp = new URLSearchParams(location.search).get('theme'); if (qp) localStorage.setItem('theme', qp); const saved = localStorage.getItem('theme'); if (saved) { document.documentElement.setAttribute('data-theme', saved); th.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x.textContent.toLowerCase() === saved ? 'true' : 'false')); } } catch (e) {}
  }
  document.getElementById('built').textContent = `Data through ${DATA.data_through}. Latest snapshot ${DATA.built_at}. ${DATA.raw_manifest.length} raw snapshots, hashes in docs/REPRODUCIBILITY.md.`;
  toolbar(); story(); kpis(); render(); nav();
})();
