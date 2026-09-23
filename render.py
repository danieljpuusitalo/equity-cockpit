"""Turn the analysed payload into a single self-contained HTML file.

No build step, no CDN, no network at view time. One file you can open on a
plane, mail to yourself, or keep in a folder for five years and still read.
"""
from __future__ import annotations

import json
import datetime as dt

import config as C
import overview as overview_mod

MARKER = "/*__DATA__*/"
LIB_MARKER = "/*__CHARTLIB__*/"
TEMPLATE = C.ROOT / "assets" / "dashboard.tmpl.html"
# TradingView Lightweight Charts, vendored rather than linked. A CDN <script>
# tag is a dependency that breaks silently the day the URL moves; a file in this
# folder does not. Update it by replacing the file - there is no build step.
CHARTLIB = C.ROOT / "assets" / "lightweight-charts.standalone.production.js"


# Keys the analysis joins on and the page never reads. The rendered file is
# deployed, so anything left in the payload is published behind the gate even
# though nothing on screen shows it. Custody identity reaches the page as the
# `account` label; the number stays in Python.
PRIVATE_KEYS = frozenset({"account_no"})


def _scrub(obj):
    """Drop PRIVATE_KEYS at every depth, so a section added later cannot carry
    one onto the page by being built from a position row."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items() if k not in PRIVATE_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def payload(positions_valued, watchlist, alerts, health, fx, sources,
            history=None, coverage=None, book_return=None, indicators=None,
            exposure=None, reporting=None, activity=None):
    """The single object the page renders. Nothing is computed in the browser
    that could have been computed here - the page displays, it does not decide."""
    total_value = round(sum(h["value_eur"] or 0 for h in positions_valued), 2)
    total_cost = round(sum(h["cost_eur"] or 0 for h in positions_valued), 2)
    holdings = []
    for row in positions_valued:
        out = dict(row)
        out["ticker"] = row.get("tunnus") or row.get("name")
        holdings.append(out)
    totals = {
        "value_eur": total_value,
        "cost_eur": total_cost,
        "pl_eur": round(total_value - total_cost, 2),
        "pl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0,
        # Money-weighted annual return across every lot in the book. P/L
        # says how much; this says how fast, which is what tells a
        # three-year hold apart from a three-week one at the same +18%.
        "irr_pct": (book_return or {}).get("irr_pct"),
        "irr_since": (book_return or {}).get("since"),
        "irr_note": (book_return or {}).get("note"),
    }
    return _scrub({
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "holdings": holdings,
        "watchlist": watchlist,
        # symbol -> {fetched, bars:[[date,o,h,l,c], ...]}, in the symbol's own
        # quote currency. Targets and triggers from Notion are in that same
        # currency, so the chart draws all three without converting anything.
        "history": history or {},
        # Per-holding: is it monitored, by which standard, and what is missing.
        # Stocks answer to a thesis, funds to a target weight - see
        # analyse.coverage for why those are different questions.
        "coverage": coverage or {},
        # symbol -> latest value of every indicator, computed off the same
        # cached bars the chart draws, so this costs no extra fetch. Descriptive
        # only: numbers and words like "overbought", never a buy or a sell. The
        # thesis decides; this is the weather report it decides in.
        "indicators": indicators or {},
        # The book seen through its wrappers: sector, industry, geography,
        # single-name, concentration, fee drag and blended multiples. Every one
        # of those tables carries its own `resolved_pct`, because Yahoo
        # discloses ten constituents per fund and ten rows is most of a defence
        # thematic and almost none of a world tracker. The page must print that
        # figure beside the chart it qualifies - see exposure.py's header.
        "exposure": exposure or {},
        # The reporting calendar ahead and the record behind it. The upcoming
        # quarter arrives from Yahoo with a NaN result and is carried here as
        # null, never as zero - see reporting.py's header for why that is the
        # single rule that module exists to enforce.
        "reporting": reporting or {},
        # What the book did between the last two Nordnet exports. The export
        # lists holdings and never transactions, so a sale exists here only as
        # the difference between two of them - and `comparable` is load-bearing
        # on this one. An empty `changes` means "nothing sold" ONLY when
        # `comparable` is true; the rest of the time it means the question
        # could not be asked, and the page must say which. See activity.py.
        "activity": activity or {},
        "alerts": alerts,
        "health": health,
        "fx": fx,
        "sources": sources,
        "totals": totals,
        # The book as one thing rather than as a list: custody accounts folded,
        # the treemap already laid out, today's move measured over the part of
        # the book that actually has a previous close, and the P/L attributed
        # in euros. This is what the Overview opens on, so none of it may be
        # computed in the browser - including the rectangles.
        "overview": overview_mod.build(holdings, totals),
        # symbol -> {irr_pct, since, note}. Folded across custody accounts here
        # rather than in the page, because a blended IRR is not the average of
        # two IRRs and the browser has no way to know that.
        "returns": (book_return or {}).get("by_symbol", {}),
        "thresholds": {
            "check_soon_days": C.CHECK_SOON_DAYS,
            "decay_alert_pts": C.DECAY_ALERT_PTS,
            "trigger_near_pct": C.TRIGGER_NEAR_PCT,
            "price_divergence_pct": C.PRICE_DIVERGENCE_PCT,
            "csv_stale_days": C.CSV_STALE_DAYS,
            "run_stale_days": C.RUN_STALE_DAYS,
        },
    })


def write(data, out_dir=None):
    out_dir = out_dir or C.OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    # The sidecar is the human- and script-readable view of a run. Two years of
    # bars for thirty symbols pretty-printed would bury it, so history is left
    # to the HTML, which is the only thing that draws it.
    sidecar = {k: v for k, v in data.items() if k != "history"}
    json_path = out_dir / "portfolio.json"
    json_path.write_text(json.dumps(sidecar, indent=1, ensure_ascii=False,
                                    default=str), encoding="utf-8")

    template = TEMPLATE.read_text(encoding="utf-8")
    for marker in (MARKER, LIB_MARKER):
        if marker not in template:
            raise RuntimeError(
                f"{TEMPLATE.name} lost its {marker} marker - the template was "
                "edited in a way the renderer cannot fill.")
    if not CHARTLIB.exists():
        raise RuntimeError(
            f"{CHARTLIB.name} is missing from assets/. It is vendored, not "
            "downloaded at run time - restore the file from the repo.")

    blob = json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))
    # A closing tag inside a string literal would end the <script> block early.
    blob = blob.replace("</", "<\\/")
    html = (template.replace(LIB_MARKER, CHARTLIB.read_text(encoding="utf-8"))
                    .replace(MARKER, blob))
    html_path = out_dir / "dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path, json_path
