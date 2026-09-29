"""The book over time: equity curve, time-weighted return, benchmark, risk.

Everything else on the page is point-in-time. This module gives the book a time
dimension, and it is built from nothing but what is already on disk: the lot
export (units, cost and purchase date per lot) and the cached daily bars.

## What the curve is, and what it is not

It is the daily EUR value of **the lots you still hold**. Each lot enters the
curve on its own purchase date, as an external flow equal to what it cost.
Anything sold before the first export this machine has seen is invisible, so
this is not "the portfolio's history" and must never be labelled as if it
were. The payload carries `basis: "held-lots"` as a field precisely so the page
prints the caveat under the chart instead of in a footnote somebody deletes.

A lot that cannot be valued - no public feed, no bars, no FX series for its
currency, no purchase date - is **excluded and counted**, never valued at zero
and never valued at cost. `cost_covered_pct` says how much of the book the
curve speaks for.

## Returns

- **TWR** chain-links daily returns `r_d = (V_d - F_d) / V_{d-1} - 1`, where
  `F_d` is the cost of lots bought that day. A purchase therefore moves the
  value and not the return. This is the figure a benchmark can be compared to.
- **IRR** (money-weighted, `analyse.xirr`) stays where it was. The two answer
  different questions and are always labelled by name.

A period whose start predates the curve has **no** return (`None`), not the
since-start return and not zero.

## Benchmark

MSCI ACWI in EUR through a UCITS ETF (`config.BENCHMARK`). Two things are
derived from it:

- its own period returns, and the book's excess over them in percentage points;
- a **shadow portfolio** that buys the benchmark with exactly the book's
  flows, on the same days. That is the line the chart overlays: "what the same
  money, at the same times, would be worth in ACWI" - the public-market
  equivalent, and the only overlay that is honest when money arrives over time.

No benchmark bars means no benchmark: every benchmark-derived number is `None`.

## Risk

Volatility, drawdown, beta and correlation are measured on the **TWR index**,
never on the value: the value jumps on every purchase and would report a
monthly savings plan as a volatile asset. Daily closes from different venues
are forward-filled onto one calendar, which understates daily correlation
between a Xetra close and a New York one; it is the standard compromise and
it is stated here rather than hidden.

Per-position risk contribution is `w_i (Σw)_i / wᵀΣw` over a common recent
window, summing to 100. A holding with fewer than `MIN_RISK_OBS` daily returns
is excluded and counted, never given zero correlation.
"""
import datetime as dt
import math

import indicators

PERIODS = ("1D", "1W", "1M", "3M", "YTD", "1Y", "ALL")
TRADING_DAYS = 252
RISK_WINDOW = 252       # most recent daily returns the covariance is read over
MIN_RISK_OBS = 60       # fewer than this and a holding's risk is not estimated
MIN_STAT_OBS = 20       # fewer daily returns than this and vol/beta are None


def _d(text):
    return dt.date.fromisoformat(str(text)[:10])


def _closes(series):
    """{date: close} for the positive closes in a cached {fetched, bars}."""
    return {b[0]: b[4] for b in ((series or {}).get("bars") or [])
            if len(b) > 4 and b[4] is not None and b[4] > 0}


def _ffill(mapping, dates):
    """Values on `dates`, carrying the last known one forward, None before the first."""
    out, last = [], None
    for day in dates:
        if day in mapping:
            last = mapping[day]
        out.append(last)
    return out


def fx_series(fx_history, pairs):
    """ccy -> {date: EUR per one unit}. EUR itself maps to None, meaning 1.

    Each pair is quoted EURxxx, so one unit of xxx is worth 1/close EUR. GBp is
    a hundredth of GBP. A currency whose pair has no bars is simply absent,
    which makes every lot quoted in it "excluded", not "worth nothing".
    """
    out = {"EUR": None}
    for ccy, pair in pairs.items():
        closes = _closes((fx_history or {}).get(pair))
        if closes:
            out[ccy] = {d: 1.0 / c for d, c in closes.items()}
    if "GBP" in out:
        out["GBp"] = {d: v / 100.0 for d, v in out["GBP"].items()}
    return out


# ------------------------------------------------------------------- curve

def book_curve(lots, symbol_of, history, fx):
    """Daily EUR value of the held lots, with the flows that built it.

    `symbol_of` maps ISIN to Yahoo symbol, `history` is symbol -> cached bars,
    `fx` is `fx_series` output. Returns dates, value, flow, per-symbol value
    and flow (for attribution), per-symbol EUR price (for risk), and the
    exclusions with their reasons.
    """
    included, excluded = [], {}

    def exclude(lot, sym, reason):
        key = (sym or lot.get("tunnus") or lot.get("name") or "?", reason)
        row = excluded.setdefault(key, {"symbol": key[0], "reason": reason,
                                        "n_lots": 0, "cost_eur": 0.0})
        row["n_lots"] += 1
        row["cost_eur"] += lot.get("cost_eur") or 0.0

    for lot in lots:
        sym = symbol_of.get(lot["isin"])
        if not sym or sym == "MISSING":
            exclude(lot, None, "no public price feed")
            continue
        closes = _closes(history.get(sym))
        if not closes:
            exclude(lot, sym, "no price history")
        elif lot["ccy"] not in fx:
            exclude(lot, sym, f"no FX history for {lot['ccy']}")
        elif not lot.get("bought"):
            exclude(lot, sym, "no purchase date")
        else:
            included.append((lot, sym, closes))

    def first_available(lot, closes):
        rate = fx[lot["ccy"]]
        return max([min(closes)] + ([min(rate)] if rate else []))

    empty = {"basis": "held-lots", "dates": [], "value": [], "flow": [],
             "sym_value": {}, "sym_flow": {}, "sym_price": {},
             "excluded": sorted(excluded.values(), key=lambda r: -r["cost_eur"]),
             "n_lots": len(lots), "n_included": 0, "cost_covered_pct": None}
    if not included:
        return empty

    # The curve starts where every included lot can be valued: the earliest
    # bar anywhere, pushed later by any lot bought before its own symbol (or
    # currency) has a bar. After that date every lot's entry has a price.
    avail = {id(lot): first_available(lot, closes) for lot, _, closes in included}
    start = max([min(avail.values())]
                + [avail[id(lot)] for lot, _, _ in included
                   if lot["bought"][:10] < avail[id(lot)]])
    dates = sorted({d for _, _, closes in included for d in closes if d >= start})

    n = len(dates)
    value, flow = [0.0] * n, [0.0] * n
    sym_value, sym_flow, sym_price = {}, {}, {}
    rate_cache = {}
    kept = []
    for lot, sym, closes in included:
        bought = lot["bought"][:10]
        entry = next((i for i, d in enumerate(dates) if d >= max(bought, start)), None)
        if entry is None:
            exclude(lot, sym, "bought after the last bar")
            continue
        if sym not in sym_price:
            ccy = lot["ccy"]
            if ccy not in rate_cache:
                rate_cache[ccy] = ([1.0] * n if fx[ccy] is None
                                   else _ffill(fx[ccy], dates))
            price = _ffill(closes, dates)
            sym_price[sym] = [p * r if p is not None and r is not None else None
                              for p, r in zip(price, rate_cache[ccy])]
            sym_value[sym], sym_flow[sym] = [0.0] * n, [0.0] * n
        eur = sym_price[sym]
        for i in range(entry, n):
            v = lot["units"] * eur[i]
            value[i] += v
            sym_value[sym][i] += v
        if bought > start:
            flow[entry] += lot["cost_eur"] or 0.0
            sym_flow[sym][entry] += lot["cost_eur"] or 0.0
        kept.append(lot)

    # If nothing was held on the first date (every lot bought later than the
    # earliest bar), the curve starts on the first day something was. The
    # lots that enter that day are its opening capital, not a flow.
    k = next((i for i, v in enumerate(value) if v > 0), None)
    if k is None:
        return empty
    cut = lambda xs: xs[k:]
    dates, value, flow = cut(dates), cut(value), cut(flow)
    flow[0] = 0.0
    for d in (sym_value, sym_flow, sym_price):
        for sym in d:
            d[sym] = cut(d[sym])
    for sym in sym_flow:
        sym_flow[sym][0] = 0.0

    total_cost = sum(l.get("cost_eur") or 0.0 for l in lots)
    kept_cost = sum(l.get("cost_eur") or 0.0 for l in kept)
    return {
        "basis": "held-lots",
        "dates": dates, "value": value, "flow": flow,
        "sym_value": sym_value, "sym_flow": sym_flow, "sym_price": sym_price,
        "excluded": sorted(({**r, "cost_eur": round(r["cost_eur"], 2)}
                            for r in excluded.values()),
                           key=lambda r: -r["cost_eur"]),
        "n_lots": len(lots), "n_included": len(kept),
        "cost_covered_pct": (round(kept_cost / total_cost * 100, 1)
                             if total_cost else None),
    }


def daily_returns(value, flow):
    """r[i] = (V_i - F_i) / V_{i-1} - 1, aligned to input; r[0] is None."""
    out = [None]
    for i in range(1, len(value)):
        prev = value[i - 1]
        out.append((value[i] - flow[i]) / prev - 1.0 if prev > 0 else None)
    return out


def twr_index(returns, base=100.0):
    """Chain-linked index. A day with no return carries the level - it is
    only ever the first day, because the curve starts on a held day."""
    out, level = [], base
    for r in returns:
        if r is not None:
            level *= 1.0 + r
        out.append(level)
    return out


# ----------------------------------------------------------------- periods

def _months_back(day, months):
    y, m = divmod(day.year * 12 + day.month - 1 - months, 12)
    m += 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(day.day, last))


def base_index(dates, period):
    """Index of the date a period is measured FROM, or None when the period
    starts before the curve does. Returns cover (base, last]."""
    if len(dates) < 2:
        return None
    if period == "ALL":
        return 0
    if period == "1D":
        return len(dates) - 2
    end = _d(dates[-1])
    target = {"1W": end - dt.timedelta(days=7),
              "1M": _months_back(end, 1), "3M": _months_back(end, 3),
              "1Y": _months_back(end, 12),
              "YTD": dt.date(end.year - 1, 12, 31)}[period]
    if target < _d(dates[0]):
        return None
    target = target.isoformat()
    return max(i for i, d in enumerate(dates) if d <= target)


def _compound(returns):
    level = 1.0
    for r in returns:
        if r is not None:
            level *= 1.0 + r
    return level - 1.0


def _mean(xs):
    return sum(xs) / len(xs)


def _cov(a, b):
    ma, mb = _mean(a), _mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)


def _vol_pct(returns):
    rs = [r for r in returns if r is not None]
    if len(rs) < MIN_STAT_OBS:
        return None
    return math.sqrt(_cov(rs, rs) * TRADING_DAYS) * 100.0


def _r(x, digits=2):
    return None if x is None else round(x, digits)


def period_stats(dates, returns, index, bench_price):
    """Per period: TWR, benchmark return, excess (pp), vol, drawdown, beta.

    `bench_price` is aligned to `dates` (None where the benchmark has no bar
    yet) or None when there is no benchmark at all.
    """
    bench_ret = None
    if bench_price:
        bench_ret = [None] + [
            (bench_price[i] / bench_price[i - 1] - 1.0)
            if bench_price[i] and bench_price[i - 1] else None
            for i in range(1, len(dates))]
    out = {}
    for period in PERIODS:
        b = base_index(dates, period)
        if b is None:
            out[period] = None
            continue
        window = returns[b + 1:]
        twr = _compound(window) * 100.0
        bench = None
        if bench_price and bench_price[b] and bench_price[-1]:
            bench = (bench_price[-1] / bench_price[b] - 1.0) * 100.0
        dd, peak, trough = indicators.max_drawdown(index[b:])
        beta = corr = None
        if bench_ret:
            pairs = [(x, y) for x, y in zip(window, bench_ret[b + 1:])
                     if x is not None and y is not None]
            if len(pairs) >= MIN_STAT_OBS:
                xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
                vb, vx = _cov(ys, ys), _cov(xs, xs)
                if vb > 0 and vx > 0:
                    beta = _cov(xs, ys) / vb
                    corr = _cov(xs, ys) / math.sqrt(vb * vx)
        out[period] = {
            "from": dates[b], "n_days": len(window),
            "twr_pct": _r(twr),
            "bench_pct": _r(bench),
            "excess_pp": _r(twr - bench) if bench is not None else None,
            "vol_pct": _r(_vol_pct(window)),
            "mdd_pct": _r(dd),
            "mdd_peak": dates[b + peak] if dd else None,
            "mdd_trough": dates[b + trough] if dd else None,
            "beta": _r(beta), "corr": _r(corr),
        }
    return out


def shadow(value, flow, bench_price):
    """The benchmark bought with the book's own money on the book's own days.

    None when the benchmark has no price on the curve's first day - a shadow
    that starts late would compare different amounts of money.
    """
    if not bench_price or not bench_price[0] or not value:
        return None
    units, out = value[0] / bench_price[0], []
    for i, p in enumerate(bench_price):
        if i and flow[i]:
            units += flow[i] / p
        out.append(units * p)
    return out


def attribution(curve, period):
    """EUR contribution per symbol over a period: V_end - V_base - flows.

    Sums exactly to the book's own change less flows over the same period,
    which is the check `tests/test_performance.py` makes.

    `pct` is the name's own EUR price return over the same window - what one
    unit did, independent of when this book bought it or how many it holds.
    None when either end has no price (the listing started inside the
    window, or the currency has no bar): absent, never a flat 0%.
    """
    b = base_index(curve["dates"], period)
    if b is None:
        return None
    rows = []
    for sym, vals in curve["sym_value"].items():
        pnl = vals[-1] - vals[b] - sum(curve["sym_flow"][sym][b + 1:])
        p = curve["sym_price"].get(sym) or []
        p0, p1 = (p[b], p[-1]) if len(p) > b else (None, None)
        pct = (p1 / p0 - 1.0) * 100.0 if p0 and p1 else None
        rows.append({"symbol": sym, "eur": round(pnl, 2), "pct": _r(pct)})
    rows.sort(key=lambda r: r["eur"])
    return rows


# -------------------------------------------------------------------- risk

def risk(curve):
    """Correlation matrix and risk contribution over a common recent window."""
    prices = curve["sym_price"]
    n = len(curve["dates"])
    rets, excluded = {}, []
    for sym, p in prices.items():
        r = [(p[i] / p[i - 1] - 1.0) if p[i] and p[i - 1] else None
             for i in range(max(1, n - RISK_WINDOW), n)]
        # Only an unbroken recent run counts: the tail after the last gap.
        tail = []
        for x in reversed(r):
            if x is None:
                break
            tail.append(x)
        if len(tail) < MIN_RISK_OBS:
            excluded.append({"symbol": sym, "n_obs": len(tail)})
            continue
        rets[sym] = tail[::-1]
    total = sum(v[-1] for v in curve["sym_value"].values())
    if not rets or not total:
        return {"window_days": 0, "symbols": [], "corr": [], "contribution": [],
                "excluded": excluded, "weight_covered_pct": None,
                "book_vol_pct": None}
    window = min(len(r) for r in rets.values())
    syms = sorted(rets, key=lambda s: -curve["sym_value"][s][-1])
    series = [rets[s][-window:] for s in syms]
    held = [curve["sym_value"][s][-1] for s in syms]
    covered = sum(held)
    w = [h / covered for h in held]
    cov = [[_cov(a, b) for b in series] for a in series]
    sw = [sum(cov[i][j] * w[j] for j in range(len(w))) for i in range(len(w))]
    var = sum(w[i] * sw[i] for i in range(len(w)))
    contribution = [{
        "symbol": s,
        "weight_pct": round(w[i] * 100, 2),
        "rc_pct": round(w[i] * sw[i] / var * 100, 2) if var > 0 else None,
        "vol_pct": round(math.sqrt(cov[i][i] * TRADING_DAYS) * 100, 1),
    } for i, s in enumerate(syms)]
    corr = [[round(cov[i][j] / math.sqrt(cov[i][i] * cov[j][j]), 2)
             if cov[i][i] > 0 and cov[j][j] > 0 else None
             for j in range(len(syms))] for i in range(len(syms))]
    return {
        "window_days": window, "symbols": syms, "corr": corr,
        "contribution": contribution, "excluded": excluded,
        "weight_covered_pct": round(covered / total * 100, 1),
        "book_vol_pct": (round(math.sqrt(var * TRADING_DAYS) * 100, 1)
                         if var > 0 else None),
    }


def listing_currency(holdings):
    """Book value split by the currency each line is QUOTED in.

    This is the listing currency, not the economic exposure: a EUR-listed world
    tracker is mostly dollar assets. The look-through geography in
    `exposure` is the underlying answer; this one is what the broker converts.
    Unvalued lines are counted apart, never folded in at zero.
    """
    by, unvalued = {}, 0
    for h in holdings:
        v = h.get("value_eur")
        if v is None:
            unvalued += 1
            continue
        ccy = "GBP" if h.get("ccy") == "GBp" else (h.get("ccy") or "?")
        by[ccy] = by.get(ccy, 0.0) + v
    total = sum(by.values())
    rows = [{"ccy": c, "eur": round(v, 2),
             "pct": round(v / total * 100, 1) if total else None}
            for c, v in sorted(by.items(), key=lambda kv: -kv[1])]
    return {"rows": rows, "n_unvalued": unvalued}


def recorded_points(history_rows):
    """The real book values this machine recorded, last reading per day.

    These are observations, not reconstructions, so the page draws them as
    points over the curve rather than splicing them into it.
    """
    by_day = {}
    for row in history_rows:
        if row.get("date") and row.get("value_eur") is not None:
            by_day[row["date"]] = row["value_eur"]
    return [{"date": d, "value_eur": v} for d, v in sorted(by_day.items())]


# ------------------------------------------------------------------- build

def _pack_dates(dates):
    days = [_d(d) for d in dates]
    return {"d0": dates[0] if dates else None,
            "dd": [0] + [(days[i] - days[i - 1]).days for i in range(1, len(days))]
            if dates else []}


def build(lots, symbol_of, history, fx_history, fx_pairs, benchmark,
          holdings=(), recorded=()):
    """Everything the page's time dimension needs, in one packed object.

    `benchmark` is {"symbol", "label", "ccy"}; its bars live in `fx_history`
    beside the FX pairs, because both are reference series nobody holds.
    """
    fx = fx_series(fx_history, fx_pairs)
    curve = book_curve(lots, symbol_of, history, fx)
    dates = curve["dates"]
    out = {
        "basis": curve["basis"],
        "n_lots": curve["n_lots"], "n_included": curve["n_included"],
        "cost_covered_pct": curve["cost_covered_pct"],
        "excluded": curve["excluded"],
        "listing_currency": listing_currency(holdings),
        "recorded": recorded_points(recorded),
    }
    bench_meta = {"symbol": benchmark.get("symbol"), "label": benchmark.get("label")}
    if not dates:
        out.update({"curve": None, "periods": {p: None for p in PERIODS},
                    "attribution": {p: None for p in PERIODS}, "risk": risk(curve),
                    "benchmark": {**bench_meta, "absent": "no book curve"}})
        return out

    returns = daily_returns(curve["value"], curve["flow"])
    index = twr_index(returns)
    bench_closes = _closes((fx_history or {}).get(benchmark.get("symbol")))
    bench_price = None
    if bench_closes:
        rate = fx.get(benchmark.get("ccy") or "EUR", "absent")
        if rate != "absent":
            px = _ffill(bench_closes, dates)
            fxr = [1.0] * len(dates) if rate is None else _ffill(rate, dates)
            bench_price = [p * r if p is not None and r is not None else None
                           for p, r in zip(px, fxr)]
            if not any(bench_price):
                bench_price = None
    shadow_value = shadow(curve["value"], curve["flow"], bench_price)
    if bench_price is None:
        bench_out = {**bench_meta, "absent": "no benchmark bars"}
    else:
        base = next((p for p in bench_price if p), None)
        bench_out = {**bench_meta, "absent": None,
                     "index": [_r(p / base * 100, 3) if p else None
                               for p in bench_price],
                     "shadow": ([_r(v) for v in shadow_value]
                                if shadow_value else None)}

    out.update({
        "curve": {**_pack_dates(dates),
                  "value": [_r(v) for v in curve["value"]],
                  "index": [_r(v, 3) for v in index],
                  # sparse: [position, EUR] for each day that received money
                  "flows": [[i, _r(f)] for i, f in enumerate(curve["flow"]) if f]},
        "benchmark": bench_out,
        "periods": period_stats(dates, returns, index, bench_price),
        "attribution": {p: attribution(curve, p) for p in PERIODS},
        "risk": risk(curve),
    })
    return out
