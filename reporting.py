"""The reporting calendar and the record behind it.

Two questions this answers that no other part of the cockpit can:

    what reports next, in what order of money at risk
    and when it last reported, was it better or worse than expected

THE ONE RULE THIS MODULE EXISTS TO ENFORCE: a quarter that has not been
reported is not a quarter that was reported as zero. Yahoo ships the upcoming
row with a NaN result, and every figure below treats absent as absent - it is
never averaged in, never counted as a miss, and never drawn as a bar at the
floor. The same mistake has already been made twice in this codebase against
two different vendors, and both times it manufactured a decline.

Pure: no network, no clock, no files. `today` is always passed in.
"""
from __future__ import annotations

import datetime as dt

import config as C


def _date(text):
    try:
        return dt.date.fromisoformat(str(text)[:10])
    except (TypeError, ValueError):
        return None


def _fields(cache, symbol):
    return ((cache or {}).get(symbol) or {}).get("fields") or {}


# ------------------------------------------------------------------ the record

def record(fields, limit=8):
    """Beats, misses and the typical size of the gap, over recent quarters.

    The median and not the mean, because one 215% surprise - Amazon has one on
    the record - would otherwise set the whole reading on its own. The count of
    quarters it is computed over rides along, so four quarters of history
    cannot be mistaken for eight.
    """
    rows = [r for r in (fields.get("history") or [])
            if r.get("surprise_pct") is not None][:limit]
    if not rows:
        return {"n": 0, "beats": 0, "misses": 0, "inline": 0,
                "median_surprise_pct": None, "last": None}
    surprises = sorted(r["surprise_pct"] for r in rows)
    middle = len(surprises) // 2
    median = (surprises[middle] if len(surprises) % 2
              else (surprises[middle - 1] + surprises[middle]) / 2)
    return {
        "n": len(rows),
        # A hair either side of consensus is not a beat. The threshold is one
        # number in config, applied here rather than in the page, so the
        # board and the alerts cannot disagree about what counts.
        "beats": sum(1 for r in rows if r["surprise_pct"] > C.EARNINGS_SURPRISE_PTS),
        "misses": sum(1 for r in rows if r["surprise_pct"] < -C.EARNINGS_SURPRISE_PTS),
        "inline": sum(1 for r in rows
                      if abs(r["surprise_pct"]) <= C.EARNINGS_SURPRISE_PTS),
        "median_surprise_pct": round(median, 1),
        "last": rows[0],
    }


def growth(fields):
    """Revenue and earnings against the SAME quarter a year earlier.

    Not against last quarter. A retailer's fourth quarter beats its third
    every year without anything having happened, and a cockpit that reported
    that as growth would be reporting the calendar.

    Returns None for either leg when the year-ago quarter is missing - several
    European names in this book file half-yearly and simply have no Q1 or Q3,
    and an absent quarter is not a quarter of zero revenue.
    """
    quarters = fields.get("quarters") or []
    if not quarters:
        return {"period": None, "revenue_yoy_pct": None, "eps_yoy_pct": None,
                "revenue": None, "net_income": None, "prior_period": None}
    latest = quarters[0]
    end = _date(latest["period"])
    prior = None
    if end:
        # Fiscal quarter ends drift by a few days year to year, so the match is
        # nearest-to-a-year-ago rather than exact, bounded so a missing quarter
        # cannot silently pair with one six months out.
        target = end - dt.timedelta(days=365)
        best = None
        for q in quarters[1:]:
            when = _date(q["period"])
            if not when:
                continue
            gap = abs((when - target).days)
            if gap <= 45 and (best is None or gap < best):
                best, prior = gap, q

    def change(now, was):
        if now is None or was is None or was == 0:
            return None
        # A sign flip has no percentage. Swinging from a loss to a profit is
        # not "+300% growth"; it is a different kind of event and gets said in
        # words elsewhere rather than invented as a number here.
        if (now < 0) != (was < 0):
            return None
        return round((now / was - 1) * 100, 1)

    return {
        "period": latest["period"],
        "prior_period": (prior or {}).get("period"),
        "revenue": latest.get("revenue"),
        "net_income": latest.get("net_income"),
        "revenue_yoy_pct": change(latest.get("revenue"), (prior or {}).get("revenue")),
        "eps_yoy_pct": change(latest.get("eps"), (prior or {}).get("eps")),
    }


# ---------------------------------------------------------------- the calendar

def calendar(positions, cache, today, horizon_days=None):
    """What reports in the next few weeks, nearest first.

    Each row carries the position's weight, because the question behind the
    calendar is not "who reports Tuesday" but "how much of the book is in
    front of a print this month".

    A name whose next date is unknown is reported as unknown, in its own count.
    Yahoo had no scheduled date at all for one holding in this book while still
    having six years of history for it, so silence here is a real state.
    """
    horizon = horizon_days or C.EARNINGS_HORIZON_DAYS
    total = sum(p["value_eur"] or 0 for p in positions) or 0.0
    rows, unknown, value_ahead = [], [], 0.0

    for pos in positions:
        if pos.get("klass") == "fund":
            continue
        fields = _fields(cache, pos.get("symbol"))
        weight = (pos["value_eur"] / total * 100) if total and pos["value_eur"] else 0.0
        nxt = fields.get("next") or {}
        when = _date(nxt.get("date"))
        if not when:
            unknown.append({"symbol": pos.get("symbol"), "name": pos.get("name"),
                            "weight_pct": round(weight, 2),
                            # Distinguishes "we never fetched this" from "Yahoo
                            # has the company and has no date for it". Only the
                            # second is a fact about the company.
                            "has_history": bool(fields.get("history"))})
            continue
        days = (when - today).days
        if days > horizon:
            continue
        row = {
            "symbol": pos.get("symbol"), "name": pos.get("name"),
            "date": str(when), "days": days,
            "weight_pct": round(weight, 2),
            "value_eur": round(pos["value_eur"] or 0, 2),
            # Yahoo's own flag for "this date is extrapolated from last year",
            # carried through rather than dropped. Printing a guessed date
            # beside a confirmed one without marking it is the whole
            # derived-status bug class in one column.
            "estimated": nxt.get("estimated"),
            "eps_estimate": nxt.get("eps_estimate"),
            "eps_high": nxt.get("eps_high"),
            "eps_low": nxt.get("eps_low"),
            "revenue_estimate": nxt.get("revenue_estimate"),
            "soon": days <= C.EARNINGS_SOON_DAYS,
            "record": record(fields),
            "growth": growth(fields),
        }
        rows.append(row)
        value_ahead += pos["value_eur"] or 0

    rows.sort(key=lambda r: (r["date"], -r["weight_pct"]))
    unknown.sort(key=lambda r: -r["weight_pct"])
    return {
        "rows": rows,
        "unknown": unknown,
        "n": len(rows),
        "n_unknown": len(unknown),
        "n_soon": sum(1 for r in rows if r["soon"]),
        "horizon_days": horizon,
        "value_ahead_eur": round(value_ahead, 2),
        "pct_ahead": round(value_ahead / total * 100, 1) if total else 0.0,
    }


def latest(positions, cache, today, limit=None):
    """The most recent reported quarter per stock, newest print first.

    This is the "what came in" half. It reads only rows that carry an actual
    result, so the upcoming quarter can never appear here wearing a zero.
    """
    total = sum(p["value_eur"] or 0 for p in positions) or 0.0
    rows = []
    for pos in positions:
        if pos.get("klass") == "fund":
            continue
        fields = _fields(cache, pos.get("symbol"))
        rec = record(fields)
        if not rec["last"]:
            continue
        last = rec["last"]
        when = _date(last["date"])
        rows.append({
            "symbol": pos.get("symbol"), "name": pos.get("name"),
            "date": last["date"],
            "days_ago": (today - when).days if when else None,
            "weight_pct": round(pos["value_eur"] / total * 100, 2)
            if total and pos["value_eur"] else 0.0,
            "eps_estimate": last.get("eps_estimate"),
            "eps_reported": last.get("eps_reported"),
            "surprise_pct": last.get("surprise_pct"),
            "beat": (None if last.get("surprise_pct") is None
                     else last["surprise_pct"] > C.EARNINGS_SURPRISE_PTS),
            "record": rec,
            "growth": growth(fields),
            "currency": fields.get("currency"),
        })
    rows.sort(key=lambda r: (r["date"], r["weight_pct"]), reverse=True)
    return rows[:limit] if limit else rows


# ------------------------------------------------------------------- assemble

def book(holdings, cache, today):
    """Everything the page and the alerts need, off one pass. Pure."""
    seen, positions = {}, []
    for row in holdings:
        symbol = row.get("yahoo")
        if not symbol or symbol == "MISSING":
            continue
        # Holdings are per ISIN per account; a name held in both custody
        # accounts reports once, not twice, so the accounts fold first.
        if symbol in seen:
            seen[symbol]["value_eur"] += row.get("value_eur") or 0
            continue
        seen[symbol] = {
            "symbol": symbol,
            "name": row.get("name") or symbol,
            "value_eur": row.get("value_eur") or 0,
            "klass": C.ASSET_CLASS.get(row.get("isin"), "stock"),
        }
        positions.append(seen[symbol])

    ahead = calendar(positions, cache, today)
    return {
        "calendar": ahead,
        "latest": latest(positions, cache, today),
        "n_covered": sum(1 for p in positions if p["klass"] != "fund"
                         and _fields(cache, p["symbol"])),
        "n_stocks": sum(1 for p in positions if p["klass"] != "fund"),
        "asof": str(today),
    }


# --------------------------------------------------------------------- alerts

def alerts(view):
    """Two things worth a line: a print coming, and a print that landed badly.

    Nothing here fires on a date alone being unknown - that is a gap in Yahoo,
    not an event in the book, and it belongs on the page rather than in a
    notification.
    """
    out = []
    for row in view["calendar"]["rows"]:
        if not row["soon"]:
            continue
        when = ("tomorrow" if row["days"] == 1 else
                "today" if row["days"] == 0 else f"in {row['days']} days")
        estimate = ("" if row["eps_estimate"] is None
                    else f", consensus {row['eps_estimate']:.2f}")
        guess = " (Yahoo's estimated date, not confirmed)" if row["estimated"] else ""
        out.append({
            "level": "info",
            "title": f"{row['symbol']} reports {when}",
            "detail": (f"{row['name']} reports {row['date']}{estimate}. "
                       f"{row['weight_pct']:.1f}% of the book"
                       f"{guess}."),
        })

    for row in view["latest"]:
        surprise = row["surprise_pct"]
        # Only a fresh print. An old miss is history and has had a quarter to
        # be acted on; re-announcing it every morning is the thing this board
        # exists not to do.
        if surprise is None or row["days_ago"] is None:
            continue
        if row["days_ago"] > C.EARNINGS_SOON_DAYS:
            continue
        if abs(surprise) < C.EARNINGS_SURPRISE_PTS:
            continue
        missed = surprise < 0
        out.append({
            "level": "warning" if missed else "info",
            "title": f"{row['symbol']} {'missed' if missed else 'beat'} "
                     f"by {abs(surprise):.0f}%",
            "detail": (f"{row['name']} reported {row['date']}: "
                       f"{row['eps_reported']:.2f} against "
                       f"{row['eps_estimate']:.2f} expected. "
                       f"{row['weight_pct']:.1f}% of the book."),
        })
    return out
