/* ------------------------------------------------------------- research */
/* The Equity Log as a board: one card per row on the Log, in lanes by the
   verdict written there. Nothing on a card is decided here. The marks are the
   flags the build raised (and DERIVE restates on a tick), found by the ticker
   in their key; "not held" is the coverage list analyse.py wrote; a Held
   disagreement is the health problem cockpit.py raised. The page re-tests no
   threshold of its own, so the board and Needs you cannot disagree about
   what is near a trigger. */

const RS = {f: 'all'};

// Lanes in the order a decision reads: what to buy, what to wait on, what was
// passed on. A verdict the Log adds later gets its own lane after these rather
// than vanishing, and a row with none is shown under "No verdict", not dropped.
const LANES = ['Buy-worthy', 'Watch', 'Pass'];

// Flags by the ticker in their key (`trigger-near:ERIC-B.ST`). Only kinds
// about one name carry a second part; book-wide flags have none and are
// skipped here, which is right - they belong to no card.
function flagsByTicker() {
  const m = new Map();
  for (const a of (D.alerts || [])) {
    const [kind, t] = String(a.key || '').split(':');
    if (!t) continue;
    if (!m.has(t)) m.set(t, []);
    m.get(t).push({kind, level: a.level, title: a.title});
  }
  return m;
}

// Where Notion and the broker disagree on Held. Raised by cockpit.py as a
// health problem keyed held-{ticker}-{blank|mismatch}; the kind is the last
// dash-part, and a ticker may carry dashes of its own, so cut from the right.
function heldRifts() {
  const m = new Map();
  for (const p of ((D.health || {}).problems || [])) {
    const k = String(p.key || '');
    if (!k.startsWith('held-') || k.lastIndexOf('-') <= 5) continue;
    m.set(k.slice(5, k.lastIndexOf('-')), p.title || 'Notion and the broker disagree on Held');
  }
  return m;
}

// What each flag kind is called on a card. The decay flag's direction is its
// level: the build raises a narrowed upside as a warning and a widened one as
// good, so the label reads that rather than the sign again.
const MARKNAME = {'trigger-hit': 'trigger hit', 'trigger-near': 'near trigger',
  'check-due': 'check due', 'inflection': 'inflection due',
  'multiple-stale': 'multiple stale'};
const markName = (f) => f.kind === 'decay'
  ? (f.level === 'good' ? 'upside widened' : 'upside narrowed')
  : (MARKNAME[f.kind] || f.kind);
// A widened upside is good news about a thesis, not a gain on a position, so
// it takes the accent rather than the gain colour.
const markTone = (f) => f.level === 'good' ? 'var(--accent)'
  : (LEVEL[f.level] || 'var(--muted)');

function checkText(w) {
  const d = w.days_to_check;
  if (d == null) return '<span class="na">no date written</span>';
  if (d < 0) return `<span class="od">overdue by ${-d} day${d === -1 ? '' : 's'}</span>`;
  return `${d === 0 ? 'today' : `in ${d} day${d === 1 ? '' : 's'}`}${
    w.next_check ? ` · ${esc(w.next_check)}` : ''}`;
}

function triggerText(w) {
  if (w.trigger_level == null) return '<span class="na">none written</span>';
  const lvl = `${esc(w.trigger_kind || 'at')} ${px(w.trigger_level)}`;
  if (w.trigger_hit) return `${lvl} · <b>hit</b>`;
  return `${lvl} · ${w.trigger_gap_pct == null ? '<span class="na">no live price</span>'
    : num(Math.abs(w.trigger_gap_pct), 1) + '% away'}`;
}

// Upside now against upside when it was written down. Both are shown, never
// merged: the distance between them is the point (rule 3 - the recorded figure
// is the evidence the write-up is stale). No gain/loss colour: an upside is a
// forecast, not a result.
function upsideText(w) {
  if (w.upside_now == null && w.upside_at_eval == null)
    return '<span class="na">no target</span>';
  return `${pct(w.upside_now, 1)} now · ${pct(w.upside_at_eval, 1)} at the ${
    w.last_eval ? esc(w.last_eval) : 'last'} check${w.upside_decay_pts == null ? ''
      : ` · ${w.upside_decay_pts > 0 ? '+' : ''}${num(w.upside_decay_pts, 1)} pts`}`;
}

// One ordering for a lane: a hit trigger first, then anything overdue, then
// anything flagged, then the rest; within each, the nearest check first and an
// undated one last.
function rsRank(w, fl) {
  if (fl.some((f) => f.kind === 'trigger-hit')) return 0;
  if (w.days_to_check != null && w.days_to_check < 0) return 1;
  if (fl.some((f) => f.level === 'critical' || f.level === 'warning')) return 2;
  return 3;
}

function rsCard(w, fl, rift, notHeld) {
  const sym = w.yahoo || w.ticker;
  const clickable = ROWSYM.has(sym);
  const marks = fl.map((f) => `<span class="rmark" title="${esc(f.title)}"><span
      class="dot" style="background:${markTone(f)}"></span>${esc(markName(f))}</span>`)
    .concat(rift ? [`<span class="rmark" title="${esc(rift)}"><span class="dot"
      style="background:var(--warn)"></span>Held disagrees</span>`] : [])
    .join('');
  return `<article class="rcard${clickable ? ' click' : ''}"${
      clickable ? ` data-sym="${esc(sym)}"` : ''} data-tk="${esc(w.ticker)}">
    <header><b>${esc(w.ticker)}</b>${notHeld ? '' : '<span class="hb">held</span>'}
      <span class="co" title="${esc(w.company || '')}">${esc(w.company || '')}</span></header>
    <dl class="rk">
      <dt>Trigger</dt><dd>${triggerText(w)}</dd>
      <dt>Upside</dt><dd>${upsideText(w)}</dd>
      <dt>Check</dt><dd>${checkText(w)}</dd>
    </dl>${marks ? `<div class="rmarks">${marks}</div>` : ''}</article>`;
}

function paintResearch() {
  const box = $('#research');
  if (!box) return;
  const W = D.watchlist || [];
  const FL = flagsByTicker(), RF = heldRifts();
  const NH = new Set((D.coverage || {}).researched_not_held || []);
  const flOf = (w) => FL.get(w.ticker) || [];
  const needs = (w) => flOf(w).length > 0 || RF.has(w.ticker)
    || (w.days_to_check != null && w.days_to_check < 0);
  const keep = {
    all: () => true,
    held: (w) => !NH.has(w.ticker),
    unheld: (w) => NH.has(w.ticker),
    look: needs,
  };
  const n = (f) => W.filter(keep[f]).length;
  const count = (kind) => W.filter((w) => flOf(w).some((f) => f.kind === kind)).length;
  const overdue = W.filter((w) => w.days_to_check != null && w.days_to_check < 0).length;

  const shown = W.filter(keep[RS.f] || keep.all);
  const verdicts = [...new Set(W.map((w) => w.verdict || 'No verdict'))];
  const order = LANES.filter((v) => verdicts.includes(v))
    .concat(verdicts.filter((v) => !LANES.includes(v)).sort());
  const lanes = order.map((v) => {
    const rows = shown.filter((w) => (w.verdict || 'No verdict') === v)
      .sort((a, b) => rsRank(a, flOf(a)) - rsRank(b, flOf(b))
        || (a.days_to_check == null) - (b.days_to_check == null)
        || (a.days_to_check || 0) - (b.days_to_check || 0));
    return `<section class="lane"><h3><span>${v === 'No verdict' ? esc(v)
        : verdictBadge(v)}</span><span class="rt">${rows.length}${
        rows.length !== W.filter((w) => (w.verdict || 'No verdict') === v).length
          ? ' of ' + W.filter((w) => (w.verdict || 'No verdict') === v).length : ''}</span></h3>
      ${rows.length ? rows.map((w) => rsCard(w, flOf(w), RF.get(w.ticker), NH.has(w.ticker))).join('')
        : '<div class="lnote">Nothing in this lane under this filter.</div>'}</section>`;
  }).join('');

  const seg = (f, l) => `<button class="seg" data-rf="${f}" aria-pressed="${RS.f === f}">${
    l} <b>${n(f)}</b></button>`;
  box.innerHTML = `<div class="rbar">
      <div class="rsum">${W.length} on the Log · ${count('trigger-hit')} trigger${
        count('trigger-hit') === 1 ? '' : 's'} hit · ${count('trigger-near')} near · ${
        count('check-due')} check${count('check-due') === 1 ? '' : 's'} due · ${
        overdue} overdue · ${NH.size} researched, not held${RF.size
          ? ` · ${RF.size} where Notion and the broker disagree on Held` : ''}</div>
      <div class="segs rsegs">${seg('all', 'All')}${seg('held', 'Held')}${
        seg('unheld', 'Not held')}${seg('look', 'Needs a look')}</div></div>
    ${W.length ? `<div class="lanes">${lanes}</div>`
      : '<div class="lnote">The Equity Log has no rows in this build.</div>'}`;
}

on('#research', 'click', (e) => {
  const t = e.target && e.target.closest ? e.target : null;
  if (!t) return;
  const f = t.closest('[data-rf]');
  if (f) { RS.f = f.getAttribute('data-rf'); paintResearch(); return; }
  const c = t.closest('[data-sym]');
  if (c) jump(c.getAttribute('data-sym'));
});
