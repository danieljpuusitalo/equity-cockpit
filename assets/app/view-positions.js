/* ----------------------------------------------------------------- rail */

function visible() {
  const q = state.q.trim().toLowerCase();
  return ROWS.filter((r) => {
    if (state.filter === 'held'  && !r.isHeld) return false;
    if (state.filter === 'watch' && !r.w) return false;
    if (state.filter === 'flag'  && !r.flags.length) return false;
    if (q && !(r.label + ' ' + r.company).toLowerCase().includes(q)) return false;
    return true;
  });
}

function paintRail() {
  const rows = visible();
  if (!rows.length) {
    $('#list').innerHTML = '<div class="empty">Nothing matches that filter.</div>';
    return;
  }
  $('#list').innerHTML = rows.map((r) => `
    <div class="row" data-sym="${esc(r.sym)}" role="option"
         aria-selected="${r.sym === state.sym}">
      <div class="sym">${esc(r.label)}${r.worst
        ? `<i class="dot" style="background:${LEVEL[r.worst]}"></i>` : ''}${
        r.cov && !r.cov.covered
          ? `<i class="ring" title="Not monitored — ${esc(r.cov.gap || '')}"></i>` : ''}</div>
      <div class="px num">${fresh(r.freshness)}${px(r.price)}</div>
      <div class="co">${esc(r.company)}</div>
      <div class="chg num ${cls(r.day_pct)}">${r.isHeld
        ? pct(r.day_pct, 1) : '<span style="color:var(--muted)">watch</span>'}</div>
    </div>`).join('');
}

/* ------------------------------------------------------------- mid pane */

function paintHead(r) {
  const wk = r.w;
  $('#symhead').innerHTML = `
    <span class="tk">${esc(r.label)}</span>
    <span class="co">${esc(r.company)}</span>
    ${wk && wk.verdict ? verdictBadge(wk.verdict) : ''}
    <span class="px num">${fresh(r.freshness)}${px(r.price)}<span style="font-size:var(--t-3);
      color:var(--muted);margin-left:5px">${esc(r.ccy)}</span></span>
    <span class="chg num ${cls(r.day_pct)}">${r.day_pct == null ? '' : pct(r.day_pct)}</span>`;
}

function verdictBadge(v) {
  const k = String(v).toLowerCase();
  const c = k.includes('buy') || k.includes('add') ? 'b-buy'
          : k.includes('trim') ? 'b-trim'
          : k.includes('exit') || k.includes('sell') ? 'b-exit' : 'b-watch';
  return `<span class="badge ${c}">${esc(v)}</span>`;
}

function paintStrip() {
  const withValue = ROWS.filter((r) => r.value_eur > 0);
  $('#stripnote').textContent =
    `${withValue.length} positions · ${(D.sources || {}).lots} lots · ` +
    `width is share of ${eur(D.totals.value_eur)}`;
  $('#bars').innerHTML = withValue.map((r) => `
    <div class="bar" data-sym="${esc(r.sym)}" data-sel="${r.sym === state.sym ? 1 : 0}"
      style="flex:${r.weight.toFixed(3)} 1 0"
      title="${esc(r.label)} — ${r.weight.toFixed(1)}% · ${eur(r.value_eur)}"></div>`
  ).join('');
}

/* --------------------------------------------------------- thesis pane */

function paintThesis(r) {
  const w = r.w, h = r.h, out = [];

  if (w) {
    const decay = w.upside_decay_pts;

    /* The thesis leads, because it is the thing the rest of this pane is
       evidence for or against. Empty says so out loud rather than collapsing
       the section - a name whose reason to be held was never written down is
       the finding, not a rendering gap. */
    const infl = w.inflection_date
      ? `<dl class="kv under">
         <dt>Settles on</dt><dd>${esc(w.inflection_date)}${w.days_to_inflection == null
           ? '' : ` <span style="color:var(--muted)">${w.days_to_inflection}d</span>`}</dd>
         ${w.inflection_event ? `<dt>Event</dt><dd>${esc(w.inflection_event)}</dd>` : ''}
         </dl>` : '';
    // The empty-thesis line used to assert "the board carries a target and a
    // trigger for this name" unconditionally - for a name with neither, the
    // page said so anyway. It is derived now: it lists what the board actually
    // records, and says plainly when the answer is nothing.
    const onBoard = [w.target != null && 'a target',
                     w.trigger_level != null && 'a trigger'].filter(Boolean);
    const noThesis = 'No thesis written. ' + (onBoard.length
      ? `The board records ${onBoard.join(' and ')} for this name but never `
        + 'why it is owned — so there is nothing here for the price to agree '
        + 'or disagree with.'
      : 'The board records no target, no trigger and no reason: this position '
        + 'is held without a written view of any kind.');
    out.push(`<div class="tsec"><div class="tlabel">THE THESIS</div>
      <div class="prose"${w.thesis ? '' : ' style="color:var(--muted)"'}>${
        w.thesis ? esc(w.thesis) : noThesis
      }</div>${infl}</div>`);

    out.push(`<div class="tsec"><div class="tlabel">THE CALL</div><dl class="kv">
      <dt>Verdict</dt><dd>${verdictBadge(w.verdict || '—')}</dd>
      <dt>Tier</dt><dd>${esc(w.tier || '—')}</dd>
      <dt>Target</dt><dd>${px(w.target)} ${esc(w.ccy || '')}</dd>
      <dt>Upside now</dt><dd class="${cls(w.upside_now)}">${pct(w.upside_now, 1)}</dd>
      <dt>Upside at eval</dt><dd>${pct(w.upside_at_eval, 1)}</dd>
      <dt>Drift since eval</dt><dd class="${cls(w.drift_pct)}">${pct(w.drift_pct, 1)}</dd>
      <dt>Last evaluated</dt><dd>${esc(w.last_eval || '—')}${w.days_since_eval == null
        ? '' : ` <span style="color:var(--muted)">${w.days_since_eval}d</span>`}</dd>
      <dt>Next check</dt><dd>${esc(w.next_check || '—')}${w.days_to_check == null
        ? '' : ` <span style="color:var(--muted)">${w.days_to_check}d</span>`}</dd>
      </dl>${Math.abs(decay || 0) >= (D.thresholds || {}).decay_alert_pts
        ? `<div class="prose under" style="color:var(--warn-ink)">
           ⚠ The board still claims ${pct(w.upside_at_eval, 1)}; today it is
           ${pct(w.upside_now, 1)} — <b>${Math.abs(decay).toFixed(1)} points</b>
           of decay. The thesis has not been re-checked since ${esc(w.last_eval)}.</div>` : ''}
      </div>`);

    out.push(`<div class="tsec"><div class="tlabel">WHAT WOULD CHANGE YOUR MIND</div>
      ${w.trigger_level ? `<dl class="kv over">
        <dt>Level</dt><dd>${esc(w.trigger_kind || '')} ${px(w.trigger_level)}</dd>
        <dt>Gap to level</dt><dd class="${w.trigger_hit ? 'dn-t' : ''}">
          ${pct(w.trigger_gap_pct, 1)}${w.trigger_hit ? ' · HIT' : ''}</dd></dl>`
        : `<div class="prose over" style="color:var(--muted)">
           No price level parsed from this trigger — it is a condition, not a
           number. Read it and judge for yourself.</div>`}
      <div class="prose">${esc(w.trigger || 'Nothing written down.')}</div></div>`);

    out.push(paintMultiples(w, r));

    const noted = [['Moat', w.moat], ['Market', w.market],
                   ['Evaluations', w.evaluations]]
      .filter((kv) => kv[1] != null && kv[1] !== '');
    if (noted.length) out.push(`<div class="tsec"><div class="tlabel">AS RECORDED</div>
      <dl class="kv">${noted.map((kv) =>
        `<dt>${esc(kv[0])}</dt><dd>${esc(kv[1])}</dd>`).join('')}</dl></div>`);
  } else {
    out.push(`<div class="tsec"><div class="tlabel">THE CALL</div>
      <div class="prose">Not on the Equity Log. You own it, but no target, thesis or
      falsifying condition is written down — so nothing here can tell you when it
      stops being a good idea.</div></div>`);
  }

  out.push(paintMissing(r));

  if (h) out.push(`<div class="tsec"><div class="tlabel">THE POSITION</div><dl class="kv">
    <dt>Units</dt><dd>${qty(h.units)}</dd>
    <dt>Account${h.accounts.length > 1 ? 's' : ''}</dt><dd>${esc(h.accounts.join(', '))}</dd>
    <dt>Value</dt><dd>${eur(h.value_eur)}</dd>
    <dt>Cost</dt><dd>${eur(h.cost_eur)}</dd>
    <dt>P/L</dt><dd class="${cls(h.pl_pct)}">${pct(h.pl_pct, 1)} · ${eur(h.pl_eur)}</dd>
    ${(() => { const rr = (D.returns || {})[h.sym] || {};
       return rr.irr_pct != null
         ? `<dt>Annualised</dt><dd class="${cls(rr.irr_pct)}">${pct(rr.irr_pct, 1)}/yr
            <span style="color:var(--muted)">since ${esc(rr.since || '')}</span>${
            atBuild('a money-weighted return needs the dated lot cashflows, which '
                    + 'are not carried in this page')}</dd>`
         : rr.note
           ? `<dt>Annualised</dt><dd style="color:var(--muted)">${esc(rr.note)}</dd>`
           : ''; })()}
    <dt>Weight</dt><dd>${h.weight.toFixed(1)}%</dd>
    ${riskRow(h.sym)}
    <dt>Off 52w high</dt><dd>${pct(h.off_high, 1)}</dd>
    <dt>Bucket</dt><dd>${esc(h.bucket || '—')}</dd></dl></div>`);

  out.push(paintBehaviour(r));

  if (r.flags.length) out.push(`<div class="tsec"><div class="tlabel">FLAGS</div>
    ${r.flags.map((a) => `<div class="alert">
      <span class="dot" style="background:${LEVEL[a.level] || 'var(--muted)'}"></span>
      <span><div class="t">${esc(a.title)}</div>
      <div class="d">${esc(a.detail)}</div></span></div>`).join('')}</div>`);

  $('#thesis').innerHTML = out.join('');
}

/* This name's share of the book's risk, as performance.risk computed it:
   weight times its covariance with the covered book, over the variance. A name
   the estimate left out - too few unbroken days, or no variance to share -
   says "not estimated" and why. Never 0%: a name nobody measured is not a
   name that carries no risk. */
function riskRow(sym) {
  const R = PERF.risk || {};
  const c = (R.contribution || []).find((x) => x.symbol === sym);
  const x = (R.excluded || []).find((e) => e.symbol === sym);
  const dd = c && c.rc_pct != null
    ? `${num(c.rc_pct, 1)}% <span style="color:var(--muted)">of book risk · ${
        num(c.weight_pct, 1)}% of the weight measured · ${num(c.vol_pct, 1)}% vol, ${
        R.window_days}d</span>${atBuild('risk is estimated from the daily closes '
          + 'at build, and a live tick does not restate it')}`
    : `<span style="color:var(--muted)">not estimated${x
        ? ` — only ${x.n_obs} unbroken days of prices` : ''}</span>`;
  return `<dt>Share of risk</dt><dd>${dd}</dd>`;
}

/* The board's figures against today's. Nothing is reconciled and nothing is
   overwritten - the whole point of the section is the distance between the two
   columns, and a merged number would hide exactly that. The left column is what
   Daniel wrote down when he last evaluated the name; the right is Yahoo this
   morning. Where the board is silent the row still shows, because "we never
   recorded this" is itself worth seeing next to a live number. */
function paintMultiples(w, r) {
  const L = w.live || {}, ccy = esc(w.ccy || r.ccy || '');
  // Deliberately achromatic. A multiple that fell since the write-up is
  // cheaper, not worse, and green/red here would have the page taking a view
  // on which direction is good news - which is the thesis's job, not this
  // table's. The sign and the size are the whole message.
  const drift = (d) => d == null ? '' : `<span class="drift">${pct(d, 0)}</span>`;

  // Both helpers test the RAW value, not the formatted one. They used to test
  // the output of num(), which returns '—' rather than null, so the guard was
  // unreachable and every row rendered whether or not it had anything in it.
  const row = (label, was, raw, fmt, d, suffix) =>
    (was == null && raw == null) ? '' :
    `<dt>${esc(label)}</dt><dd class="was">${was == null ? '—' : esc(was)}</dd>
     <dd>${raw == null ? '—' : fmt}${suffix || ''}${drift(d)}</dd>`;
  const live = (label, raw, fmt, suffix) => raw == null ? '' :
    `<dt>${esc(label)}</dt><dd>${fmt}${suffix || ''}</dd>`;

  // Three of these nine have two sides; six have one. The Equity Log has no
  // field for P/B, EPS, ROE, margin, beta or market cap, so those rows were
  // printing a dash under a "Board" heading that could never be filled - a
  // column promising a comparison that does not exist. They are their own list
  // now, with no second column to be empty in.
  const compared = [
    row('P/E', w.pe, L.pe, num(L.pe, 1), w.pe_drift_pct),
    row('Fwd P/E', w.fwd_pe, L.fwd_pe, num(L.fwd_pe, 1), w.fwd_pe_drift_pct),
    row('Net debt/EBITDA', w.net_debt_ebitda, L.net_debt_ebitda,
        num(L.net_debt_ebitda, 2)),
  ].filter(Boolean).join('');

  const current = [
    live('P/B', L.pb, num(L.pb, 1)),
    live('EPS', L.eps, num(L.eps, 2), ` <span class="drift">${ccy}</span>`),
    live('Return on equity', L.roe_pct, num(L.roe_pct, 1) + '%'),
    live('Net margin', L.margin_pct, num(L.margin_pct, 1) + '%'),
    live('Beta', L.beta, num(L.beta, 2)),
    live('Market cap', L.market_cap, big(L.market_cap),
         ` <span class="drift">${ccy}</span>`),
  ].filter(Boolean).join('');
  if (!compared && !current && L.street_target == null) return '';

  /* The street's target, deliberately without the street's verdict. A number
     you can hold your own target up against is evidence; a word telling you to
     buy is somebody else making the decision this pane exists to make. */
  const street = L.street_target == null ? '' : `
    <dl class="kv under">
      <dt>Street target</dt><dd>${px(L.street_target * (w.price_scale || 1))} ${ccy}${L.street_analysts
        ? ` <span style="color:var(--muted)">${L.street_analysts} analysts</span>` : ''}</dd>
      <dt>Street sees</dt><dd class="${cls(w.street_upside_pct)}">${pct(w.street_upside_pct, 1)}</dd>
      <dt>You see</dt><dd class="${cls(w.upside_now)}">${pct(w.upside_now, 1)}</dd>
    </dl>`;

  const sector = L.sector
    ? `<div class="prose under" style="color:var(--muted)">${esc(L.sector)}${
        L.industry ? ' · ' + esc(L.industry) : ''}</div>` : '';

  // Headed by who said it and when, like the Board column. It used to read
  // "Now", which on a page whose prices tick every minute claimed these tick
  // too - they do not. They are Yahoo's own figures from the cached fetch.
  const asof = L.asof ? ' ' + esc(String(L.asof).slice(5, 10)) : '';
  return `<div class="tsec"><div class="tlabel">THE MULTIPLES</div>
    ${compared ? `<dl class="trio">
      <dt></dt>
      <dd class="hd">Board${w.last_eval ? ' ' + esc(String(w.last_eval).slice(5)) : ''}</dd>
      <dd class="hd" title="Yahoo's own figure, fetched ${esc(L.asof || 'at the build')}; not re-read on a live tick">Yahoo${asof}</dd>
      ${compared}
    </dl>` : ''}
    ${current ? `<div class="lnote" style="margin:${compared ? '11px' : '0'} 0 5px"
      >Not on the board — current values only.</div>
      <dl class="kv">${current}</dl>` : ''}
    ${street}${sector}</div>`;
}

/* Coverage, as money. The prose above already explains why an unexamined
   position is a problem; what this section adds is how much of the book is
   riding on one. Covered names get nothing - the thesis section above is
   already the evidence, and a green "all good" box would be noise. */
function paintMissing(r) {
  const c = r.cov;
  if (!c || c.covered) return '';
  const stock = c.klass === 'stock';
  /* The word "placeholder" travels with the number everywhere the number
     goes. A target that reads like a policy IS a policy to whoever finds it
     next, and these eleven were filled in by a rule, not a decision. */
  const held = c.target_basis === 'placeholder';
  const alloc = c.target_weight_pct == null ? '' : `
    <dl class="kv under">
      <dt>Target weight</dt><dd>${num(c.target_weight_pct, 1)}%${
        held ? ' <span class="est" title="Filled in by a rule, not a decision. '
             + 'Not a policy, and never alerted on.">placeholder</span>' : ''}</dd>
      <dt>Drift</dt><dd class="${cls(c.drift_pts)}">${c.drift_pts == null
        ? '—' : num(c.drift_pts, 1) + ' pts'}</dd></dl>`;
  return `<div class="tsec"><div class="tlabel">WHAT'S MISSING</div>
    <dl class="kv">
      <dt>At stake</dt><dd>${eur(c.value_eur)} · ${num(c.weight_pct, 1)}% of the book</dd>
      <dt>Judged by</dt><dd>${stock ? 'a thesis' : 'an allocation'}</dd>
    </dl>
    <div class="prose under">${esc(cap(c.gap) || 'Not monitored.')}${
      stock
        ? ' — so there is no target to measure today against and no condition that '
          + 'would tell you the reasoning had broken.'
        : ' — an index tracker answers to a weight, not to a story, and without '
          + 'one there is no band for it to drift out of.'}</div>${alloc}</div>`;
}

/* The chart, read back as numbers. Descriptive only: this section says where
   price is, never what to do about it - "overbought" is weather, and the
   thesis above is the decision. Everything here was computed in Python off the
   cached daily bars, so it costs no extra fetch.

   It used to say it "cannot disagree with what is plotted a pane to the left".
   That stopped being true the moment the chart's last candle started tracking
   the live price: these numbers are as at the build and the final candle is
   not. The gap is one partial session on a 252-day window - immaterial to
   MA200, visible in RSI on a sharp day - and every row here carries its own
   `asof`, which is the honest place for the reader to settle it. Recomputing
   the indicators live was considered and refused: they are Python's output,
   proved against Python, and a second implementation in the page is exactly
   the two-answers-for-one-fact trap this repo keeps falling into. */
function paintBehaviour(r) {
  const i = r.ind;
  if (!i) return '';
  const rows = [];
  if (i.rsi != null) rows.push(`<dt>RSI ${i.rsi_period}</dt><dd>${num(i.rsi, 1)}
    <span style="color:var(--muted)">${esc(i.rsi_state || '')}</span>
    ${meter(i.rsi, 0, 100, [30, 70])}</dd>`);
  // No tick marks on these two: the ends of the track already ARE the bands,
  // and a 1px rule at left:100% renders half outside the bar it belongs to.
  if (i.bb_pct_b != null) rows.push(`<dt>In its band</dt><dd>${num(i.bb_pct_b * 100, 0)}%
    <span style="color:var(--muted)">${num(i.bb_lower, 2)}–${num(i.bb_upper, 2)}</span>
    ${meter(i.bb_pct_b, 0, 1)}</dd>`);
  if (i.macd_hist != null) rows.push(`<dt>MACD histogram</dt>
    <dd class="${cls(i.macd_hist)}">${num(i.macd_hist, 2)}
    <span style="color:var(--muted)">line ${num(i.macd, 2)} · signal
    ${num(i.macd_signal, 2)}</span></dd>`);
  if (i.ma_spread_pct != null) rows.push(`<dt>MA50 vs MA200</dt>
    <dd class="${cls(i.ma_spread_pct)}">${pct(i.ma_spread_pct, 1)}</dd>`);
  if (i.above_sma200_pct != null) rows.push(`<dt>Above MA200</dt>
    <dd class="${cls(i.above_sma200_pct)}">${pct(i.above_sma200_pct, 1)}</dd>`);
  if (i.vol_30d != null) rows.push(`<dt>Volatility</dt><dd>${num(i.vol_30d, 1)}%
    <span style="color:var(--muted)">annualised, 30d</span></dd>`);
  if (i.atr_pct != null) rows.push(`<dt>Daily range</dt><dd>${num(i.atr_pct, 2)}%
    <span style="color:var(--muted)">ATR ${num(i.atr, 2)}</span></dd>`);
  if (i.max_drawdown_pct != null) rows.push(`<dt>Max drawdown</dt>
    <dd class="dn-t">${pct(i.max_drawdown_pct, 1)}</dd>`);
  // range.pct is WHERE the close sits between the low and the high, not how
  // wide the band is. Labelling it "wide" would have read as a volatility
  // number and been wrong by a mile on anything that has halved.
  if (i.range && i.range.pct != null) rows.push(`<dt>In its ${i.range.days}d range</dt>
    <dd>${num(i.range.pct, 0)}%
    <span style="color:var(--muted)">${num(i.range.low, 2)}–${num(i.range.high, 2)}</span>
    ${meter(i.range.pct, 0, 100)}</dd>`);
  if (i.volume && i.volume.relative != null) rows.push(`<dt>Volume</dt>
    <dd>${num(i.volume.relative, 2)}×
    <span style="color:var(--muted)">the ${i.volume.period}d average</span></dd>`);
  if (!rows.length) return '';
  return `<div class="tsec"><div class="tlabel">THE CHART</div>
    <dl class="kv">${rows.join('')}</dl>
    <div class="prose under" style="color:var(--muted)">
      ${i.bars} bars to ${esc(i.asof)}. Description, not advice — none of this
      knows why you own it.</div></div>`;
}

/* ----------------------------------------------------------------- chart */

let chart = null, candles = null, lines = [], mas = {}, chartKey = null, chartLen = 0;
let relLine = null;

/* The name against the book or against ACWI, as one line: price over the
   index, both rebased to 100 on the first bar of the window where both exist.
   Above 100 the name has done better over what is on screen; below, worse.

   Presentation of two series the payload already carries, not a new figure -
   the same rebasing Home does to start its shadow level with the book. Each
   bar is matched to the index on the last curve date at or before it, so a
   day the curve skipped borrows the day before rather than inventing one, and
   a bar after the build's last curve date is read against that date. */
function relSeries(slice, which) {
  const B = which === 'bench' ? (BENCH.absent ? null : BENCH.index) : CURVE.index;
  if (!B || !CURVE.n) return [];
  const out = [];
  let j = 0, p0 = null, b0 = null;
  for (const bar of slice) {
    while (j + 1 < CURVE.n && CURVE.date[j + 1] <= bar[0]) j++;
    if (CURVE.date[j] > bar[0]) continue;
    const bi = B[j];
    if (bi == null || !(bi > 0) || !(bar[4] > 0)) continue;
    if (p0 == null) { p0 = bar[4]; b0 = bi; }
    out.push({time: bar[0], value: 100 * (bar[4] / p0) / (bi / b0)});
  }
  return out;
}

// Why a relative line cannot be drawn, or null when it can. Written onto the
// button itself, so an option that does nothing says so before it is pressed.
function relWhy(which) {
  if (!CURVE.n) return 'the build carries no book curve to measure against';
  if (which === 'bench' && (BENCH.absent || !BENCH.index))
    return 'the build carries no ACWI series' + (BENCH.absent
      ? ' (' + String(BENCH.absent) + ')' : '');
  return null;
}

/* Simple moving average over closes, as a rolling sum - one pass, no window
   re-summing, so 500 bars costs 500 additions rather than 25,000.

   It is computed over the WHOLE series and sliced afterwards, never over the
   visible window. An MA50 computed inside a 1M view would be a 21-day average
   wearing a "50" label, and it would be wrong at exactly the left edge where
   you are looking for the cross. */
function sma(bars, period) {
  if (!bars || bars.length < period) return [];
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i][4];
    if (i >= period) sum -= bars[i - period][4];
    if (i >= period - 1) out.push({time: bars[i][0], value: sum / period});
  }
  return out;
}

function themeOpts() {
  const cssVar = (n, fallback) => {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(n).trim();
      return v || fallback;
    } catch (e) { return fallback; }
  };
  return {
    // attributionLogo defaults to TRUE in v4.2+ and stamps a tradingview.com
    // link into the corner of the pane. It is a documented option, not a
    // licence condition - Apache-2.0 asks that the notice be preserved, and it
    // is: the library is inlined verbatim, @license header and all, a few
    // hundred lines above this one.
    // The fallbacks are the light-mode token values. They only apply if
    // getComputedStyle throws, so they are a last resort rather than a second
    // copy of the palette - but palette_check.py reads the :root block and
    // would not see them, so keep them in step by hand when a token moves.
    layout: {background:{color:'transparent'}, textColor:cssVar('--muted','#6f6d67'),
             // 11 is --t-2 without the unit; the library wants a number. The
             // family comes from the same token as the rest of the page, so
             // the axis labels and the table beside them cannot drift apart.
             fontSize:11.5,
             fontFamily:cssVar('--font-ui', 'system-ui,-apple-system,sans-serif'),
             attributionLogo:false},
    grid: {vertLines:{color:cssVar('--grid','#e1e0d9')},
           horzLines:{color:cssVar('--grid','#e1e0d9')}},
    // The axis was on the library's default formatter and the tables were on
    // px(), so the same close appeared as "1250.00" on the chart and "1,250.00"
    // in the row beside it. One formatter, so a price is written one way on
    // this page. The currency is not repeated per tick - it is stated once, in
    // the pane head next to the ticker.
    localization: {priceFormatter: px},
    rightPriceScale:{borderColor:cssVar('--axis','#c3c2b7')},
    timeScale:{borderColor:cssVar('--axis','#c3c2b7')},
    crosshair:{mode:0, vertLine:{color:cssVar('--axis','#c3c2b7'), labelBackgroundColor:
      cssVar('--ink-2','#52514e')}, horzLine:{color:cssVar('--axis','#c3c2b7'),
      labelBackgroundColor:cssVar('--ink-2','#52514e')}},
    upColor:cssVar('--up','#2f9e63'), downColor:cssVar('--down','#8c2a34'),
    target:cssVar('--target','#4a55c8'), trigger:cssVar('--trigger','#8f6900'),
    // Deliberately achromatic. Four plotted hues is the ceiling - a fifth was
    // rejected at dE 10.7 against a candle body - and a moving average is
    // context, not identity. Grey is also the only mark on the plot with no
    // hue at all, which is the strongest colour-blind separation available and
    // costs nothing.
    ma:cssVar('--ink-2','#52514e'),
    // The relative line is a comparison, not a price, so it gets no hue either
    // and its own scale on the left: an index at 100 drawn on a price axis
    // would sit wherever 100 happens to fall in the listing's currency.
    rel:cssVar('--muted','#6f6d67'),
    leftPriceScale:{borderColor:cssVar('--axis','#c3c2b7')},
  };
}

// Hollow up, filled down - the Western convention, and more usefully a second
// channel. Green and red separate at dE 15.2 under deuteranopia, which is
// enough but is not much; fill separates at any severity of anything, so a
// reader who gets no hue at all still reads the chart from the body alone.
const candleOpts = (T) => ({
  upColor:'rgba(0,0,0,0)', downColor:T.downColor,
  borderUpColor:T.upColor, borderDownColor:T.downColor,
  wickUpColor:T.upColor, wickDownColor:T.downColor,
});

// Intraday candles for the 1D and 5D ranges. The daily series moves one bar in
// ~250 when a quote lands, so a year-wide chart looks frozen while the price
// beside it ticks. These are Yahoo's own five- and fifteen-minute bars, fetched
// for the one symbol on screen and refetched at most once per poll, so the
// chart draws real up and down candles as the session trades.
//
// Held apart from D.history for the same reason LIVEBAR is: live figures never
// overwrite recorded ones. A failed refetch keeps the last good bars and says
// so; it never blanks a chart that was drawing a moment ago.
const INTRA = new Map();          // 'sym|days' -> {bars, interval, error, at, tried}
const INTRA_PENDING = new Set();
const INTRA_ON = location.protocol === 'http:' || location.protocol === 'https:';
const INTRA_STALE_MS = 55000;     // just under the 60s poll, so every tick refetches
const intraKey = (sym, days) => sym + '|' + days;

async function intraFetch(sym, days) {
  const k = intraKey(sym, days);
  if (!INTRA_ON || !sym || INTRA_PENDING.has(k)) return;
  INTRA_PENDING.add(k);
  const prev = INTRA.get(k);
  let got;
  try {
    const res = await fetch('/api/bars', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({symbol: sym, range: days === 5 ? '5d' : '1d'}),
    });
    if (!res.ok) throw new Error('bars endpoint returned ' + res.status);
    const j = await res.json();
    // Re-checked here, not trusted from the endpoint: a zero or a null that
    // got through would draw a wick to the floor.
    const bars = (Array.isArray(j.bars) ? j.bars : []).filter((b) => Array.isArray(b)
      && b.length >= 5 && b.slice(0, 5).every((v) => typeof v === 'number' && v > 0));
    got = (!bars.length && prev && prev.bars.length)
      ? Object.assign({}, prev, {error: j.error || 'empty refetch', tried: Date.now()})
      : {bars, interval: j.interval || '', error: bars.length ? null : (j.error || 'no bars'),
         at: new Date(), tried: Date.now()};
  } catch (e) {
    const why = (e && e.message) || 'intraday unavailable';
    got = prev && prev.bars.length
      ? Object.assign({}, prev, {error: why, tried: Date.now()})
      : {bars: [], interval: '', error: why, at: null, tried: Date.now()};
  } finally {
    INTRA_PENDING.delete(k);
  }
  INTRA.set(k, got);
  if (state.sym === sym && state.days === days && state.view === 'positions') {
    const r = ROWS.find((x) => x.sym === sym);
    if (r) paintChart(r);
  }
}

// Yahoo's timestamps are UTC seconds and the chart library labels them as UTC.
// Shifted by the viewer's own offset so an Amsterdam open reads 09:00, not 07:00.
const localSec = (t) => t - new Date(t * 1000).getTimezoneOffset() * 60;
const hhmm = (d) => d ? d.toTimeString().slice(0, 5) : '';

function paintChart(r) {
  const box = $('#chart'), miss = $('#nochart');
  // The library is vendored, not fetched, so this only fires if assets/ was
  // gutted - but a page that half-renders in silence is the thing we avoid.
  if (typeof LightweightCharts === 'undefined' || !box || !box.getBoundingClientRect) {
    if (miss) { miss.style.display = 'flex';
      miss.textContent = 'Chart library missing from assets/.'; }
    return;
  }
  // Nothing is drawn into a box that cannot be measured. The chart takes its
  // size from the container at construction, and with autoSize on there is no
  // way back: the vendored v4.2.3 makes resize() a no-op while the observer is
  // installed (`resize(t,i,n){this.autoSizeActive()||...}`) and applyOptions
  // will not re-measure either. So a chart built while Positions was hidden is
  // zero-wide for as long as its ResizeObserver takes to fire - which in a
  // background tab is never, because rAF is throttled there. Measured: with
  // the container at 661x891 for a second and a half, every canvas was still
  // 0 wide on a 300px backing store.
  //
  // Deferring costs nothing, because setView('positions') repaints after it
  // un-hides the view and is the only way this surface can be reached.
  const rect = box.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  // The cached series with today's quote merged into its last candle. Taken
  // once, here, so the slice, both moving averages and fitContent() all see the
  // same series - an MA computed off the cached bars while the candles carry a
  // live one would stop a day short of the price it is supposed to be averaging.
  const bars = barsFor(r);
  if (!bars || !bars.length) {
    if (chart) { chart.remove(); chart = null; candles = null; lines = []; mas = {};
      relLine = null; chartKey = null; }
    box.innerHTML = '';
    miss.style.display = 'flex';
    miss.textContent = `No price history for ${r.label}. Yahoo returned nothing for ` +
      'this symbol; the rest of the page is unaffected.';
    return;
  }
  miss.style.display = 'none';

  // 1D and 5D draw intraday bars when there are some; otherwise they fall back
  // to the last month of daily candles and the note under the chart says why.
  const intraday = state.days === 1 || state.days === 5;
  let ibars = null, inote = null;
  if (intraday) {
    const got = INTRA.get(intraKey(r.sym, state.days));
    if (!INTRA_ON) {
      inote = 'Intraday candles need the live page; showing the last month of daily candles';
    } else {
      if (!got || Date.now() - got.tried > INTRA_STALE_MS) intraFetch(r.sym, state.days);
      if (got && got.bars.length) ibars = got;
      else if (!got) inote = 'Loading intraday candles; daily candles meanwhile';
      else inote = `No intraday data for ${r.label} (${got.error}); showing daily candles`;
    }
  }

  const T = themeOpts();
  if (!chart) {
    chart = LightweightCharts.createChart(box, Object.assign({
      autoSize: true, handleScale:{axisPressedMouseMove:false},
    }, T));
    candles = chart.addCandlestickSeries(candleOpts(T));
    // Same colour for both, told apart by weight and dash - so the pair is
    // never distinguished by colour alone, same contract as target/trigger.
    // No last value and no price line: an MA does not belong on the axis, and
    // two extra axis labels would crowd out the two that matter.
    const maOpts = {color:T.ma, priceLineVisible:false, lastValueVisible:false,
                    crosshairMarkerVisible:false};
    mas[50] = chart.addLineSeries(Object.assign({lineWidth:1, title:'MA50',
      lineStyle:LightweightCharts.LineStyle.Solid}, maOpts));
    mas[200] = chart.addLineSeries(Object.assign({lineWidth:2, title:'MA200',
      lineStyle:LightweightCharts.LineStyle.Dashed}, maOpts));
    relLine = chart.addLineSeries({priceScaleId:'left', color:T.rel, lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Dotted, priceLineVisible:false,
      crosshairMarkerVisible:false, lastValueVisible:true});
  }

  // Slice by DATE, not by row count. Bars are trading days - about 252 a year -
  // so bars.slice(-365) is fifteen months of chart under a button labelled 1Y.
  let slice = bars;
  const span = intraday ? 30 : state.days;
  if (span > 0) {
    const last = Date.parse(bars[bars.length - 1][0]);
    const from = last - span * 86400000;
    slice = bars.filter((b) => Date.parse(b[0]) >= from);
  }
  if (!slice.length) slice = bars.slice(-2);
  // A live tick redraws this chart every minute. Refitting it each time threw
  // away whatever the reader had zoomed or panned to, so a chart tied to a
  // moving price was unusable exactly while the price was moving. Same symbol,
  // same range, same overlays: keep their view and let only the last candle
  // move. Anything they changed themselves still gets a fresh fit.
  const viewKey = [r.sym, state.days, ibars ? 'i' : 'd', state.ma[50], state.ma[200],
    state.rel || ''].join('|');
  let keep = viewKey === chartKey ? chart.timeScale().getVisibleLogicalRange() : null;
  const drawn = ibars ? ibars.bars.length : slice.length;
  // A new five-minute bar arriving while the reader is looking at the right
  // edge scrolls the view along with it, the way a trading screen does. Parked
  // anywhere else, the view stays where they put it.
  if (keep && keep.to >= chartLen - 1.5 && drawn > chartLen) {
    keep = {from: keep.from + (drawn - chartLen), to: keep.to + (drawn - chartLen)};
  }
  chartKey = viewKey;
  chartLen = drawn;
  chart.applyOptions({timeScale: {timeVisible: !!ibars, secondsVisible: false}});
  candles.setData(ibars
    ? ibars.bars.map((b) => ({time:localSec(b[0]), open:b[1], high:b[2], low:b[3], close:b[4]}))
    : slice.map((b) => ({time:b[0], open:b[1], high:b[2], low:b[3], close:b[4]})));

  // Full-history MA, then clipped to the window. ISO dates compare correctly as
  // strings, so no parsing is needed here. A symbol with fewer than `period`
  // bars yields an empty series rather than a misleading partial one.
  const edge = slice[0][0];
  for (const p of [50, 200]) {
    if (!mas[p]) continue;
    // A daily average has no place on a five-minute axis: it would be one
    // flat step per session. Off while intraday bars are drawn.
    mas[p].setData(state.ma[p] && !ibars ? sma(bars, p).filter((pt) => pt.time >= edge) : []);
  }

  // The relative line reads daily closes against a daily index, so it is off
  // while intraday bars are drawn, the same as the averages.
  for (const n of document.querySelectorAll('#ranges .rbtn[data-rel]')) {
    const why = relWhy(n.getAttribute('data-rel'));
    if (why) n.setAttribute('disabled', ''); else n.removeAttribute('disabled');
    n.setAttribute('title', why ? 'Not available: ' + why
      : n.getAttribute('data-rel') === 'bench'
        ? 'Price relative to ACWI, rebased to 100 at the left edge'
        : 'Price relative to this book, rebased to 100 at the left edge');
  }
  const relOn = state.rel && !relWhy(state.rel) ? state.rel : null;
  const rel = relOn && !ibars ? relSeries(slice, relOn) : [];
  if (relLine) {
    relLine.applyOptions({title: relOn === 'bench' ? 'vs ACWI' : 'vs book'});
    relLine.setData(rel);
  }
  chart.applyOptions({leftPriceScale: {visible: rel.length > 0}});

  lines.forEach((l) => { try { candles.removePriceLine(l); } catch (e) {} });
  lines = [];
  const w = r.w;
  // The candles are in Yahoo's unit and the board's lines are in the board's.
  // Where those differ (cents vs rand) the lines go back into Yahoo's unit,
  // or a rand target draws as a flat line along the bottom of a cents chart.
  const unit = (w && w.price_scale) || 1;
  // Both lines carry a title and an axis label, so target and trigger are never
  // told apart by colour alone - solid vs dashed, plus the words themselves.
  if (w && w.target) lines.push(candles.createPriceLine({
    price:w.target / unit, color:T.target, lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Solid,
    axisLabelVisible:true, title:'target'}));
  if (w && w.trigger_level) lines.push(candles.createPriceLine({
    price:w.trigger_level / unit, color:T.trigger, lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,
    axisLabelVisible:true, title:'trigger'}));

  // Derived from the drawn series, not from LIVE alone: a symbol the live layer
  // asked about and missed keeps a build-time candle, and this line has to say
  // so rather than inherit the tape's verdict for the page as a whole.
  const note = $('#livebar');
  if (note) {
    const tail = bars[bars.length - 1];
    const merged = r.freshness === 'live' && LIVEBAR.has(r.sym);
    if (ibars) {
      const lastT = new Date(ibars.bars.at(-1)[0] * 1000);
      note.textContent = `${ibars.interval.replace('m', '-minute')} candles, last ${hhmm(lastT)}`
        + (ibars.error ? ` · refresh failed at ${hhmm(new Date(ibars.tried))}, holding the last good bars`
                       : ` · fetched ${hhmm(ibars.at)}`);
    } else if (inote) note.textContent = inote;
    else note.textContent = merged
      ? `Last candle ${tail[0]}, still forming · ${
          LIVE && LIVE.at ? LIVE.at.toTimeString().slice(0, 5) : 'live'}`
      : `Last candle ${tail[0]}, as at the build`;
    // What the dotted line is measured against, and what is inside it. A
    // price in dollars over a euro index carries the dollar's move too.
    if (state.rel) {
      const vs = state.rel === 'bench' ? 'ACWI' : 'the book';
      note.textContent += relWhy(state.rel) ? ` · no line vs ${vs}: ${relWhy(state.rel)}`
        : ibars ? ` · the line vs ${vs} is daily, off on intraday candles`
        : !rel.length ? ` · no overlap with ${vs} in this window`
        : ` · dotted: vs ${vs}, 100 at ${rel[0].time}` + (r.ccy && r.ccy !== 'EUR'
          ? `; ${r.ccy} price against a EUR index, so the currency move is in it` : '');
    }
  }

  if (keep) chart.timeScale().setVisibleLogicalRange(keep);
  else chart.timeScale().fitContent();
}

function retheme() {
  if (!chart) return;
  const T = themeOpts();
  chart.applyOptions(T);
  if (candles) candles.applyOptions(candleOpts(T));
  for (const p of [50, 200]) if (mas[p]) mas[p].applyOptions({color:T.ma});
  const r = ROWS.find((x) => x.sym === state.sym);
  if (r) paintChart(r);
}

