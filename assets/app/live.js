// --------------------------------------------------------------- live prices
//
// Everything above this line renders the file exactly as it was built. This
// block, and only this block, makes the page move on its own.
//
// It asks /api/quotes - an edge function on the same deployment, behind the
// same password gate - for current prices and FX, then rewrites the
// price-derived fields and repaints. The book itself (units, cost, accounts,
// theses, coverage) is untouched: those change when Nordnet is exported, not
// when a price ticks, and pretending otherwise would be the whole point of the
// exercise thrown away.
//
// Three rules it does not break:
//
//  - A holding the vendor could not price KEEPS its build-time price. It is
//    never zeroed, never carried at yesterday's close relabelled as today, and
//    it is COUNTED and shown in the tape. Absent is not zero.
//  - D.generated is never touched. The render clock is the evidence of how old
//    the underlying book is; the live clock sits next to it, not on top.
//  - A failed fetch is a visible state, not a silent no-op. `Live off` means
//    something different from no chip at all, and both mean something
//    different from a fresh timestamp.
(function liveLayer() {
  // Opened from disk there is no origin to call, and nothing is wrong with
  // that - the local file is the primary way this page is read. Stay silent
  // rather than showing a failure the reader cannot act on.
  if (location.protocol !== 'http:' && location.protocol !== 'https:') return;

  const POLL_MS = 60000;
  let LAST_OK = null;   // the last tick whose prices D was restated from
  const rows = (D.holdings || []).filter((h) => h.yahoo && h.yahoo !== 'MISSING');
  const wrows = (D.watchlist || []).filter((w) => w.yahoo && w.yahoo !== 'MISSING');
  if (!rows.length && !wrows.length) return;

  const symbols = [...new Set([...rows, ...wrows].map((r) => r.yahoo))];
  // What the live layer is even capable of asking about. A row filtered out
  // above - no Yahoo mapping, or mapped to MISSING - is never asked, so it must
  // never be marked stale: nothing refused it, and nothing was ever going to
  // move it. It reads `as at build`, which is the truth.
  for (const s of symbols) LIVEASK.add(s);
  // Held rows only. A watchlist row needs a price and a day move; it is not
  // valued in euro, so its currency needs no rate. Asking for one means the
  // response reports a currency as missing forever - the book carries a
  // watchlist entry whose ccy is literally "Other" - and a warning that is
  // always on is a warning nobody reads.
  const currencies = [...new Set(rows.map((r) => r.ccy).filter(Boolean))];

  // The render-time totals, kept so they are never simply lost to an
  // overwrite. Same reason the render clock survives.
  if (!D.totals_built) D.totals_built = Object.assign({}, D.totals);

  function applyQuotes(data) {
    const q = data.quotes || {};
    const fx = data.fx || {};
    const unpriced = [];
    // Refilled every tick, not accumulated: a symbol that missed last time and
    // priced this time has to be able to go back to saying so.
    LIVEMISS.clear();

    for (const h of rows) {
      const hit = q[h.yahoo];
      const rate = fx[h.ccy];
      // Both, or neither, and both positive.
      //
      // A price without its FX rate would be valued at the wrong scale, which
      // is worse than being a few minutes old. And the price is re-checked for
      // being a usable number HERE as well as in the endpoint, because this is
      // the side where a bad one becomes a euro figure on screen. A zero that
      // got past the endpoint would silently value the position at nothing,
      // and a zero rate would do the same to every row in that currency.
      if (!hit || !(hit.price > 0) || !(rate > 0)) {
        unpriced.push(h.yahoo);
        LIVEMISS.add(h.yahoo);
        continue;
      }
      h.price = hit.price;
      // Rounded to the cent HERE, exactly where analyse.value_holdings rounds
      // it, because everything downstream divides by it. Carry the unrounded
      // product into the weights and the totals and the page disagrees with
      // Python in the last digit across several dozen fields at once - all of
      // them individually defensible, none of them reconcilable.
      h.value_eur = Math.round(hit.price * (h.units || 0) * rate * 100) / 100;
      h.day_pct = hit.changePct;
      h.stale = false;
      h.live_asof = hit.asOf;
      // The chart's last candle, kept in its own map - see noteLiveBar. Called
      // for every symbol that priced, not only the one on screen, so switching
      // rows shows a current candle immediately instead of one that catches up
      // on the next tick.
      noteLiveBar(h.yahoo, hit);
      // Everything else a price implies - P/L, off_high, the broker check, the
      // weights, the treemap, coverage, the watchlist upsides - is DERIVE's
      // job, below. Patching a field here as well is how the page ended up
      // with two prices for one holding in the first place.
    }

    for (const w of wrows) {
      const hit = q[w.yahoo];
      // Same guard, same reason. A watchlist miss is not counted in the tape's
      // `n unpriced` - it costs the reader no euros - but it still has to mark
      // its own price, or a frozen watchlist column looks exactly like a live
      // one that has not moved today.
      if (!hit || !(hit.price > 0)) { LIVEMISS.add(w.yahoo); continue; }
      // price_now is the field the rest of the page reads: `w.price` does not
      // exist in the payload, so writing to it updated nothing and failed
      // silently - the watchlist has no euro value to look wrong, so a dead
      // write there shows up as a column that simply never moves.
      //
      // Scaled into the board's unit by the factor Python chose at build
      // (analyse.board_scale): a Johannesburg quote arrives in cents against a
      // board written in rand, and read raw it is a 100x move.
      w.price_now = hit.price * (w.price_scale || 1);
      w.day_pct = hit.changePct;
      w.live_asof = hit.asOf;
      // A watchlist row has a chart too, and it is the surface the thesis is
      // argued against. It gets the same live candle for the same reason.
      noteLiveBar(w.yahoo, hit);
    }

    // One call, one source of truth. Every price-derived number in D is
    // recomputed from D.holdings by the same code that was proved against
    // Python's own output at boot - rather than by a second, shorter, subtly
    // different sum written here.
    DERIVE.all();

    LIVE = {
      at: new Date(),
      asked: symbols.length,
      priced: Object.keys(q).length,
      // Held positions only. An unpriced watchlist row costs the reader
      // nothing; an unpriced holding is a number in the total that did not
      // move with the others, and that is worth saying out loud.
      missing: unpriced,
      fxMissing: data.fxMissing || [],
      error: null,
    };
    LAST_OK = LIVE;

    foldHoldings();
    buildRows();
    repaint();
  }

  function repaint() {
    try {
      paintTape();
      // Only the surface on screen; the others are marked and painted on the
      // way in (paintSurface). Every tick marks all three before painting one,
      // so nothing hidden can skip a tick and come back one tick behind.
      for (const s of ['home', 'overview', 'positions', 'sheet']) UNPAINTED.add(s);
      paintSurface(shownSurface());
    } catch (e) {
      // A repaint that throws must not leave a half-updated page claiming to
      // be live.
      LIVE = {at: new Date(), asked: symbols.length, priced: 0, missing: [],
        fxMissing: [], error: 'repaint failed: ' + (e && e.message)};
      try { paintTape(); } catch (e2) {}
    }
  }

  let inflight = false;
  async function tick() {
    if (inflight) return;
    inflight = true;
    try {
      const r = await fetch('/api/quotes', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({symbols, currencies}),
      });
      if (!r.ok) throw new Error('quotes endpoint returned ' + r.status);
      applyQuotes(await r.json());
    } catch (e) {
      const why = (e && e.message) || 'live prices unavailable';
      // After a good tick, D already holds that tick's prices and keeps them.
      // Saying `off` then made every mark read `as at build` over numbers
      // that were not the build's, and the candle snapped back while the
      // price beside it did not.
      LIVE = LAST_OK
        ? Object.assign({}, LAST_OK, {error: why, carried: true, failedAt: new Date()})
        : {at: new Date(), asked: symbols.length, priced: 0, missing: [],
           fxMissing: [], error: why};
      // The whole page, not just the tape. A tick that succeeded and then one
      // that failed used to leave every per-price freshness mark still reading
      // `live` while the chip above them read `off` - the page contradicting
      // itself about its own age. repaint() cannot recurse here: its own catch
      // only sets LIVE and paints the tape.
      try { foldHoldings(); buildRows(); repaint(); } catch (e2) {
        try { paintTape(); } catch (e3) {}
      }
    } finally {
      inflight = false;
    }
  }

  // Deliberately exposed. The interesting behaviour of this block is what it
  // does when the endpoint lies to it - an empty quote map, a zero price, a
  // missing FX rate, a 500 - and none of that is reachable from outside
  // without a handle to re-run the fetch under a stubbed `fetch`. A guard
  // nobody has killed on purpose is not a guard yet.
  //
  // It exposes no data the page is not already showing, and the page is behind
  // the password gate regardless.
  window.cockpitLive = {tick, state: () => LIVE};

  tick();
  // Polling a hidden tab burns the free tier's invocations to redraw something
  // nobody is looking at. Refresh on the way back instead.
  setInterval(() => {
    if (document.visibilityState === 'visible') tick();
  }, POLL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') tick();
  });
})();
