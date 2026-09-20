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
if (!html.includes('<script id="app">')) {
  console.error(`SMOKE FAIL  ${path}: no <script id="app"> block found`);
  process.exit(1);
}
const js = html.split('<script id="app">')[1].split('</script>')[0];

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
  globalThis.__smoke = {rows: ROWS.length, bad: bad};
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
console.log(`SMOKE OK  ${path} · ${s.rows} rows painted, no runtime errors`);
