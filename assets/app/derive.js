/* ----------------------------------------------------- derived numbers */
//
// Every number on this page that is a function of a price, recomputed in one
// place, from one input: D.holdings.
//
// Python computes all of it at build time and the page used to simply print
// the answers. That was correct while the page was a photograph. It stopped
// being correct the moment prices started arriving in the browser: the tape
// went live while the Overview's P/L, the treemap's areas, the concentration
// figures, the coverage percentage and every watchlist upside stayed frozen at
// build time. One page quoting two different books, with nothing on screen
// saying which number came from which.
//
// So the arithmetic is TRANSCRIBED, not approximated. Each function below is a
// port of the Python that owns the same number and is named after it, down to
// the decimal places - which are deliberately inconsistent in the original
// (off_high is 1dp, pl_pct is 2dp, hhi is 4dp, book_ter_pct is 3dp) and are
// inconsistent here in exactly the same way.
//
// `parity()` is what makes that claim checkable rather than asserted: it runs
// the whole recompute against the prices the file was BUILT with and demands
// it reproduce Python's own output. A port that has never been run against its
// original is not a port, it is a second opinion.
//
// The look-through - sectors, industries, geography, single names and fund
// overlap - IS recomputed, from each fund's published composition, which the
// build carries as D.lookthrough (exposure.inputs). Each is value times a
// fixed weight, so it follows a price exactly.
//
// Three things are deliberately NOT recomputed, and the page says so rather
// than letting them look live:
//   * the money-weighted return (IRR) - it needs the dated lot cashflows, and
//     those are not in this payload at all;
//   * the blended multiples - each P/E is the vendor's figure struck at the
//     vendor's own price. Re-weighting them on a live price while the ratios
//     themselves stay at Yahoo's asof would be a hybrid of two moments that
//     neither source ever published;
//   * the indicators - RSI, the moving averages, ATR - which are functions of
//     daily closing bars and are supposed to be yesterday's.
const DERIVE = (function () {
  // Python's round() is half-to-even and JS's is half-away-from-zero. On
  // binary floats an exact tie essentially never occurs, so this is the same
  // function in practice - and `parity` compares with a tolerance of one unit
  // in the last place rather than demanding bit equality, which is what makes
  // the difference genuinely not matter.
  const R = (n, dp) => (n == null || !isFinite(n)) ? null
    : Math.round(n * Math.pow(10, dp)) / Math.pow(10, dp);

  /* ---- treemap.py:19-85, transcribed ---- */

  function worst(row, side) {
    const total = row.reduce((a, b) => a + b, 0);
    if (total <= 0 || side <= 0) return Infinity;
    return Math.max((side * side * Math.max(...row)) / (total * total),
                    (total * total) / (side * side * Math.min(...row)));
  }

  // A value that is null or <= 0 is DROPPED, never floored so it still draws.
  // The caller reports the drop; see allocation().
  function squarify(items, width, height) {
    width = width == null ? 100 : width;
    height = height == null ? 100 : height;
    let vals = items.filter((kv) => kv[1] != null && kv[1] > 0)
                    .map((kv) => [kv[0], Number(kv[1])])
                    .sort((a, b) => b[1] - a[1]);
    if (!vals.length) return [];

    const total = vals.reduce((a, kv) => a + kv[1], 0);
    const scale = (width * height) / total;
    vals = vals.map((kv) => [kv[0], kv[1] * scale]);

    const out = [];
    let x = 0, y = 0, w = width, h = height;
    while (vals.length) {
      const side = Math.min(w, h);
      let n = 1;
      while (n < vals.length) {
        const row = vals.slice(0, n).map((kv) => kv[1]);
        if (worst(vals.slice(0, n + 1).map((kv) => kv[1]), side) > worst(row, side)) break;
        n += 1;
      }
      const row = vals.slice(0, n);
      vals = vals.slice(n);
      const span = row.reduce((a, kv) => a + kv[1], 0);

      if (w >= h) {                       // row runs down the left edge
        const rw = h ? span / h : 0;
        let oy = y;
        for (const [key, v] of row) {
          const rh = span ? (v / span) * h : 0;
          out.push({key, x, y: oy, w: rw, h: rh});
          oy += rh;
        }
        x += rw; w -= rw;
      } else {                            // row runs across the top edge
        const rh = w ? span / w : 0;
        let ox = x;
        for (const [key, v] of row) {
          const rw = span ? (v / span) * w : 0;
          out.push({key, x: ox, y, w: rw, h: rh});
          ox += rw;
        }
        y += rh; h -= rh;
      }
    }
    return out;
  }

  /* ---- analyse.value_holdings, analyse.price_sanity ---- */

  // analyse.py:91-124 and 281-296. The per-row figures the live feed does not
  // itself supply. `price`, `value_eur`, `day_pct` and `stale` are written by
  // the caller from the quote; everything here is derived from those.
  function holdings(rows) {
    for (const h of rows) {
      const cost = h.cost_eur;
      // A cost of exactly zero yields null, not zero: a position transferred
      // in without a purchase price is unknowable, not flat. Truthiness is the
      // test in the original and it is the test here.
      h.pl_eur = cost ? R(h.value_eur - cost, 2) : null;
      h.pl_pct = cost ? R((h.value_eur / cost - 1) * 100, 2) : null;
      // 52-week high is a build-time fact the live feed does not carry, so
      // off_high moves only because the price did - which is the whole point
      // of the measure. Without a high it is null, never zero.
      h.off_high = (!h.stale && h.year_high)
        ? R((h.price / h.year_high - 1) * 100, 1) : null;
      // The broker's own valuation is the independent check that the symbol
      // mapping is right, and it only means anything against a live price.
      if (!h.stale && h.nordnet_mv_eur) {
        h.vs_nordnet_pct = R((h.value_eur / h.nordnet_mv_eur - 1) * 100, 1);
      }
    }
    return rows;
  }

  /* ---- overview.py, transcribed ---- */

  // overview.py:33-42. Falls back to the ISIN for the index funds that have no
  // Yahoo symbol: real positions with real value and no chart behind them.
  const ovKey = (h) => (h.yahoo && h.yahoo !== 'MISSING')
    ? h.yahoo : 'isin:' + h.isin;

  // overview.py:45-95. One row per name, custody accounts merged. P/L percent
  // is recomputed from the merged value and cost - it is NOT the average of
  // the two accounts' percentages.
  function fold(rows, klassByKey) {
    const out = new Map();
    for (const row of rows) {
      const key = ovKey(row);
      let cur = out.get(key);
      if (!cur) {
        const sym = row.yahoo;
        cur = {key, sym: (sym && sym !== 'MISSING') ? sym : null,
               ticker: row.ticker || row.tunnus || key, name: row.name,
               klass: klassByKey ? klassByKey.get(key) : null,
               bucket: row.bucket, accounts: [],
               value_eur: 0, cost_eur: 0,
               // The same symbol has the same day move in both accounts, so
               // this is carried across rather than combined. Null stays null.
               day_pct: row.day_pct == null ? null : row.day_pct,
               price: row.price, units: 0};
        out.set(key, cur);
      }
      cur.value_eur += row.value_eur || 0;
      cur.cost_eur += row.cost_eur || 0;
      cur.units += row.units || 0;
      if (row.day_pct != null) cur.day_pct = row.day_pct;
      if (row.account && !cur.accounts.includes(row.account)) cur.accounts.push(row.account);
    }
    const list = [];
    for (const cur of out.values()) {
      const value = R(cur.value_eur, 2), cost = R(cur.cost_eur, 2);
      cur.value_eur = value; cur.cost_eur = cost;
      cur.units = R(cur.units, 4);
      cur.pl_eur = cost ? R(value - cost, 2) : null;
      cur.pl_pct = cost ? R((value / cost - 1) * 100, 2) : null;
      cur.accounts.sort();
      list.push(cur);
    }
    list.sort((a, b) => b.value_eur - a.value_eur);
    return list;
  }

  // overview.py:98-125. Measured over the part of the book that HAS a day
  // move, against what that same part closed at - never against the whole
  // book, which would understate every day by however much is unpriced.
  function dayMove(rows) {
    const priced = rows.filter((r) => r.day_pct != null);
    const quiet = rows.filter((r) => r.day_pct == null);
    const value = priced.reduce((a, r) => a + r.value_eur, 0);
    // value / (1 + d), NOT value * (1 - d). The two agree on a quiet day and
    // drift on exactly the days you would want the number to be right.
    const opened = priced.filter((r) => r.day_pct !== -100)
      .reduce((a, r) => a + r.value_eur / (1 + r.day_pct / 100), 0);
    const moved = value - opened;
    const quietValue = quiet.reduce((a, r) => a + r.value_eur, 0);
    return {
      value_eur: R(moved, 2),
      pct: opened ? R(moved / opened * 100, 2) : null,
      n_priced: priced.length,
      n_quiet: quiet.length,
      quiet_eur: R(quietValue, 2),
      covered_pct: (value || quiet.length)
        ? R(value / (value + quietValue) * 100, 1) : 0,
    };
  }

  // overview.py:128-160. Area is weight and nothing else is implied, so the
  // whole map is relaid on every tick - a tile whose label says 8.2% while its
  // area is last hour's 8.0% is a picture that lies quietly.
  function allocation(rows, total) {
    total = total == null ? rows.reduce((a, r) => a + r.value_eur, 0) : total;
    const byKey = new Map(rows.map((r) => [r.key, r]));
    const tiles = squarify(rows.map((r) => [r.key, r.value_eur])).map((rect) => {
      const row = byKey.get(rect.key);
      return Object.assign({}, rect, {
        sym: row.sym, ticker: row.ticker, name: row.name,
        klass: row.klass, bucket: row.bucket, value_eur: row.value_eur,
        weight_pct: total ? R(row.value_eur / total * 100, 2) : 0,
        pl_pct: row.pl_pct, pl_eur: row.pl_eur, day_pct: row.day_pct,
      });
    });
    const drawn = tiles.reduce((a, t) => a + t.value_eur, 0);
    return {tiles, n: tiles.length, value_eur: R(drawn, 2),
            n_undrawn: rows.length - tiles.length,
            undrawn_eur: R(total - drawn, 2)};
  }

  // overview.py:163-182. Percent is the right unit here; euros is the right
  // unit in contributors. Giving both the same answer is how a dashboard ends
  // up saying nothing twice.
  function movers(rows, limit) {
    limit = limit || 5;
    const priced = rows.filter((r) => r.day_pct != null)
                       .sort((a, b) => b.day_pct - a.day_pct);
    const trim = priced.map((r) => ({
      sym: r.sym, ticker: r.ticker, name: r.name, day_pct: r.day_pct,
      value_eur: r.value_eur,
      day_eur: r.day_pct !== -100
        ? R(r.value_eur - r.value_eur / (1 + r.day_pct / 100), 2) : null}));
    return {
      up: trim.filter((r) => r.day_pct > 0).slice(0, limit),
      down: trim.slice().reverse().filter((r) => r.day_pct < 0).slice(0, limit),
      n_priced: priced.length,
      n_quiet: rows.filter((r) => r.day_pct == null).length};
  }

  // overview.py:185-211. Shares are taken against total ABSOLUTE movement, so
  // a winner and a loser of the same size both read as meaningful rather than
  // cancelling into a denominator of nearly zero.
  function contributors(rows, limit) {
    limit = limit || 6;
    const known = rows.filter((r) => r.pl_eur != null);
    const gross = known.reduce((a, r) => a + Math.abs(r.pl_eur), 0);
    const trim = known.slice().sort((a, b) => b.pl_eur - a.pl_eur).map((r) => ({
      sym: r.sym, ticker: r.ticker, name: r.name, pl_eur: r.pl_eur,
      pl_pct: r.pl_pct, value_eur: r.value_eur,
      share_pct: gross ? R(Math.abs(r.pl_eur) / gross * 100, 1) : 0}));
    return {
      best: trim.filter((r) => r.pl_eur > 0).slice(0, limit),
      worst: trim.slice().reverse().filter((r) => r.pl_eur < 0).slice(0, limit),
      n_known: known.length, n_unknown: rows.length - known.length};
  }

  /* ---- exposure.py: the part that needs only position values ---- */

  // exposure.py:94-116. Merged by ISIN, NOT by account: carrying the split
  // through would double every name held in both and make the look-through
  // wrong in a way that looks like concentration.
  function positions(rows, meta) {
    const merged = new Map();
    for (const h of rows) {
      const isin = h.isin;
      if (!merged.has(isin)) {
        const sym = h.yahoo;
        merged.set(isin, {isin, symbol: (sym && sym !== 'MISSING') ? sym : null,
                          name: h.name || '',
                          klass: (meta && meta.klass.get(isin)) || 'stock',
                          value_eur: 0});
      }
      merged.get(isin).value_eur += h.value_eur || 0;
    }
    return [...merged.values()].sort((a, b) => b.value_eur - a.value_eur);
  }

  // exposure.py:412-439. Measured on positions, deliberately NOT on the
  // look-through: only part of each fund is disclosed, and unplaced mass would
  // read as diversification. A falsy value is DROPPED, not counted as a
  // position worth nothing - which changes n and hhi, not just the sum.
  function concentration(pos, total) {
    const values = pos.map((p) => p.value_eur).filter((v) => v)
                      .sort((a, b) => b - a);
    if (!values.length || !total) {
      return {n: 0, top1_pct: 0, top5_pct: 0, top10_pct: 0, hhi: 0, effective_n: 0};
    }
    const weights = values.map((v) => v / total);
    const sum = (arr) => arr.reduce((a, b) => a + b, 0);
    const hhi = sum(weights.map((w) => w * w));
    return {
      n: values.length,
      top1_pct: R(sum(weights.slice(0, 1)) * 100, 1),
      top5_pct: R(sum(weights.slice(0, 5)) * 100, 1),
      top10_pct: R(sum(weights.slice(0, 10)) * 100, 1),
      hhi: R(hhi, 4),
      // From the UNROUNDED hhi, as in the original.
      effective_n: hhi ? R(1 / hhi, 1) : 0,
    };
  }

  // exposure.py:444-480. A fund whose TER is not published is not treated as
  // free: its value counts against coverage, so the euro figure reads as a
  // floor rather than a total.
  function fees(pos, terBySymbol, total) {
    let annual = 0, covered = 0, fundValue = 0;
    const rows = [];
    for (const p of pos) {
      if (p.klass !== 'fund' || !p.value_eur) continue;
      const value = p.value_eur;
      fundValue += value;
      const ter = terBySymbol.has(p.symbol) ? terBySymbol.get(p.symbol) : null;
      const cost = ter != null ? value * ter / 100 : null;
      if (cost != null) { annual += cost; covered += value; }
      rows.push({symbol: p.symbol, name: p.name, value_eur: R(value, 2),
                 ter_pct: ter, annual_eur: cost != null ? R(cost, 2) : null});
    }
    rows.sort((a, b) => (b.annual_eur || 0) - (a.annual_eur || 0));
    return {rows, annual_eur: R(annual, 2), fund_value_eur: R(fundValue, 2),
            covered_eur: R(covered, 2),
            unresolved_eur: R(fundValue - covered, 2),
            resolved_pct: fundValue ? R(covered / fundValue * 100, 1) : 0,
            // Two denominators, two different questions: what the funds cost
            // as funds, and what they cost as a share of everything.
            sleeve_ter_pct: covered ? R(annual / covered * 100, 3) : null,
            book_ter_pct: total ? R(annual / total * 100, 3) : null};
  }

  // exposure.py:529-547.
  function funds(pos, total, metaBySymbol) {
    const out = [];
    for (const p of pos) {
      if (p.klass !== 'fund') continue;
      const m = metaBySymbol.get(p.symbol) || {};
      out.push({symbol: p.symbol, name: p.name, value_eur: R(p.value_eur, 2),
                weight_pct: total ? R(p.value_eur / total * 100, 2) : 0,
                ter_pct: m.ter_pct == null ? null : m.ter_pct,
                n_disclosed: m.n_disclosed || 0,
                disclosed_pct: m.disclosed_pct == null ? null : m.disclosed_pct,
                has_sectors: !!m.has_sectors});
    }
    out.sort((a, b) => b.value_eur - a.value_eur);
    return out;
  }

  /* ---- exposure.py: the look-through, which needs the composition ---- */

  // Every breakdown below is a sum of position value times a published weight
  // that does not move with a price, so it restates exactly - PROVIDED the
  // weights are here. They arrive as D.lookthrough, written by
  // exposure.inputs(). Without it these are not called and the page keeps
  // saying "as at build"; see lookMark().

  const SECTOR_ALIASES = {realestate: 'real_estate', real_estate: 'real_estate'};
  const SUFFIX_COUNTRY = {
    AS: 'Netherlands', BR: 'Belgium', CO: 'Denmark', DE: 'Germany',
    F: 'Germany', HE: 'Finland', HK: 'Hong Kong', IR: 'Ireland',
    KQ: 'South Korea', KS: 'South Korea', L: 'United Kingdom', LS: 'Portugal',
    MC: 'Spain', MI: 'Italy', NS: 'India', OL: 'Norway', PA: 'France',
    SI: 'Singapore', ST: 'Sweden', SW: 'Switzerland', T: 'Japan',
    TA: 'Israel', TO: 'Canada', TW: 'Taiwan', VI: 'Austria', WA: 'Poland',
  };

  // exposure.py:56-58. str.capitalize() lowercases the tail; so does this.
  const label = (key) => String(key).split('_')
    .map((p) => p ? p[0].toUpperCase() + p.slice(1).toLowerCase() : '').join(' ');

  // exposure.py:61-66.
  function sectorKey(name) {
    if (!name) return null;
    const key = String(name).trim().toLowerCase().replace(/ /g, '_').replace(/-/g, '_');
    return (Object.prototype.hasOwnProperty.call(SECTOR_ALIASES, key)
      ? SECTOR_ALIASES[key] : key) || null;
  }

  // exposure.py:69-83. A bare ticker is a US listing by Yahoo's convention; a
  // bare numeric code is not, and resolves to null rather than to America.
  function countryFor(symbol) {
    if (!symbol) return null;
    const text = String(symbol).trim();
    if (text.includes('.')) {
      const sfx = text.slice(text.lastIndexOf('.') + 1).toUpperCase();
      return Object.prototype.hasOwnProperty.call(SUFFIX_COUNTRY, sfx)
        ? SUFFIX_COUNTRY[sfx] : null;
    }
    return /^\p{L}+$/u.test(text.replace(/-/g, '')) ? 'United States' : null;
  }

  // exposure.py:119-136. Rows keep the buckets' insertion order and then sort
  // stably on the ROUNDED value, which is what Python sorts on too.
  function breakdown(buckets, unresolved, total, extra) {
    const rows = [];
    let placed = 0;
    for (const [key, value] of buckets) {
      rows.push({key, label: label(key), value_eur: R(value, 2),
                 pct: total ? R(value / total * 100, 2) : 0});
      placed += value;
    }
    rows.sort((a, b) => b.value_eur - a.value_eur);
    return Object.assign({rows, value_eur: R(placed, 2),
                          unresolved_eur: R(unresolved, 2),
                          resolved_pct: total ? R(placed / total * 100, 1) : 0,
                          n: rows.length}, extra || {});
  }

  const add = (m, k, v) => m.set(k, (m.get(k) || 0) + v);

  // exposure.py:141-180. Fund cash is left unresolved, never scaled away.
  function sectors(pos, LT, total) {
    const buckets = new Map(), direct = new Map(), indirect = new Map();
    let unresolved = 0;
    for (const p of pos) {
      const value = p.value_eur;
      if (!value) continue;
      if (p.klass === 'fund') {
        const weights = (LT.funds[p.symbol] || {}).sectors || {};
        let placed = 0;
        for (const [raw, pct] of Object.entries(weights)) {
          const key = sectorKey(raw);
          if (!key || !pct) continue;
          const part = value * pct / 100;
          add(buckets, key, part); add(indirect, key, part);
          placed += part;
        }
        unresolved += Math.max(0, value - placed);
      } else {
        const key = sectorKey((LT.stocks[p.symbol] || {}).sector);
        if (key) { add(buckets, key, value); add(direct, key, value); }
        else unresolved += value;
      }
    }
    const table = breakdown(buckets, unresolved, total);
    for (const r of table.rows) {
      r.direct_eur = R(direct.get(r.key) || 0, 2);
      r.indirect_eur = R(indirect.get(r.key) || 0, 2);
    }
    return table;
  }

  // exposure.py:185-210. Funds report no industries, so they are unresolved
  // here by construction.
  function industries(pos, LT, total) {
    const buckets = new Map();
    let unresolved = 0;
    for (const p of pos) {
      const value = p.value_eur;
      if (!value) continue;
      if (p.klass === 'fund') { unresolved += value; continue; }
      const name = (LT.stocks[p.symbol] || {}).industry;
      if (name) add(buckets, name, value);
      else unresolved += value;
    }
    const table = breakdown(buckets, unresolved, total);
    for (const r of table.rows) r.label = r.key;
    return table;
  }

  // exposure.py:215-256. Domicile for a stock, listing venue for a fund's
  // constituent - two proxies on one axis, and the basis line says so.
  function geography(pos, LT, total) {
    const buckets = new Map();
    let unresolved = 0;
    for (const p of pos) {
      const value = p.value_eur;
      if (!value) continue;
      if (p.klass === 'fund') {
        let placed = 0;
        for (const line of (LT.funds[p.symbol] || {}).top_holdings || []) {
          const country = countryFor(line.symbol);
          const pct = line.pct || 0;
          if (!country || !pct) continue;
          const part = value * pct / 100;
          add(buckets, country, part);
          placed += part;
        }
        unresolved += Math.max(0, value - placed);
      } else {
        const country = (LT.stocks[p.symbol] || {}).country;
        if (country) add(buckets, country, value);
        else unresolved += value;
      }
    }
    const table = breakdown(buckets, unresolved, total,
      {basis: 'stated domicile for directly-held stocks, '
            + 'listing venue for fund constituents'});
    for (const r of table.rows) r.label = r.key;
    return table;
  }

  // exposure.py:261-334. The indirect side is a floor: ten constituents per
  // fund are disclosed, and resolved_pct says how much of the book got named.
  function names(pos, LT, total) {
    const rows = new Map();
    let resolved = 0;
    const touch = (symbol, name) => {
      if (!rows.has(symbol)) {
        rows.set(symbol, {symbol, name: name || symbol,
                          direct_eur: 0, indirect_eur: 0, via: []});
      } else if (name && rows.get(symbol).name === symbol) {
        rows.get(symbol).name = name;
      }
      return rows.get(symbol);
    };
    for (const p of pos) {
      const value = p.value_eur;
      if (!value) continue;
      if (p.klass !== 'fund') {
        if (p.symbol) { touch(p.symbol, p.name).direct_eur += value; resolved += value; }
        continue;
      }
      for (const line of (LT.funds[p.symbol] || {}).top_holdings || []) {
        const child = line.symbol, pct = line.pct || 0;
        if (!child || !pct) continue;
        const part = value * pct / 100;
        const row = touch(child, line.name);
        row.indirect_eur += part;
        row.via.push({fund: p.symbol, pct: R(pct, 2), value_eur: R(part, 2)});
        resolved += part;
      }
    }
    const out = [];
    for (const r of rows.values()) {
      const t = r.direct_eur + r.indirect_eur;
      const s = LT.stocks[r.symbol] || {};
      r.via.sort((a, b) => b.value_eur - a.value_eur);
      out.push({
        symbol: r.symbol, name: r.name,
        direct_eur: R(r.direct_eur, 2), indirect_eur: R(r.indirect_eur, 2),
        value_eur: R(t, 2),
        pct: total ? R(t / total * 100, 2) : 0,
        direct_pct: total ? R(r.direct_eur / total * 100, 2) : 0,
        indirect_pct: total ? R(r.indirect_eur / total * 100, 2) : 0,
        held_both_ways: r.direct_eur > 0 && r.indirect_eur > 0,
        via: r.via,
        sector: sectorKey(s.sector),
        industry: s.industry || null,
        country: s.country || countryFor(r.symbol)});
    }
    out.sort((a, b) => b.value_eur - a.value_eur);
    return {rows: out, n: out.length, value_eur: R(resolved, 2),
            unresolved_eur: R(Math.max(0, total - resolved), 2),
            resolved_pct: total ? R(resolved / total * 100, 1) : 0,
            n_both_ways: out.filter((r) => r.held_both_ways).length};
  }

  // exposure.py:339-410. Every figure is a floor; disclosed_pct per side says
  // how much of each fund was visible at all.
  function overlap(pos, LT, total) {
    const lines = new Map(), sizes = new Map();
    for (const p of pos) {
      if (p.klass !== 'fund' || !p.symbol || !p.value_eur) continue;
      const m = new Map();
      for (const line of (LT.funds[p.symbol] || {}).top_holdings || []) {
        const child = line.symbol, pct = line.pct || 0;
        if (child && pct) add(m, child, pct);
      }
      if (m.size) { lines.set(p.symbol, m); sizes.set(p.symbol, p.value_eur); }
    }
    const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
    const sum = (arr) => arr.reduce((a, b) => a + b, 0);
    const keys = [...lines.keys()].sort(cmp);
    const pairs = [];
    keys.forEach((a, i) => {
      for (const b of keys.slice(i + 1)) {
        const A = lines.get(a), B = lines.get(b);
        // Same tiebreak as the Python: weight, then symbol.
        const shared = [...A.keys()].filter((c) => B.has(c))
          .sort((x, y) => ((B.get(y) + A.get(y)) - (A.get(x) + B.get(x))) || cmp(x, y));
        if (!shared.length) continue;
        const eur = sum(shared.map((c) =>
          sizes.get(a) * A.get(c) / 100 + sizes.get(b) * B.get(c) / 100));
        const share = (F) => {
          const all = sum([...F.values()]);
          return all ? R(sum(shared.map((c) => F.get(c))) / all * 100, 1) : 0;
        };
        pairs.push({a, b, shared, n_shared: shared.length,
                    n_a: A.size, n_b: B.size,
                    a_disclosed_in_shared_pct: share(A),
                    b_disclosed_in_shared_pct: share(B),
                    a_disclosed_pct: R(sum([...A.values()]), 1),
                    b_disclosed_pct: R(sum([...B.values()]), 1),
                    value_eur: R(eur, 2),
                    pct: total ? R(eur / total * 100, 2) : 0});
      }
    });
    pairs.sort((x, y) => y.value_eur - x.value_eur);
    return {pairs, n_pairs: pairs.length, n_funds: lines.size,
            n_substantial: pairs.filter((p) => Math.max(
              p.a_disclosed_in_shared_pct, p.b_disclosed_in_shared_pct) >= 50).length};
  }

  /* ---- analyse.coverage: analyse.py:488-591 ---- */

  // Coverage rows are per ISIN per account, one for one with D.holdings, so
  // the join is on both. `covered` is a Notion and config fact and is left
  // alone; what moves with a price is the euro, the weight and the drift.
  //
  // The join key is the account LABEL, not the account number: the coverage
  // table deliberately does not carry the number, and D.holdings does. Keying
  // on `account_no` therefore missed every single row - and because a missed
  // row just keeps Python's value, the parity check passed with a perfect
  // score against a function that wrote nothing at all. Caught by halving a
  // position and watching the coverage weights not move. `unmatched` is
  // returned so a future miss is a number on screen rather than silence.
  function coverage(cov, rows) {
    // The `or 1.0` floor is the original's, and it is load-bearing: an empty
    // book yields percentages against one euro rather than a divide by zero.
    const total = rows.reduce((a, h) => a + (h.value_eur || 0), 0) || 1;
    const by = new Map();
    for (const h of rows) by.set(h.isin + '|' + h.account, h);
    let unmatched = 0;
    for (const r of cov.rows || []) {
      const h = by.get(r.isin + '|' + r.account);
      if (!h) { unmatched += 1; continue; }   // no holding, nothing to restate
      r.value_eur = h.value_eur;
      r.weight_pct = R((h.value_eur || 0) / total * 100, 2);
      if (r.target_weight_pct != null) {
        r.drift_pts = R(r.weight_pct - r.target_weight_pct, 2);
      }
    }
    (cov.rows || []).sort((a, b) => (b.value_eur || 0) - (a.value_eur || 0));
    const uncovered = (cov.rows || []).filter((r) => !r.covered);
    const uncoveredValue = uncovered.reduce((a, r) => a + (r.value_eur || 0), 0);
    cov.value_total_eur = R(total, 2);
    cov.value_uncovered_eur = R(uncoveredValue, 2);
    // From the raw sum, not from the rounded euro figure above.
    cov.pct_uncovered = R(uncoveredValue / total * 100, 1);
    return unmatched;
  }

  /* ---- analyse.join_watchlist: the price-derived half ---- */

  // analyse.py:348-368 and 450-453. `price_at_eval`, `target`, `pe`,
  // `upside_at_eval` and everything else written down on the board are
  // RECORDED figures and are not touched here - CLAUDE.md rule 3. Only the
  // comparisons against today's price are restated.
  //
  // `live.pe`, `live.pb`, `live.ps` and `live.market_cap` are deliberately
  // left alone too. They are Yahoo's own figures at Yahoo's own asof, and the
  // price they were struck against is not in this payload - one holding quotes
  // in pence and its P/E is a hundred times the naive price-over-EPS, which is
  // exactly how a plausible-looking rescale goes wrong. They carry an asof and
  // they keep it.
  function watchlist(items) {
    for (const w of items) {
      const price = w.price_now, target = w.target, ev = w.price_at_eval;
      w.stale_price = price == null;
      w.drift_pct = (price && ev) ? R((price / ev - 1) * 100, 2) : null;
      w.upside_now = (price && target) ? R((target / price - 1) * 100, 1) : null;
      // Subtracts two already-rounded 1dp figures and rounds again, as the
      // original does. Reproduce it exactly or the decay alert quantises into
      // a different bucket than the one Telegram reported.
      w.upside_decay_pts = (w.upside_now != null && w.upside_at_eval != null)
        ? R(w.upside_now - w.upside_at_eval, 1) : null;
      const level = w.trigger_level;
      if (level && price) {
        w.trigger_gap_pct = R((level / price - 1) * 100, 1);
        w.trigger_hit = w.trigger_kind === 'below' ? price <= level : price >= level;
      } else {
        w.trigger_gap_pct = null;
        w.trigger_hit = null;
      }
      // In Yahoo's unit; price is in the board's (analyse.attach_fundamentals).
      const street = (w.live || {}).street_target * (w.price_scale || 1);
      w.street_upside_pct = (street && price)
        ? R((street / price - 1) * 100, 1) : null;
    }
    return items;
  }

  /* ---- reporting.py: the weights, which are value over value ---- */

  // reporting.py:134-222. A different denominator on purpose: it folds by
  // Yahoo symbol and DROPS anything without one, so the index funds are not in
  // its base. Restating it on the book's total instead would silently change
  // what every weight in that table means.
  function reporting(rep, rows) {
    const byKey = new Map();
    for (const h of rows) {
      const sym = h.yahoo;
      if (!sym || sym === 'MISSING') continue;
      byKey.set(sym, (byKey.get(sym) || 0) + (h.value_eur || 0));
    }
    const total = [...byKey.values()].reduce((a, v) => a + v, 0) || 0;
    // Counted, not shrugged off - for the same reason coverage counts. A join
    // that quietly matches nothing leaves Python's numbers in place and looks
    // exactly like a join that worked.
    let unmatched = 0;
    const restate = (list) => {
      for (const r of list || []) {
        const v = byKey.has(r.symbol || r.sym) ? byKey.get(r.symbol || r.sym) : null;
        if (v == null) { unmatched += 1; continue; }
        r.value_eur = R(v, 2);
        r.weight_pct = (total && v) ? R(v / total * 100, 2) : 0;
      }
    };
    const cal = rep.calendar || {};
    restate(cal.rows); restate(cal.unknown); restate(rep.latest);
    // reporting.py:174-186. The headline "n prints, x% of the book" sat on the
    // Overview and the Earnings section as the build's share while every row
    // under it moved.
    if (cal.rows) {
      const ahead = cal.rows.reduce((a, r) => a + (byKey.get(r.symbol || r.sym) || 0), 0);
      cal.value_ahead_eur = R(ahead, 2);
      cal.pct_ahead = total ? R(ahead / total * 100, 1) : 0;
    }
    (cal.rows || []).sort((a, b) => String(a.date).localeCompare(String(b.date))
                                    || b.weight_pct - a.weight_pct);
    (cal.unknown || []).sort((a, b) => b.weight_pct - a.weight_pct);
    (rep.latest || []).sort((a, b) => String(b.date).localeCompare(String(a.date))
                                      || b.weight_pct - a.weight_pct);
    return unmatched;
  }

  /* ---- analyse.alerts: the flags, restated on the live price ---- */

  // analyse.py alerts(). Until this existed every flag on the page - the tape
  // count, the rail dots, the Flagged filter, the Overview card, the pane's
  // FLAGS - was the build's list, while the numbers beside them moved. A name
  // could read HIT in its own pane with no trigger flag anywhere, and a flag
  // could go on claiming "3.1% from its trigger" of a price an hour gone.
  //
  // Only the kinds analyse.alerts writes are rebuilt, in its order and with
  // its wording to the character, because the same sentence goes to Telegram
  // and the two must never disagree about what a flag says. Health problems
  // ride in that list unchanged. reporting.alerts and activity.alerts, which
  // cockpit.py appends after the sort, are kept exactly as built: they read
  // the calendar and the export diff, not a price.
  const OWN = ['coverage:', 'weight-drift:', 'trigger-hit:', 'check-due:',
               'inflection:', 'trigger-near:', 'decay:', 'multiple-stale:'];
  let BUILT_ALERTS = null;

  // Python's formatting, not JS's. They differ in exactly the places a flag
  // lives: a tie rounds to even in Python and away from zero in toFixed, and
  // str(120.0) is "120.0" where String(120) is "120".
  const pyFixed = (x, d) => {
    const m = Math.pow(10, d), t = x * m;
    return Math.abs(t % 1) === 0.5 ? (2 * Math.round(t / 2) / m).toFixed(d) : x.toFixed(d);
  };
  const pyRound = (x) => Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : Math.round(x);
  const pyComma = (x) => pyFixed(x, 0).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const pySigned = (x, d) => (x >= 0 ? '+' : '') + pyFixed(x, d);
  const pyG = (x) => String(Number(x.toPrecision(6)));
  const pyStr = (x) => Number.isInteger(x) ? x.toFixed(1) : String(x);

  // analyse.days_until. Calendar days, both ends read as dates - no clock and
  // no timezone, so the answer is the same as Python's on the same day.
  const dayNum = (s) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || '');
    return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) / 86400000 : null;
  };
  const daysUntil = (s, today) => {
    const a = dayNum(s), b = dayNum(today);
    return a == null || b == null ? null : a - b;
  };

  function alerts(items, cover, th, today) {
    if (!BUILT_ALERTS) BUILT_ALERTS = (D.alerts || []).slice();
    // An older payload without these thresholds cannot be restated honestly.
    // It keeps its build list, and STATS says so.
    const need = ['weight_drift_pct', 'multiple_drift_pct', 'check_soon_days',
                  'trigger_near_pct', 'decay_alert_pts'];
    if (!th || need.some((k) => th[k] == null)) return false;

    for (const w of items) {
      w.days_to_check = daysUntil(w.next_check, today);
      w.days_to_inflection = daysUntil(w.inflection_date, today);
      const since = daysUntil(w.last_eval, today);
      w.days_since_eval = since == null ? null : -since;
    }

    const found = [];
    if (cover && cover.n_uncovered) {
      const biggest = (cover.rows || []).filter((r) => !r.covered).slice(0, 3);
      found.push({level: 'warning', key: `coverage:${cover.n_uncovered}`,
        title: `${pyFixed(cover.pct_uncovered, 0)}% of the book ` +
               `(${cover.n_uncovered} holdings) is not being monitored`,
        detail: biggest.map((r) => `${r.ticker} EUR ${pyComma(r.value_eur)} - ${r.gap}`)
                       .join('; ')});
    }
    for (const r of (cover || {}).rows || []) {
      const drift = r.drift_pts;
      if (drift == null || Math.abs(drift) <= th.weight_drift_pct) continue;
      if (r.target_basis === 'placeholder') continue;
      const side = drift > 0 ? 'above' : 'below';
      found.push({level: 'warning', key: `weight-drift:${r.ticker}:${pyRound(drift)}`,
        title: `${r.ticker} is ${pyFixed(Math.abs(drift), 1)} pts ${side} its ` +
               `${pyG(r.target_weight_pct)}% target weight`,
        detail: `EUR ${pyComma(r.value_eur)}, ${pyFixed(r.weight_pct, 1)}% of ` +
                `the book against a ${pyG(r.target_weight_pct)}% target. ` +
                `The band is ${pyG(th.weight_drift_pct)} pts.`});
    }
    for (const w of items) {
      if (!w.trigger_hit) continue;
      found.push({level: 'critical', key: `trigger-hit:${w.ticker}`,
        title: `${w.ticker} has hit its written trigger`,
        detail: `Live ${pyFixed(w.price_now, 2)} ${w.ccy} vs trigger ` +
                `${pyStr(w.trigger_level)}. ${w.trigger}`});
    }
    for (const w of items) {
      const days = w.days_to_check;
      if (days == null || days < 0 || days > th.check_soon_days) continue;
      found.push({level: 'warning', key: `check-due:${w.ticker}:${w.next_check}`,
        title: `${w.ticker} catalyst in ${days} days (${w.next_check})`,
        detail: w.trigger || ''});
    }
    for (const w of items) {
      const days = w.days_to_inflection;
      if (days == null || days < 0 || days > th.check_soon_days) continue;
      const event = (w.inflection_event || '').trim();
      found.push({level: 'warning', key: `inflection:${w.ticker}:${w.inflection_date}`,
        title: `${w.ticker}: ${event || 'inflection event'} in ` +
               `${days} days (${w.inflection_date})`,
        detail: w.thesis || w.trigger || 'No thesis written for this name.'});
    }
    for (const w of items) {
      const gap = w.trigger_gap_pct;
      if (gap == null || w.trigger_hit || Math.abs(gap) > th.trigger_near_pct) continue;
      found.push({level: 'warning', key: `trigger-near:${w.ticker}`,
        title: `${w.ticker} is ${pyFixed(Math.abs(gap), 1)}% from its trigger`,
        detail: `Live ${pyFixed(w.price_now, 2)} ${w.ccy}, ` +
                `trigger at ${pyStr(w.trigger_level)}.`});
    }
    for (const w of items) {
      const decay = w.upside_decay_pts;
      if (decay == null || Math.abs(decay) < th.decay_alert_pts) continue;
      found.push({level: decay < 0 ? 'warning' : 'good',
        key: `decay:${w.ticker}:${pyRound(decay)}`,
        title: `${w.ticker} upside ${decay > 0 ? 'widened' : 'narrowed'} ` +
               `${pyFixed(w.upside_at_eval, 1)}% -> ${pyFixed(w.upside_now, 1)}%`,
        detail: `Price moved ${pySigned(w.drift_pct, 1)}% since the ` +
                `${w.last_eval} check. The board still says ` +
                `${pyFixed(w.upside_at_eval, 1)}%.`});
    }
    for (const w of items) {
      const drift = w.pe_drift_pct;
      if (drift == null || Math.abs(drift) < th.multiple_drift_pct) continue;
      const live = (w.live || {}).pe;
      found.push({level: 'warning', key: `multiple-stale:${w.ticker}:${pyRound(drift / 10)}`,
        title: `${w.ticker}: today's P/E is ${pyFixed(Math.abs(drift), 0)}% ` +
               `${drift > 0 ? 'above' : 'below'} the board's`,
        detail: `The board says ${pyG(w.pe)}` +
                (w.last_eval ? `, typed at the ${w.last_eval} check` : ' and never dated') +
                `; Yahoo says ${pyFixed(live, 1)} today. The multiple in that ` +
                'write-up is not the one you own now.'});
    }
    for (const a of BUILT_ALERTS) if (a.health) found.push(a);

    const order = {critical: 0, warning: 1, good: 2};
    const rank = (a) => (a.level in order ? order[a.level] : 3);
    // Array.prototype.sort is stable, as Python's sort is.
    found.sort((a, b) => rank(a) - rank(b));
    const appended = BUILT_ALERTS.filter((a) => !a.health &&
      !OWN.some((p) => String(a.key || '').startsWith(p)));
    // In place, for the same reason as D.overview: anything holding D.alerts
    // must see the restated list, not the boot-time one.
    D.alerts = D.alerts || [];
    D.alerts.length = 0;
    D.alerts.push(...found, ...appended);
    return true;
  }

  // Today on this machine's calendar, as Python's date.today() reads it.
  const localToday = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-` +
           String(d.getDate()).padStart(2, '0');
  };

  /* ---- the one entry point ---- */

  // Static facts the recompute needs and cannot derive: which ISIN is a fund,
  // and what each fund's published TER and disclosure are. Read once, from the
  // build-time payload, because none of them move with a price.
  let META = null, STATS = null;
  function meta() {
    if (META) return META;
    const klass = new Map();
    for (const r of (D.coverage || {}).rows || []) klass.set(r.isin, r.klass);
    const klassByKey = new Map();
    for (const h of D.holdings || []) klassByKey.set(ovKey(h), klass.get(h.isin));
    const ter = new Map(), fundMeta = new Map();
    for (const f of (D.exposure || {}).funds || []) {
      ter.set(f.symbol, f.ter_pct == null ? null : f.ter_pct);
      fundMeta.set(f.symbol, f);
    }
    META = {klass, klassByKey, ter, fundMeta};
    return META;
  }

  // Recompute every price-derived figure in D from D.holdings, in place.
  //
  // Order matters once: the per-holding figures are restated first, because
  // value_eur is rounded to the cent BEFORE anything downstream divides by it.
  // Deriving a weight from the unrounded product disagrees with Python in the
  // last digit across several dozen fields at once.
  function all(today) {
    today = today || localToday();
    const M = meta();
    const rows = D.holdings || [];
    holdings(rows);

    // render.py:28-39. Note pl_pct falls back to 0, not null, here - and to
    // null on a single holding. Two fallbacks for the same condition, both
    // transcribed rather than harmonised, because harmonising them here would
    // put a number on screen that the Telegram message does not agree with.
    // Assigned INTO the existing objects, never over them. The page captures
    // `const OV = D.overview` once at module scope; swapping in a fresh object
    // would leave every one of those captures pointing at the boot-time answer
    // while D itself moved on - which is the exact failure this whole module
    // exists to remove, reintroduced one level up.
    const value = R(rows.reduce((a, h) => a + (h.value_eur || 0), 0), 2);
    const cost = R(rows.reduce((a, h) => a + (h.cost_eur || 0), 0), 2);
    D.totals = D.totals || {};
    Object.assign(D.totals, {
      value_eur: value, cost_eur: cost, pl_eur: R(value - cost, 2),
      pl_pct: cost ? R((value / cost - 1) * 100, 2) : 0,
    });

    const folded = fold(rows, M.klassByKey);
    const ovTotal = folded.reduce((a, r) => a + r.value_eur, 0);
    D.overview = D.overview || {};
    Object.assign(D.overview, {
      rows: folded, n: folded.length, value_eur: R(ovTotal, 2),
      day: dayMove(folded), allocation: allocation(folded, ovTotal),
      movers: movers(folded), contributors: contributors(folded),
      totals: D.totals,
    });

    const pos = positions(rows, M);
    const expTotal = pos.reduce((a, p) => a + p.value_eur, 0);
    D.exposure = D.exposure || {};
    Object.assign(D.exposure, {
      total_eur: R(expTotal, 2), n_positions: pos.length,
      concentration: concentration(pos, expTotal),
      fees: fees(pos, M.ter, expTotal),
      funds: funds(pos, expTotal, M.fundMeta),
    });
    // Multiples are deliberately not in this list: see the note at the top of
    // this module. Only the linear breakdowns follow a price.
    const LT = D.lookthrough;
    if (LT) {
      Object.assign(D.exposure, {
        sectors: sectors(pos, LT, expTotal),
        industries: industries(pos, LT, expTotal),
        geography: geography(pos, LT, expTotal),
        names: names(pos, LT, expTotal),
        overlap: overlap(pos, LT, expTotal),
      });
    }

    // Every join's misses, kept. A recompute that silently restates nothing is
    // indistinguishable from one that restates everything correctly - both
    // leave Python's numbers on screen - so the only way to tell them apart is
    // to count. STATS is what `health()` reads and what the mutation harness
    // asserts on.
    STATS = {
      holdings: rows.length,
      folded: folded.length,
      positions: pos.length,
      // A fund whose TER is unresolved is a known gap, not a miss: it is
      // already reported as unresolved_eur. This counts a fund the fees table
      // could not find at all.
      funds_untermed: D.exposure.fees.rows.filter((r) => r.ter_pct == null).length,
      // Whether the look-through was restated at all. False means the payload
      // carried no composition and those breakdowns are Python's, as at build.
      lookthrough: !!LT,
      coverage_unmatched: D.coverage ? coverage(D.coverage, rows) : 0,
      reporting_unmatched: D.reporting ? reporting(D.reporting, rows) : 0,
      watchlist: D.watchlist ? watchlist(D.watchlist).length : 0,
    };
    // Last: it reads the coverage and watchlist figures restated just above.
    // False means the flags on screen are the build's, and the page says so.
    STATS.alerts = alerts(D.watchlist || [], D.coverage, D.thresholds, today);
  }

  /* ---- the proof ---- */

  // Run the whole recompute against the prices the file was built with and
  // compare, field by field, with what Python wrote. Any disagreement beyond
  // one unit in the last decimal place the original rounds to is a defect in
  // this port, and it is reported rather than absorbed.
  //
  // Deep-copies the payload first, so asking the question cannot change the
  // answer.
  function parity() {
    const before = JSON.parse(JSON.stringify({
      totals: D.totals, overview: D.overview, exposure: D.exposure,
      coverage: D.coverage, watchlist: D.watchlist, reporting: D.reporting,
      holdings: D.holdings, alerts: D.alerts}));
    // On the build's own calendar day. Parity asks whether the port reproduces
    // Python on Python's inputs, and "today" is one of them: a catalyst 12
    // days out at build is 11 days out tomorrow, and that is not a defect.
    all(String(D.generated || '').slice(0, 10) || undefined);
    const bad = [], near = [];
    let checked = 0;
    const walk = (path, was, now, tol) => {
      if (was === now) { checked += 1; return; }
      if (was == null || now == null) {
        checked += 1;
        if (was !== now) bad.push({path, was, now});
        return;
      }
      if (typeof was === 'number' && typeof now === 'number') {
        checked += 1;
        const d = Math.abs(was - now);
        // Reported, not absorbed. A tolerance that quietly swallows a
        // systematic last-digit drift is a tolerance that will later swallow
        // the first real divergence too - `near` being empty is the evidence
        // that the tolerance is currently doing no work at all.
        if (d > tol) bad.push({path, was, now});
        else if (d > 1e-9) near.push({path, was, now});
        return;
      }
      if (Array.isArray(was) && Array.isArray(now)) {
        if (was.length !== now.length) { bad.push({path: path + '.length',
          was: was.length, now: now.length}); return; }
        was.forEach((v, i) => walk(path + '[' + i + ']', v, now[i], tol));
        return;
      }
      if (was && now && typeof was === 'object') {
        for (const k of Object.keys(was)) walk(path + '.' + k, was[k], now[k], tol);
        return;
      }
      checked += 1;
      if (String(was) !== String(now)) bad.push({path, was, now});
    };
    // One cent, and one unit in the last place of the coarsest percentage.
    // Tighter than that is measuring float noise, not agreement.
    const T = 0.011;
    walk('totals', before.totals, D.totals, T);
    walk('overview', before.overview, D.overview, T);
    walk('exposure.total_eur', before.exposure.total_eur, D.exposure.total_eur, T);
    walk('exposure.concentration', before.exposure.concentration,
         D.exposure.concentration, T);
    walk('exposure.fees', before.exposure.fees, D.exposure.fees, T);
    walk('exposure.funds', before.exposure.funds, D.exposure.funds, T);
    if (D.lookthrough) {
      for (const k of ['sectors', 'industries', 'geography', 'names', 'overlap']) {
        walk('exposure.' + k, before.exposure[k], D.exposure[k], T);
      }
    }
    walk('coverage', before.coverage, D.coverage, T);
    walk('watchlist', before.watchlist, D.watchlist, T);
    walk('reporting', before.reporting, D.reporting, T);
    walk('holdings', before.holdings, D.holdings, T);
    // Exact: every field is a string, and the strings are what Telegram sends.
    if (STATS.alerts) walk('alerts', before.alerts, D.alerts, 0);
    return {ok: !bad.length, checked, mismatches: bad.slice(0, 40),
            n_mismatches: bad.length,
            n_near: near.length, near: near.slice(0, 40)};
  }

  return {all, parity, stats: () => STATS,
          squarify, fold, dayMove, allocation, concentration};
})();

// Run at boot, before anything reads D - so the very first paint is already the
// ported arithmetic's output rather than Python's, and any disagreement between
// the two is visible immediately instead of appearing the moment a price lands.
// Shipping a port that only runs when the data has already changed means the
// one run you can check is the one run you never do.
const PARITY = DERIVE.parity();

