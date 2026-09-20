"""Every external boundary lives here: the Nordnet export, Notion, Yahoo.

Rule for this module: a source that fails degrades, it never raises into the
caller. Each returns data plus an explicit problem list, so a broken source
shows up as a red line on the dashboard instead of a dead run.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
import datetime as dt
from pathlib import Path

import config as C

# ---------------------------------------------------------------- Nordnet CSV

# The exact header the parser is written against. Checked on every run:
# if Nordnet changes its export, you find out immediately and by name.
NORDNET_HEADER = [
    "Tulostuspäivä", "Salkku", "Hankintapäivä", "Instrumentti", "Tunnus",
    "ISIN", "Valuutta", "Määrä", "Hankintahinta (Noteerausvaluutta)",
    "Hankintahinta (EUR)", "Hankinta-arvo (Noteerausvaluutta)",
    "Hankinta-arvo (EUR)", "Markkina-arvo (Noteerausvaluutta)",
    "Markkina-arvo (EUR)", "Tuotto-%", "Tuotto-% (p.a)",
]


class SourceError(Exception):
    """Raised only by selftest paths, never during a normal run."""


def _num(s):
    """Nordnet writes Finnish decimals: '1 211,5' -> 1211.5"""
    if s is None:
        return None
    s = s.replace("\xa0", "").replace(" ", "").strip()
    if not s or s == "-":
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _read_csv_text(path: Path) -> str:
    """Nordnet exports UTF-16. Tolerate the other plausible encodings anyway."""
    raw = path.read_bytes()
    for enc in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "\t" in text.split("\n", 1)[0]:
            return text
    raise SourceError(f"{path.name}: not tab-separated in any known encoding")


def nordnet_lots(project_dir: Path | None = None):
    """Every purchase lot across both accounts. Returns (lots, problems)."""
    project_dir = project_dir or C.PROJECT_DIR
    problems, lots = [], []
    files = sorted(project_dir.glob(C.NORDNET_GLOB))
    if not files:
        problems.append(f"no {C.NORDNET_GLOB} found in {project_dir}")
        return lots, problems

    for path in files:
        try:
            text = _read_csv_text(path)
        except SourceError as e:
            problems.append(str(e))
            continue
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        missing = [h for h in NORDNET_HEADER if h not in (reader.fieldnames or [])]
        if missing:
            problems.append(
                f"{path.name}: Nordnet export format changed - missing columns "
                f"{missing}. Parser needs updating."
            )
            continue
        for row in reader:
            isin = (row.get("ISIN") or "").strip()
            units = _num(row.get("Määrä"))
            if not isin or not units:
                continue
            lots.append({
                "isin": isin,
                "account_no": (row.get("Salkku") or "").strip(),
                "name": (row.get("Instrumentti") or "").strip(),
                "tunnus": (row.get("Tunnus") or "").strip(),
                "ccy": (row.get("Valuutta") or "").strip(),
                "units": units,
                "cost_eur": _num(row.get("Hankinta-arvo (EUR)")) or 0.0,
                "nordnet_mv_eur": _num(row.get("Markkina-arvo (EUR)")) or 0.0,
                "bought": (row.get("Hankintapäivä") or "").strip(),
                "exported": (row.get("Tulostuspäivä") or "").strip(),
                "source_file": path.name,
            })
    if not lots and not problems:
        problems.append("Nordnet files parsed but contained no usable lots")
    return lots, problems


def positions(lots):
    """Collapse lots into one row per (ISIN, account)."""
    agg = {}
    for lot in lots:
        key = (lot["isin"], lot["account_no"])
        pos = agg.setdefault(key, {
            "isin": lot["isin"],
            "account_no": lot["account_no"],
            "account": C.ACCOUNTS.get(lot["account_no"], lot["account_no"]),
            "name": lot["name"], "tunnus": lot["tunnus"], "ccy": lot["ccy"],
            "units": 0.0, "cost_eur": 0.0, "nordnet_mv_eur": 0.0,
            "lots": 0, "first_bought": lot["bought"], "exported": lot["exported"],
            "bucket": C.BUCKETS.get(lot["isin"], "Unclassified"),
            "yahoo": C.YAHOO.get(lot["isin"], "MISSING"),
        })
        pos["units"] += lot["units"]
        pos["cost_eur"] += lot["cost_eur"]
        pos["nordnet_mv_eur"] += lot["nordnet_mv_eur"]
        pos["lots"] += 1
        pos["first_bought"] = min(pos["first_bought"], lot["bought"])
    for pos in agg.values():
        pos["units"] = round(pos["units"], 4)
        pos["cost_eur"] = round(pos["cost_eur"], 2)
        pos["nordnet_mv_eur"] = round(pos["nordnet_mv_eur"], 2)
    return sorted(agg.values(), key=lambda p: -p["nordnet_mv_eur"])


def export_age_days(lots, today=None):
    """How stale is the Nordnet export itself."""
    today = today or dt.date.today()
    dates = {lot["exported"] for lot in lots if lot["exported"]}
    if not dates:
        return None, None
    newest = max(dates)
    try:
        return (today - dt.date.fromisoformat(newest)).days, newest
    except ValueError:
        return None, newest


# ------------------------------------------------------------------- Prices

def _fast_info(symbol, retries=3, pause=0.6):
    import yfinance as yf
    for attempt in range(retries):
        try:
            fi = yf.Ticker(symbol).fast_info
            price = fi.get("lastPrice")
            if price:
                return {
                    "price": float(price),
                    "prev_close": fi.get("previousClose"),
                    "year_high": fi.get("yearHigh"),
                    "year_low": fi.get("yearLow"),
                    "currency": fi.get("currency"),
                }
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(pause)
    return None


def fx_rates():
    """Units of EUR per 1 unit of currency. Returns (rates, problems)."""
    problems = {}
    rates = {"EUR": 1.0}
    for ccy, pair in C.FX_PAIRS.items():
        quote = _fast_info(pair)
        if quote and quote["price"]:
            rates[ccy] = 1.0 / quote["price"]
        else:
            rates[ccy] = None
            problems[ccy] = f"FX pair {pair} did not resolve"
    rates["GBp"] = rates["GBP"] / 100 if rates.get("GBP") else None
    return rates, problems


def quotes(symbols):
    """Fetch many symbols. A miss is recorded, never fatal."""
    out, problems = {}, {}
    for symbol in symbols:
        if not symbol or symbol == "MISSING":
            continue
        quote = _fast_info(symbol)
        if quote:
            out[symbol] = quote
        else:
            problems[symbol] = "no price from Yahoo after 3 attempts"
    return out, problems


def _bars(symbol):
    """Two years of daily OHLCV, or None. Rounded on the way out - four decimals
    is more precision than any chart can draw, and the file is read by a browser.

    A bar is [date, open, high, low, close, volume]. Volume is the sixth element
    and was added after the chart was written, so everything that reads a bar
    positionally (b[0]..b[4]) is unaffected. It is an int, not a float, because
    a share count is a count; and it is the only field allowed to be 0, because
    a real trading day with no turnover exists and is itself information.
    """
    import yfinance as yf
    try:
        frame = yf.Ticker(symbol).history(period=C.PRICE_HISTORY_PERIOD,
                                          interval="1d", auto_adjust=True)
    except Exception:
        return None
    if frame is None or frame.empty:
        return None
    has_volume = "Volume" in frame.columns
    volumes = frame["Volume"] if has_volume else [None] * len(frame.index)
    rows = []
    for stamp, o, h, l, c, v in zip(frame.index, frame["Open"], frame["High"],
                                    frame["Low"], frame["Close"], volumes):
        if c != c:                                  # NaN - a holiday row
            continue
        try:
            vol = int(v) if v is not None and v == v else None
        except (TypeError, ValueError, OverflowError):
            vol = None
        rows.append([str(stamp.date()), round(float(o), 4), round(float(h), 4),
                     round(float(l), 4), round(float(c), 4), vol])
    return rows or None


def _bars_have_volume(bars):
    """Is this bar list in the six-element OHLCV shape? Checked on the last bar,
    which is the one a partial rewrite would leave short."""
    return bool(bars) and len(bars[-1]) >= 6


def _write_symbol_cache(path, previous, fresh, today):
    """Write previous-plus-fresh. Never fresh alone, never nothing at all.

    Every fetcher below builds its result from the symbols it was ASKED about,
    so writing that result as the whole file makes the caller's question the
    file's new contents. A narrower call then deletes every symbol it did not
    mention, and a call with no symbols empties the file outright.

    That is not hypothetical. On 2026-09-20 the test suite drove the full
    pipeline against a one-stock fake book; `fund_composition` was handed an
    empty fund list, wrote `{"symbols":{}}` over a populated cache, and the
    board dropped from 99% sector resolution to 51% and lost its whole
    reporting calendar while printing "All sources fresh".

    The per-symbol ladders already refuse to let a THIN vendor answer overwrite
    a good one. This is that same rule one level up, and it is the rule this
    codebase keeps having to relearn: **a source answering with less than it
    should is not the same as it saying nothing.** Here the source is the
    caller, and a symbol absent from the question is unasked, not gone.

    Entries for symbols nobody asks about any more are kept, not pruned. They
    cost bytes; the alternative is a delete rule that has to be sure a holding
    is really sold, and this function cannot be sure of that.

    Returns True if it wrote.
    """
    if not fresh:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": str(today),
                                "symbols": {**(previous or {}), **fresh}},
                               separators=(",", ":")), encoding="utf-8")
    return True


def price_history(symbols, today=None, cached_only=False):
    """Daily bars per symbol, cached on disk and refetched once per day.

    The cache is what makes charts affordable on a 07:40 schedule: Yahoo is asked
    for a symbol only when what we hold is not from today. A symbol that fails
    keeps its last good bars and is reported stale - a chart that is a day old is
    worth far more than no chart.

    `cached_only` serves whatever is on disk and asks Yahoo for nothing. The
    intraday refresh runs every half hour and daily bars do not change in that
    time, so paying for them 26 times a day would buy nothing and spend the
    rate limit the live prices need. It also does not WRITE the cache: a
    read-only pass has no business restamping a file whose dates are what the
    next full run reads to decide whether to fetch.

    Returns (history, problems, pulled). `pulled` is how many symbols this run
    actually asked Yahoo for. It cannot be derived from the cache afterwards -
    the second run of a day looks identical to the first - and without it the
    log cannot tell you whether the cache is working.
    """
    today = today or dt.date.today()
    cache = {}
    if C.PRICE_HISTORY_CACHE.exists():
        try:
            cache = json.loads(C.PRICE_HISTORY_CACHE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}                              # corrupt cache is not fatal
    series = cache.get("symbols", {})

    out, problems, pulled = {}, {}, 0
    for symbol in symbols:
        if not symbol or symbol == "MISSING":
            continue
        held = series.get(symbol)
        # A cache written before volume existed holds five-element bars. Serving
        # those is worse than refetching: the indicators would report "no volume"
        # for the life of the cache and look like a broken feed rather than a
        # stale one. Shape mismatch therefore forces a pull, once.
        if held and held.get("bars") and not _bars_have_volume(held["bars"]):
            held = None
        if held and held.get("fetched") == str(today) and held.get("bars"):
            out[symbol] = held
            continue
        if cached_only:
            if held and held.get("bars"):
                out[symbol] = held
            else:
                problems[symbol] = "no cached history"
            continue
        bars = _bars(symbol)
        if bars:
            out[symbol] = {"fetched": str(today), "bars": bars}
            pulled += 1
        elif held and held.get("bars"):
            out[symbol] = held                      # keep yesterday's rather than none
            problems[symbol] = f"history not refreshed; showing {held.get('fetched')}"
        else:
            problems[symbol] = "no history from Yahoo"

    if not cached_only:
        _write_symbol_cache(C.PRICE_HISTORY_CACHE, series, out, today)
    return out, problems, pulled


# ------------------------------------------------------------- fundamentals

# What we keep out of the 150-180 keys `.info` returns. Everything here is
# either a multiple the board records by hand, or context for one.
#
# `recommendationKey` is deliberately NOT among them, and it is the one field
# here worth explaining. Yahoo returns "strong_buy" / "hold" / "none", and it
# would render as a badge for free. It is left on the floor for the same reason
# indicators.snapshot never emits a BUY: this board belongs to someone who
# writes his own thesis, and the moment a page prints somebody else's verdict
# next to his, it is making the decision the thesis exists to make.
# `targetMeanPrice` is kept, because a number you can hold your own target up
# against is evidence; a verb telling you what to do is not.
#
# `dividendYield` is also skipped: yfinance has shipped it as both a fraction
# and a percentage across versions, and a yield of "0.79" that might be 0.79%
# or 79% is worse than no yield at all. If it is wanted later, verify the unit
# against a known payer first - do not infer it from the magnitude.
#
# `country` is kept for the geography split, and it is worth being precise
# about what it is: the company's stated domicile, NOT where its revenue comes
# from. Ahold Delhaize returns "Netherlands" while most of the money is
# American. Every surface that shows it has to say so, because a geography
# chart is exactly the kind of thing a reader assumes means revenue.
#
# `priceToSalesTrailing12Months` is kept only because the book-level multiple
# needs it: a fund reports P/S and a stock has to answer on the same axis, or
# the blended figure silently covers the tracker half of the book and nothing
# else. Verified live on four listings 2026-09-20 before being added - Yahoo
# spells it with the `TrailingTwelveMonths` suffix and returns nothing for the
# shorter name.
_INFO_FIELDS = ("trailingPE", "forwardPE", "priceToBook",
                "priceToSalesTrailing12Months", "marketCap",
                "trailingEps", "forwardEps", "totalDebt", "totalCash",
                "ebitda", "sector", "industry", "country", "targetMeanPrice",
                "numberOfAnalystOpinions", "returnOnEquity", "profitMargins",
                "beta")


def _info(symbol, retries=2, pause=0.5):
    """One symbol's `.info`, or None. Never raises."""
    import yfinance as yf
    for attempt in range(retries):
        try:
            info = yf.Ticker(symbol).info
            if info:
                return info
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(pause)
    return None


def _shape_info(info):
    """The handful of figures the board actually argues with.

    Returns None when nothing usable came back, which is the normal and
    expected answer for a fund - not a fault, and not worth a problem entry.
    """
    def num(key):
        value = info.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if value == value else None        # NaN

    debt, cash, ebitda = num("totalDebt"), num("totalCash"), num("ebitda")
    # Net debt, not gross: Nokia carries more cash than debt, and a gross-debt
    # ratio would report a net-cash balance sheet as levered. Negative is
    # correct and meaningful here - it means net cash.
    net_debt_ebitda = None
    if debt is not None and ebitda:
        net_debt_ebitda = round((debt - (cash or 0.0)) / ebitda, 2)

    out = {
        "pe": num("trailingPE"),
        "fwd_pe": num("forwardPE"),
        "pb": num("priceToBook"),
        "ps": num("priceToSalesTrailing12Months"),
        "market_cap": num("marketCap"),
        "eps": num("trailingEps"),
        "fwd_eps": num("forwardEps"),
        "net_debt_ebitda": net_debt_ebitda,
        "street_target": num("targetMeanPrice"),
        "street_analysts": num("numberOfAnalystOpinions"),
        "roe_pct": (num("returnOnEquity") or 0) * 100 if num("returnOnEquity") is not None else None,
        "margin_pct": (num("profitMargins") or 0) * 100 if num("profitMargins") is not None else None,
        "beta": num("beta"),
        "sector": info.get("sector") or None,
        "industry": info.get("industry") or None,
        "country": info.get("country") or None,
    }
    # A lone trailing P/E on an accumulating ETF is a portfolio-weighted
    # aggregate wearing a company's clothes - IMAE.AS returns exactly that and
    # nothing else. Require a real company's worth of fields before believing
    # any of it.
    if sum(1 for v in out.values() if v is not None) < 4:
        return None
    return out


def fundamentals(symbols, today=None, cached_only=False):
    """Live multiples per symbol, cached on disk and refetched once a day.

    Same contract as price_history: ask Yahoo only when what we hold is not
    from today, keep the last good answer when a fetch fails, and report
    staleness rather than dropping the figure. A symbol that has never returned
    anything is cached as an explicit null so the miss is visible in the file
    rather than looking like a symbol nobody asked about.

    `cached_only` serves the disk and asks nothing, for the intraday refresh.
    A P/E does not move between 10:00 and 10:30 in any way this board acts on,
    and `.info` is the expensive call - it is also the one that answers THIN
    under a rate limit, which is the fault this module went to some trouble to
    stop mistaking for a fund. Asking it 26 times a day would manufacture the
    conditions for that fault.

    Returns (data, problems, pulled).
    """
    today = today or dt.date.today()
    cache = {}
    if C.FUNDAMENTALS_CACHE.exists():
        try:
            cache = json.loads(C.FUNDAMENTALS_CACHE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}
    series = cache.get("symbols", {})

    out, problems, pulled = {}, {}, 0
    for symbol in symbols:
        if not symbol or symbol == "MISSING":
            continue
        held = series.get(symbol)
        if held and held.get("fetched") == str(today):
            out[symbol] = held
            continue
        if cached_only:
            if held:
                out[symbol] = held
            else:
                problems[symbol] = "no cached fundamentals"
            continue
        info = _info(symbol)
        shaped = _shape_info(info) if info else None
        if shaped:
            out[symbol] = {"fetched": str(today), "fields": shaped}
            pulled += 1
        elif info is not None and (held or {}).get("fields"):
            # Answered, but with less than a company's worth of fields - from a
            # symbol that HAS answered properly before. That is a degraded
            # response, not a reclassification: yfinance returns a thin dict on
            # a rate limit as readily as it does for a fund, and `_info` only
            # returns None when the dict is empty outright. Writing the null
            # here would blank a real stock's multiples with no problem
            # recorded, which reads identically to the company having stopped
            # reporting. Keep the last good answer and say it is stale.
            out[symbol] = held
            problems[symbol] = (f"fundamentals came back thin; showing "
                                f"{held.get('fetched')}")
        elif info is not None:
            # Answered, but with nothing a company would have, and nothing
            # better was ever cached. A fund. Record the miss so tomorrow's run
            # does not read it as unasked.
            out[symbol] = {"fetched": str(today), "fields": None}
            pulled += 1
        elif held:
            out[symbol] = held
            problems[symbol] = f"fundamentals not refreshed; showing {held.get('fetched')}"
        else:
            problems[symbol] = "no fundamentals from Yahoo"

    if not cached_only:
        _write_symbol_cache(C.FUNDAMENTALS_CACHE, series, out, today)
    return out, problems, pulled


# --------------------------------------------------------- fund composition

def _pct(value):
    """A weight as a float in 0..1, or None. Never raises, never returns NaN."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value:                                          # NaN
        return None
    return value


def _funds_data(symbol, retries=2, pause=0.5):
    """One symbol's `.funds_data`, or None. Never raises."""
    import yfinance as yf
    for attempt in range(retries):
        try:
            data = yf.Ticker(symbol).funds_data
            if data is not None:
                return data
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(pause)
    return None


def _shape_funds_data(data):
    """What a fund is made of, in the shape the look-through wants.

    Returns None when nothing usable came back. Every branch is defensive
    because `.funds_data` is a set of lazy pandas accessors, each of which can
    raise independently - a fund can answer with sectors and refuse holdings.

    The valuation block is INVERTED on the way through. Yahoo ships those four
    rows as yields (P/E 0.04437), and the only thing standing between that and
    a page claiming a market-wide P/E of 0.04 is this function.
    """
    out = {"top_holdings": [], "sectors": {}, "asset_classes": {},
           "ter": None, "valuation": {}}

    try:
        table = data.top_holdings
        if table is not None and len(table):
            for symbol, row in table.iterrows():
                weight = _pct(row.get("Holding Percent"))
                if weight is None:
                    continue
                out["top_holdings"].append({
                    "symbol": str(symbol),
                    "name": str(row.get("Name") or "").strip() or None,
                    "pct": round(weight * 100, 4)})
    except Exception:
        pass

    try:
        sectors = data.sector_weightings or {}
        for key, weight in sectors.items():
            weight = _pct(weight)
            if weight:                          # drop the explicit zeroes
                out["sectors"][str(key)] = round(weight * 100, 4)
    except Exception:
        pass

    try:
        classes = data.asset_classes or {}
        for key, weight in classes.items():
            weight = _pct(weight)
            if weight:
                out["asset_classes"][str(key)] = round(weight * 100, 4)
    except Exception:
        pass

    try:
        ops = data.fund_operations
        # Column is named for the symbol; take the first, not by label, because
        # the second column is a category average that is NA for every European
        # UCITS fund in this book.
        ter = _pct(ops.iloc[:, 0].get("Annual Report Expense Ratio"))
        out["ter"] = round(ter * 100, 4) if ter is not None else None
    except Exception:
        pass

    try:
        rows = data.equity_holdings.iloc[:, 0]
        for label, key in (("Price/Earnings", "pe"), ("Price/Book", "pb"),
                           ("Price/Sales", "ps"), ("Price/Cashflow", "pcf")):
            yield_ = _pct(rows.get(label))
            # Invert. A zero would divide, and a yield of zero is not a
            # multiple of infinity - it is an absent figure wearing a number.
            if yield_:
                out["valuation"][key] = round(1.0 / yield_, 2)
    except Exception:
        pass

    # Sectors are the load-bearing field: they are what makes the split cover
    # 100% of the book. Holdings are capped at ten rows and are always partial,
    # so they cannot be the test of whether the fetch worked.
    if not out["sectors"] and not out["top_holdings"]:
        return None
    return out


def fund_composition(symbols, today=None, cached_only=False):
    """What each fund holds, cached on disk and refetched once a day.

    Same contract and the same degradation ladder as `fundamentals`, for the
    same reasons - including keeping the last good answer when a fetch comes
    back thin rather than writing the blank over it. The failure this guards is
    the one already on the record twice in this codebase: a vendor answering
    with LESS than it should, and the system recording that as the fund having
    become empty.

    `cached_only` serves the disk and asks nothing. A fund's sector weights do
    not move intraday in any way this board acts on, and the refresh runs 26
    times a day.

    Returns (data, problems, pulled).
    """
    today = today or dt.date.today()
    cache = {}
    if C.FUND_COMPOSITION_CACHE.exists():
        try:
            cache = json.loads(C.FUND_COMPOSITION_CACHE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}
    series = cache.get("symbols", {})

    out, problems, pulled = {}, {}, 0
    for symbol in symbols:
        if not symbol or symbol == "MISSING":
            continue
        held = series.get(symbol)
        if held and held.get("fetched") == str(today):
            out[symbol] = held
            continue
        if cached_only:
            if held:
                out[symbol] = held
            else:
                problems[symbol] = "no cached composition"
            continue
        data = _funds_data(symbol)
        shaped = _shape_funds_data(data) if data is not None else None
        if shaped:
            out[symbol] = {"fetched": str(today), "fields": shaped}
            pulled += 1
        elif (held or {}).get("fields"):
            out[symbol] = held
            problems[symbol] = (f"composition came back empty; showing "
                                f"{held.get('fetched')}")
        else:
            out[symbol] = {"fetched": str(today), "fields": None}
            pulled += 1
            problems[symbol] = "no composition from Yahoo"

    if not cached_only:
        _write_symbol_cache(C.FUND_COMPOSITION_CACHE, series, out, today)
    return out, problems, pulled


# ------------------------------------------------------------------- earnings

# Measured on 2026-09-20 across eleven symbols before a line of this was
# written, because the failure modes are not in the documentation:
#
#   .get_earnings_dates()   answered for 10/10 stocks, EMPTY for the fund.
#                           Carries past and future in one frame. 25 rows for
#                           an established name, 4 for a recent listing.
#   .calendar               forward consensus. 'Earnings Date' is a LIST and
#                           that list can be EMPTY while earnings_dates still
#                           has rows - Admicom had no scheduled next date at
#                           all. An empty list means unknown, not today.
#   .quarterly_income_stmt  5-6 quarters of revenue and net income. Some
#                           European names skip a quarter (half-year lines
#                           only); the gap is real and is left as a gap.
#   isEarningsDateEstimate  True means Yahoo guessed the date off last year's
#                           pattern. Microsoft and Amazon were guesses; the
#                           seven European names were confirmed. A page that
#                           prints a guessed date without saying so claims
#                           more than it knows.
#
# THE TRAP, and it is the same one this codebase has now hit three times: the
# upcoming quarter arrives as a row whose Reported EPS is NaN. Coerced to zero
# it becomes a company that earned nothing and missed consensus by 100%. NaN
# means not yet reported. It is carried as None and never as a number.

_EARNINGS_ROWS = (("Total Revenue", "revenue"), ("Net Income", "net_income"),
                  ("Operating Income", "operating_income"),
                  ("Gross Profit", "gross_profit"), ("Diluted EPS", "eps"))


def _fin(value):
    """A figure or None. NaN, NaT and pandas-NA all collapse to None."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _day(value):
    """Anything date-like as an ISO day string, or None.

    Yahoo indexes the earnings frame in America/New_York even for Helsinki
    and Copenhagen names, so the clock time on a European row is fiction.
    Only the date is kept; nothing downstream is entitled to the hour.
    """
    if value is None:
        return None
    try:
        if value != value:                                          # NaT
            return None
    except (TypeError, ValueError):
        pass
    for attr in ("date",):
        if hasattr(value, attr):
            try:
                return str(getattr(value, attr)())
            except (TypeError, ValueError):
                pass
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" else None


def _shape_earnings(ticker, today):
    """One company's reporting record and its next date, or None.

    Every accessor is wrapped separately: a name can answer with a calendar
    and refuse the income statement, and half an answer is worth keeping.
    """
    out = {"history": [], "quarters": [], "next": None, "currency": None}

    try:
        frame = ticker.get_earnings_dates(limit=24)
        if frame is not None and len(frame):
            for stamp, row in frame.iterrows():
                day = _day(stamp)
                if not day:
                    continue
                reported = _fin(row.get("Reported EPS"))
                entry = {"date": day,
                         "eps_estimate": _fin(row.get("EPS Estimate")),
                         "eps_reported": reported,
                         "surprise_pct": _fin(row.get("Surprise(%)"))}
                # Reported or not is the split, NOT date against today. A row
                # can sit in the past with nothing filed against it, and that
                # is an absent result rather than a future one.
                if reported is not None:
                    out["history"].append(entry)
                elif day > str(today):
                    out["next"] = {"date": day, "estimated": None,
                                   "eps_estimate": entry["eps_estimate"],
                                   "eps_high": None, "eps_low": None,
                                   "revenue_estimate": None}
            out["history"].sort(key=lambda r: r["date"], reverse=True)
    except Exception:
        pass

    try:
        cal = ticker.calendar or {}
        dates = cal.get("Earnings Date") or []
        day = _day(dates[0]) if dates else None
        if day:
            out["next"] = out["next"] or {"date": day, "estimated": None,
                                          "eps_estimate": None}
            out["next"]["date"] = day
        if out["next"]:
            out["next"]["eps_estimate"] = (out["next"].get("eps_estimate")
                                           or _fin(cal.get("Earnings Average")))
            out["next"]["eps_high"] = _fin(cal.get("Earnings High"))
            out["next"]["eps_low"] = _fin(cal.get("Earnings Low"))
            out["next"]["revenue_estimate"] = _fin(cal.get("Revenue Average"))
    except Exception:
        pass

    try:
        info = ticker.info or {}
        out["currency"] = info.get("financialCurrency") or info.get("currency")
        if out["next"] is not None:
            flag = info.get("isEarningsDateEstimate")
            out["next"]["estimated"] = bool(flag) if flag is not None else None
    except Exception:
        pass

    try:
        frame = ticker.quarterly_income_stmt
        if frame is not None and not frame.empty:
            for column in frame.columns:
                day = _day(column)
                if not day:
                    continue
                quarter = {"period": day}
                for label, key in _EARNINGS_ROWS:
                    quarter[key] = (_fin(frame.at[label, column])
                                    if label in frame.index else None)
                if any(quarter[k] is not None for _, k in _EARNINGS_ROWS):
                    out["quarters"].append(quarter)
            out["quarters"].sort(key=lambda q: q["period"], reverse=True)
    except Exception:
        pass

    if not out["history"] and not out["quarters"] and not out["next"]:
        return None
    return out


def earnings(symbols, today=None, cached_only=False):
    """When each company reported, what it did, and when it reports next.

    Stocks only. Funds were measured and answer with a 404 - asking eleven of
    them on every run would be eleven guaranteed failures a run, and the
    caller filters before it gets here.

    Same degradation ladder as `fundamentals` and `fund_composition`: a thin
    answer never overwrites a good cached one, and `cached_only` serves disk
    and asks nothing. An earnings date does not move intraday and the refresh
    runs 26 times a day.

    Returns (data, problems, pulled).
    """
    today = today or dt.date.today()
    cache = {}
    if C.EARNINGS_CACHE.exists():
        try:
            cache = json.loads(C.EARNINGS_CACHE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            cache = {}
    series = cache.get("symbols", {})

    out, problems, pulled = {}, {}, 0
    for symbol in symbols:
        if not symbol or symbol == "MISSING":
            continue
        held = series.get(symbol)
        if held and held.get("fetched") == str(today):
            out[symbol] = held
            continue
        if cached_only:
            if held:
                out[symbol] = held
            else:
                problems[symbol] = "no cached earnings"
            continue
        shaped = None
        try:
            import yfinance as yf
            shaped = _shape_earnings(yf.Ticker(symbol), today)
        except Exception:
            shaped = None
        if shaped:
            out[symbol] = {"fetched": str(today), "fields": shaped}
            pulled += 1
        elif (held or {}).get("fields"):
            out[symbol] = held
            problems[symbol] = (f"earnings came back empty; showing "
                                f"{held.get('fetched')}")
        else:
            out[symbol] = {"fetched": str(today), "fields": None}
            pulled += 1
            problems[symbol] = "no earnings from Yahoo"

    if not cached_only:
        _write_symbol_cache(C.EARNINGS_CACHE, series, out, today)
    return out, problems, pulled


# -------------------------------------------------------------------- Notion

def _load_env_file(path: Path):
    """Minimal .env reader. No dependency, no surprises."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def notion_token():
    return (os.environ.get("NOTION_TOKEN")
            or _load_env_file(C.ROOT / ".env").get("NOTION_TOKEN"))


def _plain(prop):
    """Flatten one Notion property to a scalar."""
    if not isinstance(prop, dict):
        return None
    kind = prop.get("type")
    val = prop.get(kind)
    if kind in ("title", "rich_text"):
        return "".join(part.get("plain_text", "") for part in val or []) or None
    if kind == "select":
        return (val or {}).get("name")
    if kind == "date":
        return (val or {}).get("start")
    if kind in ("number", "checkbox", "url"):
        return val
    if kind == "formula":
        inner = val or {}
        return inner.get(inner.get("type"))
    if kind == "status":
        return (val or {}).get("name")
    return None


def equity_log(cached_only=False):
    """The Notion Equity Log. Live if a token exists, else the cached snapshot.

    Returns (rows, meta) where meta records which path was taken and how old
    the data is, so the dashboard can be honest about it.

    `cached_only` skips Notion entirely, for the intraday refresh. A thesis is
    not rewritten between 10:00 and 10:30; what changes intraday is the price
    it is held against. Skipping the read keeps the refresh free of a second
    vendor and of a credential that can expire mid-afternoon.
    """
    if cached_only:
        rows, meta = _equity_log_cached()
        if not rows:
            meta["problem"] = ("intraday refresh has no Equity Log cache to "
                               "read; run `cockpit.py run` to populate it")
        return rows, meta
    token = notion_token()
    if token:
        rows, problem = _equity_log_live(token)
        if rows:
            C.EQUITY_LOG_CACHE.parent.mkdir(parents=True, exist_ok=True)
            C.EQUITY_LOG_CACHE.write_text(json.dumps(
                {"fetched": dt.datetime.now().isoformat(timespec="seconds"),
                 "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
            return rows, {"mode": "live", "age_days": 0, "problem": None}
        cached = _equity_log_cached()
        cached[1]["problem"] = f"live read failed ({problem}); using cache"
        return cached
    rows, meta = _equity_log_cached()
    meta["problem"] = meta["problem"] or (
        "no NOTION_TOKEN - using cached log. Run `cockpit.py sync-notion` "
        "in Claude to refresh, or add a token for hands-off updates.")
    return rows, meta


def _equity_log_live(token):
    import requests
    url = f"https://api.notion.com/v1/data_sources/{C.EQUITY_LOG_DATA_SOURCE}/query"
    headers = {"Authorization": f"Bearer {token}",
               "Notion-Version": "2025-09-03",
               "Content-Type": "application/json"}
    rows, cursor = [], None
    try:
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code != 200:
                return [], f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            for page in data.get("results", []):
                props = page.get("properties", {})
                row = {name: _plain(props.get(name)) for name in C.NOTION_PROPS}
                row["page_id"] = page.get("id")
                rows.append(row)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    except Exception as e:                      # network, DNS, timeout
        return [], f"{type(e).__name__}: {e}"
    return rows, None


def _equity_log_cached():
    if not C.EQUITY_LOG_CACHE.exists():
        return [], {"mode": "missing", "age_days": None,
                    "problem": "no Equity Log cache and no NOTION_TOKEN"}
    data = json.loads(C.EQUITY_LOG_CACHE.read_text(encoding="utf-8"))
    age = None
    try:
        fetched = dt.datetime.fromisoformat(data["fetched"])
        age = (dt.datetime.now() - fetched).days
    except Exception:
        pass
    return data.get("rows", []), {"mode": "cache", "age_days": age, "problem": None}


def notion_schema_ok():
    """Selftest helper: do the properties we read still exist?"""
    token = notion_token()
    if not token:
        return None, "no token; cannot verify live schema"
    rows, problem = _equity_log_live(token)
    if problem:
        return False, problem
    if not rows:
        return False, "Equity Log returned zero rows"
    missing = [p for p in C.NOTION_PROPS
               if p not in C.NOTION_PROPS_OPTIONAL
               and all(r.get(p) is None for r in rows)]
    if missing:
        return False, (f"properties returned nothing for every row: {missing}. "
                       "Renamed in Notion?")
    return True, None
