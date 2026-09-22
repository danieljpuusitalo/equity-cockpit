"""Equity cockpit - the one entry point.

    python cockpit.py run          full run: read, price, analyse, render, notify
    python cockpit.py run --quiet  same, but never message Telegram
    python cockpit.py refresh      re-price and re-render only; no Notion, no
                                   Telegram, nothing fetched that does not move
                                   intraday. Safe to run every half hour.
    python cockpit.py selftest     offline checks - does the wiring still hold?
    python cockpit.py doctor       what is stale, missing or drifting, in English
    python cockpit.py sync-notion FILE.json   load an Equity Log snapshot into cache

Design rule for this file: it orchestrates and it reports. Every decision worth
testing lives in analyse.py; every external boundary lives in sources.py.
"""
from __future__ import annotations

import re
import sys
import json
import argparse
import subprocess
import datetime as dt

import config as C
import sources
import analyse
import activity
import exposure
import reporting
import indicators
import render
import notify

HEARTBEAT = C.STATE / "last_run.json"
# Deliberately a different file from HEARTBEAT. See refresh() for why the two
# must not be the same one.
REFRESH_BEAT = C.STATE / "last_refresh.json"
HISTORY = C.STATE / "history.jsonl"
# The lot book as of the last export that was genuinely new. This is the only
# memory the cockpit has of what it used to hold, and it is the only way a sale
# is ever visible: the export lists holdings, never transactions. See
# activity.py. It is NOT a heartbeat and must not be used as one - a run that
# refuses to compare still leaves it exactly as it was.
LOT_BOOK = C.STATE / "lot-book.json"


# ---------------------------------------------------------------- heartbeat

def read_heartbeat():
    if not HEARTBEAT.exists():
        return None
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_heartbeat(summary):
    C.STATE.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(json.dumps(summary, indent=1, default=str),
                         encoding="utf-8")


def read_refresh_beat():
    if not REFRESH_BEAT.exists():
        return None
    try:
        return json.loads(REFRESH_BEAT.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_refresh_beat(summary):
    C.STATE.mkdir(parents=True, exist_ok=True)
    REFRESH_BEAT.write_text(json.dumps(summary, indent=1, default=str),
                            encoding="utf-8")


def read_lot_book():
    if not LOT_BOOK.exists():
        return None
    try:
        return json.loads(LOT_BOOK.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def write_lot_book(book):
    C.STATE.mkdir(parents=True, exist_ok=True)
    LOT_BOOK.write_text(json.dumps(book, indent=1, default=str),
                        encoding="utf-8")


def lot_activity(lots, positions, csv_date, csv_problems, persist):
    """What changed since the last export, and whether we could tell.

    Three rules live here rather than in activity.py, because all three are
    about this process rather than about the arithmetic:

    1. A BAD PARSE IS NEVER DIFFED. Against yesterday's book, a truncated or
       unreadable CSV reads as the entire portfolio having been sold. The
       module has its own backstop for the mass-exit shape, but the caller
       knowing the parse reported problems is the better signal and it comes
       first.
    2. THE FINDING OUTLIVES THE RUN THAT FOUND IT. Exports arrive days apart
       and runs happen twice a day, so the run that first sees a new export is
       the only one that can compute the diff. If the stored changes were not
       re-served, a sale would appear on the page for one run and then vanish,
       which is worse than never showing it. `stale` says which it is.
    3. ONLY A FULL RUN WRITES. A refresh re-reads the same local CSV and is
       welcome to display the finding, but the file that decides whether the
       next comparison happens is not a read-only mode's to advance.
    """
    previous = read_lot_book()
    current = activity.snapshot(lots, csv_date, positions)

    if csv_problems or not lots:
        why = (f"the export parsed with {len(csv_problems)} problem(s)"
               if csv_problems else "the export parsed to no lots at all")
        view = {"comparable": False, "changes": [], "stale": False, "n": 0,
                "reason": f"{why} - a bad read of this file is "
                          f"indistinguishable from having sold everything in it",
                "from_exported": (previous or {}).get("exported"),
                "to_exported": current.get("exported")}
        return view

    view = dict(activity.diff(previous, current))
    view["stale"] = False

    if view["comparable"]:
        if persist:
            write_lot_book({
                "exported": current["exported"],
                "previous_exported": (previous or {}).get("exported"),
                "at": dt.datetime.now().isoformat(timespec="seconds"),
                "changes": view["changes"],
                "positions": current["positions"]})
    elif previous and previous.get("exported") == current.get("exported"):
        # Rule 2. The stored changes still describe the most recent thing the
        # book actually did; what is not available is a NEW comparison.
        view["changes"] = previous.get("changes") or []
        view["from_exported"] = previous.get("previous_exported")
        view["to_exported"] = previous.get("exported")
        view["stale"] = True
    elif previous is None and persist:
        # Seed. Nothing is reported - there is nothing to report against - but
        # the next new export has something to compare itself to.
        write_lot_book({
            "exported": current["exported"],
            "previous_exported": None,
            "at": dt.datetime.now().isoformat(timespec="seconds"),
            "changes": [],
            "positions": current["positions"]})

    view["n"] = len(view["changes"])
    return view


def append_history(record):
    """Append-only. The one thing no portfolio product gives you: your own
    history, in a format you can still read when the product is gone."""
    C.STATE.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def earnings_cache_leaks(cached, funds):
    """Which funds ended up in the earnings cache, and how many stocks are in it.

    A function rather than four lines inside selftest, because inline it was
    unfalsifiable and nobody noticed. It read the whole file, whose keys are
    `{"fetched", "symbols"}` - so the intersection with a set of tickers was
    empty by construction and the detail line said "2 stocks cached" on every
    run no matter what the cache held. Same shape as the bug class this repo
    keeps meeting: a check that always passes reads exactly like a check that
    found nothing wrong.
    """
    symbols = (cached or {}).get("symbols", {})
    return len(symbols), sorted(set(symbols) & set(funds))


# ------------------------------------------------------------------- health

def health(csv_age, csv_date, source_problems, mapping_findings,
           log_meta, last_run, mismatches=(), feeds=(), today=None):
    """One honest status for the whole machine.

    'ok' means every input is fresh and every mapping checks out. Anything
    else says so on the page rather than quietly rendering stale numbers.
    """
    today = today or dt.date.today()
    problems = []

    # Composition, earnings and multiples are counted onto the page and kept
    # out of here on purpose: one fund Yahoo will not break out is a coverage
    # figure, not a fault, and raising it would make the board permanently
    # amber over a vendor's ordinary gaps. That reasoning holds right up to
    # zero. A feed asked about eight funds that answers for none of them is not
    # thin, it is not answering - and on 2026-09-20 that exact state existed
    # (an emptied cache, read back in refresh mode) while the page printed
    # "All sources fresh". The difference between some and none is the whole
    # signal, so it is the only threshold here.
    for feed in feeds:
        if not feed["asked"] or feed["resolved"]:
            continue
        problems.append({
            "level": "critical", "key": f"feed-silent-{feed['name']}",
            "title": f"{feed['label']} answered for none of "
                     f"{feed['asked']} symbols",
            "detail": feed["detail"]})

    for problem in source_problems:
        problems.append({"level": "critical", "key": f"source-{hash(problem) & 0xffff}",
                         "title": "A data source failed", "detail": problem})

    for finding in mapping_findings:
        problems.append({"level": "critical",
                         "key": f"mapping-{finding['isin']}",
                         "title": f"{finding['ticker']} price mapping looks wrong",
                         "detail": finding["message"]})

    if csv_age is not None and csv_age > C.CSV_STALE_DAYS:
        problems.append({
            "level": "warning", "key": f"csv-stale-{csv_date}",
            "title": f"Nordnet export is {csv_age} days old",
            "detail": f"Exported {csv_date}. Units and cost basis are frozen at "
                      f"that date; any trade since then is invisible. Re-export "
                      f"'ostoerittain' from Nordnet into the project folder."})

    if last_run:
        try:
            gap = (today - dt.date.fromisoformat(last_run["at"][:10])).days
            if gap > C.RUN_STALE_DAYS:
                problems.append({
                    "level": "critical", "key": "run-stale",
                    "title": f"The cockpit had not run for {gap} days",
                    "detail": "The scheduled task is not firing. Check Task "
                              "Scheduler: task 'EquityCockpit'."})
        except (ValueError, KeyError, TypeError):
            pass

    if log_meta.get("problem"):
        problems.append({"level": "warning", "key": "notion-log",
                         "title": "Equity Log is not live",
                         "detail": log_meta["problem"]})

    # Where the board and the broker tell different stories about what is held.
    # These belong here rather than being appended by the caller, or the
    # headline counts fewer problems than the list actually holds.
    for issue in mismatches:
        blank = issue["kind"] == "blank"
        problems.append({
            "level": "warning", "key": f"held-{issue['ticker']}-{issue['kind']}",
            "title": (f"{issue['ticker']}: Held is blank on the board" if blank
                      else f"{issue['ticker']}: Notion and the broker disagree on Held"),
            "detail": issue["message"]})

    worst =("broken" if any(p["level"] == "critical" for p in problems)
             else "degraded" if problems else "ok")
    headline = {"ok": "All sources fresh",
                "degraded": (f"1 thing needs attention" if len(problems) == 1
                             else f"{len(problems)} things need attention"),
                "broken": "This page may be wrong"}[worst]
    detail = ("Nordnet export, live prices, FX and the Equity Log all answered."
              if worst == "ok" else
              "; ".join(p["title"] for p in problems))
    return {"status": worst, "headline": headline, "detail": detail,
            "problems": problems, "log_mode": log_meta.get("mode")}


# ---------------------------------------------------------------------- run

def run(quiet=False, verbose=True):
    """The full daily cycle: read everything, price it, tell Telegram."""
    return _cycle("full", quiet=quiet, verbose=verbose)


def refresh(verbose=True):
    """Re-price and re-render, nothing else.

    The daily run happens once, at 07:40, and Yahoo is ~15 minutes delayed even
    then - so by the afternoon the page shows a price eight hours old while
    looking exactly as authoritative as it did at breakfast. This closes that
    gap and touches nothing else: no Notion read, no Telegram pass, no fetch of
    anything that does not move intraday.

    What it deliberately does NOT do is write the run heartbeat or a history
    line. Both belong to the full cycle. A refresh that stamped `last_run.json`
    would keep the "the cockpit had not run for N days" check permanently
    satisfied while the daily task lay dead - the page would report a fresh
    board it had not actually read in a week. The heartbeat has to keep meaning
    the thing it is checked for.
    """
    return _cycle("refresh", quiet=True, verbose=verbose)


def _cycle(mode, quiet=False, verbose=True):
    started = dt.datetime.now()
    say = print if verbose else (lambda *a, **k: None)
    # One flag, read in four places. Everything that does not move between
    # 09:30 and 10:00 is served from the disk it was written to this morning.
    cached = mode == "refresh"

    lots, csv_problems = sources.nordnet_lots()
    positions = sources.positions(lots)
    csv_age, csv_date = sources.export_age_days(lots)
    say(f"  Nordnet: {len(lots)} lots -> {len(positions)} positions "
        f"(exported {csv_date}, {csv_age}d ago)")

    log_rows, log_meta = sources.equity_log(cached_only=cached)
    say(f"  Equity Log: {len(log_rows)} rows ({log_meta['mode']}"
        + (", not re-read" if cached else "") + ")")

    fx, fx_problems = sources.fx_rates()
    symbols = sorted({p["yahoo"] for p in positions if p["yahoo"]}
                     | {(r.get("Ticker") or "").strip() for r in log_rows})
    quotes, quote_problems = sources.quotes(symbols)
    say(f"  Prices: {len(quotes)}/{len(symbols)} symbols, "
        f"{len(fx)-1} FX pairs")

    history, history_problems, pulled = sources.price_history(
        symbols, cached_only=cached)
    say(f"  History: {len(history)}/{len(symbols)} symbols "
        f"({pulled} pulled from Yahoo, {len(history)-pulled} from cache)")

    # Multiples are a stock question. Funds are asked nothing - Yahoo returns
    # nothing for them anyway, and the coverage model judges them by weight.
    # Everything on the Equity Log is asked, held or not: the Log is the
    # research pipeline, and a name being researched is exactly when its P/E
    # matters.
    funda_symbols = sorted(
        {(r.get("Ticker") or "").strip() for r in log_rows
         if (r.get("Ticker") or "").strip()}
        | {p["yahoo"] for p in positions
           if p["yahoo"] and p["yahoo"] != "MISSING"
           and C.ASSET_CLASS.get(p["isin"], "stock") == "stock"})
    funda, funda_problems, funda_pulled = sources.fundamentals(
        funda_symbols, cached_only=cached)
    priced_funda = sum(1 for v in funda.values() if v.get("fields"))
    say(f"  Fundamentals: {priced_funda}/{len(funda_symbols)} symbols carry "
        f"multiples ({funda_pulled} pulled from Yahoo, "
        f"{len(funda)-funda_pulled} from cache)")

    # The exact inverse population to the one above: funds only. Asked through
    # a different yfinance accessor, cached in a different file, and asked at
    # all only because the ticker on a position row says nothing about what is
    # inside it - two of these trackers hold a name that is also held outright.
    comp_symbols = sorted({p["yahoo"] for p in positions
                           if p["yahoo"] and p["yahoo"] != "MISSING"
                           and C.ASSET_CLASS.get(p["isin"], "stock") == "fund"})
    comp, comp_problems, comp_pulled = sources.fund_composition(
        comp_symbols, cached_only=cached)
    with_comp = sum(1 for v in comp.values() if v.get("fields"))
    say(f"  Composition: {with_comp}/{len(comp_symbols)} funds broken out "
        f"({comp_pulled} pulled from Yahoo, {len(comp)-comp_pulled} from cache)")

    # Held stocks only, and deliberately not the whole Equity Log: this feeds a
    # calendar of what is coming against money actually at risk, and a name
    # being researched has no position to be exposed through. Funds are absent
    # because the endpoint 404s for them - measured, not assumed.
    earn_symbols = sorted({p["yahoo"] for p in positions
                           if p["yahoo"] and p["yahoo"] != "MISSING"
                           and C.ASSET_CLASS.get(p["isin"], "stock") == "stock"})
    earn, earn_problems, earn_pulled = sources.earnings(
        earn_symbols, cached_only=cached)
    with_earn = sum(1 for v in earn.values() if v.get("fields"))
    say(f"  Earnings: {with_earn}/{len(earn_symbols)} stocks have a reporting "
        f"record ({earn_pulled} pulled from Yahoo, "
        f"{len(earn)-earn_pulled} from cache)")

    holdings = analyse.value_holdings(positions, quotes, fx)
    # Money-weighted return off the live price, not the export-date figure
    # Nordnet ships in columns the parser asserts and then ignores.
    book_return = analyse.attach_returns(holdings, lots)
    mapping = analyse.price_sanity(holdings)
    watchlist = analyse.join_watchlist(log_rows, quotes, holdings)
    # Beside the recorded multiples, never over them. Must run before alerts(),
    # which reads the drift this computes.
    analyse.attach_fundamentals(watchlist, funda)
    mismatches = analyse.reconcile(watchlist)

    problems = list(csv_problems)
    problems += [f"FX {k}: {v}" for k, v in fx_problems.items()]
    # A missing price on a symbol with no public feed is expected, not a fault.
    known_missing = {p["yahoo"] for p in positions if p["yahoo"] is None}
    problems += [f"price {k}: {v}" for k, v in quote_problems.items()
                 if k not in known_missing]

    # Read once and used twice: health checks it for staleness, and the page
    # prints it so a refreshed price is never mistaken for a refreshed board.
    last_run = read_heartbeat()
    # Asked-versus-answered for the three feeds whose ordinary gaps are a
    # coverage figure rather than a fault. health() only speaks when a feed
    # answers for nothing at all; the counts themselves still go to the page.
    feeds = [
        {"name": "composition", "label": "Fund composition",
         "asked": len(comp_symbols), "resolved": with_comp,
         "detail": "Every fund came back without a breakdown. The sector and "
                   "look-through tables are running on the positions alone, so "
                   f"read them as the book's {len(comp_symbols)} fund lines "
                   "rather than what is inside them. Check state/"
                   "fund-composition.json, then run a full pass."},
        {"name": "earnings", "label": "The reporting calendar",
         "asked": len(earn_symbols), "resolved": with_earn,
         "detail": "No held stock has a reporting date. The calendar is empty "
                   "because nothing answered, not because nothing is due. "
                   "Check state/earnings.json, then run a full pass."},
        {"name": "fundamentals", "label": "Multiples",
         "asked": len(funda_symbols), "resolved": priced_funda,
         "detail": "Nothing on the Equity Log or in the book carries a P/E. "
                   "Every valuation figure on the page is the recorded one. "
                   "Check state/fundamentals.json, then run a full pass."},
    ]
    state = health(csv_age, csv_date, problems, mapping, log_meta,
                   last_run, mismatches, feeds)

    cover = analyse.coverage(holdings, watchlist)
    say(f"  Coverage: {len(cover['rows']) - cover['n_uncovered']}/"
        f"{len(cover['rows'])} monitored "
        f"({cover['n_stocks']} stocks by thesis, {cover['n_funds']} funds by "
        f"weight); EUR {cover['value_uncovered_eur']:,.0f} "
        f"({cover['pct_uncovered']:.0f}%) uncovered")

    exposures = exposure.look_through(holdings, funda, comp)
    say(f"  Exposure: {exposures['sectors']['n']} sectors covering "
        f"{exposures['sectors']['resolved_pct']:.0f}% of the book; "
        f"{exposures['names']['n']} names resolved "
        f"({exposures['names']['resolved_pct']:.0f}%), "
        f"{exposures['concentration']['effective_n']:g} effective positions")
    # Said out loud because it is the input to a decision nobody can make from
    # the position list: two funds filed under different themes can be drawing
    # on one pot of names, and a target weight argued from the bucket labels
    # would size two sleeves that are partly the same sleeve.
    ov = exposures["overlap"]
    if ov["pairs"]:
        worst = ov["pairs"][0]
        say(f"  Overlap: {ov['n_pairs']} fund pairs share a disclosed name, "
            f"{ov['n_substantial']} substantially; widest is {worst['a']} x "
            f"{worst['b']} on {worst['n_shared']} names, EUR "
            f"{worst['value_eur']:,.0f} ({worst['pct']:.1f}% of the book)")

    reports = reporting.book(holdings, earn, dt.date.today())
    cal = reports["calendar"]
    say(f"  Reporting: {cal['n']} prints in the next {cal['horizon_days']} days "
        f"({cal['n_soon']} inside a week, {cal['pct_ahead']:.0f}% of the book); "
        f"{cal['n_unknown']} without a scheduled date")

    # What the book did since the last export. Only a full run advances the
    # stored lot book; see lot_activity() for the other two rules.
    moves = lot_activity(lots, positions, csv_date, csv_problems,
                         persist=not cached)
    if moves["n"]:
        kinds = {}
        for change in moves["changes"]:
            kinds[change["kind"]] = kinds.get(change["kind"], 0) + 1
        say(f"  Activity: {moves['n']} change(s) between the "
            f"{moves['from_exported']} and {moves['to_exported']} exports ("
            + ", ".join(f"{v} {k}" for k, v in sorted(kinds.items())) + ")"
            + (" - carried from the last comparison, not recomputed"
               if moves["stale"] else ""))
    else:
        say(f"  Activity: no sales visible - {moves['reason'] or 'no change'}")

    alerts = analyse.alerts(watchlist, holdings, state, cover)
    # Appended rather than merged into analyse.alerts: those read the Equity
    # Log and the position file, this reads a vendor calendar. Keeping the two
    # sources of judgement apart is why a broken feed here cannot silence a
    # thesis alert there.
    alerts = alerts + reporting.alerts(reports)
    # Same argument once more. This one reads two exports against each other
    # and nothing else, and it is the only alert on the board that can be
    # raised by something Daniel did rather than by something the market did.
    alerts = alerts + activity.alerts(moves, watchlist)
    data = render.payload(holdings, watchlist, alerts, state, fx, {
        "nordnet_export_date": csv_date,
        "nordnet_export_age_days": csv_age,
        "nordnet_files": sorted({lot["source_file"] for lot in lots}),
        "equity_log_mode": log_meta["mode"],
        "equity_log_age_days": log_meta.get("age_days"),
        "lots": len(lots),
        # A chart that is missing or a day old is cosmetic, not a data fault, so
        # it is counted here rather than raised into health.
        "history_symbols": len(history),
        "history_problems": len(history_problems),
        # Same reasoning as history: a name without multiples is a fund or a
        # thin listing, not a broken feed, so it is counted rather than raised.
        "fundamentals_asked": len(funda_symbols),
        "fundamentals_priced": priced_funda,
        "fundamentals_problems": len(funda_problems),
        # Same reasoning again: a fund Yahoo will not break out is a coverage
        # figure on the exposure tables, not a broken feed.
        "composition_asked": len(comp_symbols),
        "composition_resolved": with_comp,
        "composition_problems": len(comp_problems),
        "earnings_asked": len(earn_symbols),
        "earnings_resolved": with_earn,
        "earnings_problems": len(earn_problems),
        # 'full' read every source; 'refresh' re-priced and served the rest off
        # disk. The page shows which, because an intraday page is fresher in
        # exactly one respect and a reader has no way to tell from the numbers.
        "run_mode": mode,
        "last_full_run": (last_run or {}).get("at"),
    }, history=history, coverage=cover, book_return=book_return,
       indicators=indicators.snapshot_all(history), exposure=exposures,
       reporting=reports, activity=moves)

    over = data["overview"]
    day, alloc = over["day"], over["allocation"]
    # The quiet count is the number worth watching here: it is how much of the
    # book has no previous close and is therefore absent from the day move
    # rather than sitting in it as a zero.
    say(f"  Overview: {over['n']} names folded from {len(holdings)} rows; "
        f"{alloc['n']} tiles laid out; day move "
        + ("unmeasurable" if day["pct"] is None else f"{day['pct']:+.2f}%")
        + f" over {day['covered_pct']:.0f}% of the book "
          f"({day['n_quiet']} quiet)")

    html_path, json_path = render.write(data)
    say(f"  Rendered: {html_path}")

    if cached:
        # Not dry_run - not called at all. The alert dedupe state notify keeps
        # is what stops the same alert being sent twice; a refresh touching it
        # 26 times a day would either spam or, worse, quietly mark tomorrow's
        # real alert as already seen.
        sent = {"sent": 0, "skipped": 0}
        say("  Telegram: not contacted - refresh re-prices, it does not alert")
    else:
        sent = notify.notify(alerts, data, dry_run=quiet)
        # 'sent' counts alerts, and they all travel in one message - say so, or
        # the line reads as if you were just messaged eight times.
        say(f"  Telegram: "
            + ("no message - nothing new" if not sent["sent"]
               else f"1 message carrying {sent['sent']} alert"
                    f"{'' if sent['sent'] == 1 else 's'}")
            + f" ({sent['skipped']} already known)"
            + (f", problem: {sent['problem']}" if sent.get("problem") else ""))

    summary = {
        "at": started.isoformat(timespec="seconds"),
        "mode": mode,
        "seconds": round((dt.datetime.now() - started).total_seconds(), 1),
        "status": state["status"],
        "value_eur": data["totals"]["value_eur"],
        "cost_eur": data["totals"]["cost_eur"],
        "pl_pct": data["totals"]["pl_pct"],
        "positions": len(holdings),
        "watchlist": len(watchlist),
        "priced": len(quotes), "symbols": len(symbols),
        "alerts": len(alerts), "notified": sent["sent"],
        "problems": [p["title"] for p in state["problems"]],
    }
    if cached:
        # A separate file, and no history line.
        #
        # Checked rather than assumed: `history.jsonl` is NOT one row per day -
        # it already holds 32 records across 6 dates, because every manual run
        # appends one. So the objection is not "it would stop being daily". It
        # is that a record carries no `mode`, so a scheduled 26-a-day cadence
        # would be indistinguishable from the 07:40 run inside the one file any
        # future chart of the book's value reads - and a day's change computed
        # across a mixed series would be wrong with nothing to show for it.
        # An intraday value series is worth having; it needs a field saying
        # what it is first. Until then the refresh stays out.
        write_refresh_beat(summary)
    else:
        write_heartbeat(summary)
        append_history({
            "date": started.date().isoformat(),
            "at": summary["at"],
            "value_eur": summary["value_eur"], "cost_eur": summary["cost_eur"],
            "pl_pct": summary["pl_pct"], "status": summary["status"],
            "by_account": _by_account(holdings),
            "holdings": {h["ticker"]: h["value_eur"] for h in data["holdings"]},
        })
    say(f"  {state['headline']}: {state['detail']}")
    return summary


def _by_account(holdings):
    out = {}
    for row in holdings:
        out[row["account"]] = round(out.get(row["account"], 0)
                                    + (row["value_eur"] or 0), 2)
    return out


# ----------------------------------------------------------------- selftest

# Directories the .gitignore excludes wholesale. Anything outside these is a
# candidate for being committed, so it is what the leak scan has to read.
_NOT_COMMITTED = {"state", "out", "__pycache__", ".pytest_cache", ".git",
                  ".venv", "venv"}

# A Nordnet account number is eight digits. Every eight-digit run that may
# appear in a committable file is listed here by hand, and this list is the
# whole point: the identifier scan below can only ever catch numbers that are
# already in portfolio.local.json, so a real account number typed from memory,
# from a checkpoint, or from a closed account sails straight through it. That
# has now happened twice, both times into tests/. Shape catches what the
# identifier set cannot.
#
# Adding an entry here is meant to be a deliberate act by a person who has
# looked at the number. If a test needs an account, use one of the fakes below
# rather than extending the list - a public commit cannot be unpublished.
_EIGHT_DIGITS = re.compile(r"(?<!\d)\d{8}(?!\d)")
_KNOWN_EIGHT = {
    "12345678", "87654321",          # portfolio.example.json, the documented fakes
    "11111111", "22222222", "99999999",   # test fixtures, visibly not real
    "00000000",                      # the all-zero UUID in the example file
    "86400000",                      # milliseconds in a day (dashboard.tmpl.html)
}


def _account_shape_scan():
    """Eight-digit runs in committable files that nobody has vouched for.

    Deliberately dumber than the identifier scan and that is the value: it
    knows nothing about what Daniel owns, so it cannot be defeated by a number
    the private file has never seen.
    """
    found = []
    for path, rel, text in _committable_files():
        for hit in sorted(set(_EIGHT_DIGITS.findall(text))):
            if hit not in _KNOWN_EIGHT:
                line = next((i for i, ln in enumerate(text.splitlines(), 1)
                             if hit in ln), 0)
                found.append(f"{rel}:{line}: {hit}")
    if found:
        return False, (f"{len(found)} unvouched eight-digit run(s), "
                       f"first {found[0]} - if it is not an account, add it to "
                       "_KNOWN_EIGHT; if it is, remove it from the file")
    return True, f"{len(_KNOWN_EIGHT)} vouched, no others"


def _git_ignored(paths):
    """Which of these would git refuse to commit? None if git cannot say.

    The scan used to decide this itself, from a hand-kept list of directory
    names. That list was a second, worse copy of .gitignore, and it drifted the
    first time a new ignored directory appeared: `deploy/public/` holds the
    rendered book, .gitignore excludes it, and the scan read it anyway and
    reported the account numbers inside it as a leak. A guess about what is
    committable is the same bug as a status that claims more than it means -
    so ask the authority instead of modelling it.
    """
    # Forward slashes going in, forward slashes coming back. Handed a Windows
    # path, git echoes it C-quoted - `"deploy\\public\\index.html"`, with the
    # quotes and the doubled backslash - which matches no key any caller will
    # build, so every lookup silently misses and the whole scan quietly widens.
    #
    # Bytes, not text. `text=True` runs newline translation on the way IN as
    # well as out, so on Windows the "\n" separators below reach git as
    # "\r\n" and every path arrives with a trailing carriage return attached.
    # Git dutifully treats that CR as part of the filename, and the answers
    # come back keyed to names that match nothing the caller will ever look
    # up. It is the file-format version of this repo's recurring bug: the
    # reply looks like an answer and is about a slightly different question.
    wanted = [p.as_posix() for p in paths]
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=str(C.ROOT), input="\n".join(wanted).encode("utf-8"),
            capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    # 0 = at least one ignored, 1 = none ignored. Anything else means git did
    # not answer the question, and a non-answer must not read as "nothing is
    # ignored" - that would be a scan that passes by failing.
    if proc.returncode not in (0, 1):
        return None
    out = proc.stdout.decode("utf-8", "replace")
    ignored = {ln.strip().strip('"') for ln in out.splitlines() if ln.strip()}
    # A result that claims nothing at all is ignored, in a repo whose
    # .gitignore is the only reason it is publishable, is not a result.
    if not ignored:
        return None
    return ignored


def _committable_files():
    """Every file a `git push` could carry, as (path, relative path, text)."""
    candidates = [p for p in sorted(C.ROOT.rglob("*")) if p.is_file()
                  and not set(p.relative_to(C.ROOT).parts) & {".git"}]
    ignored = _git_ignored([p.relative_to(C.ROOT) for p in candidates])

    for path in candidates:
        rel = path.relative_to(C.ROOT)
        if ignored is not None:
            if rel.as_posix() in ignored:
                continue
        elif set(rel.parts) & _NOT_COMMITTED:
            # Fallback only: git was not available. Coarser, and it is the
            # reason _NOT_COMMITTED still exists.
            continue
        # Belt and braces, and the load-bearing half when git cannot answer:
        # .env and the *.local.* files are gitignored, which is exactly why the
        # real numbers live in them. Reading them here would report the secret
        # as a leak from the one place it belongs.
        if path.suffix in {".csv", ".pyc"} or "local" in rel.name or rel.name == ".env":
            continue
        try:
            yield path, rel, path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def _leak_scan():
    """Would a `git push` of this folder disclose the book?

    The repo is publishable only because the holdings live in one gitignored
    file. That is a property of the *current* file layout, not of the code, so
    nothing stops a later edit from pasting a symbol map back into config.py -
    and the failure is silent and permanent, because a public commit cannot be
    unpublished. So it is asserted on every selftest rather than trusted.

    Looks for the two things that identify the book: ISINs (12 chars, the two
    leading letters are a country code) and broker account numbers.

    Necessary and not sufficient. It can only match what portfolio.local.json
    already names, so it is paired with _account_shape_scan, which matches on
    shape and therefore catches numbers this set has never heard of.
    """
    secrets = set(C.YAHOO) | set(C.ACCOUNTS)
    if C.EQUITY_LOG_DATA_SOURCE:
        secrets.add(C.EQUITY_LOG_DATA_SOURCE)

    found = []
    for path, rel, text in _committable_files():
        if rel.name == ".gitignore":
            continue
        hits = sorted(s for s in secrets if s in text)
        if hits:
            found.append(f"{rel}: {', '.join(hits[:3])}")

    if found:
        return False, f"{len(found)} committable file(s) leak: {found[0]}"
    return True, f"{len(secrets)} identifiers, none in committable files"


def selftest():
    """Offline wiring checks. Fails loudly, by name, on the things that rot."""
    checks, failed = [], 0

    def check(name, ok, detail=""):
        nonlocal failed
        checks.append((name, ok, detail))
        if not ok:
            failed += 1

    # This one is first because it is the failure the scheduler is most likely
    # to hit: this machine has several Pythons and only one of them has
    # yfinance. A task that picks the wrong interpreter fails every morning
    # with no prices and nothing to show for it.
    try:
        import yfinance
        check("python: yfinance importable",
              True, f"{yfinance.__version__} @ {sys.executable}")
    except Exception as exc:
        check("python: yfinance importable", False,
              f"{exc} - running {sys.executable}; use run.ps1")

    check("config: project folder exists", C.PROJECT_DIR.exists(), str(C.PROJECT_DIR))
    check("config: template present", render.TEMPLATE.exists(), str(render.TEMPLATE))
    tmpl = render.TEMPLATE.read_text(encoding="utf-8") if render.TEMPLATE.exists() else ""
    check("config: template has data marker", render.MARKER in tmpl)
    check("config: template has chart-lib marker", render.LIB_MARKER in tmpl)
    # Vendored, not linked. If this file goes missing the page still opens but
    # the middle pane is blank, which is exactly the kind of quiet breakage the
    # selftest exists to make loud.
    lib = render.CHARTLIB.stat().st_size if render.CHARTLIB.exists() else 0
    check("assets: chart library vendored", lib > 100_000,
          f"{lib // 1024} KB" if lib else f"missing: {render.CHARTLIB}")
    # Without this the euro sign renders as "a-hat-euro" the moment the file is
    # opened over http rather than from disk. Caught by eye, not by the tests.
    check("config: template declares utf-8", 'charset="utf-8"' in tmpl[:1024])
    # The sheet's interactive layer has no test that can fail - a template
    # edited back into flat tables still renders, still smoke-tests clean, and
    # just quietly stops being drivable. These are the three hooks the whole
    # thing hangs off: the section nav container, the per-section marker the
    # nav and the collapse are built from, and the state object the tables
    # read. Losing any one of them is silent everywhere else.
    hooks = [h for h in ('id="sheetnav"', 'data-sec=', 'const SS =')
             if h not in tmpl]
    check("assets: sheet is still interactive", not hooks,
          f"template lost: {', '.join(hooks)}" if hooks
          else "nav, collapsible sections and shared filter state all present")
    # Same argument one level up. The Overview is the page's landing surface
    # and it is built entirely in script: delete the grid container and the
    # page still opens, still smoke-tests clean, and simply shows an empty
    # screen where the book used to be. Four hooks, same as above - the two
    # containers, the view switch, and the treemap tiles that are the one
    # thing here the browser must not be allowed to lay out for itself.
    ov = [h for h in ('id="ovgrid"', 'id="v-overview"', 'function setView',
                      'class="tmap"') if h not in tmpl]
    check("assets: overview is still built", not ov,
          f"template lost: {', '.join(ov)}" if ov
          else "grid, view switch and treemap container all present")

    # The chart is the only element on the page that measures its own container,
    # and with autoSize on it gets exactly one chance - the vendored library
    # makes resize() a no-op for as long as the observer is installed. The
    # zero-size guard in paintChart is what keeps construction out of a hidden
    # container. Delete it and the page still opens, still smoke-tests clean,
    # and builds a zero-wide chart on every cold load; whether it ever recovers
    # is then the ResizeObserver's business rather than this repo's.
    guard = [h for h in ('const rect = box.getBoundingClientRect();',
                         'if (!rect.width || !rect.height) return;')
             if h not in tmpl]
    check("assets: chart refuses a box it cannot measure", not guard,
          f"template lost: {', '.join(guard)}" if guard
          else "paintChart still defers on a zero-size container")

    # Two narrow tiers, not one. The single stacked fallback this replaced was
    # measured at a 1000px canvas: 2589px of page, the thesis 1077px below the
    # fold, and the rail a 320px box over 2019px of names nested inside a page
    # that also scrolled. Collapsing the tiers back into one breakpoint is the
    # obvious tidy-up and it restores exactly that.
    tiers = [t for t in ('(max-width:1180px) and (min-width:761px)',
                         'grid-template-areas:"rail mid" "rail thesis"',
                         '(max-width:760px)') if t not in tmpl]
    check("assets: narrow layout keeps both tiers", not tiers,
          f"template lost: {', '.join(tiers)}" if tiers
          else "two-column tier and one-column fallback both present")

    # The Activity section is the only part of the sheet that must render when
    # it has nothing to show, because its empty state carries the finding: an
    # absent section reads as "nothing was sold", and the thing it most often
    # has to say is "I could not tell". The natural tidy-up here is the one
    # every other section gets - `!rows.length ? '' : ...` around the whole
    # block - and applying it would restore the exact defect the module was
    # written for, silently. So the hooks checked are the section itself AND
    # the sentence that distinguishes the two empty states.
    act = [h for h in ('data-sec="act"', 'No comparison was possible',
                       'it is the absence of a report')
           if h not in tmpl]
    check("assets: activity says which kind of empty it is", not act,
          f"template lost: {', '.join(act)}" if act
          else "the section and both of its empty states are present")

    # The wide tier, which is the one no test here can reach: the Chrome
    # sidebar caps innerWidth at 955 and resize_window does not move it, so
    # every browser measurement this repo has ever taken was of a narrow tier.
    # Two things hold the twelve-track grid up and both fail silently.
    #
    # The tracks: on `auto-fit` the viewport chose the column count, which at
    # 1920 resolved to six and left Concentration alone on a row with five
    # empty tracks beside it. Declared spans mean nothing without fixed tracks.
    #
    # The scoping: `.ovgrid > .ov-8` and `.ovgrid > *` TIE on specificity
    # (0,1,1 each - one class, one element), so source order decides between
    # them. Scoped, every span class is declared after the default it must beat
    # and beats it. Unscoped, a bare `.ov-8{}` is (0,1,0), loses to the `> *`
    # default outright, and the card silently takes 4 tracks instead of 8. The
    # page still opens, the smoke test still passes, every unit test stays
    # green, and the orphan-row bug is back at a width nobody here can measure.
    css = re.sub(r"/\*.*?\*/", " ", tmpl.split("</style>")[0], flags=re.S)
    grid = []
    # Read the tracks off the `.ovgrid` rule itself, not off the stylesheet.
    # `.ovtop` declares the same twelve tracks one rule below - deliberately,
    # so a stat edge lines up with a card edge - so a substring search over the
    # whole sheet stays satisfied by the headline band long after the card grid
    # has gone back to auto-fit. That version of this check was written first
    # and the mutation run is the only reason it did not ship.
    ovgrid = re.search(r"\.ovgrid\{([^}]*)\}", css)
    if not ovgrid:
        grid.append("the .ovgrid rule is gone")
    elif "grid-template-columns:repeat(12,minmax(0,1fr))" not in ovgrid.group(1):
        grid.append("the twelve fixed tracks are gone (auto-fit again?): "
                    + ovgrid.group(1).strip()[:70])
    spans = re.findall(r"([^{}]*\.ov-\d+[^{}]*)\{", css)
    loose = sorted({part.strip() for sel in spans for part in sel.split(",")
                    if ".ov-" in part
                    and not part.strip().startswith(".ovgrid > .ov-")})
    if loose:
        grid.append(f"span rules not scoped as children: {', '.join(loose)}")
    check("assets: overview spans outrank the grid default", not grid,
          "; ".join(grid) if grid
          else f"twelve fixed tracks, {len(spans)} span rules all scoped "
               f"`.ovgrid > .ov-N`")

    # The type scale is only a scale while it is the only source of sizes. It
    # decayed into 15 font-sizes, 10 weights and 10 radii once before, one rule
    # at a time, and no single edit in that drift looked wrong on its own. So
    # the check is not "is there a scale" - it is "is anything still bypassing
    # it". Raw literals are counted outside the :root block that defines them.
    style = tmpl.split("</style>")[0]
    body_css = style[style.index("*{box-sizing:border-box}"):] \
        if "*{box-sizing:border-box}" in style else style
    raw = {name: sorted(set(re.findall(pat, body_css)))
           for name, pat in (("font-size", r"font-size:([\d.]+px)"),
                             ("font-weight", r"font-weight:(\d+)"),
                             ("border-radius", r"border-radius:([\d.]+px)"),
                             ("gap", r"gap:([\d.]+px)"))}
    stray = {k: v for k, v in raw.items() if v}
    check("assets: type scale has no bypasses", not stray,
          "; ".join(f"{k}: {', '.join(v)}" for k, v in stray.items()) if stray
          else "sizes, weights, radii and gaps all come from :root tokens")

    # Right-aligned is correct for the numeric columns and wrong for every word
    # column, which is how six tables came to right-rag their sector, account
    # and currency cells against a hard edge. The opt-out has to exist AND be
    # used; a rule nobody applies is the same as no rule.
    # The count is reported rather than compared to a threshold. There is no
    # defensible number of text columns to demand - it changes whenever a
    # column is added - but a run that prints 2 where the last one printed 20
    # is a regression anybody can see, and inventing a floor here would just be
    # a recalled number pretending to be a requirement.
    marked = tmpl.count('class="t"') + tmpl.count(' t"')
    align = []
    if "th.t,td.t{text-align:left}" not in tmpl.replace(" ", ""):
        align.append("the .t opt-out rule is gone")
    elif not marked:
        align.append("the .t rule exists but nothing uses it")
    if "thead th{position:sticky" not in tmpl:
        align.append("table headers no longer stick")
    check("assets: tables align words left and numbers right", not align,
          "; ".join(align) if align
          else f"{marked} text columns opt out of the numeric default, "
               f"headers sticky")

    # An unclosed row tag is the worst kind of defect this page can have,
    # because it does not break the page - it silently shifts one table's
    # values a column left of their own headings and keeps looking tidy. The
    # funds table shipped like that: `<tr class=... data-on="0"` with no `>`,
    # so the browser parsed `<td` as an attribute, ate the symbol cell, and
    # rendered eight cells under nine headers. Every figure in that table was
    # sitting under the wrong name.
    unclosed = re.findall(r"<(tr|thead|tbody)\b[^>]{0,400}?<t[dh]\b", tmpl)
    check("assets: no table row swallows its first cell", not unclosed,
          f"{len(unclosed)} unclosed row/section tag(s): {set(unclosed)}"
          if unclosed else "every row tag closes before its cells")

    # DESIGN.md 5b says not to hand-tune the plotted colours and to re-run the
    # validator if you change one. That was unenforceable while the validator
    # lived outside the repo, so a palette could drift and nothing would notice.
    # tools/palette_check.py reads the tokens straight out of the template, so
    # this check has no second copy of the palette to go stale against.
    try:
        sys.path.insert(0, str(C.ROOT / "tools"))
        import palette_check

        # Fed the template text this function already read, so the check runs
        # against the same bytes as every other assets: check above it.
        res = palette_check.evaluate(palette_check.read_tokens(tmpl))
        check("assets: palette still separable",
              not res.failures,
              "; ".join(res.failures[:3]) if res.failures
              else f"{len(res.rows)} checks across both modes, all pass")
    except Exception as exc:                       # noqa: BLE001 - report, never crash
        check("assets: palette still separable", False, f"checker failed: {exc}")

    # A placeholder target that renders as a bare number IS a policy to whoever
    # reads the page next, and the repo already has form for exactly this - a
    # derived status claiming more than it means. Both render sites have to
    # carry the marker, so both are hooked; losing either one is invisible in
    # every other check, because the page still draws a perfectly good number.
    basis = [h for h in ('title="Placeholder, not a policy"',
                         'title="Filled in by a rule, not a decision.')
             if h not in tmpl]
    check("assets: a placeholder target says so", not basis,
          f"template lost: {', '.join(basis)}" if basis
          else "marked in the coverage table and in the thesis pane")

    placeholders = sorted(i for i, b in C.TARGET_BASIS.items()
                          if b == "placeholder" and C.TARGET_WEIGHT.get(i)
                          is not None)
    check("config: placeholder targets are declared, not silent",
          all(C.TARGET_BASIS.get(i) in ("policy", "placeholder")
              for i in C.TARGET_BASIS),
          f"{len(placeholders)} placeholder, "
          f"{sum(1 for i, b in C.TARGET_BASIS.items() if b == 'policy' and C.TARGET_WEIGHT.get(i) is not None)} written policy")

    check("privacy: holdings file is gitignored", *_leak_scan())
    check("privacy: no unvouched account numbers", *_account_shape_scan())

    lots, problems = sources.nordnet_lots()
    check("nordnet: export parses", bool(lots) and not problems,
          "; ".join(problems) or f"{len(lots)} lots")
    positions = sources.positions(lots)
    unmapped = [p for p in positions if p["yahoo"] == "MISSING"]
    check("nordnet: every ISIN is mapped", not unmapped,
          ", ".join(f"{p['tunnus']} ({p['isin']})" for p in unmapped)
          or f"{len(positions)} positions")
    unbucketed = [p for p in positions if p["bucket"] == "Unclassified"]
    check("config: every ISIN has a bucket", not unbucketed,
          ", ".join(p["tunnus"] for p in unbucketed))

    # Yahoo 404s a fund on the earnings endpoint, so a fund that slipped into
    # this cache means the caller's class filter has broken and every run is
    # buying guaranteed failures. Reads the cache rather than the network:
    # selftest is offline.
    if C.EARNINGS_CACHE.exists():
        try:
            cached = json.loads(C.EARNINGS_CACHE.read_text(encoding="utf-8"))
        except ValueError:
            cached = {}
        funds = {C.YAHOO[i] for i, k in C.ASSET_CLASS.items()
                 if k == "fund" and C.YAHOO.get(i)}
        n, leaked = earnings_cache_leaks(cached, funds)
        check("earnings: funds are not asked", not leaked,
              f"in the cache: {', '.join(leaked)}" if leaked
              else f"{n} stocks cached, no funds")

    level, kind = analyse.parse_trigger("Price below USD 285 does the same")
    check("analyse: trigger parser", (level, kind) == (285.0, "below"),
          f"got {level} {kind}")
    level, _ = analyse.parse_trigger("below 3,700p")
    check("analyse: thousands separator", level == 3700.0, f"got {level}")
    level, _ = analyse.parse_trigger("margin below 20% would worry me")
    check("analyse: ignores percentages", level is None, f"got {level}")

    check("nordnet: Finnish decimals", sources._num("1 211,5") == 1211.5)

    rows, meta = sources.equity_log()
    check("notion: Equity Log readable", bool(rows),
          f"{len(rows)} rows via {meta['mode']}"
          + (f" - {meta['problem']}" if meta.get("problem") else ""))
    if rows:
        blank = [p for p in C.NOTION_PROPS
                 if p not in C.NOTION_PROPS_OPTIONAL
                 and all(r.get(p) in (None, "") for r in rows)]
        check("notion: no property returns empty for every row", not blank,
              f"empty: {blank}" if blank else "")

    ok, problem = sources.notion_schema_ok()
    if ok is not None:
        check("notion: live schema matches config", ok, problem or "")

    width = max(len(n) for n, _, _ in checks)
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    print(f"\n  {len(checks) - failed}/{len(checks)} passed")
    return failed


# ------------------------------------------------------------------- doctor

def doctor():
    beat = read_heartbeat()
    if not beat:
        print("  Never run. Try: python cockpit.py run")
        return 1
    age = (dt.datetime.now() - dt.datetime.fromisoformat(beat["at"]))
    print(f"  Last run   {beat['at']}  ({age.days}d {age.seconds // 3600}h ago)")
    # Printed on its own line, never folded into the one above. The two answer
    # different questions - "when was the board last read" and "how old is the
    # price on screen" - and a single freshness number would answer neither.
    warm = read_refresh_beat()
    if warm:
        try:
            gap = dt.datetime.now() - dt.datetime.fromisoformat(warm["at"])
            # Total minutes, not `.seconds` - that field resets every midnight
            # and would report a two-day-old refresh as twenty minutes old.
            mins = int(gap.total_seconds() // 60)
            print(f"  Refreshed  {warm['at']}  "
                  f"({mins // 60}h {mins % 60}m ago, prices only)")
        except (ValueError, KeyError, TypeError):
            pass
    print(f"  Status     {beat['status']}")
    print(f"  Book       EUR {beat['value_eur']:,.0f}  "
          f"({beat['pl_pct']:+.2f}% vs cost)")
    print(f"  Coverage   {beat['priced']}/{beat['symbols']} symbols priced, "
          f"{beat['positions']} positions, {beat['watchlist']} watchlist rows")
    print(f"  Alerts     {beat['alerts']} open, {beat['notified']} sent last run")
    if beat["problems"]:
        print("  Problems:")
        for problem in beat["problems"]:
            print(f"    - {problem}")
    else:
        print("  Problems   none")
    if HISTORY.exists():
        lines = HISTORY.read_text(encoding="utf-8").strip().splitlines()
        print(f"  History    {len(lines)} runs recorded in {HISTORY.name}")
    return 0 if beat["status"] == "ok" else 1


# -------------------------------------------------------------- sync-notion

def sync_notion(path):
    """Load an Equity Log snapshot into the cache.

    The hands-off path is a NOTION_TOKEN in .env. This exists for when there
    isn't one: Claude reads the board over MCP, writes the rows to a JSON
    file, and this imports it. Same cache either way.
    """
    raw = json.loads(open(path, encoding="utf-8").read())
    rows = raw["rows"] if isinstance(raw, dict) and "rows" in raw else raw
    if not isinstance(rows, list) or not rows:
        print("  Expected a list of row objects, or {'rows': [...]}.")
        return 1
    unknown = sorted({k for r in rows for k in r} - set(C.NOTION_PROPS) - {"page_id"})
    missing = [p for p in C.NOTION_PROPS if all(p not in r for r in rows)]
    C.STATE.mkdir(parents=True, exist_ok=True)
    C.EQUITY_LOG_CACHE.write_text(json.dumps(
        {"fetched": dt.datetime.now().isoformat(timespec="seconds"), "rows": rows},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"  Cached {len(rows)} rows -> {C.EQUITY_LOG_CACHE}")
    if missing:
        print(f"  Note: no row carried {missing} - those columns will read blank.")
    if unknown:
        print(f"  Note: ignoring extra keys {unknown}.")
    return 0


# ---------------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(prog="cockpit", description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--quiet", action="store_true",
                         help="analyse and render, but send nothing")
    sub.add_parser("refresh")
    sub.add_parser("selftest")
    sub.add_parser("doctor")
    sync = sub.add_parser("sync-notion")
    sync.add_argument("file")
    args = parser.parse_args(argv)

    if args.cmd == "run":
        print("Equity cockpit")
        summary = run(quiet=args.quiet)
        return 0 if summary["status"] != "broken" else 1
    if args.cmd == "refresh":
        print("Equity cockpit - intraday refresh")
        summary = refresh()
        return 0 if summary["status"] != "broken" else 1
    if args.cmd == "selftest":
        print("Selftest")
        return 1 if selftest() else 0
    if args.cmd == "doctor":
        print("Doctor")
        return doctor()
    if args.cmd == "sync-notion":
        return sync_notion(args.file)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
