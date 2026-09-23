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
  globalThis.__smoke = {rows: ROWS.length, tiles: drawn, bad: bad,
                        parity: PARITY.checked, moved: moved, flagged: flagged,
                        linked: linked};
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
  + `price: ${s.flagged}, ${s.linked} flags link to their position, jump box `
  + `reaches every name, no runtime errors`);
