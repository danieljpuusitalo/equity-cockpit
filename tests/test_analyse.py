"""Offline tests. No network, no Notion, no Nordnet folder.

Every case here is a real string from the Equity Log or a real row from the
Nordnet export, including the two that produced false alerts on the first
live run. A test that isn't about something that actually broke is decoration.
"""
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import config as C        # noqa: E402
import analyse            # noqa: E402
import sources            # noqa: E402


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
