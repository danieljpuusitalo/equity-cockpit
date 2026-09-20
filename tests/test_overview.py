"""The book seen as one thing: folding, the day move, and attribution.

Fixture identifiers throughout, and no clock - `overview` is pure, so nothing
in here changes answer tomorrow.

The theme, again: a position that cannot be measured is excluded and counted,
never measured as zero. Three of the tests below are that rule in three
different units (percent, euros, pixels).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C                                              # noqa: E402
import overview                                                 # noqa: E402

STOCK_A, STOCK_B = "XX0000000001", "XX0000000002"
FUND_A = "XX0000000101"


@pytest.fixture
def fake_book(monkeypatch):
    monkeypatch.setattr(C, "ASSET_CLASS", {
        STOCK_A: "stock", STOCK_B: "stock", FUND_A: "fund"})


def holding(isin, yahoo, value, cost=None, day=None, account="OST",
            name=None, units=1.0):
    return {"isin": isin, "yahoo": yahoo, "name": name or yahoo,
            "ticker": yahoo, "value_eur": value, "cost_eur": cost,
            "day_pct": day, "account": account, "units": units,
            "bucket": "Test", "price": 1.0}


# ----------------------------------------------------------------- folding

def test_a_name_in_two_accounts_is_one_row(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 600.0, 500.0, account="OST"),
                          holding(STOCK_A, "AAA", 400.0, 300.0, account="AOT")])
    assert len(rows) == 1
    assert rows[0]["value_eur"] == 1000.0
    assert rows[0]["cost_eur"] == 800.0
    assert rows[0]["accounts"] == ["AOT", "OST"]


def test_the_folded_return_is_value_weighted_not_averaged(fake_book):
    """+100% on 200 and +0% on 800 is +20% on the name, not +50%. Averaging
    two accounts' percentages is the obvious wrong answer and it flatters
    whichever account is smallest."""
    rows = overview.fold([holding(STOCK_A, "AAA", 400.0, 200.0),
                          holding(STOCK_A, "AAA", 800.0, 800.0,
                                  account="AOT")])
    assert rows[0]["pl_pct"] == 20.0


def test_a_position_with_no_cost_has_no_return_rather_than_zero(fake_book):
    [row] = overview.fold([holding(STOCK_A, "AAA", 500.0, cost=None)])
    assert row["pl_pct"] is None and row["pl_eur"] is None


def test_a_holding_with_no_yahoo_symbol_still_appears(fake_book):
    """The Nordnet index funds have no symbol at all. They are real money and
    belong in the book; they simply have no chart, which the page learns from
    `sym` being None."""
    [row] = overview.fold([holding(FUND_A, "MISSING", 148.0, 143.0)])
    assert row["sym"] is None
    assert row["value_eur"] == 148.0


def test_rows_come_back_largest_first(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 100.0),
                          holding(STOCK_B, "BBB", 900.0)])
    assert [r["sym"] for r in rows] == ["BBB", "AAA"]


# --------------------------------------------------------------- the day move

def test_the_day_move_divides_by_what_the_book_opened_at(fake_book):
    """The arithmetic that is easy to get subtly wrong: today's value is the
    result of the move, so yesterday is value / (1 + d), never value * (1 - d).
    A single position's book move must equal that position's own move."""
    rows = overview.fold([holding(STOCK_A, "AAA", 1010.0, day=1.0)])
    day = overview.day_move(rows)
    assert day["pct"] == pytest.approx(1.0, abs=1e-9)
    assert day["value_eur"] == pytest.approx(10.0, abs=0.01)


def test_a_position_with_no_day_move_is_excluded_not_counted_flat(fake_book):
    """The trap in its day-move form. Several holdings price off a Nordnet
    market value with no previous close. Folded in as 0% they would drag every
    day's reading toward nothing, forever, and never explain why."""
    rows = overview.fold([holding(STOCK_A, "AAA", 1000.0, day=2.0),
                          holding(FUND_A, "MISSING", 1000.0, day=None)])
    day = overview.day_move(rows)
    assert day["pct"] == pytest.approx(2.0, abs=1e-9)      # not 1.0
    assert day["n_quiet"] == 1
    assert day["quiet_eur"] == 1000.0
    assert day["covered_pct"] == 50.0


def test_the_day_move_is_value_weighted(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 900.0, day=0.0),
                          holding(STOCK_B, "BBB", 110.0, day=10.0)])
    day = overview.day_move(rows)
    assert day["pct"] == pytest.approx(1.0, abs=1e-9)


def test_a_book_with_no_priced_position_has_no_day_move(fake_book):
    day = overview.day_move(overview.fold(
        [holding(FUND_A, "MISSING", 500.0, day=None)]))
    assert day["pct"] is None                              # not 0.0
    assert day["n_priced"] == 0


# -------------------------------------------------------------- the allocation

def test_tile_weights_sum_to_the_book(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 600.0),
                          holding(STOCK_B, "BBB", 300.0),
                          holding(FUND_A, "MISSING", 100.0)])
    alloc = overview.allocation(rows)
    assert sum(t["weight_pct"] for t in alloc["tiles"]) == pytest.approx(
        100.0, abs=0.01)
    assert alloc["n_undrawn"] == 0


def test_a_tile_area_matches_its_weight(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 750.0),
                          holding(STOCK_B, "BBB", 250.0)])
    for tile in overview.allocation(rows)["tiles"]:
        assert tile["w"] * tile["h"] == pytest.approx(
            tile["weight_pct"] * 100.0, rel=1e-6)


def test_an_unpriced_position_is_reported_as_undrawn(fake_book):
    """The treemap cannot draw a position worth nothing, so the count has to
    say so. Tiles that quietly sum to less than the book are a map with a hole
    in it and no legend."""
    rows = overview.fold([holding(STOCK_A, "AAA", 1000.0),
                          holding(STOCK_B, "BBB", 0.0)])
    alloc = overview.allocation(rows)
    assert alloc["n"] == 1 and alloc["n_undrawn"] == 1


def test_a_tile_with_no_cost_basis_carries_no_colour(fake_book):
    [tile] = overview.allocation(
        overview.fold([holding(STOCK_A, "AAA", 500.0, cost=None)]))["tiles"]
    assert tile["pl_pct"] is None


# ------------------------------------------------------------------- movers

def test_movers_split_gainers_from_losers(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 100.0, day=5.0),
                          holding(STOCK_B, "BBB", 100.0, day=-3.0),
                          holding(FUND_A, "MISSING", 100.0, day=None)])
    mv = overview.movers(rows)
    assert [r["sym"] for r in mv["up"]] == ["AAA"]
    assert [r["sym"] for r in mv["down"]] == ["BBB"]
    assert mv["n_quiet"] == 1


def test_a_flat_position_is_neither_a_gainer_nor_a_loser(fake_book):
    mv = overview.movers(overview.fold(
        [holding(STOCK_A, "AAA", 100.0, day=0.0)]))
    assert mv["up"] == [] and mv["down"] == []
    assert mv["n_priced"] == 1                             # it was still read


def test_losers_are_listed_worst_first(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 100.0, day=-1.0),
                          holding(STOCK_B, "BBB", 100.0, day=-9.0)])
    assert [r["sym"] for r in overview.movers(rows)["down"]] == ["BBB", "AAA"]


# -------------------------------------------------------------- contributors

def test_the_money_is_attributed_in_euros_not_percent(fake_book):
    """The whole reason this function exists. A 60% gain on a small position
    is not the thing that made the year; a 12% gain on the biggest one is. A
    ranking by percent gets this exactly backwards."""
    rows = overview.fold([
        holding(STOCK_A, "AAA", 160.0, 100.0),        # +60%, +60 EUR
        holding(STOCK_B, "BBB", 5600.0, 5000.0)])     # +12%, +600 EUR
    best = overview.contributors(rows)["best"]
    assert [r["sym"] for r in best] == ["BBB", "AAA"]
    assert best[0]["share_pct"] == pytest.approx(90.9, abs=0.1)


def test_a_winner_and_a_loser_do_not_cancel_in_the_denominator(fake_book):
    """Shares are taken against gross absolute movement. Against net P/L, a
    book that is +500 and -480 would hand its two positions shares of 2500%
    and -2400%, which is arithmetic, not information."""
    rows = overview.fold([holding(STOCK_A, "AAA", 1500.0, 1000.0),
                          holding(STOCK_B, "BBB", 520.0, 1000.0)])
    con = overview.contributors(rows)
    assert con["best"][0]["share_pct"] == pytest.approx(51.0, abs=0.5)
    assert con["worst"][0]["share_pct"] == pytest.approx(49.0, abs=0.5)


def test_a_position_with_no_cost_is_uncounted_not_ranked_at_zero(fake_book):
    rows = overview.fold([holding(STOCK_A, "AAA", 1200.0, 1000.0),
                          holding(STOCK_B, "BBB", 500.0, cost=None)])
    con = overview.contributors(rows)
    assert con["n_known"] == 1 and con["n_unknown"] == 1
    assert [r["sym"] for r in con["best"]] == ["AAA"]
    assert con["worst"] == []


# --------------------------------------------------------------------- build

def test_build_is_pure_and_totals_are_carried_not_recomputed(fake_book):
    view = overview.build(
        [holding(STOCK_A, "AAA", 600.0, 500.0, day=1.0)],
        totals={"value_eur": 600.0, "irr_pct": 13.0})
    assert view["n"] == 1
    assert view["value_eur"] == 600.0
    assert view["totals"]["irr_pct"] == 13.0
    assert view["allocation"]["n"] == 1
    assert view["day"]["n_priced"] == 1


def test_an_empty_book_builds_rather_than_raising(fake_book):
    view = overview.build([])
    assert view["n"] == 0
    assert view["allocation"]["tiles"] == []
    assert view["day"]["pct"] is None
    assert view["contributors"]["best"] == []
