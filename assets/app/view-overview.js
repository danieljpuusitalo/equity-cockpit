/* ------------------------------------------------------------ risk (view 4) */
/* Routed and stored as 'overview' so old links and the guards that name its
   containers still hold; on screen it is Risk, because Home is the overview. */
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

// What a Yahoo symbol is called on screen. The risk block is keyed by symbol,
// the rail by label; reading the label off ROWS keeps the two spelled alike.
const labOf = (s) => { const r = ROWS.find((x) => x.sym === s); return r ? r.label : s; };

// Correlation shade. Not --pos/--neg: a correlation is not a gain or a loss,
// and green for "moves together" would say it is good news. Positive mixes the
// accent into the plane, negative the muted ink; strength is the mix.
const ctone = (c) => c == null ? 'var(--surface-2)'
  : `color-mix(in srgb, var(--${c < 0 ? 'muted' : 'accent'}) ${
      Math.round(Math.min(Math.abs(c), 1) * 80)}%, var(--plane))`;

// The beta the headline quotes. 1Y first because that is the horizon the rest
// of this view is measured over; failing that, the longest period that has
// one. Returns the period key with the figures so the stat can say which.
function betaPeriod() {
  const P = PERF.periods || {};
  const keys = ['1Y'].concat(PERIODS.map((p) => p[0]).reverse());
  const k = keys.find((x) => P[x] && P[x].beta != null);
  return k ? {k, p: P[k]} : null;
}

// Risk contribution per name, against its weight. Two bars on one scale so the
// question the card exists for reads at a glance: does this name carry more of
// the book's movement than of its money. A name the estimate could not reach
// is listed as "not estimated", never drawn as a zero-width bar.
function riskHtml() {
  const R = PERF.risk || {};
  const rows = (R.contribution || []).slice()
    .sort((a, b) => (b.rc_pct == null) - (a.rc_pct == null)
      || (b.rc_pct || 0) - (a.rc_pct || 0));
  if (!rows.length && !(R.excluded || []).length)
    return '<div class="lnote">No risk estimate in this build: the curve has no'
      + ' priced history to measure.</div>';
  const max = Math.max(1e-9, ...rows.map((r) => Math.max(r.rc_pct || 0, r.weight_pct || 0)));
  const bar = (v, c) => `<i class="${c}" style="width:${
    Math.max(0, v || 0) / max * 100}%"></i>`;
  const lines = rows.map((r) => {
    const clickable = ROWSYM.has(r.symbol);
    return `<div class="rrow${clickable ? ' click' : ''}"${
        clickable ? ` data-sym="${esc(r.symbol)}"` : ''}
      title="${esc(labOf(r.symbol))} · ${num(r.weight_pct, 1)}% of the weight measured · ${
        r.rc_pct == null ? 'risk not estimated' : num(r.rc_pct, 1) + '% of book risk'} · ${
        num(r.vol_pct, 1)}% vol">
      <div class="t">${esc(labOf(r.symbol))}</div>
      <div class="rb">${bar(r.weight_pct, 'w')}${bar(r.rc_pct, 'r')}</div>
      <div class="v">${r.rc_pct == null ? '<span class="na">not estimated</span>'
        : num(r.rc_pct, 1) + '%'}</div></div>`;
  }).join('');
  const measured = new Set((R.symbols || []).concat((R.excluded || []).map((x) => x.symbol)));
  const outside = ROWS.filter((r) => r.isHeld && !measured.has(r.sym)).map((r) => r.label);
  const short = (R.excluded || []).map((x) => `${esc(labOf(x.symbol))} (${x.n_obs} days)`);
  return lines
    + `<div class="rkey"><span><i class="w"></i>share of weight</span>
       <span><i class="r"></i>share of risk</span></div>`
    + `<div class="lnote">Each name's share of the book's variance over the last
       ${R.window_days || 0} trading days, from daily closes at build. A share
       above the weight means the name moves the book more than its size says.
       Measured on ${num(R.weight_covered_pct, 0)}% of the book.${short.length
         ? ` Not estimated, too short a history: ${short.join(', ')}.` : ''}${
       outside.length ? ` ${outside.length} held name${outside.length === 1 ? ' is'
         : 's are'} not in the curve and not measured: ${esc(outside.join(', '))}.` : ''}
       ${atBuild('risk is estimated from the daily closes at build, and a live tick'
         + ' does not restate it')}</div>`;
}

// The matrix as the payload has it, in its own order (largest position
// first), so the top-left corner is where the money is. A pair with too little
// shared history arrives as null and is drawn blank, not as zero correlation.
function corrHtml() {
  const R = PERF.risk || {}, S = R.symbols || [], C = R.corr || [];
  if (S.length < 2) return '<div class="lnote">Fewer than two names measured; '
    + 'there is no pair to correlate.</div>';
  const head = S.map((s) => `<span class="cl" title="${esc(labOf(s))}">${
    esc(labOf(s))}</span>`).join('');
  const body = S.map((a, i) => {
    const clickable = ROWSYM.has(a);
    return `<span class="rl${clickable ? ' click' : ''}"${
        clickable ? ` data-sym="${esc(a)}"` : ''}>${esc(labOf(a))}</span>`
      + S.map((b, j) => {
        const c = (C[i] || [])[j];
        return i === j ? '<i class="dg"></i>'
          : `<i style="background:${ctone(c)}" title="${esc(labOf(a))} × ${
              esc(labOf(b))} · ${c == null ? 'not enough shared history' : num(c, 2)}"></i>`;
      }).join('');
  }).join('');
  const ramp = Array.from({length: 9}, (_, i) => {
    const f = i / 8;
    return `${ctone(-1 + 2 * f)} ${(f * 100).toFixed(1)}%`;
  }).join(',');
  return `<div class="corr" style="grid-template-columns:auto repeat(${S.length},minmax(0,1fr))">
      <span></span>${head}${body}</div>
    <div class="tmapkey"><span>Daily-return correlation, ${R.window_days || 0} days</span>
      <span>−1</span><span class="ramp" style="background:linear-gradient(90deg,${ramp})"></span
      ><span>+1</span></div>`;
}

function paintOverview() {
  const alloc = OV.allocation || {};
  const X = D.exposure || {}, con = OV.contributors || {};
  const conc = X.concentration || {}, fees = X.fees || {}, lap = X.overlap || {};
  const R = PERF.risk || {}, B = D.performance && D.performance.benchmark;
  const lc = PERF.listing_currency || {};
  const bp = betaPeriod();

  // The risk headline. Performance lives on Home; this band answers the other
  // question - how much the book moves, with what, and what it costs to hold.
  $('#ovtop').innerHTML = [
    stat('Volatility', R.book_vol_pct == null ? '—' : `${num(R.book_vol_pct, 1)}%`,
      R.book_vol_pct == null ? 'not estimated: no priced history in the window'
        : `annualised, last ${R.window_days} trading days · ${
            num(R.weight_covered_pct, 0)}% of the book measured`),
    stat('Beta to ACWI', bp ? num(bp.p.beta, 2) : '—',
      bp ? `correlation ${num(bp.p.corr, 2)} · over ${esc(bp.k)}`
        : (B && B.absent ? 'no benchmark in this build' : 'not estimated')),
    stat('Effective positions', num(conc.effective_n, 1),
      `of ${conc.n || 0} held · the largest is ${num(conc.top1_pct, 1)}% of the book`),
    stat('Fee drag', fees.annual_eur == null ? '—' : `${eur(fees.annual_eur)}/yr`,
      fees.annual_eur == null ? 'no fund in the book publishes a TER'
        : `${num(fees.book_ter_pct, 2)}% of the book a year · ${
            num(fees.resolved_pct, 0)}% of fund value has a published TER`),
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
  // and these numbers say how spread that actually is - read together or not
  // at all.
  cards.push(card('Concentration', `${conc.n || 0} names`,
    `<dl class="kv">
      <dt>Largest position</dt><dd>${num(conc.top1_pct, 1)}%</dd>
      <dt>Top five</dt><dd>${num(conc.top5_pct, 1)}%</dd>
      <dt>Top ten</dt><dd>${num(conc.top10_pct, 1)}%</dd>
      <dt>HHI</dt><dd>${num(conc.hhi, 3)}</dd>
      <dt>Effective positions</dt><dd>${num(conc.effective_n, 1)}</dd>
    </dl>
    <div class="lnote">Effective positions is 1/HHI: the number of equally
      sized holdings that would concentrate the book as much as this one is.
      ${num(conc.effective_n, 1)} against ${conc.n || 0} held.</div>`
    + goLink('exp', 'Full exposure breakdown')));

  cards.push(card('Correlation', `${(R.symbols || []).length} names`, corrHtml(), 'ov-6'));
  cards.push(card('Risk contribution', R.book_vol_pct == null ? ''
    : `book vol ${num(R.book_vol_pct, 1)}%`, riskHtml(), 'ov-6'));

  // Return beside risk: where the money came from, against where the movement
  // comes from in the card above.
  cards.push(card('What made the money',
    con.n_unknown ? `${con.n_known} of ${con.n_known + con.n_unknown} priced`
                  : `${con.n_known || 0} positions`,
    lrows((con.best || []).concat(con.worst || []), (r) => r.pl_eur,
      (r) => eur(r.pl_eur), (r) => `${num(r.share_pct, 1)}% of gross movement`)
    + `<div class="lnote">Attributed in euros, not percent. A 60% gain on the
       smallest position is a rounding error; 12% on the largest one is the
       year.${con.n_unknown ? ` ${con.n_unknown} position${
         con.n_unknown === 1 ? ' has' : 's have'} no cost basis and cannot be
       attributed.` : ''}</div>`));

  // Listing currency, and it says so. It is the currency the line is quoted
  // in, which is not what the businesses earn in - a US fund listed in Amsterdam
  // is euros here and dollars underneath. Geography is the underlying.
  cards.push(card('Currency', `${(lc.rows || []).length} listed`,
    ((lc.rows || []).length
      ? lc.rows.map((r) => `<div class="xrow un"><div class="n">${esc(r.ccy)}</div>
          <div class="t"><i class="f" style="width:${Math.max(0, Math.min(100, r.pct || 0))}%"></i></div>
          <div class="p">${num(r.pct, 1)}%</div></div>`).join('')
      : '<div class="lnote">No valued position to group.</div>')
    + `<div class="lnote">The currency each line is listed in, not what the
       businesses earn in: a fund quoted in euros can hold dollars underneath.
       Geography is the look-through.${lc.n_unvalued ? ` ${lc.n_unvalued}
       position${lc.n_unvalued === 1 ? ' has' : 's have'} no value and ${
         lc.n_unvalued === 1 ? 'is' : 'are'} not counted.` : ''}</div>`));

  const frows = (fees.rows || []).filter((r) => r.annual_eur != null)
    .sort((a, b) => b.annual_eur - a.annual_eur).slice(0, 4);
  const nNoTer = (fees.rows || []).filter((r) => r.ter_pct == null).length;
  cards.push(card('Fees', fees.annual_eur == null ? '' : `${eur(fees.annual_eur)}/yr`,
    `<dl class="kv">
      <dt>Of the book</dt><dd>${num(fees.book_ter_pct, 3)}%</dd>
      <dt>Of the fund sleeve</dt><dd>${num(fees.sleeve_ter_pct, 3)}%</dd>
      <dt>TER published for</dt><dd>${num(fees.resolved_pct, 0)}% of fund value</dd>
    </dl>`
    + (frows.length ? `<div class="lnote">Largest drags:</div>` + frows.map((r) => {
        const clickable = ROWSYM.has(r.symbol);
        return `<div class="lrow${clickable ? ' click' : ''}"${
            clickable ? ` data-sym="${esc(r.symbol)}"` : ''} title="${esc(r.name || r.symbol)}">
          <div class="t">${esc(labOf(r.symbol))}</div>
          <div class="c">${num(r.ter_pct, 2)}% TER</div>
          <div class="v">${eur(r.annual_eur)}</div></div>`;
      }).join('') : '')
    + (nNoTer ? `<div class="lnote">${nNoTer} fund${nNoTer === 1 ? ' publishes'
        : 's publish'} no TER and ${nNoTer === 1 ? 'is' : 'are'} left out of the
        drag, not counted as free.</div>` : '')));

  cards.push(card('Sector', X.sectors
      ? `${num(X.sectors.resolved_pct, 0)}% resolved` : '',
    ovbars((X.sectors || {}).rows, 'sector', 8)
    + `<div class="lnote">Look-through: a fund's sleeve is spread across its
       disclosed constituents. Yahoo publishes ten per fund, so this names
       ${num((X.sectors || {}).resolved_pct, 0)}% of the book.</div>`));

  cards.push(card('Geography', X.geography
      ? `${num(X.geography.resolved_pct, 0)}% resolved` : '',
    ovbars((X.geography || {}).rows, 'country', 8)));

  // The overlap between funds, largest first by the euros held twice. Each
  // side's share says how much of that fund's disclosed top ten is the pair's
  // common ground, so a big fund and a small one can be read at once.
  const pairs = (lap.pairs || []).slice(0, 5);
  cards.push(card('Fund overlap', `${lap.n_substantial || 0} of ${lap.n_pairs || 0} pairs substantial`,
    (pairs.length
      ? pairs.map((p) => `<div class="lrow ov2" title="${p.n_shared} shared of ${
            p.n_a}/${p.n_b} disclosed · ${num(p.a_disclosed_in_shared_pct, 1)}% / ${
            num(p.b_disclosed_in_shared_pct, 1)}% of each side's disclosure">
          <div class="t">${esc(labOf(p.a))} × ${esc(labOf(p.b))}</div>
          <div class="c">${p.n_shared} shared</div>
          <div class="v">${num(p.pct, 2)}%</div></div>`).join('')
        + `<div class="lnote">The last column is the share of the book held twice
           through both funds of a pair. Measured on disclosed constituents only.</div>`
      : `<div class="lnote">${lap.n_funds > 1 ? 'No two funds share a disclosed holding.'
          : 'Fewer than two funds, so nothing can overlap.'}</div>`)
    + goLink('lap', 'Every pair')));

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

