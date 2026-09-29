/* -------------------------------------------------------------- holdings */
/* Every held name on one screen, as one table. The rail on Positions is a
   picker, one name wide; this is the comparison, every name against every
   other on the same columns, sortable, with the ones you do not read hidden.

   Nothing here is computed. The period return is performance.py's own
   (attribution[p].pct, each name's EUR price move over the window); P/L,
   weight and drift are the ones the live layer restates; IRR is analyse.py's
   and does not follow a price. What this file does is choose, order and
   format. A blank is a figure that does not exist, never a zero. */

const HOLD_KEY = 'ec.holdings.hide';
const HS = {sort: {k: 'weight', dir: -1}, group: false, p: HOME_PERIOD,
            hide: new Set()};
try {
  const kept = JSON.parse(localStorage.getItem(HOLD_KEY) || '[]');
  if (Array.isArray(kept)) for (const k of kept) HS.hide.add(String(k));
} catch (e) {}

const irrOf = (r) => (D.returns || {})[r.sym] || {};

// The period's attribution as a map. Held names only: a watch-only name has
// no row in it, and gets a blank rather than a 0% it never earned.
function periodPct(p) {
  const out = new Map();
  for (const a of ((PERF.attribution || {})[p] || [])) out.set(a.symbol, a.pct);
  return out;
}

// Closes over the last thirty calendar days of the series the chart draws,
// live bar included - so the shape and the price beside it end in the same
// place.
function spark30(r) {
  const bars = barsFor(r);
  if (!bars || bars.length < 2) return [];
  const from = Date.parse(bars[bars.length - 1][0]) - 30 * 864e5;
  return bars.filter((b) => Date.parse(b[0]) >= from).map((b) => b[4]);
}

// Class from coverage, and only from coverage. A name the coverage table does
// not know is its own group rather than a guess at which of the two it is.
const HGROUPS = [['fund', 'Funds'], ['stock', 'Stocks'], ['', 'Class unknown']];
const klassOf = (r) => (r.cov && (r.cov.klass === 'fund' || r.cov.klass === 'stock'))
  ? r.cov.klass : '';

// `v` is the sort value. A column without one is not sortable: a price column
// mixes currencies and a spark has no single value, so ordering either would
// rank things that are not comparable.
const HCOLS = [
  {k: 'name', l: 'Name', t: 1, fixed: 1, v: (r) => r.label.toLowerCase()},
  {k: 'weight', l: 'Weight', v: (r) => r.weight},
  {k: 'price', l: 'Price'},
  {k: 'day', l: 'Day', v: (r) => r.day_pct},
  {k: 'period', l: 'Period', v: (r, pp) => pp.get(r.sym)},
  {k: 'spark', l: '30 days', t: 1},
  {k: 'pl', l: 'P/L €', v: (r) => r.h.pl_eur},
  {k: 'plp', l: 'P/L %', v: (r) => r.h.pl_pct},
  {k: 'irr', l: 'IRR', v: (r) => irrOf(r).irr_pct},
  {k: 'drift', l: 'Drift', v: (r) => r.cov ? r.cov.drift_pts : null},
  {k: 'verdict', l: 'Verdict', t: 1, v: (r) => r.w && r.w.verdict
    ? String(r.w.verdict).toLowerCase() : null},
];

// Absent sorts last in both directions. Flipping a column must not float every
// name with no figure to the top as if nothing were the biggest number.
function holdSort(rows, pp) {
  const col = HCOLS.find((c) => c.k === HS.sort.k && c.v) || HCOLS[1];
  const d = HS.sort.dir;
  return rows.slice().sort((a, b) => {
    const x = col.v(a, pp), y = col.v(b, pp);
    const nx = x == null, ny = y == null;
    if (nx || ny) return nx === ny ? b.weight - a.weight : (nx ? 1 : -1);
    if (x < y) return -d;
    if (x > y) return d;
    return b.weight - a.weight;
  });
}

function holdCell(k, r, pp) {
  const h = r.h, na = '<span class="na">—</span>';
  if (k === 'name') return `<td class="t hn"><b>${esc(r.label)}</b>${r.worst
    ? `<i class="dot" style="background:${LEVEL[r.worst]}"></i>` : ''}<span class="co">${
    esc(r.company)}</span></td>`;
  if (k === 'weight') return `<td>${num(r.weight, 1)}%</td>`;
  if (k === 'price') return `<td>${fresh(r.freshness)}${px(r.price)}<span class="ccy">${
    esc(r.ccy)}</span></td>`;
  if (k === 'day') return `<td class="${cls(r.day_pct)}">${r.day_pct == null ? na
    : pct(r.day_pct, 1)}</td>`;
  if (k === 'period') {
    const v = pp.get(r.sym);
    return `<td class="${cls(v)}">${v == null ? na : pct(v, 1)}</td>`;
  }
  if (k === 'spark') return `<td class="t">${spark(spark30(r)) || na}</td>`;
  if (k === 'pl') return `<td class="${cls(h.pl_eur)}">${eurs(h.pl_eur)}</td>`;
  if (k === 'plp') return `<td class="${cls(h.pl_pct)}">${pct(h.pl_pct, 1)}</td>`;
  if (k === 'irr') {
    const rr = irrOf(r);
    return rr.irr_pct != null
      ? `<td class="${cls(rr.irr_pct)}" title="${esc('since ' + (rr.since || ''))}">${
          pct(rr.irr_pct, 1)}</td>`
      : `<td${rr.note ? ` title="${esc(rr.note)}"` : ''}>${na}</td>`;
  }
  if (k === 'drift') {
    const c = r.cov;
    if (!c || c.drift_pts == null) return `<td>${na}</td>`;
    return `<td class="${cls(c.drift_pts)}">${num(c.drift_pts, 1)} pts${
      c.target_basis === 'placeholder' ? ' <span class="est" title="Filled in by a '
        + 'rule, not a decision. Not a policy, and never alerted on.">placeholder</span>'
        : ''}</td>`;
  }
  if (k === 'verdict') {
    const w = r.w;
    if (!w) return '<td class="t"><span class="na">not on the Log</span></td>';
    return `<td class="t">${w.verdict ? verdictBadge(w.verdict) : ''}${w.thesis ? ''
      : ' <span class="est">no thesis</span>'}</td>`;
  }
  return '<td></td>';
}

function paintHoldings() {
  const box = $('#holdings');
  if (!box) return;
  const p = HS.p, pp = periodPct(p);
  const plabel = (PERIODS.find((x) => x[0] === p) || [p, p])[1];
  const cols = HCOLS.filter((c) => c.fixed || !HS.hide.has(c.k));
  const rows = holdSort(ROWS.filter((r) => r.isHeld), pp);

  const head = cols.map((c) => {
    const on = HS.sort.k === c.k;
    const label = c.k === 'period' ? plabel : c.l;
    return c.v
      ? `<th class="s${c.t ? ' t' : ''}" data-hk="${c.k}"${on
          ? ` data-dir="${HS.sort.dir}"` : ''}>${esc(label)}</th>`
      : `<th${c.t ? ' class="t"' : ''}>${esc(label)}</th>`;
  }).join('');

  const line = (r) => `<tr class="click" data-sym="${esc(r.sym)}">${
    cols.map((c) => holdCell(c.k, r, pp)).join('')}</tr>`;
  let body;
  if (HS.group) {
    body = HGROUPS.map(([k, name]) => {
      const g = rows.filter((r) => klassOf(r) === k);
      return g.length ? `<tr class="hgrp"><td colspan="${cols.length}">${esc(name)}
        <span>${g.length}</span></td></tr>${g.map(line).join('')}` : '';
    }).join('');
  } else body = rows.map(line).join('');

  const picks = HCOLS.filter((c) => !c.fixed).map((c) => `<button class="xtog"
    data-hc="${c.k}" aria-pressed="${!HS.hide.has(c.k)}">${esc(c.l)}</button>`).join('');
  const periods = PERIODS.map(([k, l]) => `<button class="rbtn" data-hp="${k}"
    aria-pressed="${k === p}">${esc(l)}</button>`).join('');

  box.innerHTML = `<div class="hbar">
      <div class="hper">${periods}</div>
      <button class="xtog" data-hg="1" aria-pressed="${HS.group}">Group funds and stocks</button>
    </div>
    <div class="hcols"><span class="k">Columns</span>${picks}</div>
    ${rows.length ? `<div class="scroll"><table class="htab">
      <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`
      : '<div class="hnote">Nothing held.</div>'}
    <div class="hnote">${rows.length} held · ${esc(plabel)} is each name's own EUR
      price move over the period${atBuild('period returns and IRR are computed from '
        + 'the daily closes and dated lots at build, and a live tick does not '
        + 'restate them')}</div>`;
}

on('#holdings', 'click', (e) => {
  const t = e.target;
  if (!t || !t.closest) return;
  const th = t.closest('th.s[data-hk]');
  if (th) {
    const k = th.getAttribute('data-hk');
    // Text columns start A to Z; numbers start biggest first.
    const col = HCOLS.find((c) => c.k === k);
    HS.sort = HS.sort.k === k ? {k, dir: -HS.sort.dir} : {k, dir: col && col.t ? 1 : -1};
    return paintHoldings();
  }
  const pb = t.closest('[data-hp]');
  if (pb) { HS.p = pb.getAttribute('data-hp'); return paintHoldings(); }
  if (t.closest('[data-hg]')) { HS.group = !HS.group; return paintHoldings(); }
  const cb = t.closest('[data-hc]');
  if (cb) {
    const k = cb.getAttribute('data-hc');
    if (HS.hide.has(k)) HS.hide.delete(k); else HS.hide.add(k);
    try { localStorage.setItem(HOLD_KEY, JSON.stringify([...HS.hide])); } catch (e2) {}
    return paintHoldings();
  }
  const row = t.closest('tr[data-sym]');
  if (row) jump(row.getAttribute('data-sym'));
});
