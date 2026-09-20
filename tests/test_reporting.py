"""The reporting calendar, and the one rule the module exists to enforce.

Most of this file is one test written six ways: a quarter that has not been
reported is not a quarter that was reported as zero. That failure has already
shipped twice in this codebase against two different vendors and both times it
manufactured a decline out of silence, so it is worth over-testing.

Fixture identifiers throughout. `today` is passed in everywhere, so nothing
here changes answer tomorrow.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C                                              # noqa: E402
import reporting                                                # noqa: E402

TODAY = dt.date(2026, 9, 20)
STOCK_A, STOCK_B = "XX0000000001", "XX0000000002"
FUND_A = "XX0000000101"


@pytest.fixture
def fake_book(monkeypatch):
    monkeypatch.setattr(C, "ASSET_CLASS", {
        STOCK_A: "stock", STOCK_B: "stock", FUND_A: "fund"})


def cache(**by_symbol):
    return {sym: {"fetched": str(TODAY), "fields": fields}
            for sym, fields in by_symbol.items()}


def quarter(date, estimate=None, reported=None, surprise=None):
    return {"date": date, "eps_estimate": estimate,
            "eps_reported": reported, "surprise_pct": surprise}


def position(symbol, value, klass="stock", name=""):
    return {"symbol": symbol, "name": name or symbol,
            "value_eur": value, "klass": klass}


def holding(isin, symbol, value, name="", account="ACC1"):
    return {"isin": isin, "yahoo": symbol, "value_eur": value,
            "name": name, "account": account}


# ------------------------------------------------- absent is not zero

def test_an_unreported_quarter_is_not_a_miss():
    """The trap, stated plainly. Yahoo ships the upcoming quarter with a NaN
    result, which `sources` carries through as None. Read as a number it is a
    100% miss against consensus, on every holding, forever."""
    rec = reporting.record({"history": [
        quarter("2026-10-29", estimate=2.5),               # not reported yet
        quarter("2026-07-30", estimate=2.0, reported=2.4, surprise=20.0)]})
    assert rec["n"] == 1
    assert rec["misses"] == 0
    assert rec["beats"] == 1
    assert rec["last"]["date"] == "2026-07-30"


def test_no_reported_quarter_at_all_gives_an_empty_record_not_a_zero_one():
    rec = reporting.record({"history": [quarter("2026-10-29", estimate=2.5)]})
    assert rec["n"] == 0
    assert rec["median_surprise_pct"] is None
    assert rec["last"] is None


def test_an_unreported_quarter_never_appears_in_the_latest_table(fake_book):
    view = reporting.latest(
        [position(STOCK_A, 1000.0)],
        cache(**{STOCK_A: {"history": [quarter("2026-10-29", estimate=2.5)]}}),
        TODAY)
    assert view == []


def test_a_missing_year_ago_quarter_gives_no_growth_rather_than_full_growth():
    """Several European names in this book file half-yearly. Pairing a Q3 with
    a Q1 because it is the nearest row would report six months of trading as a
    quarter's growth."""
    out = reporting.growth({"quarters": [
        {"period": "2026-06-30", "revenue": 120.0, "eps": 1.2},
        {"period": "2025-12-31", "revenue": 60.0, "eps": 0.6}]})
    assert out["revenue_yoy_pct"] is None
    assert out["prior_period"] is None


# ------------------------------------------------------------ the record

def test_the_record_uses_the_median_not_the_mean():
    """One 215% surprise - Amazon has one on the record - would otherwise set
    the whole reading on its own."""
    rows = [quarter(f"2026-0{i}-01", 1.0, 1.0, s) for i, s in
            enumerate([2.0, 3.0, 4.0, 215.0], start=1)]
    rec = reporting.record({"history": rows})
    assert rec["median_surprise_pct"] == 3.5          # not 56.0


def test_a_hair_either_side_of_consensus_is_not_a_beat():
    below = C.EARNINGS_SURPRISE_PTS - 0.1
    rec = reporting.record({"history": [
        quarter("2026-07-30", 1.0, 1.0, below),
        quarter("2026-04-30", 1.0, 1.0, -below)]})
    assert (rec["beats"], rec["misses"], rec["inline"]) == (0, 0, 2)


def test_the_record_says_how_many_quarters_it_read():
    rec = reporting.record({"history": [
        quarter("2026-07-30", 1.0, 1.1, 10.1),
        quarter("2026-04-30", 1.0, 1.1, 10.1)]})
    assert rec["n"] == 2                              # not silently "8"


# ------------------------------------------------------------- the growth

def test_growth_is_against_the_same_quarter_a_year_earlier():
    out = reporting.growth({"quarters": [
        {"period": "2026-06-30", "revenue": 110.0, "eps": 1.1},
        {"period": "2026-03-31", "revenue": 200.0, "eps": 2.0},
        {"period": "2025-06-30", "revenue": 100.0, "eps": 1.0}]})
    assert out["prior_period"] == "2025-06-30"
    assert out["revenue_yoy_pct"] == 10.0             # not -45% against Q1
    assert out["eps_yoy_pct"] == 10.0


def test_a_fiscal_quarter_end_that_drifts_a_few_days_still_pairs():
    out = reporting.growth({"quarters": [
        {"period": "2026-06-28", "revenue": 110.0},
        {"period": "2025-07-01", "revenue": 100.0}]})
    assert out["revenue_yoy_pct"] == 10.0


def test_a_sign_flip_has_no_percentage():
    """Swinging from a loss to a profit is not +300% growth. It is a different
    kind of event and gets said in words, not invented as a number."""
    out = reporting.growth({"quarters": [
        {"period": "2026-06-30", "net_income": 30.0, "eps": 0.3},
        {"period": "2025-06-30", "net_income": -10.0, "eps": -0.1}]})
    assert out["eps_yoy_pct"] is None


# ------------------------------------------------------------ the calendar

def test_the_calendar_orders_by_date_and_carries_the_weight(fake_book):
    view = reporting.calendar(
        [position(STOCK_A, 600.0), position(STOCK_B, 400.0)],
        cache(**{STOCK_A: {"next": {"date": "2026-11-04"}},
                 STOCK_B: {"next": {"date": "2026-10-23"}}}),
        TODAY)
    assert [r["symbol"] for r in view["rows"]] == [STOCK_B, STOCK_A]
    assert view["rows"][0]["weight_pct"] == 40.0
    assert view["pct_ahead"] == 100.0


def test_a_date_past_the_horizon_is_left_out_but_is_not_unknown(fake_book):
    view = reporting.calendar(
        [position(STOCK_A, 1000.0)],
        cache(**{STOCK_A: {"next": {"date": "2027-06-01"}}}),
        TODAY, horizon_days=30)
    assert view["n"] == 0
    assert view["n_unknown"] == 0                     # it has a date, just later


def test_an_unknown_date_is_reported_as_unknown_not_dropped(fake_book):
    """Yahoo had no scheduled date at all for one holding in this book while
    still carrying six years of history for it. Silence is a real state and it
    has to reach the page, or the calendar quietly under-counts the book."""
    view = reporting.calendar(
        [position(STOCK_A, 1000.0)],
        cache(**{STOCK_A: {"history": [quarter("2026-07-30", 1.0, 1.0, 0.0)]}}),
        TODAY)
    [gap] = view["unknown"]
    assert gap["symbol"] == STOCK_A
    # The distinction between "we never fetched this" and "Yahoo has the
    # company and has no date for it". Only the second is a fact about it.
    assert gap["has_history"] is True
    assert view["pct_ahead"] == 0.0


def test_an_empty_next_block_reads_as_unknown(fake_book):
    """Yahoo's `calendar['Earnings Date']` comes back as an empty LIST for some
    names, which `sources` shapes into an empty next. An empty container is not
    a date."""
    view = reporting.calendar(
        [position(STOCK_A, 1000.0)], cache(**{STOCK_A: {"next": {}}}), TODAY)
    assert view["n_unknown"] == 1


def test_yahoos_estimated_date_flag_reaches_the_row(fake_book):
    """A guessed date printed beside a confirmed one with no mark is this
    repo's derived-status bug class in one column."""
    view = reporting.calendar(
        [position(STOCK_A, 1000.0)],
        cache(**{STOCK_A: {"next": {"date": "2026-10-23", "estimated": True}}}),
        TODAY)
    assert view["rows"][0]["estimated"] is True


def test_funds_are_not_asked_for_a_reporting_date(fake_book):
    """Yahoo answers a fund with a 404 for this endpoint, measured. A tracker
    has no quarter, and a calendar row for one would be meaningless even if it
    answered."""
    view = reporting.calendar(
        [position(FUND_A, 1000.0, klass="fund")], {}, TODAY)
    assert view["n"] == 0 and view["n_unknown"] == 0


def test_soon_is_inside_the_configured_window(fake_book):
    inside = TODAY + dt.timedelta(days=C.EARNINGS_SOON_DAYS)
    outside = inside + dt.timedelta(days=1)
    view = reporting.calendar(
        [position(STOCK_A, 500.0), position(STOCK_B, 500.0)],
        cache(**{STOCK_A: {"next": {"date": str(inside)}},
                 STOCK_B: {"next": {"date": str(outside)}}}),
        TODAY)
    assert view["n_soon"] == 1


# ---------------------------------------------------------------- the book

def test_two_custody_accounts_fold_into_one_reporting_row(fake_book):
    """Holdings are per ISIN per account. A name held in both would otherwise
    appear twice in the calendar and count its weight twice."""
    view = reporting.book(
        [holding(STOCK_A, "AAA", 600.0, account="OST"),
         holding(STOCK_A, "AAA", 400.0, account="AOT")],
        cache(AAA={"next": {"date": "2026-10-23"}}), TODAY)
    [row] = view["calendar"]["rows"]
    assert row["weight_pct"] == 100.0
    assert view["n_stocks"] == 1


def test_a_symbol_the_map_never_resolved_is_skipped(fake_book):
    view = reporting.book([holding(STOCK_A, "MISSING", 1000.0)], {}, TODAY)
    assert view["n_stocks"] == 0


# ------------------------------------------------------------------ alerts

def test_an_unknown_date_does_not_fire_an_alert(fake_book):
    """A gap in Yahoo is not an event in the book. It belongs on the page,
    where it can be read in context, not in a notification that arrives every
    morning saying the same nothing."""
    view = reporting.book(
        [holding(STOCK_A, "AAA", 1000.0)],
        cache(AAA={"history": [quarter("2026-07-30", 1.0, 1.0, 0.0)]}), TODAY)
    assert reporting.alerts(view) == []


def test_a_print_inside_the_week_is_announced_once(fake_book):
    when = TODAY + dt.timedelta(days=3)
    view = reporting.book(
        [holding(STOCK_A, "AAA", 1000.0, name="Alpha")],
        cache(AAA={"next": {"date": str(when), "eps_estimate": 2.5}}), TODAY)
    [alert] = reporting.alerts(view)
    assert "in 3 days" in alert["title"]
    assert alert["level"] == "info"


def test_a_fresh_miss_is_a_warning_and_an_old_one_is_silence(fake_book):
    fresh = TODAY - dt.timedelta(days=2)
    stale = TODAY - dt.timedelta(days=C.EARNINGS_SOON_DAYS + 1)

    def view_at(date):
        return reporting.book(
            [holding(STOCK_A, "AAA", 1000.0, name="Alpha")],
            cache(AAA={"history": [quarter(str(date), 2.0, 1.0, -50.0)]}),
            TODAY)

    [alert] = reporting.alerts(view_at(fresh))
    assert alert["level"] == "warning" and "missed" in alert["title"]
    # An old miss has had a quarter to be acted on. Re-announcing it every
    # morning is the thing this board exists not to do.
    assert reporting.alerts(view_at(stale)) == []
