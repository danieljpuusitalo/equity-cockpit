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
  globalThis.__smoke = {rows: ROWS.length, tiles: drawn, bad: bad,
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

const s = globalThis.__smoke || {rows: 0, bad: ['the walk never ran']};
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
  + `period cell followed a moved attribution: ${s.periodMoved}, relative line rebased and gated: ${s.relOk}, jump box `
  + `reaches every name, no runtime errors`);
