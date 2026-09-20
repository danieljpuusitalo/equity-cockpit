"""The portfolio seen as one thing, rather than as a list of positions.

Everything here answers a question about the book that no single row can:
what is it made of, what moved it today, and what actually made the money.
The per-position view already exists and is good at what it does; this is the
altitude above it.

Three rules carried over from the rest of the repo, all of them the same rule:

  * A name held in two custody accounts is ONE holding. The board stores a row
    per ISIN per account, so anything that counts or ranks has to fold first or
    it double-counts the position and halves its apparent size.
  * A position with no day move is not a position that did not move. Several
    holdings here price off a Nordnet market value with no previous close, so
    `day_pct` is legitimately absent. Folded into a book-level move as zero it
    would drag the number toward nothing every single day. They are excluded
    and the exclusion is reported.
  * A gain is attributed in EUROS, not in percent. The position that doubled is
    not necessarily the one that made the money, and a list sorted by percent
    will confidently tell you it was.
"""
from __future__ import annotations

import config as C
import treemap

# Enough to see what is going on, few enough to read at a glance. The full
# list is one click away in the data sheet, which is what that sheet is for.
MOVER_LIMIT = 5
CONTRIBUTOR_LIMIT = 6


def _key(row):
    """A stable identity for a holding, folded across custody accounts.

    Falls back to the ISIN for the handful of Nordnet index funds that have no
    Yahoo symbol at all. Those are real positions with real value and belong on
    the map; they simply have no chart behind them, which the page discovers
    from `sym` being None rather than by guessing from the shape of the key.
    """
    sym = row.get("yahoo")
    return sym if sym and sym != "MISSING" else f"isin:{row.get('isin')}"


def fold(holdings):
    """One row per name, custody accounts merged. The basis for everything else.

    P/L percent is recomputed from the merged value and cost. It is NOT the
    average of the two accounts' percentages: the same name bought at two
    different times in two different accounts has one true return and it is
    value-weighted, not arithmetic.
    """
    out = {}
    for row in holdings:
        key = _key(row)
        cur = out.get(key)
        if cur is None:
            sym = row.get("yahoo")
            cur = out[key] = {
                "key": key,
                "sym": sym if sym and sym != "MISSING" else None,
                "ticker": row.get("ticker") or row.get("tunnus") or key,
                "name": row.get("name"),
                "klass": C.ASSET_CLASS.get(row.get("isin")),
                "bucket": row.get("bucket"),
                "accounts": [],
                "value_eur": 0.0,
                "cost_eur": 0.0,
                # The same symbol has the same day move in both accounts, so
                # this is carried across rather than combined. None stays None.
                "day_pct": row.get("day_pct"),
                "price": row.get("price"),
                "units": 0.0,
            }
        cur["value_eur"] += row.get("value_eur") or 0.0
        cur["cost_eur"] += row.get("cost_eur") or 0.0
        cur["units"] += row.get("units") or 0.0
        if row.get("day_pct") is not None:
            cur["day_pct"] = row["day_pct"]
        if row.get("account") and row["account"] not in cur["accounts"]:
            cur["accounts"].append(row["account"])

    rows = []
    for cur in out.values():
        value, cost = round(cur["value_eur"], 2), round(cur["cost_eur"], 2)
        cur["value_eur"], cur["cost_eur"] = value, cost
        cur["units"] = round(cur["units"], 4)
        # No cost basis means no return, not a return of zero. A position
        # transferred in without a purchase price is unknowable, not flat.
        cur["pl_eur"] = round(value - cost, 2) if cost else None
        cur["pl_pct"] = round((value / cost - 1) * 100, 2) if cost else None
        cur["accounts"].sort()
        rows.append(cur)
    rows.sort(key=lambda r: -r["value_eur"])
    return rows


def day_move(rows):
    """What the book did today, over the part of it that has a day move.

    `pct` is measured against the value those same priced positions closed at,
    not against the whole book. Dividing a partial move by a full denominator
    understates every day's move by however much of the book is unpriced, which
    is a bias that never corrects and never announces itself.
    """
    priced = [r for r in rows if r.get("day_pct") is not None]
    quiet = [r for r in rows if r.get("day_pct") is None]
    value = sum(r["value_eur"] for r in priced)
    # `value_eur` is today's value and `day_pct` is the move that produced it,
    # so yesterday's close is value / (1 + d) - NOT value * (1 - d). The two
    # agree to three decimal places on a quiet day and drift on exactly the
    # days you would want the number to be right.
    opened = sum(r["value_eur"] / (1 + r["day_pct"] / 100.0)
                 for r in priced if r["day_pct"] != -100.0)
    moved = value - opened
    return {
        "value_eur": round(moved, 2),
        "pct": round(moved / opened * 100, 2) if opened else None,
        "n_priced": len(priced),
        "n_quiet": len(quiet),
        "quiet_eur": round(sum(r["value_eur"] for r in quiet), 2),
        "covered_pct": round(value / (value + sum(
            r["value_eur"] for r in quiet)) * 100, 1)
        if (value or quiet) else 0.0,
    }


def allocation(rows, total=None):
    """The book as a treemap: area is weight, and nothing else is implied.

    Tiles carry their own P/L and day move so the page can colour by either
    without recomputing anything. A tile whose cost is unknown carries
    `pl_pct: None` and must be drawn neutral - colouring it green because the
    arithmetic fell out to zero would be the same lie as any other.
    """
    total = total if total is not None else sum(r["value_eur"] for r in rows)
    by_key = {r["key"]: r for r in rows}
    tiles = []
    for rect in treemap.squarify([(r["key"], r["value_eur"]) for r in rows]):
        row = by_key[rect["key"]]
        tiles.append({
            **rect,
            "sym": row["sym"], "ticker": row["ticker"], "name": row["name"],
            "klass": row["klass"], "bucket": row["bucket"],
            "value_eur": row["value_eur"],
            "weight_pct": round(row["value_eur"] / total * 100, 2)
            if total else 0.0,
            "pl_pct": row["pl_pct"], "pl_eur": row["pl_eur"],
            "day_pct": row["day_pct"],
        })
    drawn = sum(t["value_eur"] for t in tiles)
    return {
        "tiles": tiles,
        "n": len(tiles),
        "value_eur": round(drawn, 2),
        # A position the treemap could not draw is stated, never left to be
        # inferred from tiles that quietly sum to less than the book.
        "n_undrawn": len(rows) - len(tiles),
        "undrawn_eur": round(total - drawn, 2),
    }


def movers(rows, limit=MOVER_LIMIT):
    """Today's largest moves, by percent, over the positions that have one.

    Percent is the right unit here and euros is the right unit in
    `contributors` below - the two questions are different and giving both the
    same answer is how a dashboard ends up saying nothing twice.
    """
    priced = sorted((r for r in rows if r.get("day_pct") is not None),
                    key=lambda r: -r["day_pct"])
    trim = [{"sym": r["sym"], "ticker": r["ticker"], "name": r["name"],
             "day_pct": r["day_pct"], "value_eur": r["value_eur"],
             # Same basis as `day_move`: today's value less what it opened at.
             "day_eur": round(r["value_eur"]
                              - r["value_eur"] / (1 + r["day_pct"] / 100.0), 2)
             if r["day_pct"] != -100.0 else None}
            for r in priced]
    up = [r for r in trim if r["day_pct"] > 0][:limit]
    down = [r for r in reversed(trim) if r["day_pct"] < 0][:limit]
    return {"up": up, "down": down, "n_priced": len(priced),
            "n_quiet": sum(1 for r in rows if r.get("day_pct") is None)}


def contributors(rows, limit=CONTRIBUTOR_LIMIT):
    """Who actually made the money, in euros, as a share of total gain.

    This is the question a weight map and a percent ranking both dodge. A 50%
    gain on the smallest position is a rounding error; a 12% gain on the
    largest one is the year. Shares are taken against the total ABSOLUTE
    movement, so a winner and a loser of the same size both read as meaningful
    rather than cancelling into a denominator of nearly zero.
    """
    known = [r for r in rows if r.get("pl_eur") is not None]
    gross = sum(abs(r["pl_eur"]) for r in known)
    ranked = sorted(known, key=lambda r: -r["pl_eur"])
    trim = [{"sym": r["sym"], "ticker": r["ticker"], "name": r["name"],
             "pl_eur": r["pl_eur"], "pl_pct": r["pl_pct"],
             "value_eur": r["value_eur"],
             "share_pct": round(abs(r["pl_eur"]) / gross * 100, 1)
             if gross else 0.0}
            for r in ranked]
    return {
        "best": [r for r in trim if r["pl_eur"] > 0][:limit],
        "worst": [r for r in reversed(trim) if r["pl_eur"] < 0][:limit],
        "n_known": len(known),
        # Positions with no cost basis cannot be attributed. Silently ranking
        # them at zero would park them permanently in the middle of the table
        # as though they had been measured and found unremarkable.
        "n_unknown": len(rows) - len(known),
    }


def build(holdings, totals=None):
    """The whole overview payload. Pure: no clock, no network, no cache."""
    rows = fold(holdings)
    total = sum(r["value_eur"] for r in rows)
    return {
        "rows": rows,
        "n": len(rows),
        "value_eur": round(total, 2),
        "day": day_move(rows),
        "allocation": allocation(rows, total),
        "movers": movers(rows),
        "contributors": contributors(rows),
        # Carried through so the page has one place to read the headline from
        # rather than two that can disagree.
        "totals": totals or {},
    }
