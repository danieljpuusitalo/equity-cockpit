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
    closest: () => null, value: '',
    getBoundingClientRect: () => ({ width: 10, height: 10 }),
  };
  node.parentNode = { insertBefore() {}, appendChild() {} };
  return node;
};

globalThis.document = {
  querySelector: el, querySelectorAll: () => [],
  createElementNS: el, createElement: el, body: el(), documentElement: el(),
};
globalThis.window = globalThis;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.addEventListener = () => {};
globalThis.innerWidth = 1200;
globalThis.innerHeight = 800;

try {
  new Function(js)();
  console.log(`SMOKE OK  ${path} executed with no runtime errors`);
} catch (e) {
  console.error(`SMOKE FAIL  ${path}: ${e.message}`);
  process.exit(1);
}
