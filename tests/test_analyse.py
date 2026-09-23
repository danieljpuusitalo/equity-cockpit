"""Offline tests. No network, no Notion, no Nordnet folder.

Every case here is a real string from the Equity Log or a real row from the
Nordnet export, including the two that produced false alerts on the first
live run. A test that isn't about something that actually broke is decoration.
"""
import sys
import json
import pathlib
import datetime as dt

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import config as C        # noqa: E402
import analyse            # noqa: E402
import sources            # noqa: E402
import render             # noqa: E402
import notify             # noqa: E402
import cockpit            # noqa: E402


# ------------------------------------------------------------ trigger parser

def test_usd_price_level():
    assert analyse.parse_trigger(
        "price below USD 285 (~19x 2027E) does the same") == (285.0, "below")


def test_sek_price_level():
    assert analyse.parse_trigger(
        "Buy zone only if forced selling takes it below SEK 185.") == (185.0, "below")


def test_tilde_dollar():
    """VST: 'Price below ~$120' - the tilde used to defeat the match."""
    assert analyse.parse_trigger(
        "Price below ~$120 (FCFbG yield >11%) moves it to Tier 1.") == (120.0, "below")


def test_tilde_no_currency():
    assert analyse.parse_trigger("Under ~220 the add question reopens.") == (220.0, "below")


def test_pence_with_thousands_separator():
    assert analyse.parse_trigger("Price below 3,700p does the same.") == (3700.0, "below")


def test_millions_are_not_a_price():
    """Talenom: 'net debt below EUR 70M' fired a false CRITICAL on run one."""
    assert analyse.parse_trigger(
        "net debt below EUR 70M or the disposal closing at book") == (None, None)


def test_billions_are_not_a_price():
    """Take-Two: 'a reguide below $8bn' likewise."""
    assert analyse.parse_trigger(
        "or a reguide below $8bn, breaks the FY27 model") == (None, None)


def test_percentages_are_not_a_price():
    assert analyse.parse_trigger("cRPO growth under 12% breaks the case") == (None, None)


def test_multiples_are_not_a_price():
    assert analyse.parse_trigger("Leverage below 3.0x on a reported quarter") == (None, None)


def test_reference_band_rejects_implausible_level():
    """Even if the prose parses, a level nowhere near the price is not a price."""
    assert analyse.parse_trigger("below 70", reference=1.22) == (None, None)
    assert analyse.parse_trigger("below 70", reference=80.0) == (70.0, "below")


def test_empty_trigger():
    assert analyse.parse_trigger(None) == (None, None)
    assert analyse.parse_trigger("") == (None, None)


# ------------------------------------------------------------- Nordnet parse

def test_finnish_decimal():
    assert sources._num("1 211,5") == 1211.5
    assert sources._num("13,45") == 13.45
    assert sources._num("1\xa0211,5") == 1211.5


def test_blank_and_dash_are_none():
    assert sources._num("") is None
    assert sources._num("-") is None
    assert sources._num(None) is None


# These tests used to assert against the real ACCOUNTS and YAHOO maps, which
# put live account numbers and ISINs into a committable file and meant the
# suite could only pass on the one machine that had the real book. Fixture
# identifiers fix both: the test now checks the aggregation logic, which is
# what it was ever about.
FAKE_ACCT, FAKE_ACCT_2 = "11111111", "22222222"
FAKE_ISIN, FAKE_ISIN_2 = "XX0000000001", "XX0000000002"


@pytest.fixture
def fake_book(monkeypatch):
    monkeypatch.setattr(C, "ACCOUNTS", {FAKE_ACCT: "ACC1", FAKE_ACCT_2: "ACC2"})
    monkeypatch.setattr(C, "YAHOO", {FAKE_ISIN: "AAA", FAKE_ISIN_2: "BBB"})


def test_positions_aggregate_lots(fake_book):
    lots = [
        {"isin": FAKE_ISIN, "account_no": FAKE_ACCT, "name": "Acme",
         "tunnus": "AAA", "ccy": "USD", "units": 3, "cost_eur": 900.0,
         "nordnet_mv_eur": 1100.0, "bought": "2026-01-05", "exported": "2026-09-10",
         "source_file": "a.csv"},
        {"isin": FAKE_ISIN, "account_no": FAKE_ACCT, "name": "Acme",
         "tunnus": "AAA", "ccy": "USD", "units": 2, "cost_eur": 700.0,
         "nordnet_mv_eur": 733.0, "bought": "2025-11-02", "exported": "2026-09-10",
         "source_file": "a.csv"},
    ]
    [pos] = sources.positions(lots)
    assert pos["units"] == 5
    assert pos["cost_eur"] == 1600.0
    assert pos["nordnet_mv_eur"] == 1833.0
    assert pos["lots"] == 2
    assert pos["first_bought"] == "2025-11-02"     # earliest, not first seen
    assert pos["account"] == "ACC1"
    assert pos["yahoo"] == "AAA"


def test_same_isin_two_accounts_stays_separate(fake_book):
    base = {"isin": FAKE_ISIN, "name": "Acme", "tunnus": "AAA", "ccy": "EUR",
            "units": 1, "cost_eur": 10.0, "nordnet_mv_eur": 11.0,
            "bought": "2026-01-01", "exported": "2026-09-10", "source_file": "a.csv"}
    rows = sources.positions([dict(base, account_no=FAKE_ACCT),
                              dict(base, account_no=FAKE_ACCT_2)])
    assert len(rows) == 2
    assert {r["account"] for r in rows} == {"ACC1", "ACC2"}


# -------------------------------------------------------------- the join

def _holding(**kw):
    base = {"isin": "X", "account_no": FAKE_ACCT, "account": "ACC1",
            "name": "N", "tunnus": "MSFT", "ccy": "USD", "units": 10,
            "cost_eur": 1000.0, "nordnet_mv_eur": 1200.0, "lots": 1,
            "first_bought": "2026-01-01", "exported": "2026-09-10",
            "bucket": "US software", "yahoo": "MSFT"}
    base.update(kw)
    return base


def test_unpriced_position_falls_back_to_nordnet_value():
    [row] = analyse.value_holdings([_holding(yahoo=None)], {}, {"USD": 0.86})
    assert row["stale"] is True
    assert row["value_eur"] == 1200.0                 # not dropped, not zero
    assert row["stale_reason"] == "no public feed"


def test_priced_position_uses_live_price_and_fx():
    quotes = {"MSFT": {"price": 100.0, "prev_close": 98.0,
                       "year_high": 120.0, "year_low": 80.0, "currency": "USD"}}
    [row] = analyse.value_holdings([_holding()], quotes, {"USD": 0.5})
    assert row["value_eur"] == 500.0                  # 10 units * 100 * 0.5
    assert row["pl_eur"] == -500.0
    assert row["off_high"] == -16.7


def test_price_sanity_flags_a_bad_mapping():
    """The WDEF case: live price implies a value Nordnet never agreed with."""
    quotes = {"MSFT": {"price": 100.0, "prev_close": 100.0,
                       "year_high": None, "year_low": None, "currency": "USD"}}
    rows = analyse.value_holdings([_holding(nordnet_mv_eur=500.0)], quotes, {"USD": 1.0})
    [finding] = analyse.price_sanity(rows)
    assert finding["divergence_pct"] == 100.0


def test_price_sanity_passes_a_good_mapping():
    quotes = {"MSFT": {"price": 100.0, "prev_close": 100.0,
                       "year_high": None, "year_low": None, "currency": "USD"}}
    rows = analyse.value_holdings([_holding(nordnet_mv_eur=1010.0)], quotes, {"USD": 1.0})
    assert analyse.price_sanity(rows) == []
    assert rows[0]["vs_nordnet_pct"] == -1.0


def test_decay_is_measured_against_the_frozen_board_number():
    rows = [{"Ticker": "VST", "Company": "Vistra", "Verdict": "Watch",
             "Tier": "Tier 2 - Watch", "Held": "Not held", "Currency": "USD",
             "Price at eval": 135.6, "Target": 165, "Last evaluated": "2026-09-01",
             "Next check": "2026-11-05", "Trigger": "Price below ~$120 moves it to Tier 1."}]
    quotes = {"VST": {"price": 148.38, "prev_close": 147.0,
                      "year_high": None, "year_low": None, "currency": "USD"}}
    [item] = analyse.join_watchlist(rows, quotes, [])
    assert item["upside_at_eval"] == 21.7             # what the board still says
    assert item["upside_now"] == 11.2                 # what is actually true
    assert item["upside_decay_pts"] == -10.5
    assert item["trigger_level"] == 120.0
    assert item["trigger_hit"] is False


def test_reconcile_catches_a_real_disagreement():
    watchlist = [{"ticker": "ALMA.HE", "held_notion": "Not held", "held_actual": "OST"}]
    [issue] = analyse.reconcile(watchlist)
    assert issue["kind"] == "mismatch"


def test_reconcile_accepts_agreement():
    assert analyse.reconcile(
        [{"ticker": "CRM", "held_notion": "OST", "held_actual": "OST"},
         {"ticker": "LULU", "held_notion": "Not held", "held_actual": "Not held"}]) == []


def test_reconcile_flags_a_blank_held_field():
    [issue] = analyse.reconcile(
        [{"ticker": "GOOGL", "held_notion": None, "held_actual": "Not held"}])
    assert issue["kind"] == "blank"


# ------------------------------------------------------- annualised return

def _lot(isin, account, bought, cost, units=1.0):
    return {"isin": isin, "account_no": account, "name": "x", "tunnus": isin,
            "ccy": "EUR", "units": units, "cost_eur": cost,
            "nordnet_mv_eur": cost, "bought": bought, "exported": "2026-09-10",
            "source_file": "t.csv"}


def test_xirr_doubling_over_one_year():
    """100 out, 200 back exactly a year later is +100%/yr. If this drifts the
    bisection bracket or the day-count has been changed."""
    rate = analyse.xirr([(dt.date(2025, 1, 1), -100.0),
                         (dt.date(2026, 1, 1), 200.0)])
    assert rate is not None and abs(rate - 1.0) < 0.01


def test_xirr_flat_is_zero():
    rate = analyse.xirr([(dt.date(2024, 1, 1), -1000.0),
                         (dt.date(2026, 1, 1), 1000.0)])
    assert rate is not None and abs(rate) < 0.001


def test_xirr_needs_a_sign_change():
    """Two outflows and no return value has no root - None, never a number."""
    assert analyse.xirr([(dt.date(2025, 1, 1), -100.0),
                         (dt.date(2026, 1, 1), -100.0)]) is None


def test_short_hold_is_suppressed_not_annualised():
    """The live-book bug: a 3.4% gain held a weighted 25 days annualised to
    55%/yr and was displayed. It must report a reason instead of a number."""
    today = dt.date(2026, 9, 13)
    holdings = [{"isin": "A", "account_no": "1", "yahoo": "FUND",
                 "tunnus": "FUND", "value_eur": 148.0}]
    lots = [_lot("A", "1", "2026-08-30", 143.0)]
    book = analyse.attach_returns(holdings, lots, today=today)
    assert holdings[0]["irr_pct"] is None
    assert "too short to annualise" in holdings[0]["irr_note"]
    assert book["by_symbol"]["FUND"]["irr_pct"] is None


def test_weighted_guard_beats_first_date_guard():
    """First lot is 2 years old, but 97% of the money went in last week. A
    guard on the first purchase date would let this through; the cost-weighted
    one must not."""
    today = dt.date(2026, 9, 13)
    holdings = [{"isin": "B", "account_no": "1", "yahoo": "SAVE",
                 "tunnus": "SAVE", "value_eur": 5200.0}]
    lots = [_lot("B", "1", "2024-09-01", 100.0),
            _lot("B", "1", "2026-09-06", 5000.0)]
    analyse.attach_returns(holdings, lots, today=today)
    assert holdings[0]["irr_pct"] is None
    assert holdings[0]["holding_days"] < 90


def test_long_hold_reports_a_number():
    today = dt.date(2026, 9, 13)
    holdings = [{"isin": "C", "account_no": "1", "yahoo": "MSFT",
                 "tunnus": "MSFT", "value_eur": 2000.0}]
    lots = [_lot("C", "1", "2024-09-13", 1000.0)]
    analyse.attach_returns(holdings, lots, today=today)
    assert holdings[0]["irr_pct"] is not None
    assert 38 < holdings[0]["irr_pct"] < 44        # doubled over two years


def test_symbol_folds_both_custody_accounts():
    """Same symbol in two accounts is ONE line on the page, so its return is
    computed over the combined flows - not averaged from two IRRs."""
    today = dt.date(2026, 9, 13)
    holdings = [{"isin": "D", "account_no": "1", "yahoo": "DUP",
                 "tunnus": "DUP", "value_eur": 1000.0},
                {"isin": "D", "account_no": "2", "yahoo": "DUP",
                 "tunnus": "DUP", "value_eur": 1000.0}]
    lots = [_lot("D", "1", "2024-09-13", 500.0),
            _lot("D", "2", "2024-09-13", 500.0)]
    book = analyse.attach_returns(holdings, lots, today=today)
    assert len(book["by_symbol"]) == 1
    combined = book["by_symbol"]["DUP"]
    assert combined["irr_pct"] is not None
    assert 38 < combined["irr_pct"] < 44


# ------------------------------------------------- live multiples vs recorded

def _wl(**kw):
    base = {"ticker": "HAYPP.ST", "yahoo": "HAYPP.ST", "pe": 275.0,
            "fwd_pe": 40.0, "price_now": 100.0, "last_eval": "2026-08-20",
            "target": 130.0, "upside_now": 30.0}
    base.update(kw)
    return base


def _funda(symbol="HAYPP.ST", fetched="2026-09-18", **fields):
    return {symbol: {"fetched": fetched, "fields": dict(fields) if fields else None}}


def test_drift_is_measured_from_the_recorded_figure():
    """HAYPP.ST on the live board: 275 written down, 587 today. The drift is
    live/recorded - 1, so the recorded figure is the base and the sentence has
    to be phrased from the live side."""
    assert analyse._drift(275.0, 587.0) == 113.5
    # Deliberately asserting the asymmetry, because the first version of the
    # alert wording assumed it was symmetric and printed the wrong claim.
    assert analyse._drift(587.0, 275.0) == -53.2


def test_drift_needs_two_real_positive_numbers():
    for recorded, live in ((None, 20.0), (20.0, None), (0, 20.0),
                           (20.0, 0), (-5.0, 20.0), (20.0, -5.0)):
        assert analyse._drift(recorded, live) is None


def test_live_multiples_arrive_beside_the_recorded_ones_never_on_top():
    """The recorded number is a point-in-time record. Overwriting it would
    destroy the only thing the section exists to show."""
    [item] = analyse.attach_fundamentals(
        [_wl()], _funda(pe=587.0, fwd_pe=30.0, street_target=150.0))
    assert item["pe"] == 275.0                  # untouched
    assert item["live"]["pe"] == 587.0
    assert item["live"]["asof"] == "2026-09-18"
    assert item["pe_drift_pct"] == 113.5
    assert item["fwd_pe_drift_pct"] == -25.0


def test_street_upside_uses_the_same_base_as_yours():
    """Both are measured off today's price, or the two numbers printed side by
    side would not be comparable."""
    [item] = analyse.attach_fundamentals([_wl()], _funda(street_target=150.0))
    assert item["street_upside_pct"] == 50.0    # 150 / 100 - 1


def test_a_symbol_yahoo_knew_nothing_about_gets_no_live_block():
    """Funds answer with nothing usable. That is the expected case, and it must
    read as absent rather than as zero."""
    [item] = analyse.attach_fundamentals([_wl(ticker="XAIX", yahoo="XAIX.DE")],
                                         _funda("XAIX.DE"))
    assert item["live"] is None
    assert item["pe_drift_pct"] is None
    assert item["street_upside_pct"] is None


def test_unmapped_row_is_not_an_error():
    [item] = analyse.attach_fundamentals([_wl(yahoo=None)], {})
    assert item["live"] is None


def _stale_alerts(watchlist):
    return [a for a in analyse.alerts(watchlist, [], {"problems": []})
            if a["key"].startswith("multiple-stale")]


def test_stale_multiple_alert_is_phrased_from_the_live_side():
    watchlist = analyse.attach_fundamentals([_wl()], _funda(pe=587.0))
    [flag] = _stale_alerts(watchlist)
    assert flag["title"] == "HAYPP.ST: today's P/E is 114% above the board's"
    assert "275" in flag["detail"] and "587" in flag["detail"]


def test_stale_multiple_alert_names_the_symbol_so_the_pane_can_find_it():
    """The thesis pane joins flags to a name by matching the symbol string in
    key + title. An aggregate alert would never reach a pane."""
    watchlist = analyse.attach_fundamentals([_wl()], _funda(pe=587.0))
    [flag] = _stale_alerts(watchlist)
    assert "HAYPP.ST" in flag["key"] + " " + flag["title"]


def test_a_multiple_inside_the_band_raises_nothing():
    watchlist = analyse.attach_fundamentals([_wl(pe=23.6)], _funda(pe=22.9))
    assert _stale_alerts(watchlist) == []


def test_undated_board_figure_does_not_print_a_none():
    watchlist = analyse.attach_fundamentals([_wl(last_eval=None)], _funda(pe=587.0))
    [flag] = _stale_alerts(watchlist)
    assert "None" not in flag["detail"]


# ------------------------------------------------------- fund allocation drift

def _cover(ticker="EXUS.DE", weight=9.3, target=5.0, drift=4.3):
    """One fund row shaped the way coverage() emits it. Note `covered: True` -
    that is the point of these tests. A breaching fund is being monitored, so it
    is correctly absent from the coverage alert, and for a while that meant the
    breach was announced nowhere at all."""
    return {"n_uncovered": 0, "pct_uncovered": 0.0, "rows": [
        {"ticker": ticker, "klass": "fund", "value_eur": 3724.0,
         "weight_pct": weight, "target_weight_pct": target, "drift_pts": drift,
         "covered": True, "gap": "x"}]}


def _drift_alerts(cover):
    return [a for a in analyse.alerts([], [], {"problems": []}, cover)
            if a["key"].startswith("weight-drift")]


def test_a_fund_outside_its_band_alerts_even_though_it_is_covered():
    [flag] = _drift_alerts(_cover())
    assert flag["title"] == "EXUS.DE is 4.3 pts above its 5% target weight"


def test_a_fund_below_its_band_says_below():
    [flag] = _drift_alerts(_cover(weight=0.4, target=5.0, drift=-4.6))
    assert "4.6 pts below" in flag["title"]


def test_a_fund_inside_the_band_raises_nothing():
    assert _drift_alerts(_cover(weight=7.1, target=5.0, drift=2.1)) == []


def test_the_band_edge_is_not_a_breach():
    """3.0 pts is the band, not a violation of it - the same boundary coverage()
    uses, so the rail and the alert list cannot disagree about one fund."""
    assert _drift_alerts(_cover(drift=3.0)) == []


def test_a_fund_with_no_target_produces_no_drift_alert():
    """It is the coverage alert's business, not this one's. Two warnings for one
    missing number is how a list gets muted."""
    cover = _cover()
    cover["rows"][0].update(target_weight_pct=None, drift_pts=None, covered=False)
    assert _drift_alerts(cover) == []


def test_drift_alert_names_the_symbol_so_the_pane_can_find_it():
    [flag] = _drift_alerts(_cover())
    assert "EXUS.DE" in flag["key"] + " " + flag["title"]


def test_drift_key_moves_only_when_the_breach_moves_a_full_point():
    """Quantised, so re-reading the same price on Tuesday is not a new alert."""
    same = [_drift_alerts(_cover(drift=d))[0]["key"] for d in (4.3, 4.4)]
    assert same[0] == same[1]
    assert _drift_alerts(_cover(drift=5.4))[0]["key"] != same[0]


def test_alerts_still_run_with_no_coverage_block_at_all():
    assert analyse.alerts([], [], {"problems": []}) == [] or True
    assert _drift_alerts(None) == []


# ------------------------------------------------- placeholder target weights
#
# A target weight can be a written policy or a number a rule parked in the
# field so the allocation columns have something to draw. The whole point of
# `target_basis` is that those two must not behave alike, and every test below
# pins one place where they diverge. This is the repo's signature bug class
# pointed at itself: a derived status claiming more than it means.

def _book(isin="IE00B4L5Y983", value=4000.0, rest=36000.0):
    """One fund plus one anonymous makeweight, so the fund's weight is 10%."""
    return [{"isin": isin, "yahoo": "FUND.AS", "tunnus": "FUND",
             "name": "A fund", "account": "OST", "value_eur": value},
            {"isin": "ZZ0000000000", "yahoo": "OTHER.AS", "tunnus": "OTHER",
             "name": "Other", "account": "OST", "value_eur": rest}]


def _as_fund(monkeypatch, isin, target, basis=None):
    monkeypatch.setitem(analyse.C.ASSET_CLASS, isin, "fund")
    monkeypatch.setitem(analyse.C.ASSET_CLASS, "ZZ0000000000", "stock")
    monkeypatch.setitem(analyse.C.TARGET_WEIGHT, isin, target)
    monkeypatch.setitem(analyse.C.TARGET_BASIS, isin, basis or "policy")


def _fund_row(monkeypatch, target, basis=None, value=4000.0):
    isin = "IE00B4L5Y983"
    _as_fund(monkeypatch, isin, target, basis)
    rows = analyse.coverage(_book(isin, value), [])["rows"]
    return next(r for r in rows if r["isin"] == isin)


def test_a_placeholder_target_still_draws_its_drift(monkeypatch):
    """The number and its drift are the whole reason to park one - without
    them the allocation columns are empty and the feature is invisible."""
    row = _fund_row(monkeypatch, 7.0, "placeholder")
    assert row["target_weight_pct"] == 7.0
    assert row["drift_pts"] == 3.0          # 10% weight - 7% target


def test_a_placeholder_target_does_not_make_a_holding_covered(monkeypatch):
    """`covered` is what the headline counts as monitored. A placeholder is
    arithmetic, not a decision, and must not clear the coverage warning."""
    row = _fund_row(monkeypatch, 7.0, "placeholder")
    assert row["covered"] is False
    assert "placeholder" in row["gap"]


def test_a_written_policy_at_the_same_number_does_make_it_covered(monkeypatch):
    """The contrast is the test. Same weight, same target, same drift - the
    only difference is the basis, and it has to be the only difference that
    matters."""
    placeheld = _fund_row(monkeypatch, 7.0, "placeholder")
    written = _fund_row(monkeypatch, 7.0, "policy")
    assert (placeheld["target_weight_pct"], placeheld["drift_pts"]) \
        == (written["target_weight_pct"], written["drift_pts"])
    assert written["covered"] is True and placeheld["covered"] is False


def test_the_basis_reaches_the_page_so_the_number_can_be_labelled(monkeypatch):
    """The template keys its marker off this field. If coverage() stops
    emitting it the page silently renders a placeholder as a policy."""
    assert _fund_row(monkeypatch, 7.0, "placeholder")["target_basis"] \
        == "placeholder"
    assert _fund_row(monkeypatch, 7.0, "policy")["target_basis"] == "policy"


def test_no_target_carries_no_basis_at_all(monkeypatch):
    """Three states, not two. A null target is neither a policy nor a
    placeholder, and claiming either would be a fourth bug of this shape."""
    row = _fund_row(monkeypatch, None)
    assert row["target_basis"] is None
    assert row["gap"] == "no target weight set"


def test_a_breaching_placeholder_never_reaches_telegram():
    """An alert claims something needs attention. 'You have drifted from a
    number nobody chose' is not that claim, however large the drift."""
    cover = _cover(drift=9.9)
    cover["rows"][0]["target_basis"] = "placeholder"
    assert _drift_alerts(cover) == []


def test_a_breaching_written_policy_still_does():
    """The guard above must key on the basis, not disable the alert."""
    cover = _cover(drift=9.9)
    cover["rows"][0]["target_basis"] = "policy"
    assert len(_drift_alerts(cover)) == 1
    # And a row from before target_basis existed reads as a policy, because
    # every target written by hand until now was one.
    assert len(_drift_alerts(_cover(drift=9.9))) == 1


# ----------------------------------------------------------- .info shaping

def _info(**kw):
    base = {"trailingPE": 22.9, "forwardPE": 13.3, "priceToBook": 7.2,
            "marketCap": 4.4e11, "trailingEps": 6.39, "beta": 1.73}
    base.update(kw)
    return base


def test_net_debt_not_gross_debt():
    """Nokia carries more cash than debt. A gross-debt ratio would report a
    net-cash balance sheet as levered."""
    out = sources._shape_info(_info(totalDebt=5e9, totalCash=9e9, ebitda=2e9))
    assert out["net_debt_ebitda"] == -2.0


def test_no_ebitda_means_no_ratio_not_a_division_by_zero():
    out = sources._shape_info(_info(totalDebt=5e9, totalCash=1e9, ebitda=0))
    assert out["net_debt_ebitda"] is None


def test_a_lone_pe_on_an_etf_is_rejected():
    """IMAE.AS returns a trailing P/E and almost nothing else. That figure is a
    portfolio-weighted aggregate wearing a company's clothes."""
    assert sources._shape_info({"trailingPE": 18.4}) is None
    assert sources._shape_info({}) is None


def test_ratios_arrive_as_percentages():
    out = sources._shape_info(_info(returnOnEquity=0.41192, profitMargins=0.2636))
    assert round(out["roe_pct"], 2) == 41.19
    assert round(out["margin_pct"], 2) == 26.36


def test_a_zero_ratio_survives_the_percent_conversion():
    """profitMargins of exactly 0 is a real reading, not a missing one."""
    out = sources._shape_info(_info(profitMargins=0.0))
    assert out["margin_pct"] == 0.0


def test_nan_is_treated_as_absent():
    out = sources._shape_info(_info(trailingPE=float("nan")))
    assert out["pe"] is None


def test_the_streets_verdict_is_never_carried():
    """A target you can hold your own up against is evidence; a verb telling
    you what to do is somebody else making the decision."""
    out = sources._shape_info(_info(recommendationKey="buy", targetMeanPrice=239.0))
    assert out["street_target"] == 239.0
    assert "recommendationKey" not in out
    assert not any("recommend" in k for k in out)


# ---------------------------------------- the broker/board Held join (2026-09-18)

def _pos(tunnus, yahoo, account="OST", units=5.0):
    return {"tunnus": tunnus, "yahoo": yahoo, "account": account, "units": units}


def _row(ticker, held="OST"):
    return {"Ticker": ticker, "Company": ticker, "Verdict": "Watch",
            "Tier": "Tier 2 - Watch", "Held": held, "Currency": "EUR",
            "Price at eval": 100.0, "Target": 120.0,
            "Last evaluated": "2026-09-18", "Next check": None, "Trigger": None}


def test_a_holding_is_found_when_the_two_vendors_punctuate_it_differently():
    """Nordnet writes 'ERIC B', Yahoo writes 'ERIC-B.ST'. Stripping the suffix
    gives 'ERIC-B', which is not 'ERIC B', so the position went missing and the
    board was accused of claiming a holding it really had."""
    holdings = [_pos("ERIC B", "ERIC-B.ST", account="OST", units=3.0)]
    [item] = analyse.join_watchlist([_row("ERIC-B.ST")], {}, holdings)
    assert item["held_actual"] == "OST"
    assert item["held_units"] == 3.0
    assert analyse.reconcile([item]) == []


def test_the_stem_match_still_resolves():
    """ADMCM.HE against a Nordnet 'ADMCM' worked before this change and has to
    keep working - the Yahoo key is an addition, not a replacement."""
    holdings = [_pos("ADMCM", "ADMCM.HE", account="OST", units=54.0)]
    [item] = analyse.join_watchlist([_row("ADMCM.HE")], {}, holdings)
    assert item["held_actual"] == "OST"


def test_a_name_the_broker_does_not_carry_is_still_not_held():
    """The fix must not turn every row into a holding: AD.AS is genuinely
    absent from the export, and that disagreement is the alert's whole job."""
    holdings = [_pos("MSFT", "MSFT")]
    [item] = analyse.join_watchlist([_row("AD.AS")], {}, holdings)
    assert item["held_actual"] == "Not held"
    assert item["held_units"] is None
    assert len(analyse.reconcile([item])) == 1


def test_a_holding_with_no_yahoo_symbol_does_not_poison_the_index():
    """The three Nordnet index funds carry yahoo=None. A None key would collide
    them all onto one entry and make the next lookup return a random fund."""
    holdings = [_pos("Nordnet Suomi Indeksi", None),
                _pos("Nordnet Norge Indeks", None),
                _pos("MSFT", "MSFT")]
    index = analyse._held_index(holdings)
    assert None not in index
    assert index["MSFT"]["tunnus"] == "MSFT"
    assert index["NORDNET SUOMI INDEKSI"]["tunnus"] == "Nordnet Suomi Indeksi"


# ------------------------------- a thin .info must not blank a good cache

@pytest.fixture
def cache_at(tmp_path, monkeypatch):
    """Point the fundamentals cache at a scratch file and seed it."""
    def seed(symbols):
        path = tmp_path / "fundamentals.json"
        path.write_text(json.dumps({"fetched": "2026-09-18",
                                    "symbols": symbols}), encoding="utf-8")
        monkeypatch.setattr(C, "FUNDAMENTALS_CACHE", path)
        return path
    return seed


def _answers(payload):
    """Make Yahoo return `payload` for any symbol, without touching network."""
    return lambda symbol, *a, **k: payload


def test_a_thin_info_keeps_the_last_good_multiples(cache_at, monkeypatch):
    """yfinance returns a near-empty dict on a rate limit just as readily as it
    does for a fund, and `_info` only returns None when the dict is empty
    outright. Overwriting a stock's cached multiples with null would blank the
    board with nothing in `problems` - indistinguishable from the company
    having stopped reporting."""
    good = sources._shape_info(_info())
    cache_at({"NOKIA.HE": {"fetched": "2026-09-18", "fields": good}})
    monkeypatch.setattr(sources, "_info", _answers({"sector": "Technology"}))

    out, problems, pulled = sources.fundamentals(
        ["NOKIA.HE"], today=dt.date(2026, 9, 19))

    assert out["NOKIA.HE"]["fields"] == good, "the good answer was destroyed"
    assert out["NOKIA.HE"]["fetched"] == "2026-09-18", "stale date must survive"
    assert "NOKIA.HE" in problems, "a silent blank is the bug"
    assert pulled == 0


def test_a_fund_is_still_recorded_as_an_explicit_miss(cache_at, monkeypatch):
    """The null-write branch exists so tomorrow's run does not re-ask a fund
    every single day. A symbol that never produced fields keeps that."""
    cache_at({"IMAE.AS": {"fetched": "2026-09-18", "fields": None}})
    monkeypatch.setattr(sources, "_info", _answers({"trailingPE": 18.4}))

    out, problems, pulled = sources.fundamentals(
        ["IMAE.AS"], today=dt.date(2026, 9, 19))

    assert out["IMAE.AS"] == {"fetched": "2026-09-19", "fields": None}
    assert problems == {}
    assert pulled == 1


def test_a_total_failure_still_falls_back_to_the_cache(cache_at, monkeypatch):
    """The pre-existing contract, pinned so this change does not move it."""
    good = sources._shape_info(_info())
    cache_at({"NOKIA.HE": {"fetched": "2026-09-18", "fields": good}})
    monkeypatch.setattr(sources, "_info", _answers(None))

    out, problems, _ = sources.fundamentals(
        ["NOKIA.HE"], today=dt.date(2026, 9, 19))

    assert out["NOKIA.HE"]["fields"] == good
    assert "NOKIA.HE" in problems


# ----------------------------------- the intraday refresh asks for nothing
#
# `cached_only` runs 26 times a day. Every one of these tests exists because a
# refresh that quietly fetched, or quietly wrote, would be indistinguishable
# from one that did not - until the rate limit, or a restamped cache file that
# tells tomorrow's full run it has nothing to fetch.

def _explode(*a, **k):
    raise AssertionError("the refresh reached the network")


def test_a_refresh_asks_yahoo_for_no_multiples(cache_at, monkeypatch):
    good = sources._shape_info(_info())
    cache_at({"NOKIA.HE": {"fetched": "2026-09-18", "fields": good}})
    monkeypatch.setattr(sources, "_info", _explode)

    out, problems, pulled = sources.fundamentals(
        ["NOKIA.HE"], today=dt.date(2026, 9, 19), cached_only=True)

    assert out["NOKIA.HE"]["fields"] == good
    assert pulled == 0 and problems == {}


def test_a_refresh_does_not_restamp_the_fundamentals_cache(cache_at, monkeypatch):
    """The `fetched` dates in this file are what tomorrow's full run reads to
    decide whether to fetch. A read-only pass that rewrote them would talk the
    full run out of the one fetch that matters."""
    path = cache_at({"NOKIA.HE": {"fetched": "2026-09-18",
                                  "fields": sources._shape_info(_info())}})
    monkeypatch.setattr(sources, "_info", _explode)
    before = path.read_bytes()

    sources.fundamentals(["NOKIA.HE"], today=dt.date(2026, 9, 19),
                         cached_only=True)

    assert path.read_bytes() == before, "a read-only pass wrote to disk"


def test_a_refresh_serves_yesterdays_bars_without_fetching(tmp_path, monkeypatch):
    """Daily bars do not change between 10:00 and 10:30. Paying for them every
    half hour would buy nothing and spend the rate limit the prices need."""
    bars = [["2026-09-18", 4.1, 4.3, 4.0, 4.2, 1_000_000]]
    path = tmp_path / "price-history.json"
    path.write_text(json.dumps({"fetched": "2026-09-18", "symbols": {
        "NOKIA.HE": {"fetched": "2026-09-18", "bars": bars}}}), encoding="utf-8")
    monkeypatch.setattr(C, "PRICE_HISTORY_CACHE", path)
    monkeypatch.setattr(sources, "_bars", _explode)
    before = path.read_bytes()

    out, _, pulled = sources.price_history(
        ["NOKIA.HE"], today=dt.date(2026, 9, 19), cached_only=True)

    assert out["NOKIA.HE"]["bars"] == bars
    assert pulled == 0
    assert path.read_bytes() == before, "a read-only pass wrote to disk"


def test_a_refresh_never_asks_notion_even_holding_a_token(tmp_path, monkeypatch):
    """A token existing is not a reason to spend it. The thesis has not been
    rewritten since breakfast; only the price it is held against has moved."""
    path = tmp_path / "equity-log.json"
    path.write_text(json.dumps({"fetched": "2026-09-19T07:40:00",
                                "rows": [{"Ticker": "NOKIA.HE"}]}),
                    encoding="utf-8")
    monkeypatch.setattr(C, "EQUITY_LOG_CACHE", path)
    monkeypatch.setattr(sources, "notion_token", lambda: "secret_live_token")
    monkeypatch.setattr(sources, "_equity_log_live", _explode)

    rows, meta = sources.equity_log(cached_only=True)

    assert rows == [{"Ticker": "NOKIA.HE"}]
    assert meta["mode"] == "cache" and meta["problem"] is None


def test_a_refresh_with_no_cached_log_says_so(tmp_path, monkeypatch):
    """An empty board renders as a book with no thesis anywhere and no
    complaint - the page would look monitored and be nothing of the kind."""
    monkeypatch.setattr(C, "EQUITY_LOG_CACHE", tmp_path / "missing.json")
    monkeypatch.setattr(sources, "_equity_log_live", _explode)

    rows, meta = sources.equity_log(cached_only=True)

    assert rows == []
    assert "no Equity Log cache" in meta["problem"]


# ------------------------------------------- a feed that answers for nothing

def _health(feeds=()):
    return cockpit.health(0, "2026-09-19", [], [], {"mode": "cache"},
                          None, (), feeds, today=dt.date(2026, 9, 20))


def _feed(asked, resolved, name="composition"):
    return {"name": name, "label": "Fund composition", "asked": asked,
            "resolved": resolved, "detail": "d"}


def test_a_feed_that_answers_for_none_of_them_breaks_the_board():
    """The state the emptied cache produced: read back in refresh mode, every
    fund resolved to nothing, and the page said "All sources fresh"."""
    state = _health([_feed(8, 0)])
    assert state["status"] == "broken"
    assert state["headline"] == "This page may be wrong"
    assert "none of 8" in state["problems"][0]["title"]


def test_one_fund_yahoo_will_not_break_out_is_still_ok():
    """The documented intent this must not overturn: an ordinary vendor gap is
    a coverage figure on the exposure tables, not a fault on the board."""
    assert _health([_feed(8, 7)])["status"] == "ok"
    assert _health([_feed(8, 1)])["status"] == "ok"


def test_a_feed_with_nothing_to_ask_is_not_a_failure():
    """A book with no funds in it asks about none. Zero of zero is silence
    from the caller, not from Yahoo - the same distinction the cache merge
    turns on."""
    assert _health([_feed(0, 0)])["status"] == "ok"


def test_each_silent_feed_is_named_separately():
    state = _health([_feed(8, 0, "composition"), _feed(13, 0, "earnings")])
    assert {p["key"] for p in state["problems"]} == {
        "feed-silent-composition", "feed-silent-earnings"}


def test_the_run_hands_health_every_feed_it_counts_onto_the_page():
    """The defect was not the rule, it was that nothing was wired to it: the
    counts existed in the payload and went nowhere else."""
    import inspect
    body = inspect.getsource(cockpit._cycle)
    assert "mismatches, feeds)" in body
    for name in ('"name": "composition"', '"name": "earnings"',
                 '"name": "fundamentals"'):
        assert name in body, f"{name} is counted but not handed to health"


def test_the_earnings_guard_can_actually_fail():
    """The mutation that exposed it: reading the file instead of its symbols.
    That version returns no leak for any input, which is what it did in
    production while printing a confident 'no funds'."""
    cache = {"fetched": "2026-09-20",
             "symbols": {"MSFT": {}, "XAIX.DE": {}, "NOKIA.HE": {}}}
    assert cockpit.earnings_cache_leaks(cache, {"XAIX.DE", "EXUS.DE"}) == (
        3, ["XAIX.DE"])


def test_the_earnings_guard_counts_symbols_not_envelope_keys():
    cache = {"fetched": "2026-09-20", "symbols": {"MSFT": {}, "AMZN": {}}}
    n, leaked = cockpit.earnings_cache_leaks(cache, {"XAIX.DE"})
    assert (n, leaked) == (2, [])       # not 2-because-fetched-and-symbols


def test_the_earnings_guard_survives_a_cache_that_is_not_there_yet():
    assert cockpit.earnings_cache_leaks({}, {"XAIX.DE"}) == (0, [])
    assert cockpit.earnings_cache_leaks(None, {"XAIX.DE"}) == (0, [])


# --------------------------------------------- caches merge, never replace

def _cache_file(tmp_path, symbols):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"fetched": "2026-09-19", "symbols": symbols}),
                    encoding="utf-8")
    return path


def _symbols(path):
    return json.loads(path.read_text(encoding="utf-8"))["symbols"]


def test_a_narrower_call_does_not_delete_what_it_did_not_ask_about(tmp_path):
    """The defect this exists for: `out` is built from the symbols the caller
    named, and writing it as the whole file made the question the contents."""
    path = _cache_file(tmp_path, {"AAA": {"fields": 1}, "BBB": {"fields": 2}})
    sources._write_symbol_cache(path, _symbols(path), {"AAA": {"fields": 9}},
                                "2026-09-20")
    assert _symbols(path) == {"AAA": {"fields": 9}, "BBB": {"fields": 2}}


def test_an_empty_result_does_not_write_at_all(tmp_path):
    """A one-stock fake book asks for no funds. That is a question with no
    symbols in it, not a discovery that the funds are gone."""
    path = _cache_file(tmp_path, {"AAA": {"fields": 1}})
    before = path.read_text(encoding="utf-8")
    assert sources._write_symbol_cache(path, {"AAA": {"fields": 1}}, {},
                                       "2026-09-20") is False
    assert path.read_text(encoding="utf-8") == before


def test_fresh_wins_over_stale_for_the_same_symbol(tmp_path):
    path = _cache_file(tmp_path, {"AAA": {"fetched": "old"}})
    sources._write_symbol_cache(path, _symbols(path),
                                {"AAA": {"fetched": "new"}}, "2026-09-20")
    assert _symbols(path)["AAA"]["fetched"] == "new"


def test_the_write_restamps_the_file_date(tmp_path):
    path = _cache_file(tmp_path, {"AAA": {"fields": 1}})
    sources._write_symbol_cache(path, _symbols(path), {"BBB": {"fields": 2}},
                                "2026-09-20")
    assert json.loads(path.read_text(encoding="utf-8"))["fetched"] == "2026-09-20"


def test_a_first_write_needs_no_previous_cache(tmp_path):
    path = tmp_path / "nested" / "cache.json"
    assert sources._write_symbol_cache(path, None, {"AAA": {"fields": 1}},
                                       "2026-09-20") is True
    assert _symbols(path) == {"AAA": {"fields": 1}}


def test_every_symbol_cache_goes_through_the_merge(tmp_path, monkeypatch):
    """Named individually elsewhere; checked as a set here so a fifth cache
    added later cannot quietly reintroduce a full replace."""
    import inspect
    src = inspect.getsource(sources)
    for cache in ("PRICE_HISTORY_CACHE", "FUNDAMENTALS_CACHE",
                  "FUND_COMPOSITION_CACHE", "EARNINGS_CACHE"):
        assert f"_write_symbol_cache(C.{cache}" in src, f"{cache} writes raw"
    # The old shape, verbatim. If it comes back anywhere, this fails.
    assert '"symbols": out}, separators' not in src


# ------------------------------ ...and leaves the daily record alone

@pytest.fixture
def one_position_book(tmp_path, monkeypatch):
    """Every boundary `_cycle` touches, replaced. Nothing here reaches disk or
    network, so what the test observes is purely which side effects fired.

    That sentence was false for a while, and the cost was real. This fixture
    stubs boundaries by NAME, so when the pipeline grew `fund_composition` and
    `earnings` the list silently fell behind, and running `pytest` drove the
    full production run against the production cache files: the fake book has
    no funds, so `fund_composition` was handed an empty symbol list and wrote a
    37-byte `{"symbols":{}}` over the real one. The board lost 48 points of
    sector resolution and its whole reporting calendar, and said it was fresh.

    So the stubs below are no longer the only defence. Every path that points
    into the live state directory is redirected into tmp_path first, which does
    not need to know what the pipeline touches: a fetcher nobody remembered to
    stub can still only write into a directory pytest throws away. Add stubs
    for speed; the redirect is what makes the test safe.

    The redirect found a second leak the moment it was written. It was scoped
    to `config` at first, which missed `cockpit.HEARTBEAT` - so a test run was
    also overwriting `last_run.json`, the file the "hasn't run in N days" check
    reads. Hence the scan below is over modules, not over one module."""
    # Must come before anything imports or calls a fetcher. Found by scanning
    # for Paths that live under C.STATE rather than by listing names, because
    # the failure mode both times was a list that fell behind the code.
    redirected = []
    for mod in (C, cockpit, notify, sources, analyse, render):
        for name in dir(mod):
            path = getattr(mod, name, None)
            if not isinstance(path, pathlib.Path) or C.STATE not in path.parents:
                continue
            monkeypatch.setattr(mod, name, tmp_path / path.name)
            redirected.append(f"{mod.__name__}.{name}")
    assert len(redirected) >= 7, f"state paths not found - guard is dead: {redirected}"
    lot = {"isin": "FI0009000681", "account_no": "1", "name": "Nokia",
           "tunnus": "NOKIA", "ccy": "EUR", "units": 100.0, "cost_eur": 400.0,
           "nordnet_mv_eur": 420.0, "bought": "2024-01-15",
           "exported": "2026-09-19", "source_file": "fake.csv"}
    pos = dict(lot, account="OST", lots=1, first_bought="2024-01-15",
               bucket="Nordics", yahoo="NOKIA.HE")

    monkeypatch.setattr(sources, "nordnet_lots", lambda: ([lot], []))
    monkeypatch.setattr(sources, "positions", lambda lots: [pos])
    monkeypatch.setattr(sources, "export_age_days",
                        lambda lots, today=None: (0, "2026-09-19"))
    monkeypatch.setattr(sources, "equity_log",
                        lambda cached_only=False: ([], {"mode": "cache",
                                                        "age_days": 0,
                                                        "problem": None}))
    monkeypatch.setattr(sources, "fx_rates", lambda: ({"EUR": 1.0}, {}))
    monkeypatch.setattr(sources, "quotes", lambda syms: (
        {"NOKIA.HE": {"price": 4.2, "prev_close": 4.1, "year_high": 5.0,
                      "year_low": 3.0, "currency": "EUR"}}, {}))
    monkeypatch.setattr(sources, "price_history",
                        lambda syms, today=None, cached_only=False: ({}, {}, 0))
    monkeypatch.setattr(sources, "fundamentals",
                        lambda syms, today=None, cached_only=False: ({}, {}, 0))
    monkeypatch.setattr(sources, "fund_composition",
                        lambda syms, today=None, cached_only=False: ({}, {}, 0))
    monkeypatch.setattr(sources, "earnings",
                        lambda syms, today=None, cached_only=False: ({}, {}, 0))
    monkeypatch.setattr(render, "write", lambda data, out_dir=None: ("a", "b"))
    return tmp_path


def test_the_fixture_puts_every_cache_somewhere_pytest_can_throw_away(
        one_position_book):
    """The redirect is the guard; this is the guard on the guard. Deleting the
    loop in the fixture leaves every stub in place and every test still green,
    which is exactly how the first version of this fixture looked."""
    caches = {n: getattr(C, n) for n in dir(C) if n.endswith("_CACHE")
              and isinstance(getattr(C, n), pathlib.Path)}
    assert set(caches) >= {"PRICE_HISTORY_CACHE", "FUNDAMENTALS_CACHE",
                           "FUND_COMPOSITION_CACHE", "EARNINGS_CACHE"}
    for name, path in caches.items():
        assert one_position_book in path.parents, f"{name} still points at {path}"


def test_a_full_run_leaves_the_real_state_directory_untouched(one_position_book):
    """The incident itself, as a test. Stubs are a list somebody maintains, so
    this asserts the outcome instead: drive the whole pipeline and require that
    nothing in the repo's own state directory moved. A fetcher added later and
    forgotten fails here rather than on Daniel's cache."""
    if not C.STATE.is_dir():
        pytest.skip("no live state directory on this machine")
    snap = lambda: {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
                    for p in C.STATE.glob("*.json")}
    before = snap()
    cockpit.run(quiet=True, verbose=False)
    after = snap()
    assert after == before, "a full test run wrote into the live state directory"


def test_a_refresh_writes_no_heartbeat_and_no_history_line(one_position_book,
                                                           monkeypatch):
    """`last_run.json` is what the "the cockpit had not run for N days" check
    reads. A refresh stamping it would keep that check permanently satisfied
    while the daily task lay dead, and the page would report a board it had not
    read in a week. `history.jsonl` already holds several records per date, so
    the objection there is not frequency but that a record carries no `mode` -
    a scheduled 26-a-day cadence would be indistinguishable from the 07:40 run
    inside the one file a chart of the book's value would read."""
    monkeypatch.setattr(cockpit, "write_heartbeat", _explode)
    monkeypatch.setattr(cockpit, "append_history", _explode)
    monkeypatch.setattr(notify, "notify", _explode)

    summary = cockpit.refresh(verbose=False)

    assert summary["mode"] == "refresh"
    assert summary["notified"] == 0
    assert cockpit.REFRESH_BEAT.exists(), "the refresh left no trace at all"
    assert json.loads(cockpit.REFRESH_BEAT.read_text())["mode"] == "refresh"


def test_the_full_run_still_writes_both(one_position_book, monkeypatch):
    """The other half of the same guard: splitting the heartbeat must not have
    cost the full run the record it is the only writer of."""
    wrote = []
    monkeypatch.setattr(cockpit, "write_heartbeat", lambda s: wrote.append("beat"))
    monkeypatch.setattr(cockpit, "append_history", lambda r: wrote.append("history"))
    monkeypatch.setattr(notify, "notify",
                        lambda alerts, data, dry_run=False: {"sent": 0, "skipped": 0})

    summary = cockpit.run(quiet=True, verbose=False)

    assert summary["mode"] == "full"
    assert wrote == ["beat", "history"]
    assert not cockpit.REFRESH_BEAT.exists(), "a full run wrote the refresh beat"


def test_the_page_says_which_kind_of_run_painted_it(one_position_book):
    """Two pages an hour apart differ in exactly one respect and the numbers do
    not show which. If the payload does not carry it, nothing can."""
    captured = {}
    original = render.payload

    def spy(*a, **k):
        data = original(*a, **k)
        captured.update(data["sources"])
        return data

    render.payload = spy
    try:
        cockpit.refresh(verbose=False)
    finally:
        render.payload = original

    assert captured["run_mode"] == "refresh"


# ------------------------------------------- the rule that fills placeholders
#
# tools/placeholder_targets.py takes the book as arguments precisely so these
# can run against a fixture instead of Daniel's real file. The rule has to stay
# recomputable from the docstring, so each test names the arithmetic rather
# than a number someone once read off the output.

import importlib                                              # noqa: E402
PT = importlib.import_module("tools.placeholder_targets")


def _fixture_book():
    holdings = {
        "C1": {"bucket": "Broad equity - US"},
        "C2": {"bucket": "Broad equity - Europe"},
        "N1": {"bucket": "Nordic index funds"},
        "N2": {"bucket": "Nordic index funds"},
        "S1": {"bucket": "Thematic - AI"},
        "S2": {"bucket": "Thematic - defence"},
        "X1": {"bucket": "US software"},          # a stock, must be ignored
    }
    klass = {k: ("stock" if k == "X1" else "fund") for k in holdings}
    return holdings, klass


def test_the_rule_never_touches_a_stock():
    """Funds are judged by allocation, stocks by thesis. A target weight on a
    stock would be a second standard applied to something that already has
    one."""
    targets, _ = PT.plan(*_fixture_book())
    assert "X1" not in targets and len(targets) == 6


def test_core_and_satellite_are_read_off_the_bucket_not_decided_per_line():
    """No new taxonomy. If tier() stopped matching, every fund would silently
    become a satellite and the sleeve would shrink by more than half."""
    assert PT.tier("Broad equity - US") == "core"
    assert PT.tier("Nordic index funds") == "core"
    assert PT.tier("Thematic - AI") == "satellite"
    assert PT.tier(None) == "satellite"


def test_the_sleeve_splits_core_satellite_in_the_declared_ratio():
    _, table = PT.plan(*_fixture_book())
    by_tier = {}
    for row in table:
        by_tier[row["tier"]] = by_tier.get(row["tier"], 0) + row["sleeve_pct"]
    assert by_tier["core"] == pytest.approx(PT.SLEEVE_PCT * PT.CORE_PCT / 100)
    assert by_tier["satellite"] == pytest.approx(
        PT.SLEEVE_PCT * (100 - PT.CORE_PCT) / 100)


def test_equal_weight_is_per_sleeve_not_per_line():
    """Three Nordic index funds are one bucket and split one share. Weighting
    them as three lines would put a full core share on a EUR 140 position -
    which is how a placeholder stops being neutral and starts being a view."""
    targets, _ = PT.plan(*_fixture_book())
    core_share = PT.SLEEVE_PCT * PT.CORE_PCT / 100 / 3      # 3 core buckets
    assert targets["C1"] == pytest.approx(round(core_share, 2))
    assert targets["N1"] == targets["N2"] == pytest.approx(
        round(core_share / 2, 2))


def test_the_whole_plan_sums_to_the_declared_sleeve():
    """Rounding to 2dp is allowed to lose a hundredth; anything more means a
    sleeve was dropped or double-counted."""
    targets, _ = PT.plan(*_fixture_book())
    assert sum(targets.values()) == pytest.approx(PT.SLEEVE_PCT, abs=0.05)


def test_the_rule_is_blind_to_what_anything_is_currently_worth():
    """Seeding a target from today's weight turns every drift check into a
    tautology - the reason config.TARGET_WEIGHT refuses to do it. plan() is not
    even given the values, and this pins that it never needs them."""
    holdings, klass = _fixture_book()
    for isin in holdings:
        holdings[isin]["value_eur"] = 999_999.0 if isin == "S1" else 1.0
    assert PT.plan(holdings, klass)[0] == PT.plan(*_fixture_book())[0]
