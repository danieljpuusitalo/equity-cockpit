"""What the book did between two exports - the sales the CSV cannot report.

The Nordnet `ostoerittain` view is holdings-by-lot: it lists what you bought
and still hold. It never lists a sale. A name sold down from 14 shares to 7
simply appears with 7; a name sold out entirely vanishes from the file with no
row to notice. Everything downstream compares the board against the broker on
`Held`, which stays true through a partial sale, so a trim is indistinguishable
from no activity at all. On 2026-09-18 CRM went 14 -> 7 and the run printed
"All sources fresh" with `status: ok`, while the Equity Log rated it
Buy-worthy. A thesis-versus-action divergence is the single thing this cockpit
exists to surface, and it was the one divergence it could not see.

The fix is not a new feed. It is memory: keep the lot book from the last export
and diff the next one against it. A sale is then the difference between two
pictures, which is the only form in which this vendor will ever report one.

THE RULE THIS MODULE EXISTS TO ENFORCE: a file that has not been re-exported is
not a period in which nothing happened. Re-reading the same CSV yields the same
positions, and calling that "no activity" would be a derived status claiming
far more than it knows - this repo's signature bug class, and here it would be
claiming that nothing was sold. So the diff has three outcomes, not two:
changes, no changes, and **not comparable**, and the third one says so out loud
on the page. A diff is only run across two genuinely different export dates.

The second trap is the same one in the other direction: an unreadable or
truncated CSV parses to few positions or none, and against yesterday's snapshot
that reads as *the entire book was sold today*. So the caller must hand this
module a healthy parse, and `diff` additionally refuses a comparison in which
everything vanished at once (see `_IMPLAUSIBLE_EXIT_SHARE`).

The third is that units move for reasons that are not transactions. A 2:1 split
doubles the unit count with the cost basis untouched. Cost is what separates
them: a purchase costs money, a split does not. Anything that moves units while
leaving cost alone is reported as a corporate action, never as a trade.

Pure: no network, no clock, no files. `today` and the snapshot are passed in.
"""
from __future__ import annotations

# A cost difference smaller than this is rounding in the export, not money
# changing hands. `sources.positions` already rounds cost to 2 decimals.
_COST_EPSILON = 0.01

# Units are rounded to 4 decimals upstream; anything smaller is not a trade.
_UNIT_EPSILON = 0.0001

# If this share of the previous book disappears in one export, the more likely
# explanation is a bad file than a liquidation. The diff refuses rather than
# reporting twenty exits - see the module docstring. A real liquidation trips
# this too, and that is the right trade: it is reported as "not comparable,
# check the export", which asks a human to look, rather than as twenty alerts
# that might be an artefact.
#
# The FLOOR is the half that is easy to leave out and wrong to. A share test on
# its own scales all the way down: a two-holding book that sells one is 50%, a
# one-holding book that sells it is 100%, and both would be refused as corrupt
# when they are the most ordinary events there are. Below the floor, exits are
# read as exits no matter what share of the book they are - the artefact this
# guard is aimed at is a short read of a 24-line file, which is many rows at
# once or it is nothing.
_IMPLAUSIBLE_EXIT_SHARE = 0.8
_IMPLAUSIBLE_EXIT_FLOOR = 5


def _key(pos):
    """Identity is the holding in one account, not the company.

    A sale in the OST and a purchase of the same name in the AOT nets to zero
    at book level and is two real transactions. The broker's own unit is the
    account, so that is the unit here.
    """
    return f"{pos.get('isin', '')}|{pos.get('account_no', '')}"


def snapshot(lots, exported, positions=None):
    """The lot book as it stands, small enough to keep and diff.

    Built from LOTS, not from positions: `sources.positions` aggregates the
    lot ladder away and keeps only `first_bought`, and the ladder is exactly
    what distinguishes "one lot closed outright" from "every lot trimmed a
    little" - a decision against a rebalance. `buys` maps purchase date ->
    units still held from that date.

    `positions` is optional and supplies only display metadata (the account
    label and the Yahoo symbol, both of which are config lookups rather than
    anything the CSV says). Nothing compared by `diff` comes from it.
    """
    meta = {_key(p): p for p in (positions or ())}
    out = {}
    for lot in lots or ():
        key = _key(lot)
        src = meta.get(key, {})
        row = out.setdefault(key, {
            "isin": lot.get("isin", ""),
            "account_no": lot.get("account_no", ""),
            "account": src.get("account", "") or lot.get("account_no", ""),
            "ticker": lot.get("tunnus") or lot.get("name") or "",
            "name": lot.get("name", ""),
            "yahoo": src.get("yahoo"),
            "units": 0.0,
            "cost_eur": 0.0,
            "lots": 0,
            "buys": {},
        })
        units = float(lot.get("units") or 0.0)
        row["units"] = round(row["units"] + units, 4)
        row["cost_eur"] = round(
            row["cost_eur"] + float(lot.get("cost_eur") or 0.0), 2)
        row["lots"] += 1
        # Two lots bought the same day are one rung on the ladder. Nordnet
        # does split a single order across rows, and treating those as two
        # rungs would report a "closed lot" every time one of them filled.
        bought = str(lot.get("bought") or "")[:10]
        if bought:
            row["buys"][bought] = round(row["buys"].get(bought, 0.0) + units, 4)
    return {"exported": str(exported or "")[:10] or None, "positions": out}


def _buys_delta(before, after):
    """Which purchase dates vanished, and which shrank."""
    closed, trimmed = [], []
    for date, units in sorted((before or {}).items()):
        now = (after or {}).get(date)
        if now is None or float(now) <= _UNIT_EPSILON:
            closed.append({"bought": date, "units": round(float(units), 4)})
        elif float(units) - float(now) > _UNIT_EPSILON:
            trimmed.append({"bought": date,
                            "units": round(float(units) - float(now), 4)})
    return closed, trimmed


def _classify(before, after):
    """One holding, two pictures. Returns (kind, detail-fragment).

    Cost, not units, decides whether money moved. See the module docstring on
    splits: units are not evidence of a transaction on their own.
    """
    du = round(float(after["units"]) - float(before["units"]), 4)
    dc = round(float(after["cost_eur"]) - float(before["cost_eur"]), 2)
    moved_cost = abs(dc) > _COST_EPSILON
    moved_units = abs(du) > _UNIT_EPSILON

    if not moved_units and not moved_cost:
        return None, {}
    if moved_units and not moved_cost:
        return "adjusted", {
            "why": "units moved with the cost basis untouched, which is a "
                   "corporate action (a split or a redenomination), not a trade"}
    if not moved_units and moved_cost:
        return "adjusted", {
            "why": "the cost basis was restated with the unit count unchanged"}
    return ("reduced" if du < 0 else "increased"), {}


def diff(previous, current):
    """Compare two lot books. Says "cannot tell" whenever that is the truth.

    `previous` is a stored snapshot dict (or None on the first ever run);
    `current` is a fresh one from `snapshot()`. The return always carries
    `comparable` and `reason` - a caller that reads `changes` alone and finds
    it empty would be reading "we did not look" as "nothing happened".
    """
    cur_positions = (current or {}).get("positions") or {}
    cur_exported = (current or {}).get("exported")
    prev_positions = (previous or {}).get("positions") or {}
    prev_exported = (previous or {}).get("exported")

    def no(reason):
        return {"comparable": False, "reason": reason, "changes": [],
                "from_exported": prev_exported, "to_exported": cur_exported}

    if not cur_exported:
        return no("this export carries no export date")
    if previous is None:
        return no("first export on record - nothing to compare it against yet")
    if not prev_exported:
        return no("the stored lot book carries no export date")
    if cur_exported == prev_exported:
        # The whole point of the module. Re-reading one file twice is not a
        # quiet week; it is the same photograph developed twice.
        return no(f"the export has not changed since {prev_exported} - "
                  f"a re-read of the same file cannot show a sale")
    if cur_exported < prev_exported:
        return no(f"this export ({cur_exported}) is older than the one on "
                  f"record ({prev_exported})")

    changes = []
    for key, before in sorted(prev_positions.items()):
        after = cur_positions.get(key)
        if after is None:
            closed, _ = _buys_delta(before.get("buys"), {})
            changes.append({
                "kind": "exited", "key": key,
                "ticker": before.get("ticker", ""), "name": before.get("name", ""),
                "yahoo": before.get("yahoo"), "account": before.get("account", ""),
                "units_before": before.get("units"), "units_after": 0.0,
                "units_delta": -round(float(before.get("units") or 0.0), 4),
                "cost_delta": -round(float(before.get("cost_eur") or 0.0), 2),
                "lots_closed": closed, "lots_trimmed": []})
            continue
        kind, extra = _classify(before, after)
        if not kind:
            continue
        closed, trimmed = _buys_delta(before.get("buys"), after.get("buys"))
        row = {
            "kind": kind, "key": key,
            "ticker": after.get("ticker", ""), "name": after.get("name", ""),
            "yahoo": after.get("yahoo"), "account": after.get("account", ""),
            "units_before": round(float(before.get("units") or 0.0), 4),
            "units_after": round(float(after.get("units") or 0.0), 4),
            "units_delta": round(float(after.get("units") or 0.0)
                                 - float(before.get("units") or 0.0), 4),
            "cost_delta": round(float(after.get("cost_eur") or 0.0)
                                - float(before.get("cost_eur") or 0.0), 2),
            "lots_closed": closed, "lots_trimmed": trimmed}
        row.update(extra)
        changes.append(row)

    for key, after in sorted(cur_positions.items()):
        if key in prev_positions:
            continue
        changes.append({
            "kind": "opened", "key": key,
            "ticker": after.get("ticker", ""), "name": after.get("name", ""),
            "yahoo": after.get("yahoo"), "account": after.get("account", ""),
            "units_before": 0.0,
            "units_after": round(float(after.get("units") or 0.0), 4),
            "units_delta": round(float(after.get("units") or 0.0), 4),
            "cost_delta": round(float(after.get("cost_eur") or 0.0), 2),
            "lots_closed": [],
            "lots_trimmed": []})

    gone = sum(1 for c in changes if c["kind"] == "exited")
    if (gone >= _IMPLAUSIBLE_EXIT_FLOOR
            and gone >= _IMPLAUSIBLE_EXIT_SHARE * len(prev_positions)):
        return no(f"{gone} of {len(prev_positions)} holdings vanished from this "
                  f"export at once - that is a file to check, not a diff to "
                  f"report")

    order = {"exited": 0, "reduced": 1, "opened": 2, "increased": 3,
             "adjusted": 4}
    changes.sort(key=lambda c: (order.get(c["kind"], 9),
                                -abs(float(c.get("cost_delta") or 0.0))))
    return {"comparable": True, "reason": "", "changes": changes,
            "from_exported": prev_exported, "to_exported": cur_exported}


# ----------------------------------------------------------------- the alerts

# Verdicts under which the board is still arguing to own the name. A sale
# against one of these is the divergence; a sale of something the board rates
# Avoid or has no opinion on is news, not a contradiction.
_STILL_ARGUING = ("buy-worthy", "buy", "accumulate", "hold", "watch")


def _verdict(watchlist, change):
    for item in watchlist or ():
        tickers = {str(item.get(k) or "").upper()
                   for k in ("ticker", "yahoo", "symbol")}
        tickers.discard("")
        if str(change.get("yahoo") or "").upper() in tickers \
                or str(change.get("ticker") or "").upper() in tickers:
            return str(item.get("verdict") or "").strip()
    return ""


def _units(n):
    n = abs(float(n or 0.0))
    return f"{n:,.0f}" if abs(n - round(n)) < 1e-9 else f"{n:,.4f}".rstrip("0")


def alerts(view, watchlist=None):
    """Sales first, and loudest when the board still says own it.

    The level is not a property of the trade, it is a property of the
    disagreement. Trimming a name you rate Avoid is you acting on your own
    research. Trimming one you rate Buy-worthy is the cockpit's whole reason
    for existing, so that one is critical and the others are not.

    The key carries the export date rather than the size of the move, so the
    finding re-fires when a *new* export shows a *new* trade, and not once per
    run in between. `notify` dedupes on it.

    Gated on `changes`, deliberately not on `comparable`. A sale found last
    week is still a sale this week - the caller re-serves a stored finding
    across the runs that cannot recompute it (see `cockpit.lot_activity`), and
    gating on `comparable` would drop the alert off the board the run after it
    was raised while the divergence it names is still open. `diff` guarantees
    `changes` is empty whenever it could not compare, so there is nothing here
    that an incomparable fresh diff could smuggle through.
    """
    out = []
    to = view.get("to_exported") or ""
    for change in view.get("changes") or ():
        kind = change["kind"]
        if kind not in ("reduced", "exited"):
            continue
        ticker = change.get("ticker") or change.get("name") or "?"
        verdict = _verdict(watchlist, change)
        arguing = verdict.lower() in _STILL_ARGUING
        if kind == "exited":
            what = f"{ticker} was sold out of {change.get('account') or 'the book'}"
            detail = (f"{_units(change['units_before'])} units, "
                      f"EUR {abs(change['cost_delta']):,.0f} of cost basis, "
                      f"gone from the export dated {to}.")
        else:
            what = f"{ticker} was sold down"
            detail = (f"{_units(change['units_before'])} units -> "
                      f"{_units(change['units_after'])} in "
                      f"{change.get('account') or 'the book'} "
                      f"as of the export dated {to}.")
        closed = change.get("lots_closed") or []
        if closed:
            detail += (" Closed outright: "
                       + ", ".join(f"the {c['bought']} lot" for c in closed) + ".")
        if arguing:
            detail += (f" The board still rates it {verdict} - the research and "
                       f"the account disagree.")
        out.append({
            "level": "critical" if arguing else "warning",
            "key": f"position-{kind}:{ticker}:{to}",
            "title": what, "detail": detail})
    return out
