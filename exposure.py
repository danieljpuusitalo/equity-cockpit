"""What the book is actually made of, once the wrappers are seen through.

A portfolio held partly in funds cannot be read off its own position list. Eight
of this book's positions are trackers, and the ticker tells you nothing about
what you own through it: two of them hold Microsoft, which is also held
outright, so the real exposure to that one name is spread across three rows that
never appear near each other.

Everything here is pure. It takes the valued holdings, the per-stock
fundamentals cache and the per-fund composition cache, and returns numbers. No
network, no clock, no files - which is what makes it testable, and it is tested
against hand-computed arithmetic rather than against a fixture of itself.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE. Every breakdown reports what it
could not resolve, in the same object, as a euro amount and a percentage. Yahoo
caps a fund's holdings at ten rows, which is 82.8% of a defence thematic and
12.2% of a world ex-US tracker. A look-through that published the first number
and the second one identically would be this repo's signature defect in its
purest form: a figure claiming more than it measures. Where the mass cannot be
placed it is named `unresolved`, and every consumer is expected to show it.
"""

import config as C


# Yahoo spells its sectors two ways: Title Case in a stock's `.info`
# ("Consumer Cyclical") and squashed lower-case in a fund's sector weightings
# ("consumer_cyclical"). They are the SAME eleven sectors, which is the single
# fact that makes a whole-book sector split possible without a mapping table.
# These are the exceptions where squashing is not enough.
_SECTOR_ALIASES = {
    "realestate": "real_estate",
    "real_estate": "real_estate",
}

# Exchange suffix to country, for a fund's underlying holdings. Yahoo gives a
# fund's constituents as tickers and nothing else, so the listing venue is the
# only geography available for them.
#
# This is a LISTING VENUE, not a domicile and emphatically not a revenue split.
# It is the weaker of the two geographies this module produces and it is
# labelled as such everywhere it surfaces.
_SUFFIX_COUNTRY = {
    "AS": "Netherlands",  "BR": "Belgium",      "CO": "Denmark",
    "DE": "Germany",      "F": "Germany",       "HE": "Finland",
    "HK": "Hong Kong",    "IR": "Ireland",      "KQ": "South Korea",
    "KS": "South Korea",  "L": "United Kingdom", "LS": "Portugal",
    "MC": "Spain",        "MI": "Italy",        "NS": "India",
    "OL": "Norway",       "PA": "France",       "SI": "Singapore",
    "ST": "Sweden",       "SW": "Switzerland",  "T": "Japan",
    "TA": "Israel",       "TO": "Canada",       "TW": "Taiwan",
    "VI": "Austria",      "WA": "Poland",
}


def _label(key):
    """`consumer_defensive` -> `Consumer Defensive`."""
    return " ".join(part.capitalize() for part in str(key).split("_"))


def _sector_key(name):
    """Either spelling of a Yahoo sector, as one canonical key. None if absent."""
    if not name:
        return None
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return _SECTOR_ALIASES.get(key, key) or None


def country_for_symbol(symbol):
    """Listing country of a Yahoo ticker, or None when the venue is unknown.

    A bare ticker with no suffix is a US listing - that is Yahoo's convention,
    not an assumption about the company. `00939` and other bare non-US codes
    have no suffix and no US listing either, so they resolve to None rather
    than being silently counted as American.
    """
    if not symbol:
        return None
    text = str(symbol).strip()
    if "." in text:
        return _SUFFIX_COUNTRY.get(text.rsplit(".", 1)[-1].upper())
    # Yahoo's US tickers are letters, optionally with a class suffix (BRK-B).
    return "United States" if text.replace("-", "").isalpha() else None


def _fields(cache, symbol):
    """The `fields` block for a symbol, or {} - never None, never a KeyError."""
    if not symbol:
        return {}
    entry = cache.get(symbol) or {}
    return entry.get("fields") or {}


def _positions(holdings):
    """One row per instrument, with the two accounts collapsed.

    `sources.positions` keys by (ISIN, account) because that is how the broker
    reports it and how the value has to reconcile. Exposure does not care which
    account a share sits in - carrying the split through would double every
    name held in both and make the look-through wrong in a way that looks like
    concentration.
    """
    merged = {}
    for holding in holdings:
        isin = holding.get("isin")
        value = holding.get("value_eur") or 0.0
        if isin not in merged:
            symbol = holding.get("yahoo")
            merged[isin] = {
                "isin": isin,
                "symbol": symbol if symbol and symbol != "MISSING" else None,
                "name": holding.get("name") or C.NAMES.get(isin, "") or "",
                "klass": C.ASSET_CLASS.get(isin, "stock"),
                "value_eur": 0.0}
        merged[isin]["value_eur"] += value
    return sorted(merged.values(), key=lambda p: -p["value_eur"])


def _breakdown(buckets, unresolved_eur, total, extra=None):
    """A weights table plus the mass that could not be placed in it."""
    rows = []
    for key, value in buckets.items():
        rows.append({"key": key, "label": _label(key),
                     "value_eur": round(value, 2),
                     "pct": round(value / total * 100, 2) if total else 0.0})
    rows.sort(key=lambda r: -r["value_eur"])
    placed = sum(buckets.values())
    out = {
        "rows": rows,
        "value_eur": round(placed, 2),
        "unresolved_eur": round(unresolved_eur, 2),
        "resolved_pct": round(placed / total * 100, 1) if total else 0.0,
        "n": len(rows),
    }
    out.update(extra or {})
    return out


# ------------------------------------------------------------------- sectors

def sectors(positions, funda, comp, total):
    """Whole-book sector split, stocks and fund constituents together.

    A stock contributes its whole value to one sector. A fund contributes its
    value spread across the weights the issuer reports. Where a fund's weights
    do not sum to 100 - they never quite do, because a tracker carries a little
    cash - the remainder is unresolved rather than being scaled away. Cash is
    not a sector, and normalising it out would overstate every other row by
    exactly the amount of cash held.
    """
    buckets, unresolved, direct, indirect = {}, 0.0, {}, {}
    for pos in positions:
        value, symbol = pos["value_eur"], pos["symbol"]
        if not value:
            continue
        if pos["klass"] == "fund":
            weights = (_fields(comp, symbol) or {}).get("sectors") or {}
            placed = 0.0
            for raw, pct in weights.items():
                key = _sector_key(raw)
                if not key or not pct:
                    continue
                part = value * pct / 100.0
                buckets[key] = buckets.get(key, 0.0) + part
                indirect[key] = indirect.get(key, 0.0) + part
                placed += part
            unresolved += max(0.0, value - placed)
        else:
            key = _sector_key(_fields(funda, symbol).get("sector"))
            if key:
                buckets[key] = buckets.get(key, 0.0) + value
                direct[key] = direct.get(key, 0.0) + value
            else:
                unresolved += value

    table = _breakdown(buckets, unresolved, total)
    for row in table["rows"]:
        row["direct_eur"] = round(direct.get(row["key"], 0.0), 2)
        row["indirect_eur"] = round(indirect.get(row["key"], 0.0), 2)
    return table


# ---------------------------------------------------------------- industries

def industries(positions, funda, total):
    """Industry split. Directly-held stocks only, because nothing else exists.

    A fund reports sectors and never industries, so this covers the stock
    sleeve and says so. It is deliberately NOT blended with sector data to
    reach a bigger coverage number - an industry chart that quietly fell back
    to "Technology" for half its mass would be measuring two different things
    on one axis.
    """
    buckets, unresolved = {}, 0.0
    for pos in positions:
        value = pos["value_eur"]
        if not value:
            continue
        if pos["klass"] == "fund":
            unresolved += value
            continue
        name = _fields(funda, pos["symbol"]).get("industry")
        if name:
            buckets[name] = buckets.get(name, 0.0) + value
        else:
            unresolved += value
    table = _breakdown(buckets, unresolved, total)
    for row in table["rows"]:
        row["label"] = row["key"]                # already human-written
    return table


# ---------------------------------------------------------------- geography

def geography(positions, funda, comp, total):
    """Where the book is listed. NOT where its revenue comes from.

    Two different measurements share this axis and the difference is worth
    stating: a directly-held stock contributes its stated domicile, while a
    fund's constituents contribute their listing venue, because a ticker is all
    Yahoo gives for them. Both are proxies for the same thing and neither is
    revenue. Ahold Delhaize counts as Netherlands here and earns most of its
    money in the United States.

    Coverage is the weak point and it is reported, not smoothed: a fund can
    only place the share of itself that its ten disclosed holdings represent.
    """
    buckets, unresolved = {}, 0.0
    for pos in positions:
        value, symbol = pos["value_eur"], pos["symbol"]
        if not value:
            continue
        if pos["klass"] == "fund":
            placed = 0.0
            for line in (_fields(comp, symbol) or {}).get("top_holdings") or []:
                country = country_for_symbol(line.get("symbol"))
                pct = line.get("pct") or 0.0
                if not country or not pct:
                    continue
                part = value * pct / 100.0
                buckets[country] = buckets.get(country, 0.0) + part
                placed += part
            unresolved += max(0.0, value - placed)
        else:
            country = _fields(funda, symbol).get("country")
            if country:
                buckets[country] = buckets.get(country, 0.0) + value
            else:
                unresolved += value

    table = _breakdown(buckets, unresolved, total,
                       {"basis": "stated domicile for directly-held stocks, "
                                 "listing venue for fund constituents"})
    for row in table["rows"]:
        row["label"] = row["key"]
    return table


# -------------------------------------------------------------- single names

def names(positions, comp, funda, total):
    """True exposure per company: held outright plus held through funds.

    This is the view the position list cannot give. Microsoft is a direct
    holding and also sits inside two of the trackers, on three rows that never
    appear together anywhere else in the cockpit.

    `resolved_pct` here is the load-bearing caveat. Only ten constituents per
    fund are disclosed, so the indirect side is a floor, never a total - a name
    absent from this table is not absent from the book, it is absent from the
    top ten. The table says how much of the book it managed to name.
    """
    rows, resolved = {}, 0.0

    def touch(symbol, label):
        if symbol not in rows:
            rows[symbol] = {"symbol": symbol, "name": label or symbol,
                            "direct_eur": 0.0, "indirect_eur": 0.0,
                            "via": []}
        elif label and rows[symbol]["name"] == symbol:
            rows[symbol]["name"] = label
        return rows[symbol]

    for pos in positions:
        value, symbol = pos["value_eur"], pos["symbol"]
        if not value:
            continue
        if pos["klass"] != "fund":
            if symbol:
                touch(symbol, pos["name"])["direct_eur"] += value
                resolved += value
            continue
        for line in (_fields(comp, symbol) or {}).get("top_holdings") or []:
            child, pct = line.get("symbol"), line.get("pct") or 0.0
            if not child or not pct:
                continue
            part = value * pct / 100.0
            row = touch(child, line.get("name"))
            row["indirect_eur"] += part
            row["via"].append({"fund": symbol, "pct": round(pct, 2),
                               "value_eur": round(part, 2)})
            resolved += part

    out = []
    for row in rows.values():
        total_eur = row["direct_eur"] + row["indirect_eur"]
        row["via"].sort(key=lambda v: -v["value_eur"])
        out.append({
            "symbol": row["symbol"], "name": row["name"],
            "direct_eur": round(row["direct_eur"], 2),
            "indirect_eur": round(row["indirect_eur"], 2),
            "value_eur": round(total_eur, 2),
            "pct": round(total_eur / total * 100, 2) if total else 0.0,
            "direct_pct": round(row["direct_eur"] / total * 100, 2) if total else 0.0,
            "indirect_pct": round(row["indirect_eur"] / total * 100, 2) if total else 0.0,
            "held_both_ways": row["direct_eur"] > 0 and row["indirect_eur"] > 0,
            "via": row["via"],
            # Bucket keys so the page can cross-filter this table against the
            # breakdowns above without re-deriving anything in the browser.
            # A constituent Yahoo gives only a ticker for has no sector, and
            # that stays None rather than being guessed from its neighbours -
            # a filter that quietly invents membership is worse than one that
            # says how many rows it could not place.
            "sector": _sector_key(_fields(funda, row["symbol"]).get("sector")),
            "industry": _fields(funda, row["symbol"]).get("industry"),
            "country": (_fields(funda, row["symbol"]).get("country")
                        or country_for_symbol(row["symbol"]))})
    out.sort(key=lambda r: -r["value_eur"])

    return {"rows": out, "n": len(out),
            "value_eur": round(resolved, 2),
            "unresolved_eur": round(max(0.0, total - resolved), 2),
            "resolved_pct": round(resolved / total * 100, 1) if total else 0.0,
            "n_both_ways": sum(1 for r in out if r["held_both_ways"])}


# ------------------------------------------------------------------- overlap

def overlap(positions, comp, total):
    """Which funds are buying the same companies as each other.

    `names` above answers "how much Microsoft do I own", which is the question
    you ask about a company. This answers "are two of these funds the same
    fund", which is the question you ask about an allocation - and it is the one
    the cockpit could not answer. A bucket label is an intention, not evidence:
    a tracker filed under one theme and a tracker filed under another can still
    be drawing from one pot of names, and nothing in this repo would have said
    so. Deciding a target weight off the labels alone means sizing two sleeves
    that are partly the same sleeve.

    Every figure here is a FLOOR, for the same reason the tables above carry a
    coverage percentage: ten constituents are disclosed per fund. Two funds
    could be identical from the eleventh line down and this would report them as
    sharing nothing. `disclosed_pct` per side is what says how much of each fund
    was actually visible - read a low pair as "unknown", never as "unrelated".
    """
    funds, sizes = {}, {}
    for pos in positions:
        if pos["klass"] != "fund" or not pos["symbol"] or not pos["value_eur"]:
            continue
        lines = {}
        for line in (_fields(comp, pos["symbol"]) or {}).get("top_holdings") or []:
            child, pct = line.get("symbol"), line.get("pct") or 0.0
            if child and pct:
                lines[child] = lines.get(child, 0.0) + pct
        if lines:
            funds[pos["symbol"]] = lines
            sizes[pos["symbol"]] = pos["value_eur"]

    pairs = []
    keys = sorted(funds)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            shared = sorted(set(funds[a]) & set(funds[b]),
                            key=lambda c: -(funds[a][c] + funds[b][c]))
            if not shared:
                continue
            # The EUR that reaches these companies through BOTH funds. Not
            # "double counted" - the money is real and counted once - but it is
            # one bet arrived at twice, which is what a target weight set from
            # two separate bucket labels would fail to price.
            eur = sum(sizes[a] * funds[a][c] / 100.0 +
                      sizes[b] * funds[b][c] / 100.0 for c in shared)
            share = lambda f, s: (round(sum(funds[f][c] for c in s) /
                                        sum(funds[f].values()) * 100, 1)
                                  if sum(funds[f].values()) else 0.0)
            pairs.append({
                "a": a, "b": b,
                "shared": shared, "n_shared": len(shared),
                "n_a": len(funds[a]), "n_b": len(funds[b]),
                # Of what each fund disclosed, how much sits in common ground.
                # Asymmetric on purpose: a small fund can be wholly contained in
                # a large one, and one averaged number would hide exactly that.
                "a_disclosed_in_shared_pct": share(a, shared),
                "b_disclosed_in_shared_pct": share(b, shared),
                "a_disclosed_pct": round(sum(funds[a].values()), 1),
                "b_disclosed_pct": round(sum(funds[b].values()), 1),
                "value_eur": round(eur, 2),
                "pct": round(eur / total * 100, 2) if total else 0.0})

    pairs.sort(key=lambda p: -p["value_eur"])
    return {"pairs": pairs, "n_pairs": len(pairs), "n_funds": len(funds),
            # A pair sharing most of what it disclosed is the finding; the long
            # tail of two-name coincidences between broad trackers is not.
            "n_substantial": sum(1 for p in pairs
                                 if max(p["a_disclosed_in_shared_pct"],
                                        p["b_disclosed_in_shared_pct"]) >= 50.0)}


# ------------------------------------------------------------- concentration

def concentration(positions, total):
    """How few things this book really is, measured on positions.

    Deliberately NOT measured on the look-through. Only part of each fund is
    disclosed, and unplaced mass would read as diversification - the less a
    fund tells you, the more diversified it would appear. Position level is
    the one complete view, so it is the one that gets a headline number.

    `effective_n` is 1/HHI, the reciprocal of the sum of squared weights: the
    number of EQUAL-sized positions that would give the same concentration.
    Twenty-four positions with an effective count of nine means the tail is
    decorative.
    """
    values = sorted((p["value_eur"] for p in positions if p["value_eur"]),
                    reverse=True)
    if not values or not total:
        return {"n": 0, "top1_pct": 0.0, "top5_pct": 0.0, "top10_pct": 0.0,
                "hhi": 0.0, "effective_n": 0.0}
    weights = [v / total for v in values]
    hhi = sum(w * w for w in weights)
    return {
        "n": len(values),
        "top1_pct": round(sum(weights[:1]) * 100, 1),
        "top5_pct": round(sum(weights[:5]) * 100, 1),
        "top10_pct": round(sum(weights[:10]) * 100, 1),
        "hhi": round(hhi, 4),
        "effective_n": round(1.0 / hhi, 1) if hhi else 0.0,
    }


# ----------------------------------------------------------------- fee drag

def fees(positions, comp, total):
    """What the fund sleeve costs per year, in euros.

    Nordnet shows a TER per fund and never the bill. This multiplies each
    fund's value by its own expense ratio and adds them up, which is the only
    form of the number that is comparable to anything else on this page.

    A fund whose TER is not published is NOT treated as free. Its value counts
    against coverage, so the euro figure reads as a floor rather than a total.
    """
    annual, covered, fund_value, rows = 0.0, 0.0, 0.0, []
    for pos in positions:
        if pos["klass"] != "fund" or not pos["value_eur"]:
            continue
        value = pos["value_eur"]
        fund_value += value
        ter = (_fields(comp, pos["symbol"]) or {}).get("ter")
        cost = value * ter / 100.0 if ter is not None else None
        if cost is not None:
            annual += cost
            covered += value
        rows.append({"symbol": pos["symbol"], "name": pos["name"],
                     "value_eur": round(value, 2), "ter_pct": ter,
                     "annual_eur": round(cost, 2) if cost is not None else None})
    rows.sort(key=lambda r: -(r["annual_eur"] or 0))
    return {
        "rows": rows,
        "annual_eur": round(annual, 2),
        "fund_value_eur": round(fund_value, 2),
        "covered_eur": round(covered, 2),
        "unresolved_eur": round(fund_value - covered, 2),
        "resolved_pct": round(covered / fund_value * 100, 1) if fund_value else 0.0,
        # Two denominators, because they answer different questions: what the
        # funds cost as funds, and what they cost as a share of everything.
        "sleeve_ter_pct": round(annual / covered * 100, 3) if covered else None,
        "book_ter_pct": round(annual / total * 100, 3) if total else None,
    }


# ---------------------------------------------------------------- multiples

def multiples(positions, funda, comp, total):
    """Book-level valuation, aggregated the way a multiple actually aggregates.

    NOT the weighted average of the P/Es. A portfolio's P/E is its total value
    over its total earnings, which is the value-weighted HARMONIC mean - the
    weighted arithmetic mean of P/Es is dominated by whichever holding is
    closest to breaking even and can exceed every input. Summing earnings
    yields and inverting at the end is the same calculation and cannot blow up.

    It is also the shape the data already arrives in: Yahoo reports a fund's
    valuation rows as yields, which is why `sources._shape_funds_data` has to
    invert them and why they get inverted straight back here.

    A negative multiple is excluded, not floored. Loss-making companies have no
    meaningful P/E and averaging one in - in either direction - invents an
    earnings number that does not exist.
    """
    out = {}
    for key in ("pe", "pb", "ps"):
        weighted_yield, covered = 0.0, 0.0
        for pos in positions:
            value, symbol = pos["value_eur"], pos["symbol"]
            if not value:
                continue
            if pos["klass"] == "fund":
                ratio = ((_fields(comp, symbol) or {}).get("valuation") or {}).get(key)
            else:
                ratio = _fields(funda, symbol).get(key)
            if ratio is None or ratio <= 0:
                continue
            weighted_yield += value / ratio
            covered += value
        out[key] = round(covered / weighted_yield, 2) if weighted_yield else None
        out[f"{key}_resolved_pct"] = round(covered / total * 100, 1) if total else 0.0
    return out


# ------------------------------------------------------------------ assemble

def look_through(holdings, funda, comp):
    """Every breakdown, off one pass of the book. Pure; safe to call twice."""
    positions = _positions(holdings)
    total = sum(p["value_eur"] for p in positions)

    funds = []
    for pos in positions:
        if pos["klass"] != "fund":
            continue
        fields = _fields(comp, pos["symbol"]) or {}
        disclosed = sum(line.get("pct") or 0.0
                        for line in fields.get("top_holdings") or [])
        funds.append({
            "symbol": pos["symbol"], "name": pos["name"],
            "value_eur": round(pos["value_eur"], 2),
            "weight_pct": round(pos["value_eur"] / total * 100, 2) if total else 0.0,
            "ter_pct": fields.get("ter"),
            "n_disclosed": len(fields.get("top_holdings") or []),
            # The spread across this column is the reason every table above
            # carries a coverage figure. It runs from the low teens to the
            # low eighties within one book.
            "disclosed_pct": round(disclosed, 1),
            "has_sectors": bool(fields.get("sectors"))})
    funds.sort(key=lambda f: -f["value_eur"])

    return {
        "total_eur": round(total, 2),
        "n_positions": len(positions),
        "sectors": sectors(positions, funda, comp, total),
        "industries": industries(positions, funda, total),
        "geography": geography(positions, funda, comp, total),
        "names": names(positions, comp, funda, total),
        "overlap": overlap(positions, comp, total),
        "concentration": concentration(positions, total),
        "fees": fees(positions, comp, total),
        "multiples": multiples(positions, funda, comp, total),
        "funds": funds,
    }
