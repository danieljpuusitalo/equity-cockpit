/* ---------------------------------------------------------------- wiring */

// Which surface is up. The chart measures its container when it is drawn and
// can never re-measure afterwards, so paintChart refuses to build one into a
// hidden box. That refusal is only safe because of the call below: un-hide
// first, then paint, so the construction that was skipped at boot happens here
// against a container that has a real width. Do not reorder these two.
// Surfaces a live tick changed while they were off screen. A tick used to
// rebuild the Overview, the positions pane and all thirteen drawer tables every
// minute whether or not any of them was showing - measured at ~50ms of
// innerHTML per tick for the two hidden ones alone. It now paints what is on
// screen and marks the rest; the mark is cleared by painting on the way in, so
// a surface is never shown holding an older tick than the one beside it.
const UNPAINTED = new Set();
function shownSurface() {
  return SHEET ? 'sheet' : (state.view || 'home');
}
function paintSurface(s) {
  UNPAINTED.delete(s);
  if (s === 'sheet') paintSheet();
  else if (s === 'home') paintHome();
  else if (s === 'holdings') paintHoldings();
  else if (s === 'overview') paintOverview();
  else if (s === 'research') paintResearch();
  else if (s === 'positions' && typeof ROWS !== 'undefined' && ROWS.length
           && state.sym) select(state.sym);
}
function flushSurface() {
  const s = shownSurface();
  if (UNPAINTED.has(s)) paintSurface(s);
}

function setView(v) {
  state.view = v;
  if (!SHEET && UNPAINTED.has(v)) paintSurface(v);
  for (const n of document.querySelectorAll('#vnav .vbtn[data-view]'))
    n.setAttribute('aria-pressed', String(n.getAttribute('data-view') === v));
  const h = $('#v-home'), o = $('#v-overview'), p = $('#v-positions');
  const hd = $('#v-holdings'), rs = $('#v-research');
  if (h) h.hidden = v !== 'home';
  if (hd) hd.hidden = v !== 'holdings';
  if (o) o.hidden = v !== 'overview';
  if (rs) rs.hidden = v !== 'research';
  if (p) p.hidden = v !== 'positions';
  if (v === 'positions') {
    const r = ROWS.find((x) => x.sym === state.sym);
    if (r) paintChart(r);
  }
  paintCrumb();
  syncHash();
}

// What the drawer is sitting on top of. Both the crumb and the back button read
// from state.view rather than from each other, so they cannot disagree about
// where closing the drawer will land you.
// The Overview's route and id stay 'overview' so old links still land; what it
// is called on screen is Risk, because Home is the overview now.
const VIEWNAME = {home: 'Home', holdings: 'Holdings', overview: 'Risk',
                  positions: 'Positions', research: 'Research'};
function paintCrumb() {
  const under = VIEWNAME[state.view] || 'Home';
  const c = $('#t-crumb');
  if (c) c.textContent = 'over ' + under;
  const b = $('#t-close');
  if (b) b.textContent = 'Back to ' + under;
}

function select(sym) {
  if (!sym) return;
  state.sym = sym;
  const r = ROWS.find((x) => x.sym === sym);
  if (!r) return;
  paintRail(); paintHead(r); paintThesis(r); paintStrip(); paintChart(r);
  // Replace, never push. The arrow keys walk the rail one name at a time, and
  // pushing per step would bury the previous surface under twenty entries.
  syncHash();
}

function on(sel, ev, fn) { const n = $(sel); if (n) n.addEventListener(ev, fn); }

on('#list', 'click', (e) => {
  const row = e.target && e.target.closest && e.target.closest('.row');
  if (row) select(row.getAttribute('data-sym'));
});
on('#bars', 'click', (e) => {
  const bar = e.target && e.target.closest && e.target.closest('.bar');
  if (bar) select(bar.getAttribute('data-sym'));
});
on('#segs', 'click', (e) => {
  const b = e.target && e.target.closest && e.target.closest('.seg');
  if (!b) return;
  state.filter = b.getAttribute('data-f');
  const all = document.querySelectorAll('#segs .seg');
  for (const n of all) n.setAttribute('aria-pressed', String(n === b));
  paintRail();
});
on('#ranges', 'click', (e) => {
  const b = e.target && e.target.closest && e.target.closest('.rbtn');
  if (!b) return;
  const p = b.getAttribute('data-ma'), rel = b.getAttribute('data-rel');
  if (rel) {
    // One comparison at a time, and pressing the one in force takes it off.
    // Two relative lines on one left axis would be two rebasings to read apart.
    state.rel = state.rel === rel ? null : rel;
    for (const n of document.querySelectorAll('#ranges .rbtn[data-rel]'))
      n.setAttribute('aria-pressed', String(n.getAttribute('data-rel') === state.rel));
  } else if (p) {
    // MA buttons toggle independently; range buttons are mutually exclusive.
    // Sharing one handler means sharing one repaint, but not one selection rule.
    state.ma[p] = !state.ma[p];
    b.setAttribute('aria-pressed', String(state.ma[p]));
  } else {
    state.days = Number(b.getAttribute('data-d'));
    for (const n of document.querySelectorAll('#ranges .rbtn[data-d]'))
      n.setAttribute('aria-pressed', String(n === b));
  }
  const r = ROWS.find((x) => x.sym === state.sym);
  if (r) paintChart(r);
});
on('#q', 'input', (e) => { state.q = e.target.value || ''; paintRail(); });

/* ------------------------------------------------------------------ routing
 *
 * The page had no URL state at all: reloading always dropped you back on the
 * Overview, the browser's back button left the page entirely from wherever you
 * were, and a drawer three sections deep could not be linked or returned to.
 *
 * The route is two axes, not one. A view is where you are; the drawer is a
 * thing on top of it. So the drawer gets its own hash rather than being
 * encoded into the view's - `#/data/flag` says the drawer is up at Flags, and
 * back from it returns to whatever view was underneath. Opening the drawer
 * pushes; everything else replaces, because only the drawer is a place you
 * would want to come back from.
 *
 * Opened from disk there is no history to speak of and pushState throws on
 * some file: URLs, so every write is wrapped and falls back to assigning the
 * hash, which works everywhere and simply does not give you back.
 */
let SHEET = false;        // is the drawer up
let SHEETPUSHED = false;  // did opening it leave an entry we can go back over
let SHEETSCROLL = 0;      // display:none resets scrollTop; this survives it
let ROUTING = false;      // applying a route must never write one back

function routeOf() {
  if (SHEET) return '#/data' + (SS.at ? '/' + SS.at : '');
  if (state.view === 'positions' && state.sym) return '#/positions/' + state.sym;
  return '#/' + (state.view || 'home');
}

function syncHash(push) {
  if (ROUTING) return;
  const r = routeOf();
  if (location.hash === r) return;
  try {
    if (push && history.pushState) history.pushState(null, '', r);
    else if (history.replaceState) history.replaceState(null, '', r);
    else location.hash = r;
  } catch (e) { try { location.hash = r; } catch (e2) {} }
}

// Reading is deliberately forgiving. A hash that names a symbol we do not hold
// any more - an old bookmark, a sold position - lands on the view without the
// symbol rather than on a blank screen or an exception.
function applyHash() {
  const parts = String(location.hash || '').replace(/^#\/?/, '').split('/')
    .filter(Boolean);
  ROUTING = true;
  try {
    const head = (parts[0] || 'home').toLowerCase();
    if (head === 'data') {
      const sec = parts[1];
      if (sec) SS.at = sec;
      sheetOpen(true);
      if (sec) gotoSection(sec);
      return;
    }
    sheetOpen(false);
    if (head === 'positions') {
      setView('positions');
      if (parts[1] && ROWSYM.has(parts[1])) select(parts[1]);
    } else if (head === 'holdings') {
      setView('holdings');
    } else if (head === 'overview' || head === 'allocation' || head === 'risk') {
      setView('overview');
    } else if (head === 'research') {
      setView('research');
    } else {
      setView('home');
    }
  } finally { ROUTING = false; }
}

function sheetOpen(open) {
  const s = $('#sheet');
  if (!s) return;
  open = !!open;
  if (open === SHEET) return;
  if (!open) SHEETSCROLL = s.scrollTop || 0;
  SHEET = open;
  if (open) s.setAttribute('data-open', '1'); else s.removeAttribute('data-open');
  // aria-expanded, not aria-pressed. The button does not select a surface the
  // way a tab does; it reveals one. A bar clicked on the Overview opens the
  // drawer too, and a trigger that stayed collapsed through that would be
  // lying about what is on screen.
  const b = $('#t-sheet');
  if (b) b.setAttribute('aria-expanded', String(open));
  if (open) {
    // Restoring after the box is displayed, because a hidden element cannot be
    // scrolled. Coming back to the drawer at the top of a twelve-section
    // document, having just been two thirds of the way down it, reads as the
    // page having lost your place - which it had.
    if (UNPAINTED.has('sheet')) paintSurface('sheet');
    s.scrollTop = SHEETSCROLL;
    paintCrumb();
  } else flushSurface();
  if (open) { syncHash(true); SHEETPUSHED = !ROUTING; }
  else { syncHash(); SHEETPUSHED = false; }
}

function gotoSection(id) {
  // Jumping to a collapsed section opens it. Scrolling someone to a heading
  // with nothing under it is the navigation equivalent of a dead link.
  SS.at = id;
  SS.shut[id] = false;
  paintSheet();
  const head = $(`#sheetbody h2[data-sec="${id}"]`);
  const box = $('#sheet');
  if (!head || !box) return;
  // This used to be scrollIntoView({behavior:'smooth'}), which on this
  // container is a silent no-op - measured: the identical call without
  // `behavior` lands on the heading, with it the scrollTop never moves at all.
  // So every jump in this nav has only ever expanded the section, and the
  // reader was left at the top of an eleven-thousand-pixel document wondering
  // what the click did. Nothing threw and nothing logged.
  //
  // Scrolling the box by measurement instead. The sticky nav is subtracted
  // because it covers the top of the scrollport, and a heading scrolled to
  // exactly 0 lands underneath it.
  const nav = $('#sheetnav');
  const GAP = 8;
  const top = box.scrollTop + head.getBoundingClientRect().top
    - box.getBoundingClientRect().top
    - (nav ? nav.getBoundingClientRect().height : 0) - GAP;
  box.scrollTop = Math.max(0, top);
}

// The drawer, opened at one section. Order matters: the box has to be showing
// before gotoSection can measure where the heading sits.
function openSection(id) {
  sheetOpen(true);
  gotoSection(id);
  syncHash();
}

on('#t-sheet', 'click', () => sheetOpen(!SHEET));
// Back over the entry that opening the drawer pushed, so the browser's own
// back button and this one do the same thing rather than two similar things.
on('#t-close', 'click', () => {
  if (SHEETPUSHED && history.back) history.back(); else sheetOpen(false);
});
try { window.addEventListener('popstate', applyHash); } catch (e) {}
try { window.addEventListener('hashchange', applyHash); } catch (e) {}

/* -------------------------------------------------- the sheet, as a surface */

// Picking up a bucket from a bar or a fund row. The same key is written for
// every kind so the tables can filter on one rule; `kindLabel` is what the
// chip says, because "Sector Technology" reads and "sector technology" does
// not. Clicking the live filter again clears it - a toggle, not a trap.
const setFilter = (kind, key, label, kindLabel) => {
  const cur = SS.filter;
  SS.filter = (cur && cur.kind === kind && cur.key === key)
    ? null : {kind, key, label, kindLabel};
  paintSheet();
};

// Open a symbol in the main view. The sheet closes, because leaving it up
// would hide the chart the click just asked for.
const jump = (sym) => {
  if (!sym || !ROWSYM.has(sym)) return;
  sheetOpen(false);
  // Switching the view here rather than at each call site. A symbol clicked in
  // the drawer used to close it onto whichever view was underneath - so from
  // the Overview you asked for a chart and got the Overview back, with the
  // selection changed somewhere you could not see. The Overview's own handler
  // set the view itself, which is why it looked like it worked.
  setView('positions');
  select(sym);
};

on('#vnav', 'click', (e) => {
  const b = e.target && e.target.closest && e.target.closest('.vbtn');
  // The data-view guard outlived the button it was written for - Data is no
  // longer in this nav - but it stays: the nav is now exactly the set of real
  // views, and this is what keeps that true if anything else is ever put here.
  if (b && b.getAttribute('data-view')) setView(b.getAttribute('data-view'));
});

// Every clickable thing on the Overview leads somewhere specific. A tile or a
// ranked row opens that position; a composition bar opens the data sheet
// already filtered to it. An overview whose charts are only pictures is the
// glorified list this view exists to replace.
on('#ovgrid', 'click', (e) => {
  const t = e.target;
  if (!t || !t.closest) return;
  const go = t.closest('[data-go]');
  if (go) { openSection(go.getAttribute('data-go')); return; }
  const bar = t.closest('.xrow[data-fk]');
  if (bar) {
    const kind = bar.getAttribute('data-fk');
    sheetOpen(true);
    return setFilter(kind, bar.getAttribute('data-fv'),
      bar.getAttribute('data-fl'),
      {sector: 'Sector', country: 'Geography', industry: 'Industry'}[kind] || '');
  }
  const node = t.closest('[data-sym]');
  if (node) jump(node.getAttribute('data-sym'));   // jump() sets the view now
});

on('#sheetnav', 'click', (e) => {
  if (!e.target || !e.target.closest) return;
  if (e.target.closest('#xclear')) { SS.filter = null; return paintSheet(); }
  const b = e.target.closest('.navb');
  if (!b) return;
  gotoSection(b.getAttribute('data-go'));
  syncHash();
});

on('#sheetbody', 'click', (e) => {
  const t = e.target;
  if (!t || !t.closest) return;

  const head = t.closest('th.s');
  if (head) {
    const table = head.getAttribute('data-t'), k = head.getAttribute('data-k');
    const cur = SS.sort[table];
    SS.sort[table] = (cur && cur.k === k)
      ? {k, dir: -cur.dir}
      : {k, dir: Number(head.getAttribute('data-d0')) || -1};
    return paintSheet();
  }

  const h2 = t.closest('h2[data-sec]');
  if (h2) {
    const id = h2.getAttribute('data-sec');
    SS.shut[id] = !SS.shut[id];
    return paintSheet();
  }

  const bar = t.closest('.xrow[data-fk]');
  if (bar) return setFilter(bar.getAttribute('data-fk'),
    bar.getAttribute('data-fv'), bar.getAttribute('data-fl'),
    {sector: 'Sector', country: 'Geography', industry: 'Industry'}[
      bar.getAttribute('data-fk')] || '');

  const fund = t.closest('tr[data-fund]');
  if (fund) {
    const sym = fund.getAttribute('data-fund');
    return setFilter('fund', sym, sym, 'Inside');
  }

  const row = t.closest('[data-sym]');
  if (row) jump(row.getAttribute('data-sym'));
});

on('#xq', 'input', (e) => { SS.q = e.target.value || ''; paintSheet(); });

on('#xunits', 'click', (e) => {
  SS.units = SS.units === 'eur' ? 'pct' : 'eur';
  e.currentTarget.setAttribute('aria-pressed', String(SS.units === 'eur'));
  e.currentTarget.textContent = SS.units === 'eur' ? 'Show %' : 'Show €';
  paintSheet();
});

on('#xall', 'click', (e) => {
  const ids = [...document.querySelectorAll('#sheetbody h2[data-sec]')]
    .map((n) => n.getAttribute('data-sec'));
  const shutting = ids.some((id) => !SS.shut[id]);
  for (const id of ids) SS.shut[id] = shutting;
  e.currentTarget.setAttribute('aria-pressed', String(shutting));
  e.currentTarget.textContent = shutting ? 'Expand all' : 'Collapse all';
  paintSheet();
});

// The label said "Dark" and the markup hardcoded it, which was wrong twice
// over. On a machine whose OS prefers dark the page opened dark under a button
// offering to make it dark; and a one-word label never said whether it named
// the current state or the one click away. It names the action now, and it
// reads the state off what is actually rendered rather than off a default.
function isDark() {
  try {
    const set = document.documentElement.getAttribute('data-theme');
    if (set) return set === 'dark';
    return !!(window.matchMedia
      && window.matchMedia('(prefers-color-scheme: dark)').matches);
  } catch (e) { return false; }
}
function themeLabel() {
  const b = $('#t-theme');
  if (!b) return;
  const dark = isDark();
  b.setAttribute('aria-pressed', String(dark));
  const label = dark ? 'Switch to light' : 'Switch to dark';
  // The label is a span beside an icon; writing the button's own text would
  // take the icon with it, and the collapsed rail shows only the icon.
  const l = b.querySelector && b.querySelector('.l');
  if (l) l.textContent = label; else b.textContent = label;
  b.setAttribute('title', label);
}

on('#t-theme', 'click', () => {
  try {
    document.documentElement.setAttribute('data-theme',
      isDark() ? 'light' : 'dark');
  } catch (e) {}
  themeLabel();
  retheme();
});

// Until the button is pressed the page follows the OS, so the OS changing mid
// session changes the page - and would leave the label describing the theme
// that was up when it loaded.
try {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  const onFlip = () => {
    if (document.documentElement.getAttribute('data-theme')) return;
    themeLabel();
    retheme();
  };
  if (mq.addEventListener) mq.addEventListener('change', onFlip);
  else if (mq.addListener) mq.addListener(onFlip);
} catch (e) {}

