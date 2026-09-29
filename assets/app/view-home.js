/* ------------------------------------------------------------------ home */
/* The landing surface. Three questions, in the order they are asked in the
   morning: how is the book doing, what needs me, what is coming.

   Every figure here arrived computed in performance.py or analyse.py. What
   this file does to a number is presentation only: slicing a series to the
   selected period, and rebasing the ACWI shadow so that it starts the period
   level with the book (see shadowFrom). A reader comparing two lines that
   start apart is comparing the past, not the period they asked about. */

const PERF = D.performance || {};
const PERIODS = [['1D', '1D'], ['1W', '1W'], ['1M', '1M'], ['3M', '3M'],
                 ['YTD', 'YTD'], ['1Y', '1Y'], ['ALL', 'Since start']];
// 1Y, not ALL. Since-start is dominated by the months when the book was a
// fraction of its size, so its curve is mostly a picture of deposits.
const HOME_PERIOD = '1Y';
const TIERNAME = {act: 'Act', watch: 'Watch', tailwind: 'Tailwind'};
const TIERNOTE = {act: 'Nothing needs action.', watch: 'Nothing to watch.',
                  tailwind: 'No tailwinds flagged.'};
const UPCOMING_DAYS = 30;

// Dates of the curve, rebuilt from the day gaps it was shipped as. The gaps
// are what the payload carries because hundreds of ISO strings are kilobytes of repetition.
const CURVE = (() => {
  const c = PERF.curve || {};
  const dd = c.dd || [], out = {day: [], date: []};
  if (!c.d0 || !dd.length) return Object.assign(out, c, {n: 0});
  const t0 = Date.parse(c.d0 + 'T00:00:00Z');
  let d = 0;
  for (const g of dd) {
    d += g;
    out.day.push(d);
    out.date.push(new Date(t0 + d * 864e5).toISOString().slice(0, 10));
  }
  return Object.assign(out, c, {n: dd.length});
})();
const BENCH = PERF.benchmark || {};

// The first curve point on or after the period's own start date. The period
// was computed from that point, so the picture starts where the number does.
function periodStart(p) {
  const from = ((PERF.periods || {})[p] || {}).from;
  if (!from || !CURVE.n) return 0;
  const i = CURVE.date.findIndex((d) => d >= from);
  return i < 0 ? CURVE.n - 1 : i;
}

// The shadow buys ACWI with the book's own flows since the first lot, so at
// any later start it already carries every year of difference before it. For
// a period, it is restarted at the book's value on day one of the period and
// then keeps the same flows: S'(t) = S(t) + (V0 - S0) * B(t) / B0. That is the
// same portfolio, begun on the period's first day - not a new calculation of
// anything, and it needs nothing the payload does not already hold.
function shadowFrom(i0) {
  const S = BENCH.shadow || [], B = BENCH.index || [], V = CURVE.value || [];
  if (BENCH.absent || S[i0] == null || B[i0] == null || V[i0] == null) return null;
  const k = V[i0] - S[i0];
  return S.map((s, i) => (i < i0 || s == null || B[i] == null) ? null
    : s + k * B[i] / B[i0]);
}

// Round gridlines, four to six of them, on 1/2/5 x 10^n. No 2.5: the labels
// are thousands to one decimal, and a 250 step printed 12,250 as "12.3k".
function niceTicks(lo, hi) {
  const span = hi - lo || Math.abs(hi) || 1;
  const raw = span / 5, mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}
const eurk = (n) => Math.abs(n) >= 1e3
  ? '€' + (n / 1e3).toLocaleString('en-GB', {maximumFractionDigits: 1}) + 'k'
  : eur(n);

// A path in a 0..100 box, gaps kept as gaps. A null is a day with no value and
// is not drawn as zero - the line lifts and starts again.
function pathOf(xs, ys, lo, hi) {
  let d = '', pen = false;
  for (let j = 0; j < xs.length; j++) {
    const y = ys[j];
    if (y == null) { pen = false; continue; }
    const Y = 100 - (y - lo) / (hi - lo || 1) * 100;
    d += (pen ? 'L' : 'M') + xs[j].toFixed(2) + ' ' + Y.toFixed(2);
    pen = true;
  }
  return d;
}

// A spark is a shape, not a figure: no axis, no labels, the number it belongs
// to sits beside it. Zero is drawn when the series crosses it, because above
// or below the line is the whole reading.
function spark(ys, opts) {
  const v = ys.filter((y) => y != null);
  if (v.length < 2) return '';
  const o = opts || {};
  let lo = Math.min(...v), hi = Math.max(...v);
  if (o.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const xs = ys.map((_, j) => j / (ys.length - 1) * 100);
  const line = pathOf(xs, ys, lo, hi);
  const z = 100 - (0 - lo) / (hi - lo || 1) * 100;
  const fill = o.fill ? `<path class="sf" d="${line}L100 ${o.zero ? z.toFixed(2) : 100}L0 ${
    o.zero ? z.toFixed(2) : 100}Z"/>` : '';
  const zl = o.zero && lo < 0 && hi > 0
    ? `<line class="sz" x1="0" x2="100" y1="${z.toFixed(2)}" y2="${z.toFixed(2)}"/>` : '';
  const tone = v[v.length - 1] < (o.zero ? 0 : v[0]) ? 'dn' : 'up';
  return `<svg class="spark ${o.tone || tone}" viewBox="0 0 100 100"
    preserveAspectRatio="none" aria-hidden="true">${zl}${fill}<path class="sl"
    d="${line}"/></svg>`;
}

// What the hover reads. Rebuilt with the curve, so it always describes the
// line under the pointer and never the previous period's.
let HC = null;

function curveHtml(p) {
  const i0 = periodStart(p), n = CURVE.n;
  const V = (CURVE.value || []).slice(i0), IX = CURVE.index || [];
  if (!n || V.filter((v) => v != null).length < 2) {
    HC = null;
    return '<div class="hnote">No book-value series in this build.</div>';
  }
  const SH = shadowFrom(i0);
  const sh = SH ? SH.slice(i0) : null;
  const days = CURVE.day.slice(i0), span = days[days.length - 1] - days[0] || 1;
  const xs = days.map((d) => (d - days[0]) / span * 100);
  const all = V.concat(sh || []).filter((v) => v != null);
  let lo = Math.min(...all), hi = Math.max(...all);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.02 || 1;
  lo -= pad; hi += pad;
  const ticks = niceTicks(lo, hi).filter((t) => t >= lo && t <= hi);
  const yOf = (v) => 100 - (v - lo) / (hi - lo) * 100;
  const line = pathOf(xs, V, lo, hi);
  const lastX = xs[xs.length - 1];

  // Recorded points: what the run actually wrote down on that day, against a
  // curve reconstructed afterwards from the lots. Drawn separately because
  // they are separate evidence - where a dot sits off the line, one of the two
  // is wrong, and the page should not hide which by merging them.
  const rec = (PERF.recorded || []).map((r) => {
    const j = CURVE.date.indexOf(r.date);
    if (j < i0 || r.value_eur == null) return '';
    const x = (CURVE.day[j] - days[0]) / span * 100;
    return `<i class="hrec" style="left:${x.toFixed(2)}%;top:${yOf(r.value_eur).toFixed(2)}%"
      title="Recorded by the run of ${esc(r.date)}: ${eur(r.value_eur)}"></i>`;
  }).join('');

  HC = {i0, xs, V, sh, IX, BI: BENCH.index || [], date: CURVE.date.slice(i0), lo, hi};
  const first = CURVE.date[i0], last = CURVE.date[n - 1];
  return `<div class="hplot" id="hplot">
    <div class="hgrid">${ticks.map((t) => `<div class="hgl" style="top:${
      yOf(t).toFixed(2)}%"><span>${eurk(t)}</span></div>`).join('')}</div>
    <svg class="hsvg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <path class="harea" d="${line}L${lastX.toFixed(2)} 100L0 100Z"/>
      ${sh ? `<path class="hshadow" d="${pathOf(xs, sh, lo, hi)}"/>` : ''}
      <path class="hline" d="${line}"/>
    </svg>
    ${rec}
    <i class="hend" style="left:${lastX.toFixed(2)}%;top:${
      yOf(V[V.length - 1]).toFixed(2)}%"></i>
    <div class="hx" id="hx" hidden></div>
    <div class="htip" id="htip" hidden></div>
  </div>
  <div class="haxis"><span>${esc(first)}</span><span>${esc(last)} · last bar</span></div>`;
}

// The hover. Index ratios, not value ratios: the value moves with deposits,
// and "up 30% since March" on a book that was topped up in April is a claim
// about the bank transfer.
function curveHover(e) {
  const box = $('#hplot');
  if (!HC || !box || !box.getBoundingClientRect) return;
  const r = box.getBoundingClientRect();
  const fx = (e.clientX - r.left) / (r.width || 1) * 100;
  if (fx < 0 || fx > 100) return curveLeave();
  let j = 0;
  while (j < HC.xs.length - 1 && (HC.xs[j] + HC.xs[j + 1]) / 2 < fx) j++;
  const i = HC.i0 + j, v = HC.V[j];
  const ret = HC.IX[i] != null && HC.IX[HC.i0] ? (HC.IX[i] / HC.IX[HC.i0] - 1) * 100 : null;
  const bret = HC.BI[i] != null && HC.BI[HC.i0] ? (HC.BI[i] / HC.BI[HC.i0] - 1) * 100 : null;
  const x = $('#hx'), tip = $('#htip');
  if (!x || !tip) return;
  x.hidden = false; tip.hidden = false;
  x.style.left = HC.xs[j].toFixed(2) + '%';
  tip.style.left = HC.xs[j].toFixed(2) + '%';
  tip.classList.toggle('flip', HC.xs[j] > 62);
  tip.innerHTML = `<div class="d">${esc(HC.date[j])}</div>
    <div><span>Book</span><b>${eur(v)}</b></div>
    <div><span>Return</span><b class="${cls(ret)}">${pct(ret)}</b></div>
    ${HC.sh ? `<div><span>ACWI</span><b>${eur(HC.sh[j])}</b></div>
    <div><span>ACWI return</span><b class="${cls(bret)}">${pct(bret)}</b></div>` : ''}`;
}
function curveLeave() {
  const x = $('#hx'), tip = $('#htip');
  if (x) x.hidden = true;
  if (tip) tip.hidden = true;
}

// What the curve is a curve OF. Built from the payload's own coverage fields,
// so a lot that drops out of the reconstruction changes this sentence the
// same day it changes the line.
function basisHtml() {
  const ex = PERF.excluded || [];
  return `Book value rebuilt from ${PERF.n_included == null ? '—' : PERF.n_included} of ${
    PERF.n_lots == null ? '—' : PERF.n_lots} lots, ${num(PERF.cost_covered_pct, 1)}% of cost.`
    + (ex.length ? ` Left out: ${ex.map((x) => `${esc(x.symbol)} (${esc(x.reason)}, ${
        eur(x.cost_eur)})`).join(', ')}.` : '')
    + (BENCH.absent ? ' No ACWI series came back, so no shadow is drawn.'
       : ` Dashed: ${esc(BENCH.label || 'the benchmark')} bought with the same deposits on the
          same days, restarted level with the book on the first day shown.`)
    + ((PERF.recorded || []).length ? ' Dots: values the daily run recorded.' : '')
    + atBuild('the performance series is rebuilt from the lots at build time; a live '
              + 'price moves the book value above, not this curve');
}

const kpi = (k, v, s, sp) => `<div class="kpi"><div class="k">${esc(k)}</div>
  <div class="kv"><span class="v">${v}</span>${sp || ''}</div>
  <div class="s">${s || ''}</div></div>`;

function kpiHtml(p) {
  const P = (PERF.periods || {})[p] || {};
  const t = D.totals || {}, ot = OV.totals || {};
  const i0 = periodStart(p), IX = (CURVE.index || []).slice(i0);
  const BI = (BENCH.index || []).slice(i0);
  const rel = IX.map((x, j) => x == null || BI[j] == null || !BI[0] || !IX[0]
    ? null : ((x / IX[0]) / (BI[j] / BI[0]) - 1) * 100);
  let peak = -Infinity;
  const under = IX.map((x) => {
    if (x == null) return null;
    peak = Math.max(peak, x);
    return (x / peak - 1) * 100;
  });
  const signed = (v, f) => v == null ? '—' : `<span class="${cls(v)}">${f(v)}</span>`;
  return [
    kpi('Return', signed(P.twr_pct, (v) => pct(v, 1)),
      `time-weighted, from ${esc(P.from || '—')}`, spark(IX)),
    kpi(`vs ${BENCH.symbol ? 'ACWI' : 'benchmark'}`,
      P.excess_pp == null ? '—' : `<span class="${cls(P.excess_pp)}">${
        (P.excess_pp > 0 ? '+' : '') + num(P.excess_pp, 1)} pts</span>`,
      P.bench_pct == null ? (BENCH.absent ? 'no benchmark series' : 'not computed')
        : `ACWI ${pct(P.bench_pct, 1)} over the same days`,
      spark(rel, {zero: true})),
    kpi('Max drawdown', P.mdd_pct == null ? '—' : `<span class="dn-t">${pct(P.mdd_pct, 1)}</span>`,
      P.mdd_peak ? `${esc(P.mdd_peak)} to ${esc(P.mdd_trough)}` : 'no fall in this period',
      spark(under, {fill: true, tone: 'dn'})),
    kpi('Volatility', P.vol_pct == null ? '—' : num(P.vol_pct, 1) + '%',
      P.beta == null ? 'annualised' : `annualised · β ${num(P.beta, 2)} · ρ ${num(P.corr, 2)}`),
    kpi('Annualised', ot.irr_pct == null ? '—' : signed(ot.irr_pct, (v) => pct(v, 1)),
      ot.irr_since ? `money-weighted since ${esc(ot.irr_since)}` : esc(ot.irr_note || 'not computed')),
    kpi('Total P/L', signed(t.pl_eur, eurs),
      `${pct(t.pl_pct, 1)} on ${eur(t.cost_eur)} of cost`),
  ].join('');
}

function needsHtml() {
  const c = D.alert_counts || {};
  const all = D.alerts || [];
  return Object.keys(TIERNAME).map((tier) => {
    const list = all.filter((a) => a.tier === tier);
    return `<div class="tier" data-tier="${tier}">
      <h4><span>${TIERNAME[tier]}</span><b>${c[tier] == null ? '—' : c[tier]}</b></h4>
      ${list.length ? list.map((a) => {
        const s = symOfAlert(a);
        return `<details class="need" data-tier="${tier}"><summary><span class="dot"
          style="background:${LEVEL[a.level] || 'var(--muted)'}"></span><span
          class="t">${esc(a.title)}</span>${s ? `<button class="go" data-sym="${
          esc(s)}" title="Open ${esc(s)}">${esc(s)} &rarr;</button>` : ''}</summary>
          <p>${esc(a.detail || '')}</p></details>`;
      }).join('') : `<div class="hnote">${TIERNOTE[tier]}</div>`}</div>`;
  }).join('');
}

function moversHtml(p) {
  const rows = ((PERF.attribution || {})[p] || [])
    .filter((r) => r.eur != null).slice().sort((a, b) => b.eur - a.eur);
  if (!rows.length) return '<div class="hnote">No attribution for this period.</div>';
  const top = rows.filter((r) => r.eur > 0).slice(0, 5);
  const bot = rows.filter((r) => r.eur < 0).slice(-5);
  const as = (r) => ({sym: r.symbol, ticker: r.symbol, eur: r.eur});
  return lrows(top.concat(bot).map(as), (r) => r.eur, (r) => eurs(r.eur))
    + `<div class="hnote">Euros each position added or took away over the
       period. ${rows.length - top.length - bot.length > 0
         ? `${rows.length - top.length - bot.length} more in between.` : ''}</div>`;
}

function upcomingHtml() {
  const cal = (D.reporting || {}).calendar || {};
  const rows = (cal.rows || []).filter((r) => r.days != null && r.days <= UPCOMING_DAYS)
    .slice().sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const unk = cal.n_unknown
    ? `<div class="hnote">${cal.n_unknown} stock${cal.n_unknown === 1 ? ' has' : 's have'}
       no date from Yahoo. Missing is not "nothing due".</div>` : '';
  if (!rows.length) return `<div class="hnote">No dated results in the next ${
    UPCOMING_DAYS} days.</div>` + unk;
  return `<ol class="tl">${rows.map((r) => {
    const go = ROWSYM.has(r.symbol);
    return `<li class="${go ? 'click' : ''}${r.soon ? ' soon' : ''}"${
      go ? ` data-sym="${esc(r.symbol)}"` : ''}
      title="${esc(r.name || '')}${r.estimated
        ? ' · estimated by Yahoo, not confirmed by the company' : ''}">
      <span class="d">${esc(String(r.date).slice(5))}${r.estimated ? ' ~' : ''}</span>
      <span class="n">${esc(r.symbol)}</span>
      <span class="w">${bookPct(r)}%</span>
      <span class="in">${r.days === 0 ? 'today' : `in ${r.days}d`}</span></li>`;
  }).join('')}</ol>` + (rows.some((r) => r.estimated)
    ? '<div class="hnote">~ is a date Yahoo estimated.</div>' : '') + unk;
}

function paintHome() {
  const box = $('#home');
  if (!box) return;
  const p = state.hp || HOME_PERIOD;
  const P = (PERF.periods || {})[p] || {};
  const t = D.totals || {}, day = OV.day || {};
  const c = D.alert_counts || {};
  // First, because it sets HC: the caption describes a curve and has nothing
  // to describe when there is none.
  const curve = curveHtml(p);
  box.innerHTML = `
    <section class="hhero">
      <div class="hhead">
        <div>
          <div class="k">Book value</div>
          <div class="hv">${eur(t.value_eur)}</div>
          <div class="hs">${day.pct == null ? 'no position has a previous close'
            : `<span class="${cls(day.value_eur)}">${
                eurs(day.value_eur)} (${pct(day.pct)})</span> today`}${P.twr_pct == null ? ''
            : ` · <span class="${cls(P.twr_pct)}">${pct(P.twr_pct, 1)}</span> ${
              p === 'ALL' ? 'since the first lot' : 'over ' + esc(p)}`}</div>
        </div>
        <div class="hper" role="group" aria-label="Period">${PERIODS.map(([k, l]) =>
          `<button class="rbtn" data-hp="${k}" aria-pressed="${k === p}">${esc(l)}</button>`
        ).join('')}</div>
      </div>
      ${curve}
      ${HC ? `<div class="hcap">${basisHtml()}</div>` : ''}
    </section>
    <section class="kpis">${kpiHtml(p)}</section>
    <div class="hgrid2">
      ${card('Needs you', `${c.total == null ? '—' : c.total} open`, needsHtml(), 'hneeds')}
      ${card('Movers', esc((PERIODS.find((x) => x[0] === p) || [p, p])[1]), moversHtml(p))}
      ${card('Upcoming', `next ${UPCOMING_DAYS} days`, upcomingHtml())}
    </div>`;
}

on('#home', 'click', (e) => {
  const t = e.target && e.target.closest ? e.target : null;
  if (!t) return;
  const hp = t.closest('[data-hp]');
  if (hp) { state.hp = hp.getAttribute('data-hp'); paintHome(); return; }
  const s = t.closest('[data-sym]');
  if (s) { e.preventDefault(); jump(s.getAttribute('data-sym')); }
});
on('#home', 'mousemove', (e) => {
  if (e.target && e.target.closest && e.target.closest('#hplot')) curveHover(e);
  else curveLeave();
});
on('#home', 'mouseleave', curveLeave);
