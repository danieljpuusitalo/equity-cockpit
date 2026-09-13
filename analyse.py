"""The join. This is the part no product on the market does for you.

Notion holds the judgement (thesis, target, the condition that would change
your mind). Nordnet holds the truth about what you own. Yahoo holds the price.
Everything here exists to hold those three against each other and report where
they disagree.
"""
from __future__ import annotations

import re
import datetime as dt

import config as C

# ------------------------------------------------------------------ triggers

# Price levels written into the free-text Trigger field, e.g.
#   "Price below USD 285 does the same"
#   "Under ~220 the add question reopens"
#   "forced selling takes it below SEK 185"
#   "Price below 3,700p does the same"
_LEVEL = r"(\d[\d,.]*)"
# "~$120", "SEK 185", "USD 285", "3,700p" - currency and tilde in either order.
_PRE = r"[~≈]?\s*(?:USD|EUR|SEK|NOK|DKK|GBP|GBp|\$|€|£)?\s*[~≈]?\s*"
_PATTERNS = [
    (re.compile(r"below\s+" + _PRE + _LEVEL, re.I), "below"),
    (re.compile(r"under\s+" + _PRE + _LEVEL, re.I), "below"),
    (re.compile(r"drops?\s+to\s+" + _PRE + _LEVEL, re.I), "below"),
    (re.compile(r"above\s+" + _PRE + _LEVEL, re.I), "above"),
    (re.compile(r"over\s+" + _PRE + _LEVEL, re.I), "above"),
]

# A number wearing one of these is a quantity, not a share price: "net debt
# below EUR 70M", "reguide below $8bn", "margin below 20%", "under 12x".
# Getting this wrong is worse than parsing nothing - it fires a false alert.
_NOT_A_PRICE = re.compile(r"^\s*(?:%|x\b|m\b|mn\b|bn\b|b\b|k\b|"
                          r"million|billion|percent)", re.I)


def _to_float(raw):
    raw = raw.strip().rstrip("p").replace(" ", "")
    # 3,700 is three thousand seven hundred; 1,5 would be Finnish decimal.
    if "," in raw and "." not in raw:
        whole, _, frac = raw.rpartition(",")
        raw = raw.replace(",", "") if len(frac) == 3 else f"{whole}.{frac}"
    else:
        raw = raw.replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_trigger(text, reference=None):
    """Pull a machine-checkable price level out of trigger prose.

    Returns (level, kind) or (None, None). Deliberately conservative, because
    a wrong level is worse than no level: it wakes you at 3am over a number
    that was never a price. Two guards - a unit suffix rejects quantities
    ("EUR 70M", "$8bn", "20%"), and if a reference price is supplied the level
    must land in a plausible band around it.
    """
    if not text:
        return None, None
    for pattern, kind in _PATTERNS:
        for match in pattern.finditer(text):
            if _NOT_A_PRICE.match(text[match.end():match.end() + 12]):
                continue
            value = _to_float(match.group(1))
            if value is None:
                continue
            if reference and not (0.4 * reference <= value <= 2.5 * reference):
                continue
            return value, kind
    return None, None


def days_until(date_str, today=None):
    if not date_str:
        return None
    today = today or dt.date.today()
    try:
        return (dt.date.fromisoformat(date_str[:10]) - today).days
    except ValueError:
        return None


# ------------------------------------------------------------------ holdings

def value_holdings(positions, quotes, fx):
    """Attach live prices to positions. Anything unpriced is marked, not dropped."""
    rows = []
    for pos in positions:
        row = dict(pos)
        symbol, rate = pos["yahoo"], fx.get(pos["ccy"])
        quote = quotes.get(symbol) if symbol and symbol != "MISSING" else None

        if quote and rate:
            row["price"] = quote["price"]
            row["value_eur"] = round(quote["price"] * pos["units"] * rate, 2)
            row["stale"] = False
            prev = quote.get("prev_close")
            row["day_pct"] = (round((quote["price"] / prev - 1) * 100, 2)
                              if prev else None)
            high = quote.get("year_high")
            row["off_high"] = (round((quote["price"] / high - 1) * 100, 1)
                               if high else None)
            row["year_high"], row["year_low"] = high, quote.get("year_low")
        else:
            # Fall back to Nordnet's own valuation rather than dropping the row.
            row["price"] = None
            row["value_eur"] = pos["nordnet_mv_eur"]
            row["stale"] = True
            row["day_pct"] = row["off_high"] = None
            row["year_high"] = row["year_low"] = None
            row["stale_reason"] = ("no public feed" if symbol is None
                                   else "price fetch failed")

        cost = pos["cost_eur"]
        row["pl_eur"] = round(row["value_eur"] - cost, 2) if cost else None
        row["pl_pct"] = round((row["value_eur"] / cost - 1) * 100, 2) if cost else None
        rows.append(row)
    return rows


# ------------------------------------------------------- annualised return

# Below this a money-weighted return is arithmetically real and practically a
# lie: annualising three weeks of noise produces 400%. Reported as None with a
# reason rather than a number nobody should act on.
#
# Measured on the COST-WEIGHTED holding period, not on the first purchase date.
# The difference is not academic - it was found by cross-checking the live book.
# The Nordnet index funds are monthly savings: their first lot is over a year
# old, so a first-date guard passed them, but almost all the money went in
# recently, and a 3.4% gain over a weighted 25 days was being annualised into
# 55%/yr. Weighting by cost asks "how long was the money actually at risk",
# which is the horizon the return was earned over.
_MIN_IRR_DAYS = 90


def xirr(flows, today=None):
    """Money-weighted annual return from dated cash flows, by bisection.

    `flows` is [(date, amount)] with money out negative and money in positive.
    Bisection rather than Newton because it cannot diverge: the NPV of a normal
    buy-then-hold flow is monotonic over the bracket, so halving always
    converges or honestly reports that it cannot.

    Returns a decimal rate (0.12 == 12%/yr) or None.
    """
    flows = [(d, a) for d, a in flows if a]
    if len(flows) < 2:
        return None
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None                      # no sign change - no root to find

    base = min(d for d, _ in flows)
    span = [(d - base).days / 365.0 for d, _ in flows]
    amounts = [a for _, a in flows]

    def npv(rate):
        total = 0.0
        for years, amount in zip(span, amounts):
            try:
                total += amount / ((1.0 + rate) ** years)
            except (OverflowError, ZeroDivisionError):
                return float("inf")
        return total

    lo, hi = -0.9999, 10.0
    npv_lo, npv_hi = npv(lo), npv(hi)
    if npv_lo != npv_lo or npv_hi != npv_hi:          # NaN
        return None
    if npv_lo * npv_hi > 0:
        return None                      # root outside -99.99%..+1000%/yr
    for _ in range(200):
        mid = (lo + hi) / 2
        value = npv(mid)
        if abs(value) < 1e-7:
            return mid
        if value * npv_lo > 0:
            lo, npv_lo = mid, value
        else:
            hi = mid
    return (lo + hi) / 2


def attach_returns(holdings, lots, today=None):
    """Per-position money-weighted return, plus the portfolio as a whole.

    The Nordnet export already carries `Tuotto-%` and `Tuotto-% (p.a)` per lot,
    and the header check asserts both columns exist - but they were never
    parsed, and they would be stale anyway: they are computed on the export
    date, which is routinely days old. These are computed off the LIVE price
    instead, so they move with the book rather than with the last export.

    Simple P/L already on the row answers "how much". This answers "how fast",
    which is the question that tells a three-year hold apart from a three-week
    one at the same +18%.
    """
    today = today or dt.date.today()

    def _group_irr(group_lots, value):
        """One IRR over a set of lots against a single current value."""
        flows, first, weighted, cost = [], None, 0.0, 0.0
        for lot in group_lots:
            try:
                bought = dt.date.fromisoformat(lot["bought"][:10])
            except (ValueError, TypeError):
                continue
            if not lot["cost_eur"]:
                continue
            flows.append((bought, -lot["cost_eur"]))
            first = bought if first is None else min(first, bought)
            weighted += (today - bought).days * lot["cost_eur"]
            cost += lot["cost_eur"]
        if not flows or not value or first is None or not cost:
            return {"irr_pct": None, "since": None, "held_days": None,
                    "note": "no dated cost basis"}
        held = int(weighted / cost)          # cost-weighted days at risk
        if held < _MIN_IRR_DAYS:
            return {"irr_pct": None, "since": str(first), "held_days": held,
                    "note": f"money at risk a weighted {held}d - "
                            "too short to annualise"}
        rate = xirr(flows + [(today, value)], today)
        return {"irr_pct": round(rate * 100, 1) if rate is not None else None,
                "since": str(first), "held_days": held,
                "note": None if rate is not None else "did not converge"}

    # Per custody row, so the data sheet can show it per account.
    by_key = {}
    for lot in lots:
        by_key.setdefault((lot["isin"], lot["account_no"]), []).append(lot)
    for row in holdings:
        result = _group_irr(by_key.get((row["isin"], row["account_no"]), []),
                            row.get("value_eur"))
        row["irr_pct"] = result["irr_pct"]
        row["holding_days"] = result["held_days"]
        row["irr_note"] = result["note"]

    # Per symbol, because the page folds the two custody accounts together and
    # DESIGN forbids the browser deciding anything it could have been told. A
    # blended IRR is not the average of two IRRs, so it has to be computed over
    # the combined flows rather than averaged afterwards.
    by_symbol, value_by_symbol, lots_by_symbol = {}, {}, {}
    symbol_of = {}
    for row in holdings:
        symbol = row.get("yahoo") or row.get("tunnus")
        if not symbol or symbol == "MISSING":
            continue
        symbol_of[(row["isin"], row["account_no"])] = symbol
        value_by_symbol[symbol] = (value_by_symbol.get(symbol, 0.0)
                                   + (row.get("value_eur") or 0))
    for lot in lots:
        symbol = symbol_of.get((lot["isin"], lot["account_no"]))
        if symbol:
            lots_by_symbol.setdefault(symbol, []).append(lot)
    for symbol, group in lots_by_symbol.items():
        by_symbol[symbol] = _group_irr(group, value_by_symbol.get(symbol))

    # Portfolio level: every lot as its own outflow, the whole book as one
    # inflow today. This is the number Nordnet's per-lot column cannot give you.
    book = _group_irr(lots, sum(h.get("value_eur") or 0 for h in holdings))
    book["by_symbol"] = by_symbol
    return book


def price_sanity(holdings):
    """Cross-check live prices against Nordnet's own market value.

    Nordnet valued every lot on the export date. If our live price implies a
    wildly different number, the ISIN -> Yahoo mapping is wrong (wrong listing
    line, wrong share class, wrong currency). This is the check that caught
    WDEF. It is the difference between a dashboard you can trust and one that
    quietly lies.
    """
    findings = []
    for row in holdings:
        if row["stale"] or not row["nordnet_mv_eur"]:
            continue
        divergence = (row["value_eur"] / row["nordnet_mv_eur"] - 1) * 100
        row["vs_nordnet_pct"] = round(divergence, 1)
        if abs(divergence) >= C.PRICE_DIVERGENCE_PCT:
            findings.append({
                "isin": row["isin"], "ticker": row["tunnus"],
                "yahoo": row["yahoo"], "divergence_pct": round(divergence, 1),
                "live_value_eur": row["value_eur"],
                "nordnet_value_eur": row["nordnet_mv_eur"],
                "message": (
                    f"{row['tunnus']}: live price implies EUR {row['value_eur']:,.0f} "
                    f"but Nordnet valued it at EUR {row['nordnet_mv_eur']:,.0f} "
                    f"({divergence:+.1f}%). Check the {row['yahoo']} mapping - "
                    "wrong listing line or share class."),
            })
    return findings


# ----------------------------------------------------------------- watchlist

def join_watchlist(log_rows, quotes, holdings, today=None):
    """Recompute every Equity Log row against the live price."""
    today = today or dt.date.today()
    held_by_ticker = {h["tunnus"].upper(): h for h in holdings}
    out = []

    for row in log_rows:
        ticker = (row.get("Ticker") or "").strip()
        symbol = _yahoo_for(ticker)
        quote = quotes.get(symbol)
        price_now = quote["price"] if quote else None
        eval_price = _f(row.get("Price at eval"))
        target = _f(row.get("Target"))

        item = {
            "ticker": ticker,
            "yahoo": symbol,
            "company": row.get("Company"),
            "verdict": row.get("Verdict"),
            "tier": str(row.get("Tier") or ""),
            "held_notion": row.get("Held"),
            "ccy": row.get("Currency"),
            "price_at_eval": eval_price,
            "price_now": price_now,
            "target": target,
            "last_eval": row.get("Last evaluated"),
            "next_check": row.get("Next check"),
            "trigger": row.get("Trigger"),
            # The three fields the 2026-09-13 Notion split created. Read since
            # then, but until now dropped here - so the board held a thesis and
            # the page never showed one. If these stop arriving, check
            # NOTION_PROPS before suspecting the renderer.
            "thesis": row.get("Thesis"),
            "inflection_date": row.get("Inflection date"),
            "inflection_event": row.get("Inflection event"),
            "page_id": row.get("page_id"),
            "stale_price": price_now is None,
            "market": row.get("Market"),
            "moat": row.get("Moat"),
            "pe": _f(row.get("P/E")),
            "fwd_pe": _f(row.get("Fwd P/E")),
            "net_debt_ebitda": _f(row.get("Net debt/EBITDA")),
            "previous_verdict": row.get("Previous verdict"),
            "evaluations": row.get("Evaluations"),
        }

        item["drift_pct"] = (round((price_now / eval_price - 1) * 100, 2)
                             if price_now and eval_price else None)
        item["upside_now"] = (round((target / price_now - 1) * 100, 1)
                              if price_now and target else None)
        item["upside_at_eval"] = (round((target / eval_price - 1) * 100, 1)
                                  if eval_price and target else None)
        item["upside_decay_pts"] = (
            round(item["upside_now"] - item["upside_at_eval"], 1)
            if item["upside_now"] is not None
            and item["upside_at_eval"] is not None else None)

        level, kind = parse_trigger(row.get("Trigger"), price_now or eval_price)
        item["trigger_level"], item["trigger_kind"] = level, kind
        if level and price_now:
            gap = (level / price_now - 1) * 100
            item["trigger_gap_pct"] = round(gap, 1)
            item["trigger_hit"] = (price_now <= level if kind == "below"
                                   else price_now >= level)
        else:
            item["trigger_gap_pct"] = None
            item["trigger_hit"] = None

        item["days_to_check"] = days_until(row.get("Next check"), today)
        # A real date property, unlike the "late Oct 2026" that used to sit
        # inside the Trigger prose where no machine could read it.
        item["days_to_inflection"] = days_until(row.get("Inflection date"), today)
        item["days_since_eval"] = (
            -days_until(row.get("Last evaluated"), today)
            if days_until(row.get("Last evaluated"), today) is not None else None)

        actual = held_by_ticker.get(_base_ticker(ticker).upper())
        item["held_actual"] = actual["account"] if actual else "Not held"
        item["held_units"] = actual["units"] if actual else None
        out.append(item)
    return out


def _base_ticker(ticker):
    return (ticker or "").split(".")[0].strip()


def _yahoo_for(ticker):
    """Equity Log tickers are already Yahoo-shaped ('TNOM.HE', 'GOOGL')."""
    return (ticker or "").strip() or None


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def reconcile(watchlist):
    """Where the Notion `Held` field and the broker export disagree."""
    issues = []
    for item in watchlist:
        notion = (item["held_notion"] or "").strip()
        actual = item["held_actual"]
        if notion in ("", "-"):
            issues.append({"ticker": item["ticker"], "kind": "blank",
                           "notion": notion or "(blank)", "actual": actual,
                           "message": f"{item['ticker']}: Held is blank in Notion; "
                                      f"broker says {actual}."})
            continue
        notion_held = notion.upper() not in ("NOT HELD", "NO", "NONE")
        actual_held = actual != "Not held"
        if notion_held != actual_held:
            issues.append({"ticker": item["ticker"], "kind": "mismatch",
                           "notion": notion, "actual": actual,
                           "message": f"{item['ticker']}: Notion says '{notion}', "
                                      f"broker export says '{actual}'."})
    return issues


# ------------------------------------------------------------------ coverage

def coverage(holdings, watchlist):
    """Is every euro in the book actually being monitored, and by what standard?

    Two standards, because there are two kinds of holding:

      stock -> judged by THESIS. It owes a row on the Equity Log carrying a
               target and a condition that would falsify it.
      fund  -> judged by ALLOCATION. It owes a target weight and has to stay
               inside a drift band. A world index tracker has no thesis to
               falsify, and demanding one produces a warning that can never be
               cleared - which is indistinguishable from no warning at all.

    Written because the first honest measurement of this book found 88% of it
    by value carrying no thesis, while ten of the thirteen Equity Log rows were
    names that were not held. The Log was a research pipeline being read as a
    portfolio record, and nothing in the system said so.
    """
    total = sum(h["value_eur"] or 0 for h in holdings) or 1.0

    # Notion tickers are not Yahoo symbols (BATS.L, DOM.ST, plain GOOGL), so
    # match through the same mapping the watchlist join already uses.
    logged = {}
    for item in watchlist:
        symbol = _yahoo_for(item["ticker"])
        if symbol:
            logged[symbol] = item

    rows = []
    for h in holdings:
        isin, symbol = h["isin"], h.get("yahoo")
        klass = C.ASSET_CLASS.get(isin, "stock")
        weight = round((h["value_eur"] or 0) / total * 100, 2)
        item = logged.get(symbol) if symbol and symbol != "MISSING" else None

        row = {"isin": isin, "ticker": h.get("tunnus") or symbol or isin,
               "name": h.get("name", ""), "klass": klass, "account": h.get("account"),
               "value_eur": h["value_eur"], "weight_pct": weight,
               "target_weight_pct": None, "drift_pts": None,
               "covered": False, "gap": None}

        if klass == "fund":
            target = C.TARGET_WEIGHT.get(isin)
            row["target_weight_pct"] = target
            if target is None:
                row["gap"] = "no target weight set"
            else:
                drift = round(weight - target, 2)
                row["drift_pts"] = drift
                row["covered"] = True
                if abs(drift) > C.WEIGHT_DRIFT_PCT:
                    side = "above" if drift > 0 else "below"
                    row["gap"] = (f"{abs(drift):.1f} pts {side} its "
                                  f"{target:g}% target weight")
        else:
            if item is None:
                row["gap"] = "no thesis on the Equity Log"
            elif item.get("target") in (None, ""):
                row["gap"] = "on the Log but carries no target"
            else:
                row["covered"] = True
                if not (item.get("trigger") or "").strip():
                    row["gap"] = "target but no falsifying condition written"

        rows.append(row)

    rows.sort(key=lambda r: -(r["value_eur"] or 0))
    uncovered = [r for r in rows if not r["covered"]]

    # Rows on the Log that are not in the book. Not a fault - it is how research
    # is supposed to work - but it is why "13 logged" was read as coverage when
    # only three of those names were owned.
    held_symbols = {h.get("yahoo") for h in holdings}
    researched = sorted(i["ticker"] for i in watchlist
                        if _yahoo_for(i["ticker"]) not in held_symbols)

    return {
        "rows": rows,
        "value_total_eur": round(total, 2),
        "value_uncovered_eur": round(sum(r["value_eur"] or 0 for r in uncovered), 2),
        "pct_uncovered": round(
            sum(r["value_eur"] or 0 for r in uncovered) / total * 100, 1),
        "n_uncovered": len(uncovered),
        "n_stocks": sum(1 for r in rows if r["klass"] == "stock"),
        "n_funds": sum(1 for r in rows if r["klass"] == "fund"),
        "researched_not_held": researched,
    }


# -------------------------------------------------------------------- alerts

def alerts(watchlist, holdings, health, cover=None):
    """What actually deserves your attention today, most urgent first."""
    found = []

    # Coverage is deliberately ONE alert, not one per uncovered name. Twenty
    # separate "no thesis" warnings is a wall, and a wall gets muted; the
    # cooldown key carries the count so it re-fires when the number moves.
    if cover and cover["n_uncovered"]:
        biggest = [r for r in cover["rows"] if not r["covered"]][:3]
        found.append({
            "level": "warning",
            "key": f"coverage:{cover['n_uncovered']}",
            "title": f"{cover['pct_uncovered']:.0f}% of the book "
                     f"({cover['n_uncovered']} holdings) is not being monitored",
            "detail": "; ".join(f"{r['ticker']} EUR {r['value_eur']:,.0f} - {r['gap']}"
                                for r in biggest)})

    for item in watchlist:
        if item.get("trigger_hit"):
            found.append({
                "level": "critical", "key": f"trigger-hit:{item['ticker']}",
                "title": f"{item['ticker']} has hit its written trigger",
                "detail": f"Live {item['price_now']:.2f} {item['ccy']} vs trigger "
                          f"{item['trigger_level']}. {item['trigger']}"})

    for item in watchlist:
        days = item.get("days_to_check")
        if days is not None and 0 <= days <= C.CHECK_SOON_DAYS:
            found.append({
                "level": "warning", "key": f"check-due:{item['ticker']}:{item['next_check']}",
                "title": f"{item['ticker']} catalyst in {days} days ({item['next_check']})",
                "detail": item["trigger"] or ""})

    # The inflection date is the event that will actually settle the thesis -
    # the print, the trading update, the decision. It is a separate alert from
    # "next check" because one is a date you chose to look again and the other
    # is a date the world acts on you. Silent until a date is actually set.
    for item in watchlist:
        days = item.get("days_to_inflection")
        if days is not None and 0 <= days <= C.CHECK_SOON_DAYS:
            event = (item.get("inflection_event") or "").strip()
            found.append({
                "level": "warning",
                "key": f"inflection:{item['ticker']}:{item['inflection_date']}",
                "title": f"{item['ticker']}: {event or 'inflection event'} in "
                         f"{days} days ({item['inflection_date']})",
                "detail": (item.get("thesis") or item.get("trigger") or
                           "No thesis written for this name.")})

    for item in watchlist:
        gap = item.get("trigger_gap_pct")
        if gap is not None and not item.get("trigger_hit") and abs(gap) <= C.TRIGGER_NEAR_PCT:
            found.append({
                "level": "warning", "key": f"trigger-near:{item['ticker']}",
                "title": f"{item['ticker']} is {abs(gap):.1f}% from its trigger",
                "detail": f"Live {item['price_now']:.2f} {item['ccy']}, "
                          f"trigger at {item['trigger_level']}."})

    for item in watchlist:
        decay = item.get("upside_decay_pts")
        if decay is not None and abs(decay) >= C.DECAY_ALERT_PTS:
            direction = "widened" if decay > 0 else "narrowed"
            found.append({
                "level": "warning" if decay < 0 else "good",
                "key": f"decay:{item['ticker']}:{round(decay)}",
                "title": f"{item['ticker']} upside {direction} "
                         f"{item['upside_at_eval']:.1f}% -> {item['upside_now']:.1f}%",
                "detail": f"Price moved {item['drift_pct']:+.1f}% since the "
                          f"{item['last_eval']} check. The board still says "
                          f"{item['upside_at_eval']:.1f}%."})

    # Health problems ride in the alert list because that is what Telegram
    # reads - a task that quietly stopped running has to be able to say so.
    # The page tags them and shows them in its banner instead, so the same
    # sentence is not printed twice.
    for problem in health.get("problems", []):
        found.append({"level": problem["level"], "key": problem["key"],
                      "title": problem["title"], "detail": problem["detail"],
                      "health": True})

    order = {"critical": 0, "warning": 1, "good": 2}
    found.sort(key=lambda a: order.get(a["level"], 3))
    return found
