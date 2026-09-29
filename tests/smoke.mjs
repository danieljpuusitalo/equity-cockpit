/* Executes the dashboard's own script under a minimal DOM shim.
 *
 * A generated page that throws halfway through renders a half-empty card and
 * says nothing about it. This catches that in the build, not in your browser.
 *
 *   node tests/smoke.mjs out/dashboard.html
 */
import fs from 'fs';

const path = process.argv[2] || 'out/dashboard.html';
const html = fs.readFileSync(path, 'utf8');
// The page carries two scripts: the vendored chart library and ours. Only ours
// is worth executing here - the library is TradingView's problem, not this
// repo's, and running it under a shim would test nothing we wrote.
// Built by concatenation so the marker is never spelled out in this file
// either - see the note in the template. A second occurrence anywhere in the
// document, including inside an HTML comment, silently reassigns which block
// gets executed, and what you get back is a syntax error from inside minified
// TradingView source. That already happened once. Count first, split after.
const MARK = '<script' + ' id="app">';
const parts = html.split(MARK);
if (parts.length === 1) {
  console.error(`SMOKE FAIL  ${path}: no ${MARK} block found`);
  process.exit(1);
}
if (parts.length > 2) {
  console.error(`SMOKE FAIL  ${path}: ${parts.length - 1} blocks match `
    + `${MARK}; the marker must be unique or this test runs the wrong script. `
    + 'Check for it being written out inside a comment.');
  process.exit(1);
}
const js = parts[1].split('</script>')[0];

const el = () => {
  const node = {
    innerHTML: '', textContent: '', style: {},
    classList: { add() {}, remove() {} },
    appendChild() {}, insertBefore() {}, addEventListener() {},
    setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
    // The shim stores innerHTML as a string and never parses it, so a node can
    // honestly report that it contains nothing. The page reads its own output
    // back to build the sheet's section nav; an empty list has to be a valid
    // answer here or this test fails on the shim's limits rather than the
    // page's. What the nav actually renders is checked in a browser.
    // Same reasoning one line down: a node that never parsed its innerHTML
    // cannot honestly say it found a child, so it says it found none.
    // watchTiles guards on exactly that (`if (!box) return`), which is why
    // null is the right answer and not a hole in the shim. Without this the
    // page throws at `$('#ovgrid').querySelector('.tmap')` and the whole smoke
    // test dies before it walks a single row - it did, on committed code.
    querySelector: () => null,
    querySelectorAll: () => [], scrollIntoView() {},
    closest: () => null, value: '',
    getBoundingClientRect: () => ({ width: 10, height: 10 }),
  };
  node.parentNode = { insertBefore() {}, appendChild() {} };
  return node;
};

// One node per selector, not a fresh one per call. The page writes into #thesis
// and #sheetbody and we want to read back what it wrote; a throwaway node would
// prove the code ran and nothing about what it produced.
const nodes = new Map();
const bySel = (s) => {
  if (!nodes.has(s)) nodes.set(s, el());
  return nodes.get(s);
};

globalThis.document = {
  querySelector: bySel, querySelectorAll: () => [],
  createElementNS: el, createElement: el, body: el(), documentElement: el(),
};
globalThis.window = globalThis;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1200;
globalThis.innerHeight = 800;
// The page routes on the hash and only polls for live prices over http(s), so
// a file: location opens it on the default view with the live layer asleep.
globalThis.location = { hash: '', protocol: 'file:' };
globalThis.history = { pushState() {}, replaceState() {} };

/* The page only paints the first row at load, so running it as-is tests one
   name out of thirty-six. This walks every one of them - a section that throws
   on the single holding with no history, or prints "undefined" for the one fund
   Yahoo knows nothing about, is exactly the failure that survives a one-row
   check and then greets you on a Monday morning. */
const WALK = `
;(function () {
  const bad = [];
  const junk = ['undefined', 'NaN', '[object Object]'];
  const scan = (where, html) => {
    if (!html) { bad.push(where + ': rendered empty'); return; }
    for (const t of junk) if (html.includes(t)) bad.push(where + ': printed "' + t + '"');
  };
  for (const r of ROWS) {
    select(r.sym);
    scan('thesis ' + r.sym, document.querySelector('#thesis').innerHTML);
    scan('head ' + r.sym, document.querySelector('#symhead').innerHTML);
  }
  scan('rail', document.querySelector('#list').innerHTML);
  scan('tape', document.querySelector('#t-meta').innerHTML);
  scan('data sheet', document.querySelector('#sheetbody').innerHTML);
  scan('overview headline', document.querySelector('#ovtop').innerHTML);
  scan('overview grid', document.querySelector('#ovgrid').innerHTML);
  // Home, in every period. Each period slices the curve and the attribution
  // differently, and the one with a two-point curve is the one that divides by
  // a zero span - so all seven are painted, not just the one that opens.
  const perf = D.performance || {};
  for (const [p] of PERIODS) {
    state.hp = p;
    paintHome();
    const h = document.querySelector('#home').innerHTML || '';
    scan('home ' + p, h);
    if (((perf.curve || {}).dd || []).length > 1 && !h.includes('id="hplot"'))
      bad.push('home ' + p + ': the payload has a curve and none was drawn');
    if (perf.benchmark && !perf.benchmark.absent && !h.includes('class="hshadow"'))
      bad.push('home ' + p + ': the benchmark is present and its shadow was not drawn');
  }
  state.hp = null;
  paintHome();
  // Needs you counts what alert_counts counts. Two surfaces once counted the
  // same list their own way and disagreed; this one draws a line per alert
  // and the number above it comes from the payload, so they must agree.
  const home = document.querySelector('#home').innerHTML || '';
  for (const t of ['act', 'watch', 'tailwind']) {
    const n = (home.match(new RegExp('class="need" data-tier="' + t + '"', 'g')) || []).length;
    const want = (D.alert_counts || {})[t];
    if (n !== want) bad.push('needs you: ' + n + ' ' + t + ' line(s) drawn, alert_counts says ' + want);
  }
  const needs = (home.match(/class="need" data-tier=/g) || []).length;
  // The treemap is the one picture on the page that is laid out in Python, so
  // a tile count that disagrees with the payload means the page dropped
  // rectangles on the floor - a map with a hole in it and no legend.
  const grid = document.querySelector('#ovgrid').innerHTML || '';
  // class="tile" - no trailing space. The tile carries exactly one class and
  // its size class is added later by fitTiles, in pixels, against the laid-out
  // box. This pattern used to be /class="tile /, which the markup has never
  // produced, so the count was structurally 0 and this check could only ever
  // fail. It never surfaced because the page threw further up and the harness
  // died before reaching it - two defects covering for each other.
  const drawn = (grid.match(/class="tile"/g) || []).length;
  const want = ((D.overview || {}).allocation || {}).n || 0;
  if (drawn !== want) bad.push('treemap: ' + drawn + ' tiles drawn, ' + want + ' laid out');

  // The browser port against its Python original, on the prices the file was
  // built with. The page runs this at boot and only shows the verdict; here a
  // disagreement fails the build instead of waiting for someone to look.
  if (!PARITY.ok) {
    bad.push('parity: ' + PARITY.n_mismatches + ' of ' + PARITY.checked
      + ' fields disagree with Python');
    for (const m of PARITY.mismatches.slice(0, 8)) {
      bad.push('  ' + m.path + ': ' + JSON.stringify(m.was) + ' -> ' + JSON.stringify(m.now));
    }
  }
  // ...and the negative control, without which a perfect score proves nothing.
  // A recompute that never ran leaves Python's numbers in place and passes
  // parity exactly as well as one that ran correctly. So move a fund's price
  // and demand the look-through move with it.
  let moved = 'skipped';
  if (D.lookthrough) {
    const X = D.exposure;
    const fundIsin = new Set(((D.coverage || {}).rows || [])
      .filter((r) => r.klass === 'fund').map((r) => r.isin));
    const h = (D.holdings || []).find((r) => fundIsin.has(r.isin)
      && r.yahoo && (D.lookthrough.funds || {})[r.yahoo]);
    if (!h) {
      bad.push('negative control: no fund with a composition to perturb');
    } else {
      const was = JSON.stringify([X.sectors, X.geography, X.names, X.overlap]);
      h.value_eur = Math.round(h.value_eur * 50) / 100;   // halve it
      DERIVE.all();
      const now = JSON.stringify([X.sectors, X.geography, X.names, X.overlap]);
      if (was === now) bad.push('negative control: halving ' + h.yahoo
        + ' left the look-through unchanged - the recompute is not running');
      moved = was === now ? 'no' : 'yes';
    }
  }
  // The same control for the flags. Parity on the build's own prices passes
  // just as well if the flags were never rebuilt at all, so push one watchlist
  // name through its written trigger and demand the critical flag appear -
  // and, because it is the thing a reader acts on, the rail count follow it.
  let flagged = 'skipped';
  if (!DERIVE.stats().alerts) {
    bad.push('flags: not restated - the payload is missing a threshold the port needs');
  } else {
    const w = (D.watchlist || []).find((x) => x.trigger_level && x.price_now
      && !x.trigger_hit);
    if (w) {
      w.price_now = w.trigger_level * (w.trigger_kind === 'below' ? 0.99 : 1.01);
      DERIVE.all();
      const hit = (D.alerts || []).some((a) => a.key === 'trigger-hit:' + w.ticker);
      if (!hit) bad.push('flags: ' + w.ticker + ' pushed through its trigger and '
        + 'no trigger-hit flag appeared - the flags are frozen at build');
      flagged = hit ? 'yes' : 'no';
    }
  }
  // Navigation. The jump box has to reach every name on the rail, and a flag
  // about a position has to open that position - a flag that only reads is
  // the dead end the Overview card used to be.
  const reach = palFilter('').filter((it) => it.kind === 'Holding'
    || it.kind === 'Watchlist').length;
  if (reach !== ROWS.length) bad.push('jump box: reaches ' + reach + ' of '
    + ROWS.length + ' names');
  for (const r of ROWS) {
    if (!palFilter(r.label.toLowerCase()).some((it) => it.label === r.label))
      bad.push('jump box: typing ' + r.label + ' does not find it');
  }
  let linked = 0;
  for (const a of (D.alerts || [])) {
    const own = String(a.key || '').split(':')[1];
    if (own && ROWSYM.has(own)) {
      if (symOfAlert(a) !== own) bad.push('flag ' + a.key + ' opens '
        + symOfAlert(a) + ', not ' + own);
      else linked++;
    }
  }
  // Holdings, in every period, flat and grouped. One row per held name either
  // way: a group that drops the names whose class is unknown loses them from
  // the only table that lists everything.
  const heldN = ROWS.filter((r) => r.isHeld).length;
  const holdBox = () => document.querySelector('#holdings').innerHTML || '';
  const holdOrder = () => [...holdBox().matchAll(/<tr class="click" data-sym="([^"]*)"/g)]
    .map((m) => m[1]);
  const holdRow = (sym) => (holdBox().split('data-sym="' + sym + '"')[1] || '')
    .split('</tr>')[0];
  let holdPainted = 0;
  for (const [p] of PERIODS) {
    for (const g of [false, true]) {
      HS.p = p; HS.group = g;
      paintHoldings();
      scan('holdings ' + p + (g ? ' grouped' : ''), holdBox());
      const n = holdOrder().length;
      if (n !== heldN) bad.push('holdings ' + p + (g ? ' grouped' : '') + ': '
        + n + ' rows drawn, ' + heldN + ' held');
      holdPainted++;
    }
  }
  // This book may classify every name, so the unknown group is forced: strip
  // one name's class and it must still be drawn, under its own heading.
  const unk = ROWS.find((r) => r.isHeld && r.cov);
  if (unk) {
    const keepCov = unk.cov;
    unk.cov = null;
    HS.group = true;
    paintHoldings();
    if (holdOrder().length !== heldN || !holdBox().includes('Class unknown'))
      bad.push('holdings grouped: a name with no class was dropped, not grouped as unknown');
    unk.cov = keepCov;
  }
  HS.group = false;
  // Absent sorts last, whichever way the column is turned.
  for (const dir of [-1, 1]) {
    HS.sort = {k: 'period', dir};
    paintHoldings();
    const pp = periodPct(HS.p);
    const vals = holdOrder().map((s) => pp.get(s));
    const firstNull = vals.findIndex((v) => v == null);
    if (firstNull >= 0 && vals.slice(firstNull).some((v) => v != null))
      bad.push('holdings: sorted by period (dir ' + dir + '), a blank sits above a figure');
  }
  HS.sort = {k: 'weight', dir: -1};
  // Negative control: the period cell is the payload's figure, so moving the
  // payload has to move the cell. A column that printed a cached or recomputed
  // number would pass every scan above and fail here.
  let periodMoved = 'skipped';
  const attr = (PERF.attribution || {})[HS.p] || [];
  const a0 = attr.find((a) => a.pct != null && ROWSYM.has(a.symbol));
  if (a0) {
    paintHoldings();
    const was = holdRow(a0.symbol);
    const keep = a0.pct;
    a0.pct = keep + 17.3;
    paintHoldings();
    const now = holdRow(a0.symbol);
    a0.pct = keep;
    periodMoved = was === now ? 'no' : 'yes';
    if (was === now) bad.push('holdings: moving ' + a0.symbol + "'s attribution pct "
      + 'left its row unchanged - the period column is not reading the payload');
  }
  // A hidden column leaves the header and every row, not just the header.
  HS.hide.add('irr');
  paintHoldings();
  if (holdBox().includes('data-hk="irr"')) bad.push('holdings: hiding IRR left its header');
  HS.hide.delete('irr');
  paintHoldings();
  if (heldN && !holdBox().includes('data-hk="irr"')) bad.push('holdings: IRR did not come back');
  // Position detail with the relative line on, both ways, and its risk line.
  const firstHeld = ROWS.find((r) => r.isHeld);
  for (const rel of ['book', 'bench']) {
    if (!firstHeld) break;
    state.rel = rel;
    select(firstHeld.sym);
    scan('thesis vs ' + rel, document.querySelector('#thesis').innerHTML);
    const lb = document.querySelector('#livebar').innerHTML || '';
    for (const t of junk) if (lb.includes(t)) bad.push('livebar vs ' + rel + ': printed "' + t + '"');
  }
  state.rel = null;
  // The relative line: rebased to 100 against the book, and nothing at all
  // against a benchmark the build marked absent - even with a series left
  // lying in the payload, because "absent" is the authority, not the array.
  let relOk = 'skipped';
  const relBars = firstHeld ? barsFor(firstHeld) : null;
  if (relBars && relBars.length > 1 && CURVE.n) {
    const book = relSeries(relBars, 'book');
    if (!book.length || Math.abs(book[0].value - 100) > 1e-9)
      bad.push('relative line vs book: ' + (book.length ? 'starts at ' + book[0].value
        : 'empty') + ', not 100');
    const keepAbs = BENCH.absent, keepIdx = BENCH.index;
    BENCH.absent = 'smoke';
    BENCH.index = BENCH.index || CURVE.index;
    if (relSeries(relBars, 'bench').length) bad.push('relative line: drew vs ACWI with the benchmark marked absent');
    if (!relWhy('bench')) bad.push('relative line: an absent benchmark gives no reason');
    BENCH.absent = keepAbs; BENCH.index = keepIdx;
    relOk = 'yes';
  }
  for (const r of ROWS.filter((x) => x.isHeld)) {
    select(r.sym);
    const th = document.querySelector('#thesis').innerHTML || '';
    if (!th.includes('of book risk') && !th.includes('not estimated'))
      bad.push('thesis ' + r.sym + ': no book-risk line, neither a figure nor "not estimated"');
  }
  // Research: one card per Log row under All, and Held plus Not held is the
  // whole Log - a row that belongs to neither filter has fallen off the board.
  const resBox = () => document.querySelector('#research').innerHTML || '';
  const cardOf = (t) => (resBox().split('data-tk="' + t + '"')[1] || '').split('</article>')[0];
  const nW = (D.watchlist || []).length;
  const resN = {};
  for (const f of ['all', 'held', 'unheld', 'look']) {
    RS.f = f;
    paintResearch();
    scan('research ' + f, resBox());
    resN[f] = (resBox().match(/<article class="rcard/g) || []).length;
  }
  if (resN.all !== nW) bad.push('research: ' + resN.all + ' cards drawn, ' + nW + ' rows on the Log');
  if (resN.held + resN.unheld !== nW) bad.push('research: held ' + resN.held + ' + not held '
    + resN.unheld + ' is not the ' + nW + ' on the Log');
  RS.f = 'all';
  // Negative controls. The marks are read off D.alerts and D.health, so a flag
  // or a Held problem put there has to appear on its card, and taken away has
  // to leave it; the trigger distance is the payload's, so moving it moves
  // the card. A board that re-tested thresholds or cached a paint fails here.
  let resMoved = 'skipped';
  const rw = (D.watchlist || []).find((w) => w.trigger_level != null && !w.trigger_hit
    && w.trigger_gap_pct != null) || (D.watchlist || [])[0];
  if (rw) {
    const keepA = D.alerts, keepH = (D.health || {}).problems;
    D.alerts = (keepA || []).concat([{level: 'warning', key: 'trigger-near:' + rw.ticker,
                                      title: 'smoke'}]);
    D.health = D.health || {};
    D.health.problems = (keepH || []).concat([{key: 'held-' + rw.ticker + '-mismatch',
                                               title: 'smoke rift'}]);
    paintResearch();
    const withFlag = cardOf(rw.ticker);
    D.alerts = keepA; D.health.problems = keepH;
    paintResearch();
    const without = cardOf(rw.ticker);
    if (!withFlag.includes('near trigger')) bad.push('research: a trigger-near flag for '
      + rw.ticker + ' did not mark its card');
    if (!withFlag.includes('Held disagrees')) bad.push('research: a held problem for '
      + rw.ticker + ' did not mark its card');
    if (without.includes('smoke')) bad.push('research: a removed flag is still on the card');
    if (rw.trigger_gap_pct != null) {
      const keepG = rw.trigger_gap_pct;
      rw.trigger_gap_pct = keepG + 13.7;
      paintResearch();
      const moved = cardOf(rw.ticker);
      rw.trigger_gap_pct = keepG;
      paintResearch();
      if (moved === without) bad.push('research: moving ' + rw.ticker
        + ' trigger distance left its card unchanged');
      resMoved = moved === without ? 'no' : 'yes';
    }
  }
  // Risk: one row per estimated name, a full matrix, and an absent share
  // printed as absent. Then the share itself is moved and must move the row.
  paintOverview();
  const RK = PERF.risk || {};
  const ovg = () => document.querySelector('#ovgrid').innerHTML || '';
  const rrows = (ovg().match(/class="rrow/g) || []).length;
  if (rrows !== (RK.contribution || []).length) bad.push('risk: ' + rrows
    + ' contribution rows drawn, ' + (RK.contribution || []).length + ' in the payload');
  const nS = (RK.symbols || []).length;
  const cells = nS > 1 ? (ovg().split('class="corr"')[1] || '').split('class="tmapkey"')[0]
    .match(/<i /g) || [] : [];
  if (nS > 1 && cells.length !== nS * nS) bad.push('risk: ' + cells.length
    + ' correlation cells drawn, ' + nS * nS + ' in the matrix');
  let riskMoved = 'skipped';
  const rc0 = (RK.contribution || []).find((c) => c.rc_pct != null);
  if (rc0) {
    const rowOf = () => (ovg().slice(ovg().indexOf('class="rrow'))
      .split('<div class="t">' + esc(labOf(rc0.symbol)) + '</div>')[1]
      || '').split('</div></div>')[0];
    const was = rowOf();
    const keep = rc0.rc_pct;
    rc0.rc_pct = keep + 11.1;
    paintOverview();
    const now = rowOf();
    rc0.rc_pct = null;
    paintOverview();
    const gone = rowOf();
    rc0.rc_pct = keep;
    paintOverview();
    if (was === now) bad.push('risk: moving ' + rc0.symbol + ' share of risk left its row unchanged');
    if (!gone.includes('not estimated')) bad.push('risk: an absent share of risk for '
      + rc0.symbol + ' was not printed as not estimated');
    riskMoved = was !== now && gone.includes('not estimated') ? 'yes' : 'no';
  }
  globalThis.__smoke = {rows: ROWS.length, tiles: drawn, bad: bad,
                        research: resN.all, resMoved: resMoved, rrows: rrows,
                        cells: cells.length, riskMoved: riskMoved,
                        parity: PARITY.checked, moved: moved, flagged: flagged,
                        linked: linked, needs: needs, held: heldN,
                        holdPainted: holdPainted, periodMoved: periodMoved,
                        relOk: relOk};
})();`;

try {
  new Function(js + WALK)();
} catch (e) {
  console.error(`SMOKE FAIL  ${path}: ${e.message}`);
  process.exit(1);
}

/* Every card has to survive its source answering with nothing. The walk above
   runs on the last real book, where every source answered; a card that throws
   on an empty section or prints "undefined" for a missing one is invisible
   there and turns up the morning Yahoo or Notion has a bad day. So the page is
   run again on hollowed copies of the same payload: each group of sections set
   to the empty value of its own type, then all of them at once, then a book
   with no positions at all. The script's top-level consts live in the
   Function's own scope, so each run is a fresh page. */
const HOLLOW = `
;(function () {
  const bad = [];
  const junk = ['undefined', 'NaN', '[object Object]', 'Infinity'];
  const look = (where, sel) => {
    const h = document.querySelector(sel).innerHTML || '';
    for (const t of junk) if (h.includes(t)) bad.push(where + ': printed "' + t + '"');
  };
  const paint = (where, fn, sel) => {
    try { fn(); look(where, sel); } catch (e) { bad.push(where + ': threw ' + e.message); }
  };
  for (const [p] of PERIODS) { state.hp = p; paint('home ' + p, paintHome, '#home'); }
  state.hp = null;
  // Absent is not zero, in the two places a hollow payload used to print one:
  // a caption describing a curve that was not drawn, and a fee drag of nothing
  // when no fund's TER was known or nothing said which names were funds.
  if (!HC && document.querySelector('#home').innerHTML.includes('rebuilt from'))
    bad.push('home: the curve caption printed with no curve');
  paint('holdings', paintHoldings, '#holdings');
  paint('risk', paintOverview, '#ovtop');
  const FE = (D.exposure || {}).fees || {};
  const classed = ((D.coverage || {}).rows || []).length > 0;
  if ((!classed || (FE.fund_value_eur && !FE.covered_eur))
      && /Fee drag[\\s\\S]*?€0\\/yr/.test(document.querySelector('#ovtop').innerHTML))
    bad.push('risk: a fee drag of zero where no TER was known');
  look('risk grid', '#ovgrid');
  for (const f of ['all', 'held', 'unheld', 'look']) {
    RS.f = f;
    paint('research ' + f, paintResearch, '#research');
  }
  RS.f = 'all';
  paint('data', paintSheet, '#sheetbody');
  paint('tape', paintTape, '#t-meta');
  for (const r of ROWS) paint('position ' + r.sym, () => select(r.sym), '#thesis');
  globalThis.__hollow = bad;
})();`;
const DATA = /const D = (\{.*?\});\r?\n/s;
const real = JSON.parse(js.match(DATA)[1]);
// What render.payload() actually emits for a source that answered nothing:
// performance and lookthrough are absent (null), everything else is the empty
// of its own type. A hollow shape Python cannot produce would test the shim.
const ABSENT = new Set(['performance', 'lookthrough']);
const emptyOf = (v, k) => ABSENT.has(k) ? null
  : Array.isArray(v) ? [] : v && typeof v === 'object' ? {} : null;
const GROUPS = {
  'no performance': ['performance'],
  'no exposure': ['exposure', 'lookthrough'],
  'no Equity Log': ['watchlist', 'alerts', 'coverage'],
  'no price history': ['history', 'indicators', 'returns'],
  'no reporting or activity': ['reporting', 'activity'],
  'no overview': ['overview'],
};
const hollowOf = (keys, noBook) => {
  const H = JSON.parse(JSON.stringify(real));
  for (const k of keys) H[k] = emptyOf(H[k], k);
  // alert_counts says what alerts holds; emptying one without the other would
  // test a disagreement Python cannot produce, not an empty source.
  if (keys.includes('alerts')) H.alert_counts = {act: 0, watch: 0, tailwind: 0, total: 0};
  if (noBook) { H.holdings = []; H.totals = {}; }
  return H;
};
const cases = Object.entries(GROUPS).map(([n, k]) => [n, hollowOf(k)]);
const every = [].concat(...Object.values(GROUPS));
cases.push(['every optional section empty', hollowOf(every)]);
cases.push(['no positions at all', hollowOf(every, true)]);
const hollowBad = [];
for (const [name, H] of cases) {
  nodes.clear();
  globalThis.__hollow = null;
  const src = js.replace(DATA, () => 'const D = ' + JSON.stringify(H) + ';\n');
  try {
    new Function(src + HOLLOW)();
  } catch (e) {
    hollowBad.push(name + ': the page threw at load: ' + e.message);
    continue;
  }
  for (const b of globalThis.__hollow || ['the hollow walk never ran'])
    hollowBad.push(name + ' | ' + b);
}

/* The tick tint picks figures by position, so the diff it rests on must tint
   exactly what moved, and nothing at all once the layout moved under it:
   tinting by position after a row appeared would light up the wrong numbers.
   The unchanged pair is the control - a diff that marks everything passes the
   moved case on its own. */
nodes.clear();
new Function(js + ';globalThis.__tick = [tickDiff(["1","2","3"], ["1","2","3"]).join(),'
  + 'tickDiff(["1","2","3"], ["1","9","3"]).join(), tickDiff(["1","2"], ["1","2","3"]).join()];')();
/* Python's own format() answers, each read back from Python together with
   the exact stored value (Decimal(x)): 8.65 is stored a hair ABOVE the tie and
   rounds up; 0.35 and 2.675 are stored a hair BELOW and round down; 0.25, 2.5
   and -2.25 are exact ties and go to even. 8.65 is the control - a formatter
   that sends every apparent tie to even passes the other five, and that was
   the bug that printed +8.6% beside Python's +8.7%. */
const PYF = [[8.65, 1, '8.7'], [0.35, 1, '0.3'], [2.675, 2, '2.67'],
             [0.25, 1, '0.2'], [2.5, 0, '2'], [-2.25, 1, '-2.2']];
nodes.clear();
new Function(js + ';globalThis.__pyf = ' + JSON.stringify(PYF)
  + '.map(([x, d]) => DERIVE.pyFixed(x, d));')();
PYF.forEach(([x, d, want], i) => {
  const got = (globalThis.__pyf || [])[i];
  if (got !== want) hollowBad.push(`pyFixed(${x}, ${d}) gave ${got}, Python gives ${want}`);
});
const tk = globalThis.__tick || [];
if (tk[0] !== '' || tk[1] !== '1' || tk[2] !== '')
  hollowBad.push('tick: tickDiff marked ' + JSON.stringify(tk)
    + ', expected nothing, only index 1, and nothing after a layout change');

const s = globalThis.__smoke || {rows: 0, bad: ['the walk never ran']};
s.bad = s.bad.concat(hollowBad);
if (s.bad.length) {
  console.error(`SMOKE FAIL  ${path}: ${s.bad.length} problem(s)`);
  for (const b of s.bad.slice(0, 20)) console.error(`  ${b}`);
  process.exit(1);
}
console.log(`SMOKE OK  ${path} · ${s.rows} rows painted, ${s.tiles} treemap `
  + `tiles drawn, ${s.parity} fields at parity with Python, look-through `
  + `moved under a perturbed fund: ${s.moved}, trigger flag followed a pushed `
  + `price: ${s.flagged}, ${s.linked} flags link to their position, home paints all 7 periods with ${s.needs} needs-you lines matching alert_counts, `
  + `holdings paints ${s.held} names in ${s.holdPainted} period/grouping states, `
  + `period cell followed a moved attribution: ${s.periodMoved}, relative line rebased and gated: ${s.relOk}, `
  + `research draws ${s.research} cards and follows its flags and gaps: ${s.resMoved}, `
  + `risk draws ${s.rrows} contribution rows and ${s.cells} correlation cells, follows a moved share: ${s.riskMoved}, jump box `
  + `reaches every name, ${cases.length} hollowed payloads paint every view clean, no runtime errors`);
