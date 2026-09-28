/* -------------------------------------------------------------- overview */
/* The altitude above the rail. Every number here arrived computed - the
   treemap rectangles included - because the page displays and does not decide.
   See overview.py for the three rules it enforces, all of which are the same
   rule: a position that cannot be measured is excluded and counted, never
   measured as zero. */

const OV = D.overview || {};

// Colour by return since purchase. The four plotted colours were chosen for
// colour-vision deficiency and the palette block says not to hand-tune them,
// so this mixes --pos/--neg into the plane rather than inventing a ramp.
// Saturation saturates at TONE_CAP: past it, more green stops meaning more.
const TONE_CAP = 25;
// A position with no cost basis has no return. Drawn neutral, not green.
const tone = (p) => p == null ? 'var(--surface-2)'
  : `color-mix(in srgb, var(--${p < 0 ? 'neg' : 'pos'}) ${
      Math.round(14 + Math.min(Math.abs(p), TONE_CAP) / TONE_CAP * 52)
    }%, var(--plane))`;

const card = (title, right, body, extra) =>
  `<section class="card ${extra || ''}"><h3><span>${esc(title)}</span>`
  + (right ? `<span class="rt">${right}</span>` : '')
  + `</h3>${body}</section>`;

// A way from a card to the drawer section that holds its full table.
const goLink = (sec, label) =>
  `<button class="golink" data-go="${esc(sec)}">${esc(label)} &rarr;</button>`;

// Which position a flag is about. The key carries the ticker second
// (`trigger-hit:ERIC-B.ST`); failing that, the longest held or watched symbol
// named anywhere in the key or title - the same rule alertsFor matches on, run
// the other way.
function symOfAlert(a) {
  const k = String(a.key || '').split(':')[1];
  if (k && ROWSYM.has(k)) return k;
  const text = String(a.key || '') + ' ' + String(a.title || '');
  let best = null;
  for (const r of ROWS)
    if (text.includes(r.sym) && (!best || r.sym.length > best.length)) best = r.sym;
  return best;
}

const stat = (k, v, s) => `<div class="stat"><div class="k">${esc(k)}</div>
  <div class="v">${v}</div><div class="s">${s || ''}</div></div>`;

// Composition bars, reusing .xrow and its cross-filter attributes so a sector
// clicked here means the same thing as a sector clicked in the data sheet.
const ovbars = (rows, kind, limit) => (rows || []).slice(0, limit).map((r) => {
  const w = Math.max(0, Math.min(100, r.pct || 0));
  return `<div class="xrow" data-fk="${kind}" data-fv="${esc(r.key)}"
    data-fl="${esc(r.label || r.key)}">
    <div class="n" title="${esc(r.label || r.key)}">${esc(r.label || r.key)}</div>
    <div class="t"><i class="f" style="width:${w}%"></i></div>
    <div class="p">${num(r.pct, 1)}%</div></div>`;
}).join('');

// A ranked list with a diverging magnitude bar, scaled to the largest row in
// the card. That is the right scale here because the question is "which of
// these is biggest", not "what share of the whole is this".
const lrows = (rows, get, fmt, note) => {
  if (!rows || !rows.length) return '<div class="lnote">Nothing to show.</div>';
  const max = Math.max(...rows.map((r) => Math.abs(get(r) || 0)), 1e-9);
  return rows.map((r) => {
    const v = get(r) || 0;
    const clickable = r.sym && ROWSYM.has(r.sym);
    return `<div class="lrow ${clickable ? 'click' : ''}"
      ${clickable ? `data-sym="${esc(r.sym)}"` : ''}
      title="${esc(r.name || r.ticker || '')}${note ? ' — ' + note(r) : ''}">
      <div class="t">${esc(r.ticker || r.sym || '—')}</div>
      <div class="track"><span class="mid"></span>
        <i class="${v < 0 ? 'n' : 'p'}" style="width:${
          Math.abs(v) / max * 50}%"></i></div>
      <div class="v ${cls(v)}">${fmt(r)}</div></div>`;
  }).join('');
};

function paintOverview() {
  const t = OV.totals || {}, day = OV.day || {}, alloc = OV.allocation || {};
  const X = D.exposure || {}, con = OV.contributors || {}, mv = OV.movers || {};
  const cal = (D.reporting || {}).calendar || {};
  const conc = X.concentration || {};

  // Three, not four. The fourth was Book value, which was the tape's big number
  // reprinted underneath the tape - the same euros twice on one screen. What it
  // carried that the tape does not (the name count and the cost basis) moved
  // into the P/L subtitle, which is where "against what it cost" belongs.
  $('#ovtop').innerHTML = [
    stat('Total P/L', `<span class="${cls(t.pl_eur)}">${eur(t.pl_eur)}</span>`,
      `${pct(t.pl_pct)} against ${eur(t.cost_eur)} of cost across ${
        OV.n || 0} names`),
    stat('Annualised', t.irr_pct == null ? '—'
      : `<span class="${cls(t.irr_pct)}">${pct(t.irr_pct, 1)}</span>`,
      (t.irr_since ? `money-weighted since ${esc(t.irr_since)}`
                   : esc(t.irr_note || 'not computed'))
      + atBuild('a money-weighted return needs the dated lot cashflows, which '
                + 'are not carried in this page')),
    // The quiet count is the honest part of this stat: it says how much of the
    // book had no previous close and is therefore absent from the move rather
    // than sitting inside it as a zero.
    stat('Today', day.pct == null ? '—'
      : `<span class="${cls(day.pct)}">${pct(day.pct)}</span>`,
      day.pct == null ? 'no position has a previous close'
        : `${eur(day.value_eur)} · ${num(day.covered_pct, 0)}% of the book priced`
          + (day.n_quiet ? ` · ${day.n_quiet} without a close` : '')),
  ].join('');

  // No size class here. Which labels fit is a pixel question and this runs
  // before the box has been laid out; fitTiles answers it afterwards, against
  // the box's real width. See below.
  const tiles = (alloc.tiles || []).map((k) => {
    const clickable = k.sym && ROWSYM.has(k.sym);
    return `<div class="tile" ${clickable
        ? `data-sym="${esc(k.sym)}"` : ''}
      style="left:${k.x}%;top:${k.y}%;width:${k.w}%;height:${k.h}%;
             background:${tone(k.pl_pct)}"
      title="${esc(k.name || k.ticker)} · ${eur(k.value_eur)} · ${
        num(k.weight_pct, 1)}% of book · ${pct(k.pl_pct)} since purchase">
      <div class="tt">${esc(k.ticker)}</div>
      <div class="tw">${num(k.weight_pct, 1)}% · ${pct(k.pl_pct)}</div></div>`;
  }).join('');
  // Sampled from tone() rather than listed, so the key cannot drift from the
  // function the tiles are actually painted with.
  const ramp = Array.from({length: 17}, (_, i) => {
    const f = i / 16;
    return `${tone(-TONE_CAP + f * 2 * TONE_CAP)} ${(f * 100).toFixed(1)}%`;
  }).join(',');

  const cards = [];

  // An empty treemap used to render as a bare grey rectangle, which reads as a
  // chart that failed rather than a book with nothing in it. The key goes with
  // it: there is no colour scale to explain when there is nothing coloured.
  cards.push(card('Allocation', `${alloc.n || 0} positions`,
    tiles
      ? `<div class="tmap">${tiles}</div>
     <div class="tmapkey"><span>Area is weight, colour is return since
       purchase</span><span>−${TONE_CAP}%</span><span class="ramp"
       style="background:linear-gradient(90deg,${ramp})"></span
       ><span>+${TONE_CAP}%</span>
       ${alloc.n_undrawn ? `<span>${alloc.n_undrawn} position${
         alloc.n_undrawn === 1 ? '' : 's'} not drawn</span>` : ''}</div>`
      : `<div class="tmap empty">Nothing to draw${alloc.n_undrawn
          ? `: ${alloc.n_undrawn} position${alloc.n_undrawn === 1 ? '' : 's'}
             carry no market value` : '. No position carries a market value'}
         .</div>`,
    'ov-8'));

  // Beside the treemap, not below it. The picture shows how the book is spread
  // and these four numbers say how spread that actually is - read together or
  // not at all. Flags follows because an exception is worth more than a
  // breakdown, and it used to sit last, alone, under the calendar.
  cards.push(card('Concentration', `${conc.n || 0} names`,
    `<dl class="kv">
      <dt>Largest position</dt><dd>${num(conc.top1_pct, 1)}%</dd>
      <dt>Top five</dt><dd>${num(conc.top5_pct, 1)}%</dd>
      <dt>Top ten</dt><dd>${num(conc.top10_pct, 1)}%</dd>
      <dt>Effective positions</dt><dd>${num(conc.effective_n, 1)}</dd>
    </dl>
    <div class="lnote">Effective positions is 1/HHI: the number of equally
      sized holdings that would concentrate the book as much as this one is.
      ${num(conc.effective_n, 1)} against ${conc.n || 0} held.</div>`
    + goLink('exp', 'Full exposure breakdown')));

  const flags = (D.alerts || []);
  cards.push(card('Flags', `${flags.length}`,
    flags.length
      ? flags.slice(0, 8).map((a) => {
          // A flag names a position; clicking it opens that position. A flag
          // about the whole book (coverage, health) has no chart to open and
          // stays plain text rather than a link that goes nowhere.
          const s = symOfAlert(a);
          return `<div class="alert${s ? ' click' : ''}"${
            s ? ` data-sym="${esc(s)}"` : ''}>
          <span class="dot" style="background:${
            LEVEL[a.level] || 'var(--muted)'}"></span>
          <span><div class="t">${esc(a.title)}</div>
          <div class="d" title="${esc(a.detail)}">${esc(a.detail)}</div>
          </span></div>`;
        }).join('')
        + goLink('flag', flags.length > 8
          ? `All ${flags.length} flags (${flags.length - 8} more)` : 'All flags')
      : '<div class="lnote">Nothing tripped a threshold.</div>'));

  cards.push(card('What made the money',
    con.n_unknown ? `${con.n_known} of ${con.n_known + con.n_unknown} priced`
                  : `${con.n_known} positions`,
    lrows((con.best || []).concat(con.worst || []), (r) => r.pl_eur,
      (r) => eur(r.pl_eur), (r) => `${num(r.share_pct, 1)}% of gross movement`)
    + `<div class="lnote">Attributed in euros, not percent. A 60% gain on the
       smallest position is a rounding error; 12% on the largest one is the
       year.${con.n_unknown ? ` ${con.n_unknown} position${
         con.n_unknown === 1 ? ' has' : 's have'} no cost basis and cannot be
       attributed.` : ''}</div>`));

  // "Today's movers", not "Today" - the headline stat two rows above is
  // already called Today and is the book's single day number. Two things on
  // one screen under one word, meaning different things.
  cards.push(card("Today's movers", mv.n_quiet ? `${mv.n_priced} priced, ${
      mv.n_quiet} quiet` : `${mv.n_priced} priced`,
    lrows((mv.up || []).concat(mv.down || []), (r) => r.day_pct,
      (r) => pct(r.day_pct), (r) => eur(r.day_eur))));

  cards.push(card('Sector', X.sectors
      ? `${num(X.sectors.resolved_pct, 0)}% resolved` : '',
    ovbars((X.sectors || {}).rows, 'sector', 8)
    + `<div class="lnote">Look-through: a fund's sleeve is spread across its
       disclosed constituents. Yahoo publishes ten per fund, so this names
       ${num((X.sectors || {}).resolved_pct, 0)}% of the book.</div>`,
    'ov-6'));

  cards.push(card('Geography', X.geography
      ? `${num(X.geography.resolved_pct, 0)}% resolved` : '',
    ovbars((X.geography || {}).rows, 'country', 8),
    'ov-6'));

  // The legend is derived from the pills actually rendered, not from cal.rows.
  // The strip is capped at twelve, and a legend naming a year that only appears
  // in row thirteen would be describing something nobody can see.
  const shown = (cal.rows || []).slice(0, 12);
  const years = [...new Set(shown.map((r) => String(r.date).slice(0, 4)))].sort();
  cards.push(card('Next prints', cal.n
      ? `${cal.n} in ${cal.horizon_days} days · ${num(cal.pct_ahead, 0)}% of book`
      : 'none scheduled',
    (shown.length
      ? `<div class="cstrip">${shown.map((r) =>
          `<div class="cpill ${r.soon ? 'soon' : ''}${
               ROWSYM.has(r.symbol) ? ' click" data-sym="' + esc(r.symbol) : ''}"
             title="${esc(r.name || '')} · ${esc(String(r.date))}${
               r.estimated ? ' (estimated by Yahoo, not confirmed by the company)'
                           : ''}">
            <div class="d">${esc(String(r.date).slice(5))}${
              r.estimated ? ' ~' : ''}</div>
            <div class="t">${esc(r.symbol)}</div>
            <div class="w">${num(r.weight_pct, 1)}%</div></div>`).join('')}</div>`
        // The pills are MM-DD, so the year has to be stated once or a date in
        // January is ambiguous inside a horizon that crosses one. And a tilde
        // that nothing explains is just a typo the reader has to forgive.
        + `<div class="lnote">Dates are ${esc(years.join('–'))}, shown as
           month-day.${shown.some((r) => r.estimated)
            ? ' A ~ marks a date Yahoo estimated rather than one the company has'
              + ' confirmed.' : ''}${shown.length < (cal.rows || []).length
            ? ` ${(cal.rows || []).length - shown.length} further date${
                (cal.rows || []).length - shown.length === 1 ? '' : 's'} in the
              horizon are not drawn.` : ''}</div>`
      : '<div class="lnote">No dated results in the horizon.</div>')
    + (cal.n_unknown ? `<div class="lnote">${cal.n_unknown} stock${
        cal.n_unknown === 1 ? ' has' : 's have'} no date from Yahoo. A missing
        date is missing, not "nothing due".</div>` : ''),
    'ov-12'));

  $('#ovgrid').innerHTML = cards.join('');
  watchTiles($('#ovgrid').querySelector('.tmap'));
}

// Decide which tile labels fit, in pixels, against the box as it was actually
// laid out. This used to be decided at build time from the tile's percentage
// of the treemap - but a percentage is not a size. The same 4.5%-wide tile is
// 54px across in a 1210px box and 33px in a 728px one, and the build-time rule
// gave both of them the same label because it could only see the 4.5.
//
// Nothing here is a chosen threshold: a hidden probe tile carrying the longest
// label a real tile could carry is measured through the live CSS, so the
// numbers come from the type scale rather than from an estimate of it.
function fitTiles(box) {
  const tiles = box ? [...box.querySelectorAll('.tile')] : [];
  if (!tiles.length || !box.clientWidth || !box.clientHeight) return;

  const probe = document.createElement('div');
  probe.className = 'tile';
  probe.style.cssText = 'visibility:hidden;left:0;top:0;width:auto;height:auto';
  probe.innerHTML = '<div class="tt">MMMM</div>'
    + '<div class="tw">88.8% · −88.8%</div>';
  box.appendChild(probe);
  const hBoth = probe.offsetHeight, wBoth = probe.offsetWidth;
  probe.querySelector('.tw').remove();
  const hOne = probe.offsetHeight, wOne = probe.offsetWidth;
  probe.remove();

  for (const t of tiles) {
    const w = t.offsetWidth, h = t.offsetHeight;
    const one = h < hBoth || w < wBoth;   // no room for the weight line
    const none = h < hOne || w < wOne;    // no room for the ticker either
    t.classList.toggle('sm', one && !none);
    t.classList.toggle('xs', none);
  }
}

// Measure now, and again on every resize. Now, because a ResizeObserver's
// first delivery is a frame away and frames are throttled in a background tab
// - the same trap paintChart documents, and it bites here too: observed with
// the box at 880x377, the initial callback never arrived and every tile kept
// the full label it had no room for. The observer is for what happens after.
let TILEOBS = null;
function watchTiles(box) {
  if (TILEOBS) { TILEOBS.disconnect(); TILEOBS = null; }
  if (!box) return;
  fitTiles(box);
  if (typeof ResizeObserver === 'undefined') return;
  TILEOBS = new ResizeObserver(() => fitTiles(box));
  TILEOBS.observe(box);
}

