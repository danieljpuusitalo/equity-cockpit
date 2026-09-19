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

import sys
import json
import argparse
import datetime as dt

import config as C
import sources
import analyse
import indicators
import render
import notify

HEARTBEAT = C.STATE / "last_run.json"
# Deliberately a different file from HEARTBEAT. See refresh() for why the two
# must not be the same one.
REFRESH_BEAT = C.STATE / "last_refresh.json"
HISTORY = C.STATE / "history.jsonl"


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


def append_history(record):
    """Append-only. The one thing no portfolio product gives you: your own
    history, in a format you can still read when the product is gone."""
    C.STATE.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


# ------------------------------------------------------------------- health

def health(csv_age, csv_date, source_problems, mapping_findings,
           log_meta, last_run, mismatches=(), today=None):
    """One honest status for the whole machine.

    'ok' means every input is fresh and every mapping checks out. Anything
    else says so on the page rather than quietly rendering stale numbers.
    """
    today = today or dt.date.today()
    problems = []

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
    state = health(csv_age, csv_date, problems, mapping, log_meta,
                   last_run, mismatches)

    cover = analyse.coverage(holdings, watchlist)
    say(f"  Coverage: {len(cover['rows']) - cover['n_uncovered']}/"
        f"{len(cover['rows'])} monitored "
        f"({cover['n_stocks']} stocks by thesis, {cover['n_funds']} funds by "
        f"weight); EUR {cover['value_uncovered_eur']:,.0f} "
        f"({cover['pct_uncovered']:.0f}%) uncovered")

    alerts = analyse.alerts(watchlist, holdings, state, cover)
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
        # 'full' read every source; 'refresh' re-priced and served the rest off
        # disk. The page shows which, because an intraday page is fresher in
        # exactly one respect and a reader has no way to tell from the numbers.
        "run_mode": mode,
        "last_full_run": (last_run or {}).get("at"),
    }, history=history, coverage=cover, book_return=book_return,
       indicators=indicators.snapshot_all(history))

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


def _leak_scan():
    """Would a `git push` of this folder disclose the book?

    The repo is publishable only because the holdings live in one gitignored
    file. That is a property of the *current* file layout, not of the code, so
    nothing stops a later edit from pasting a symbol map back into config.py -
    and the failure is silent and permanent, because a public commit cannot be
    unpublished. So it is asserted on every selftest rather than trusted.

    Looks for the two things that identify the book: ISINs (12 chars, the two
    leading letters are a country code) and broker account numbers.
    """
    secrets = set(C.YAHOO) | set(C.ACCOUNTS)
    if C.EQUITY_LOG_DATA_SOURCE:
        secrets.add(C.EQUITY_LOG_DATA_SOURCE)
    # The private file and the .env are the two places these SHOULD appear.
    allowed = {C.PORTFOLIO_FILE.name, ".env", ".gitignore"}

    found = []
    for path in sorted(C.ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(C.ROOT)
        if set(rel.parts) & _NOT_COMMITTED or rel.name in allowed:
            continue
        if path.suffix in {".csv", ".pyc"} or "local" in rel.name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
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

    check("privacy: holdings file is gitignored", *_leak_scan())

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
