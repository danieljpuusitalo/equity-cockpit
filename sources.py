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


def price_history(symbols, today=None):
    """Daily bars per symbol, cached on disk and refetched once per day.

    The cache is what makes charts affordable on a 07:40 schedule: Yahoo is asked
    for a symbol only when what we hold is not from today. A symbol that fails
    keeps its last good bars and is reported stale - a chart that is a day old is
    worth far more than no chart.

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
        bars = _bars(symbol)
        if bars:
            out[symbol] = {"fetched": str(today), "bars": bars}
            pulled += 1
        elif held and held.get("bars"):
            out[symbol] = held                      # keep yesterday's rather than none
            problems[symbol] = f"history not refreshed; showing {held.get('fetched')}"
        else:
            problems[symbol] = "no history from Yahoo"

    C.PRICE_HISTORY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    C.PRICE_HISTORY_CACHE.write_text(json.dumps(
        {"fetched": str(today), "symbols": out}, separators=(",", ":")),
        encoding="utf-8")
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
_INFO_FIELDS = ("trailingPE", "forwardPE", "priceToBook", "marketCap",
                "trailingEps", "forwardEps", "totalDebt", "totalCash",
                "ebitda", "sector", "industry", "targetMeanPrice",
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
    }
    # A lone trailing P/E on an accumulating ETF is a portfolio-weighted
    # aggregate wearing a company's clothes - IMAE.AS returns exactly that and
    # nothing else. Require a real company's worth of fields before believing
    # any of it.
    if sum(1 for v in out.values() if v is not None) < 4:
        return None
    return out


def fundamentals(symbols, today=None):
    """Live multiples per symbol, cached on disk and refetched once a day.

    Same contract as price_history: ask Yahoo only when what we hold is not
    from today, keep the last good answer when a fetch fails, and report
    staleness rather than dropping the figure. A symbol that has never returned
    anything is cached as an explicit null so the miss is visible in the file
    rather than looking like a symbol nobody asked about.

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

    C.FUNDAMENTALS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    C.FUNDAMENTALS_CACHE.write_text(json.dumps(
        {"fetched": str(today), "symbols": out}, separators=(",", ":")),
        encoding="utf-8")
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


def equity_log():
    """The Notion Equity Log. Live if a token exists, else the cached snapshot.

    Returns (rows, meta) where meta records which path was taken and how old
    the data is, so the dashboard can be honest about it.
    """
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
