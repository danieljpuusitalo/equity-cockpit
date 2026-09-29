
// History ships columnar (render.pack_history) because two years of bars as
// row arrays were two thirds of the page. Unpacked once, here, back into the
// {fetched, bars:[[date,o,h,l,c]]} shape everything below was written against,
// before anything reads it. Dates are rebuilt in UTC so a day gap never meets a
// DST boundary.
(function unpackHistory() {
  const H = D.history || {};
  for (const sym of Object.keys(H)) {
    const s = H[sym];
    if (!s || !Array.isArray(s.dd)) continue;
    const rows = [];
    let t = s.d0 ? Date.parse(s.d0 + 'T00:00:00Z') : NaN;
    for (let i = 0; i < s.dd.length && t === t; i++) {
      t += s.dd[i] * 86400000;
      rows.push([new Date(t).toISOString().slice(0, 10), s.o[i], s.h[i], s.l[i], s.c[i]]);
    }
    H[sym] = {fetched: s.fetched, bars: rows};
  }
})();

/* Everything below displays; nothing decides. Any number you see was computed
   in Python and is in the payload - if a figure is wrong, fix analyse.py. */

const $  = (s) => document.querySelector(s);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
// The sign goes before the symbol: toLocaleString on a negative printed
// "€-58". A loss that rounds to nothing carries no sign.
const eur = (n) => n == null ? '—' : (Math.round(n) < 0 ? '-' : '') + '€'
  + Math.abs(Number(n)).toLocaleString('en-GB', {maximumFractionDigits:0});
// A euro CHANGE - P/L, attribution, a delta - says which way in both
// directions, the same as pct does. A level (value, cost) never takes a +.
const eurs = (n) => n == null ? '—' : (Math.round(n) > 0 ? '+' : '') + eur(n);
// A share of the book to one place, from the euros rather than from the
// two-place weight_pct beside them: 17.95178 stored as 17.95 and rounded
// again printed 17.9 next to the holdings table's 18.0 for the same line.
const bookPct = (o) => {
  const t = (D.totals || {}).value_eur;
  return num(o.value_eur != null && t > 0 ? o.value_eur / t * 100 : o.weight_pct, 1);
};
const px  = (n) => n == null ? '—' : Number(n).toLocaleString('en-GB',
  {minimumFractionDigits:2, maximumFractionDigits:2});
const pct = (n, dp) => n == null ? '—' :
  (n > 0 ? '+' : '') + Number(n).toFixed(dp == null ? 2 : dp) + '%';
const cls = (n) => n == null ? '' : (n > 0 ? 'up-t' : n < 0 ? 'dn-t' : '');
const num = (n, dp) => n == null ? '—' : Number(n).toFixed(dp == null ? 2 : dp);
// Share counts. Whole lots print whole - a holding of 240 was rendering as the
// raw float "240" beside one that summed to "83.33333333333333", which is a
// float artefact of adding lots together, not a number anybody holds. Grouped,
// and cut at four places because fractional-share brokers do not quote more.
const qty = (n) => n == null ? '—' : Number(n).toLocaleString('en-GB',
  {maximumFractionDigits:4});
// The analyser writes gaps as lowercase fragments ("no thesis on the Equity
// Log") because they are also read mid-sentence in Telegram. Here they start a
// sentence, so they get a capital - in the page, not in the payload.
const cap = (s) => !s ? '' : String(s).charAt(0).toUpperCase() + String(s).slice(1);
// Market cap in the quote currency, at the magnitude a human reads. 442bn, not
// 442,100,482,048 - the digits past the third are noise on a figure that moves
// by a percent a day.
const big = (n) => {
  if (n == null) return '—';
  const a = Math.abs(n);
  if (a >= 1e12) return (n / 1e12).toFixed(2) + 'tn';
  if (a >= 1e9)  return (n / 1e9).toFixed(1) + 'bn';
  if (a >= 1e6)  return (n / 1e6).toFixed(0) + 'm';
  return Number(n).toLocaleString('en-GB', {maximumFractionDigits:0});
};
// Where a bounded reading sits in its band, with the two conventional lines
// drawn faintly behind it. lo/hi are in the same units as v.
const meter = (v, lo, hi, marks) => {
  if (v == null) return '';
  const at = (x) => Math.max(0, Math.min(100, ((x - lo) / (hi - lo)) * 100));
  return `<span class="meter">${(marks || []).map(
    (m) => `<u style="left:${at(m).toFixed(1)}%"></u>`).join('')
  }<i style="left:${at(v).toFixed(1)}%"></i></span>`;
};
const LEVEL = {critical:'var(--crit)', warning:'var(--warn)',
               info:'var(--muted)', good:'var(--good)'};

/* ---------------------------------------------------------------- model */

// Holdings are per ISIN per account, so the same symbol can appear twice. The
// rail is a list of companies, not of custody rows - fold them together first.
const held = new Map();

// What the last live-price attempt did. `null` means no attempt has been made
// or none applies - opened from disk, for instance - and the chip stays hidden
// rather than claiming anything. Every other state, including failure, is
// recorded and shown, because a page that tried and failed must not look
// identical to one that never tried.
let LIVE = null;  // {at:Date, priced, asked, missing:[], fxMissing:[], error}

function liveChip() {
  if (!LIVE) {
    // Opened from disk the live layer never starts, and an empty chip let a
    // snapshot pass for a page that was simply between ticks.
    const web = typeof location !== 'undefined'
      && (location.protocol === 'http:' || location.protocol === 'https:');
    const built = String(D.generated || '').replace('T', ' ').slice(0, 16);
    return web
      ? 'Live <b title="waiting for the first price refresh">connecting</b>'
      : `Snapshot <b class="dn-t" title="opened from a file, so prices never `
        + `refresh here - every figure is as built at ${esc(built)}. The `
        + `deployed copy is the live one.">not live</b>`;
  }
  if (LIVE.error && LIVE.carried) {
    const was = LIVE.at.toTimeString().slice(0, 5);
    return `Live <b class="dn-t" title="${esc(LIVE.error)} · still showing the `
      + `prices that landed at ${was}, the last refresh that worked">held ${was}</b>`;
  }
  if (LIVE.error) {
    return `Live <b class="dn-t" title="${esc(LIVE.error)} · showing the prices `
      + `this file was built with">off</b>`;
  }
  const hhmm = LIVE.at.toTimeString().slice(0, 5);
  const n = (LIVE.missing || []).length;
  // The count of what did NOT come back is part of the headline, not a detail
  // in a tooltip. `40 priced` and `40 priced, 4 unpriced` are different claims
  // about the same total.
  const short = n
    ? ` <b class="dn-t" title="${esc(LIVE.missing.join(', '))} · these keep `
      + `their build-time price">${n} unpriced</b>`
    : '';
  return `Live <b title="${LIVE.priced}/${LIVE.asked} priced from Yahoo at `
    + `${esc(LIVE.at.toString())}">${hhmm}</b>${short}`;
}

// Marks a figure that the live layer deliberately does NOT recompute, and says
// why on hover. Silent about it when nothing is live, because then every number
// on the page is a build-time number and singling three of them out would imply
// the rest are something else.
//
// This is the honest half of going live. Once part of a page updates, the
// reader reasonably assumes all of it does; the figures that cannot follow have
// to say so themselves, or they become the most misleading numbers on screen
// precisely because everything around them is fresh.
// The look-through is linear in position value, so it follows a price - but
// only when the page carries each fund's published composition
// (D.lookthrough). A page built without it still says "as at build" on those
// breakdowns; claiming them live without the weights would be the bug this
// whole module was written to remove.
const LOOKTHRU_WHY = 'the look-through scales each fund by its published '
  + 'composition, and that composition is not carried in this page - so the '
  + 'breakdown moves when the file is rebuilt, not when a price ticks';

const atBuild = (why) => (LIVE && (!LIVE.error || LIVE.carried))
  ? ` · <b class="dn-t" title="${esc(why)} · this figure is as at ${
      esc(D.generated || 'the last build')}, not live">as at build</b>`
  : '';
// Keyed on whether the recompute actually ran, not on whether the key exists:
// STATS is what all() wrote, so a look-through that was skipped keeps its mark.
const lookMark = () => {
  const s = DERIVE.stats();
  return s && s.lookthrough ? '' : atBuild(LOOKTHRU_WHY);
};

// Freshness, per number rather than per page.
//
// The tape already says whether the live layer is working, and it says it once,
// at the top. That is the wrong altitude: whether a price is current is a fact
// about that price, and the reader is looking at the price, not at the tape.
// Four states, and the distinction that earns its keep is `build` against
// `stale`:
//
//   live      this tick's quote landed for this symbol
//   build     nobody has asked yet, or this symbol is not one the live layer
//             can ask about at all - no Yahoo mapping, or mapped to MISSING
//   stale     it WAS asked, and nothing usable came back; the build's price is
//             still on screen
//   unpriced  there is no price at all
//
// `build` and `stale` look identical - the same number, from the same moment -
// and mean opposite things. One is "nothing has asked", the other is "something
// asked and was refused". Collapsing them is this repo's own bug class in its
// price-shaped form: absent is not zero, and not-asked is not refused.
const LIVEASK = new Set();   // symbols the live layer puts to the vendor
const LIVEMISS = new Set();  // of those, the ones it got nothing usable for

function freshnessOf(price, wasStale, sym) {
  if (price == null) return 'unpriced';
  // A failed tick after a good one leaves the good one's prices on screen -
  // D was restated from them and nothing puts the build's back. `carried`
  // says so, and those prices keep reading `live` at the time they landed,
  // not `build`: the mark has to describe the number beside it.
  if (!LIVE || (LIVE.error && !LIVE.carried) || !LIVEASK.has(sym)) {
    return wasStale ? 'stale' : 'build';
  }
  return LIVEMISS.has(sym) ? 'stale' : 'live';
}

// The glyph lives in a slot that is reserved whether or not there is anything
// to put in it, so the page does not reflow the instant quotes land - a column
// that shifts sideways when it updates is how a reader learns to stop trusting
// where a number is.
const FRESH = {
  live: ['●', 'fr-live', 'Priced live'],
  // Deliberately says what is true rather than why. `build` covers three
  // different causes - nothing has ticked yet, the whole live layer is off, or
  // this symbol is one it cannot ask about - and the mark cannot tell them
  // apart from where it sits. The tape carries the why; the mark carries the
  // age, which is the part that belongs next to the number.
  build: ['·', 'fr-build', 'As at the build - no live price has replaced '
    + 'this one'],
  stale: ['○', 'fr-stale', 'Asked, and nothing usable came back - this is '
    + 'still the build-time price'],
  unpriced: ['', 'fr-none', 'No price'],
};

// The last candle, brought forward to the live price.
//
// Yahoo's daily series already carries TODAY as a partial bar - measured, every
// symbol in the book had a bar dated today whose close equalled the build-time
// price. So the chart was not missing a bar; it was drawing a real one that
// stopped moving at 07:40 while every number beside it went on ticking. A
// candle is the most price-shaped thing on the page, and it was the one thing
// the live layer did not reach.
//
// Held in its own map rather than written into `D.history`, for two reasons.
// `D.history` is what Python wrote and what `D.indicators` was computed from,
// and this repo's rule is that a live figure never overwrites a recorded one.
// And the merge has to be repeatable: every tick re-derives the bar from the
// cached one, so a quote that comes back lower cannot leave a high behind that
// no trade ever made.
const LIVEBAR = new Map();  // sym -> [date, open, high, low, close]

// The exchange's trading date for a quote, from Yahoo's own timestamp rather
// than from this machine's clock - `new Date()` on a page left open overnight
// would roll the date while the quote it is labelling did not.
//
// Local time is the right frame for this book: every holding lists in Europe or
// the US, and no US session crosses midnight in a European timezone. A listing
// in Asia would need the exchange's own zone, which is not in the payload - so
// if one is ever added, this is the line that has to change rather than quietly
// mislabel a bar.
function quoteDay(asOf) {
  if (!(asOf > 0)) return null;
  const d = new Date(asOf * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${
    String(d.getDate()).padStart(2, '0')}`;
}

// Merge a quote into the tail of the cached series. Never mutates `bars`.
function noteLiveBar(sym, hit) {
  const series = (D.history || {})[sym];
  const bars = series && series.bars;
  if (!bars || !bars.length || !hit || !(hit.price > 0)) return;
  const day = quoteDay(hit.asOf);
  if (!day) return;
  const last = bars[bars.length - 1];

  // The cache is AHEAD of the quote. Happens on a holiday or a halted listing,
  // where Yahoo keeps answering with the last session's price. Drawing that
  // price onto today would invent a session that did not happen, and rewriting
  // the earlier bar would be a live figure overwriting a recorded one. Do
  // neither: drop the live bar and let the cached series stand.
  if (day < last[0]) { LIVEBAR.delete(sym); return; }

  if (day === last[0]) {
    // Yahoo's own bar for today, carried forward. Open is left exactly as the
    // vendor recorded it - it is the opening print and no quote can improve on
    // it - and the range is only ever WIDENED. The true high is at least the
    // recorded high and at least the price now; the same in reverse for the
    // low. Both are floors, which is the honest direction for a bar that has
    // not finished forming.
    LIVEBAR.set(sym, [day, last[1], Math.max(last[2], hit.price),
                      Math.min(last[3], hit.price), hit.price]);
    return;
  }

  // A session the cache has never seen - the page was built before the open,
  // or has been left running across a date boundary. `session` is the endpoint's
  // aggregate of the five-minute closes, so its high and low are floors and its
  // open is the first five-minute close rather than the opening auction. With
  // nothing to draw a range from, the bar is flat at the price: a bar that says
  // "no range known yet" rather than one that invents one.
  const s = hit.session;
  const o = s && s.open > 0 ? s.open : hit.price;
  const hi = s && s.high > 0 ? Math.max(s.high, hit.price) : Math.max(o, hit.price);
  const lo = s && s.low > 0 ? Math.min(s.low, hit.price) : Math.min(o, hit.price);
  LIVEBAR.set(sym, [day, o, hi, lo, hit.price]);
}

// The cached series with the live bar merged in, or the cached series itself.
// Gated on the row's OWN freshness, which is the same value the mark beside the
// price is drawn from - so the candle and the mark cannot disagree about
// whether this symbol is live. That matters on the tick after a failure: LIVE
// carries an error, every mark falls back to `as at build`, and without this
// gate the chart would still be showing a candle that moved.
function barsFor(r) {
  const series = (D.history || {})[r.sym];
  const bars = series && series.bars ? series.bars : null;
  if (!bars || !bars.length) return null;
  const lb = r.freshness === 'live' ? LIVEBAR.get(r.sym) : null;
  if (!lb) return bars;
  const last = bars[bars.length - 1];
  // The volume column is deliberately not carried onto the live bar: no quote
  // in this response reports volume, and repeating the cached day's figure
  // beside a moved price would be a stale number wearing a live one's clothes.
  return lb[0] === last[0]
    ? bars.slice(0, -1).concat([lb])
    : bars.concat([lb]);
}

function fresh(f) {
  const m = FRESH[f] || FRESH.unpriced;
  const when = f === 'live' && LIVE && LIVE.at
    ? ' at ' + LIVE.at.toTimeString().slice(0, 5)
      + (LIVE.carried ? ' - the refresh after that failed' : '')
    : f === 'build' || f === 'stale' ? ' (' + esc(D.generated || 'last build') + ')' : '';
  return `<i class="fr ${m[1]}" aria-label="${esc(m[2] + when)}"
    title="${esc(m[2] + when)}">${m[0]}</i>`;
}

