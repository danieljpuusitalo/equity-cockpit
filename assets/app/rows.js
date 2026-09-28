// Folded once at boot, and again every time live prices land. This is a
// function rather than straight-line code for precisely that reason: the live
// layer has to rebuild these rows under the same rules, and a second copy of
// this loop would drift from this one the first time either changed.
//
// Note the rows here are NEW objects, not references into D.holdings, and
// value_eur is summed across custody accounts. So a live update cannot patch
// these in place - it writes the per-account rows in D.holdings and calls this
// again.
function foldHoldings() {
  held.clear();
  for (const h of D.holdings || []) {
    const sym = h.yahoo || h.ticker;
    if (!sym) continue;
    const cur = held.get(sym) || {sym, name:h.name, ticker:h.ticker, ccy:h.ccy,
      units:0, cost_eur:0, value_eur:0, price:h.price, day_pct:h.day_pct,
      off_high:h.off_high, bucket:h.bucket, accounts:[], stale:h.stale};
    cur.units += h.units || 0;
    cur.cost_eur += h.cost_eur || 0;
    cur.value_eur += h.value_eur || 0;
    if (h.account && !cur.accounts.includes(h.account)) cur.accounts.push(h.account);
    held.set(sym, cur);
  }
  for (const h of held.values()) {
    // Computed here, once, rather than re-inferred at each of the four places
    // a price is printed. A folded position takes its lots' price, so it takes
    // their freshness with it.
    h.freshness = freshnessOf(h.price, h.stale, h.sym);
    h.pl_eur = h.value_eur - h.cost_eur;
    h.pl_pct = h.cost_eur ? (h.value_eur / h.cost_eur - 1) * 100 : null;
    h.weight = D.totals.value_eur ? (h.value_eur / D.totals.value_eur) * 100 : 0;
  }
}
foldHoldings();

const watch = new Map();
for (const w of D.watchlist || []) {
  const sym = w.yahoo || w.ticker;
  if (sym) watch.set(sym, w);
}

// Coverage is per held position and carries its own `yahoo`, so the join needs
// no mapping the page would have to re-derive. Positions are per ISIN per
// account; a symbol held in both would land twice, and the one that matters is
// the uncovered one - a gap in either account is a gap.
const COV = (D.coverage || {});
const coverBy = new Map();
for (const c of COV.rows || []) {
  const sym = c.yahoo || c.ticker;
  if (!sym) continue;
  const prev = coverBy.get(sym);
  if (!prev || (prev.covered && !c.covered)) coverBy.set(sym, c);
}

// An alert names its subject in the key and again in the title. Matching on the
// symbol string covers both shapes without the analyser having to promise one.
const alertsFor = (sym) => (D.alerts || []).filter(
  (a) => (String(a.key || '') + ' ' + String(a.title || '')).includes(sym));
// analyse.alerts' own sort order: lower is more urgent.
const SEV = {critical: 0, warning: 1, good: 2};

// Rebuilt, not patched, for the same reason foldHoldings() is: `h` here is a
// reference into the folded map, and foldHoldings() replaces those objects
// wholesale. When this was a one-shot `const ROWS = [...]` the sheet updated on
// every tick and the rail, the strip and the detail pane went on rendering
// through references to objects nothing wrote to any more - the same page
// showing two different prices for the same holding, forty pixels apart.
const ROWS = [];
const ROWSYM = new Set();

function buildRows() {
  const rows = [...new Set([...held.keys(), ...watch.keys()])].map((sym) => {
  const h = held.get(sym), w = watch.get(sym);
  const flags = alertsFor(sym);
  return {
    sym, h, w, flags,
    cov: coverBy.get(sym) || null,
    ind: (D.indicators || {})[sym] || null,
    label: (w && w.ticker) || (h && h.ticker) || sym,
    company: (w && w.company) || (h && h.name) || sym,
    isHeld: !!h,
    price: (h && h.price) != null ? h.price : (w ? w.price_now : null),
    freshness: h ? h.freshness
      : freshnessOf(w ? w.price_now : null, w && w.stale_price, sym),
    ccy: (h && h.ccy) || (w && w.ccy) || '',
    // A watch-only name gets its day move from the live layer too; it was
    // written there and never read, so the rail showed a blank beside a price
    // that was plainly moving.
    day_pct: h ? h.day_pct : (w && w.day_pct != null ? w.day_pct : null),
    value_eur: h ? h.value_eur : null,
    weight: h ? h.weight : 0,
    // The most severe, by rank. The old fold let a later `good` overwrite an
    // earlier `warning`, so a name with both showed the calm dot.
    worst: flags.reduce((acc, a) =>
      acc && (SEV[acc] ?? 3) <= (SEV[a.level] ?? 3) ? acc : a.level, null),
  };
}).sort((a, b) => (b.value_eur || 0) - (a.value_eur || 0) ||
                  a.label.localeCompare(b.label));
  // Emptied and refilled rather than reassigned, so every closure that already
  // captured ROWS keeps seeing the live array.
  ROWS.length = 0;
  ROWS.push(...rows);
  // What `select()` can actually open. The sheet's tables reach further than
  // the rail does - the look-through names companies that are only inside a
  // fund and have no chart of their own - so a row is offered as a click only
  // when there is somewhere for the click to go. Marking every row clickable
  // and having most of them do nothing teaches you to stop clicking.
  ROWSYM.clear();
  for (const r of ROWS) ROWSYM.add(r.sym);
  return ROWS;
}
buildRows();

let state = {sym: ROWS.length ? ROWS[0].sym : null, view:'home',
             filter:'all', q:'', days:365, ma:{50:true, 200:true}};

