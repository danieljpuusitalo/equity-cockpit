"""Look-through arithmetic, checked against numbers worked out by hand.

Nothing here asserts against a saved copy of this module's own output. Every
expected value is either arithmetic small enough to verify by reading it, or a
property that has to hold whatever the inputs are. A golden file would pass
just as happily if the maths were wrong on the day it was recorded.

Fixture identifiers throughout, for the same reason test_analyse uses them: a
real ISIN in a committed file is a leak, and the logic is what is under test.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as C                                              # noqa: E402
import exposure                                                 # noqa: E402
import sources                                                  # noqa: E402

STOCK_A, STOCK_B = "XX0000000001", "XX0000000002"
FUND_A, FUND_B = "XX0000000101", "XX0000000102"


@pytest.fixture
def fake_book(monkeypatch):
    monkeypatch.setattr(C, "ASSET_CLASS", {
        STOCK_A: "stock", STOCK_B: "stock",
        FUND_A: "fund", FUND_B: "fund"})
    monkeypatch.setattr(C, "NAMES", {
        STOCK_A: "Alpha", STOCK_B: "Beta",
        FUND_A: "Fund One", FUND_B: "Fund Two"})


def holding(isin, symbol, value, name="", account="ACC1"):
    return {"isin": isin, "yahoo": symbol, "value_eur": value,
            "name": name, "account": account}


def funda(**by_symbol):
    return {sym: {"fetched": "2026-09-20", "fields": fields}
            for sym, fields in by_symbol.items()}


def comp(**by_symbol):
    return {sym: {"fetched": "2026-09-20", "fields": fields}
            for sym, fields in by_symbol.items()}


# ------------------------------------------------------------------ positions

def test_two_accounts_collapse_to_one_instrument(fake_book):
    book = [holding(STOCK_A, "AAA", 600.0, account="OST"),
            holding(STOCK_A, "AAA", 400.0, account="AOT")]
    [pos] = exposure._positions(book)
    assert pos["value_eur"] == 1000.0
    assert pos["klass"] == "stock"


def test_custody_split_does_not_double_a_name(fake_book):
    """The failure this guards: one holding in two accounts reading as two."""
    book = [holding(STOCK_A, "AAA", 500.0, account="OST"),
            holding(STOCK_A, "AAA", 500.0, account="AOT")]
    out = exposure.names(exposure._positions(book), {}, {}, 1000.0)
    assert len(out["rows"]) == 1
    assert out["rows"][0]["pct"] == 100.0


# -------------------------------------------------------------------- sectors

def test_a_stock_puts_its_whole_value_in_one_sector(fake_book):
    book = [holding(STOCK_A, "AAA", 1000.0)]
    out = exposure.sectors(exposure._positions(book),
                           funda(AAA={"sector": "Technology"}), {}, 1000.0)
    assert out["rows"] == [{"key": "technology", "label": "Technology",
                            "value_eur": 1000.0, "pct": 100.0,
                            "direct_eur": 1000.0, "indirect_eur": 0.0}]
    assert out["resolved_pct"] == 100.0


def test_a_fund_spreads_across_its_reported_weights(fake_book):
    book = [holding(FUND_A, "FFF", 1000.0)]
    out = exposure.sectors(
        exposure._positions(book), {},
        comp(FFF={"sectors": {"technology": 60.0, "healthcare": 40.0}}),
        1000.0)
    assert {r["key"]: r["value_eur"] for r in out["rows"]} == {
        "technology": 600.0, "healthcare": 400.0}
    assert out["unresolved_eur"] == 0.0


def test_a_funds_cash_is_unresolved_not_scaled_away(fake_book):
    """Weights summing to 95 leave 5 unplaced. Cash is not a sector, and
    normalising it out would overstate every remaining row."""
    book = [holding(FUND_A, "FFF", 1000.0)]
    out = exposure.sectors(
        exposure._positions(book), {},
        comp(FFF={"sectors": {"technology": 95.0}}), 1000.0)
    assert out["value_eur"] == 950.0
    assert out["unresolved_eur"] == 50.0
    assert out["resolved_pct"] == 95.0
    assert out["rows"][0]["pct"] == 95.0          # not renormalised to 100


def test_both_yahoo_spellings_of_a_sector_merge(fake_book):
    """A stock says 'Real Estate', a fund says 'realestate'. One row, or the
    whole premise of a combined split collapses."""
    book = [holding(STOCK_A, "AAA", 500.0), holding(FUND_A, "FFF", 500.0)]
    out = exposure.sectors(
        exposure._positions(book),
        funda(AAA={"sector": "Real Estate"}),
        comp(FFF={"sectors": {"realestate": 100.0}}), 1000.0)
    assert len(out["rows"]) == 1
    assert out["rows"][0]["label"] == "Real Estate"
    assert out["rows"][0]["direct_eur"] == 500.0
    assert out["rows"][0]["indirect_eur"] == 500.0


def test_a_fund_with_no_composition_is_unresolved(fake_book):
    book = [holding(FUND_A, None, 1000.0)]
    out = exposure.sectors(exposure._positions(book), {}, {}, 1000.0)
    assert out["rows"] == []
    assert out["unresolved_eur"] == 1000.0
    assert out["resolved_pct"] == 0.0


def test_a_stock_with_no_sector_is_unresolved_not_dropped(fake_book):
    """Unplaced mass must stay in the denominator. Dropping it would report
    100% coverage of a book half of which was never classified."""
    book = [holding(STOCK_A, "AAA", 400.0), holding(STOCK_B, "BBB", 600.0)]
    out = exposure.sectors(exposure._positions(book),
                           funda(AAA={"sector": "Technology"}), {}, 1000.0)
    assert out["unresolved_eur"] == 600.0
    assert out["resolved_pct"] == 40.0


# ----------------------------------------------------------------- industries

def test_industries_count_funds_as_unresolved(fake_book):
    """Funds report sectors and never industries. Falling back to the sector
    would put two different measurements on one axis."""
    book = [holding(STOCK_A, "AAA", 300.0), holding(FUND_A, "FFF", 700.0)]
    out = exposure.industries(
        exposure._positions(book),
        funda(AAA={"industry": "Grocery Stores"}), 1000.0)
    assert out["unresolved_eur"] == 700.0
    assert out["resolved_pct"] == 30.0


# ------------------------------------------------------------------ geography

def test_listing_country_from_suffix():
    assert exposure.country_for_symbol("ASML.AS") == "Netherlands"
    assert exposure.country_for_symbol("2330.TW") == "Taiwan"
    assert exposure.country_for_symbol("005930.KQ") == "South Korea"
    assert exposure.country_for_symbol("BA.L") == "United Kingdom"


def test_a_bare_ticker_is_a_us_listing():
    assert exposure.country_for_symbol("MSFT") == "United States"
    assert exposure.country_for_symbol("BRK-B") == "United States"


def test_a_bare_numeric_code_is_not_silently_american():
    """Yahoo returns '00939' inside an EM tracker. It has no suffix and it is
    not a US listing, and counting it as one would move real money into the
    wrong country."""
    assert exposure.country_for_symbol("00939") is None
    assert exposure.country_for_symbol("") is None
    assert exposure.country_for_symbol(None) is None


def test_an_unknown_suffix_resolves_to_nothing():
    assert exposure.country_for_symbol("ACME.ZZZ") is None


def test_geography_places_only_what_a_fund_discloses(fake_book):
    book = [holding(FUND_A, "FFF", 1000.0)]
    out = exposure.geography(
        exposure._positions(book), {},
        comp(FFF={"top_holdings": [{"symbol": "MSFT", "pct": 30.0},
                                   {"symbol": "ASML.AS", "pct": 10.0}]}),
        1000.0)
    assert {r["key"]: r["value_eur"] for r in out["rows"]} == {
        "United States": 300.0, "Netherlands": 100.0}
    assert out["unresolved_eur"] == 600.0
    assert out["resolved_pct"] == 40.0


def test_geography_says_what_it_is_measuring(fake_book):
    """The basis has to travel with the numbers. A geography chart is exactly
    the thing a reader assumes means revenue, and it does not."""
    out = exposure.geography([], {}, {}, 0.0)
    assert "domicile" in out["basis"] and "listing venue" in out["basis"]


# -------------------------------------------------------------- single names

def test_direct_and_indirect_exposure_combine(fake_book):
    book = [holding(STOCK_A, "MSFT", 500.0, name="Microsoft"),
            holding(FUND_A, "FFF", 500.0)]
    out = exposure.names(
        exposure._positions(book),
        comp(FFF={"top_holdings": [{"symbol": "MSFT", "name": "Microsoft Corp",
                                    "pct": 20.0}]}),
        {}, 1000.0)
    row = next(r for r in out["rows"] if r["symbol"] == "MSFT")
    assert row["direct_eur"] == 500.0
    assert row["indirect_eur"] == 100.0           # 20% of 500
    assert row["pct"] == 60.0
    assert row["held_both_ways"] is True
    assert out["n_both_ways"] == 1
    assert [v["fund"] for v in row["via"]] == ["FFF"]


def test_indirect_exposure_is_attributed_to_every_fund_carrying_it(fake_book):
    book = [holding(FUND_A, "F1", 400.0), holding(FUND_B, "F2", 600.0)]
    out = exposure.names(
        exposure._positions(book),
        comp(F1={"top_holdings": [{"symbol": "MSFT", "pct": 50.0}]},
             F2={"top_holdings": [{"symbol": "MSFT", "pct": 10.0}]}),
        {}, 1000.0)
    [row] = out["rows"]
    assert row["value_eur"] == 260.0              # 200 + 60
    assert {v["fund"]: v["value_eur"] for v in row["via"]} == {
        "F1": 200.0, "F2": 60.0}
    assert row["via"][0]["fund"] == "F1"          # largest first


def test_undisclosed_fund_mass_is_reported_not_assumed(fake_book):
    """Ten rows is most of a defence thematic and almost none of a world
    tracker. The table has to say which one it just drew."""
    book = [holding(FUND_A, "FFF", 1000.0)]
    out = exposure.names(
        exposure._positions(book),
        comp(FFF={"top_holdings": [{"symbol": "MSFT", "pct": 12.0}]}),
        {}, 1000.0)
    assert out["resolved_pct"] == 12.0
    assert out["unresolved_eur"] == 880.0


def test_name_rows_carry_the_same_bucket_keys_the_breakdowns_use(fake_book):
    """The join the page's cross-filter depends on.

    Clicking the Technology bar has to select exactly the rows the Technology
    bar counted. That only holds if both sides key on the same canonical
    string, and the two sides get it from different places - the breakdown
    normalises "Technology" and "technology" together, this table normalises
    the row. If those two ever drift the filter silently under-selects, which
    looks like a smaller sector rather than like a bug.
    """
    book = [holding(STOCK_A, "AAA", 600.0), holding(STOCK_B, "BBB", 400.0)]
    positions = exposure._positions(book)
    facts = funda(AAA={"sector": "Technology", "industry": "Software",
                       "country": "United States"},
                  BBB={"sector": "Real Estate", "industry": "REIT",
                       "country": "Finland"})

    split = exposure.sectors(positions, facts, {}, 1000.0)
    rows = exposure.names(positions, {}, facts, 1000.0)["rows"]
    by_symbol = {r["symbol"]: r for r in rows}

    assert by_symbol["AAA"]["sector"] == "technology"
    assert by_symbol["BBB"]["sector"] == "real_estate"
    for bucket in split["rows"]:
        picked = [r for r in rows if r["sector"] == bucket["key"]]
        assert picked, f"no name matches the {bucket['key']} bar"
        assert sum(r["value_eur"] for r in picked) == bucket["value_eur"]

    assert by_symbol["AAA"]["industry"] == "Software"
    assert by_symbol["BBB"]["country"] == "Finland"


def test_a_constituent_with_no_sector_is_none_not_a_guess(fake_book):
    """A fund's constituents arrive as tickers. Yahoo says nothing about what
    sector they are in, and the page reports how many rows a filter could not
    judge - which is only possible if this stays None rather than borrowing
    the fund's or the neighbour's."""
    book = [holding(FUND_A, "FFF", 1000.0)]
    rows = exposure.names(
        exposure._positions(book),
        comp(FFF={"top_holdings": [{"symbol": "MSFT", "pct": 20.0}]}),
        {}, 1000.0)["rows"]
    [row] = rows
    assert row["sector"] is None
    assert row["industry"] is None
    # Geography is the one thing a bare ticker does carry, through the listing
    # venue - and it is labelled as a venue everywhere it surfaces.
    assert row["country"] == "United States"


# ------------------------------------------------------------- concentration

def test_equal_positions_give_an_effective_count_of_themselves(fake_book):
    book = [holding(STOCK_A, "AAA", 250.0), holding(STOCK_B, "BBB", 250.0),
            holding(FUND_A, "F1", 250.0), holding(FUND_B, "F2", 250.0)]
    out = exposure.concentration(exposure._positions(book), 1000.0)
    assert out["effective_n"] == 4.0
    assert out["hhi"] == 0.25
    assert out["top1_pct"] == 25.0


def test_a_long_tail_does_not_count_as_diversification(fake_book):
    """One position at 90% and three at 3.33% is not four positions."""
    book = [holding(STOCK_A, "AAA", 900.0), holding(STOCK_B, "BBB", 40.0),
            holding(FUND_A, "F1", 30.0), holding(FUND_B, "F2", 30.0)]
    out = exposure.concentration(exposure._positions(book), 1000.0)
    assert out["n"] == 4
    assert out["effective_n"] < 1.3
    assert out["top1_pct"] == 90.0


def test_concentration_of_an_empty_book_is_zero_not_a_crash():
    assert exposure.concentration([], 0.0)["effective_n"] == 0.0


# ------------------------------------------------------------------ fee drag

def test_fee_drag_is_value_times_ter(fake_book):
    book = [holding(FUND_A, "FFF", 10_000.0)]
    out = exposure.fees(exposure._positions(book), comp(FFF={"ter": 0.35}),
                        10_000.0)
    assert out["annual_eur"] == 35.0
    assert out["sleeve_ter_pct"] == 0.35


def test_a_fund_with_no_published_ter_is_not_free(fake_book):
    """Treating an absent TER as zero would report a cheaper book than the one
    that exists, and the error grows with exactly the holdings least willing
    to disclose."""
    book = [holding(FUND_A, "F1", 1000.0), holding(FUND_B, "F2", 1000.0)]
    out = exposure.fees(exposure._positions(book),
                        comp(F1={"ter": 0.50}, F2={"ter": None}), 2000.0)
    assert out["annual_eur"] == 5.0
    assert out["covered_eur"] == 1000.0
    assert out["unresolved_eur"] == 1000.0
    assert out["resolved_pct"] == 50.0
    # The rate is over what it could price, not over the whole sleeve.
    assert out["sleeve_ter_pct"] == 0.5


def test_fee_drag_has_two_denominators(fake_book):
    """What the funds cost as funds, and what they cost against everything."""
    book = [holding(STOCK_A, "AAA", 9_000.0), holding(FUND_A, "FFF", 1_000.0)]
    out = exposure.fees(exposure._positions(book), comp(FFF={"ter": 1.0}),
                        10_000.0)
    assert out["sleeve_ter_pct"] == 1.0
    assert out["book_ter_pct"] == 0.1


def test_a_directly_held_stock_carries_no_fee(fake_book):
    book = [holding(STOCK_A, "AAA", 1000.0)]
    out = exposure.fees(exposure._positions(book), {}, 1000.0)
    assert out["annual_eur"] == 0.0
    assert out["rows"] == []


# ----------------------------------------------------------------- multiples

def test_portfolio_pe_is_harmonic_not_arithmetic(fake_book):
    """Two equal positions on 10x and 30x. Total value 2, total earnings
    1/10 + 1/30 = 2/15, so the book is on 15x - not the 20x an arithmetic
    mean would print. Same money, and the arithmetic answer is a third high."""
    book = [holding(STOCK_A, "AAA", 500.0), holding(STOCK_B, "BBB", 500.0)]
    out = exposure.multiples(
        exposure._positions(book),
        funda(AAA={"pe": 10.0}, BBB={"pe": 30.0}), {}, 1000.0)
    assert out["pe"] == 15.0
    assert out["pe_resolved_pct"] == 100.0


def test_a_loss_making_holding_is_excluded_not_averaged(fake_book):
    """A negative P/E is not a small one. Averaging it in - in either
    direction - invents an earnings figure that does not exist."""
    book = [holding(STOCK_A, "AAA", 500.0), holding(STOCK_B, "BBB", 500.0)]
    out = exposure.multiples(
        exposure._positions(book),
        funda(AAA={"pe": 20.0}, BBB={"pe": -5.0}), {}, 1000.0)
    assert out["pe"] == 20.0
    assert out["pe_resolved_pct"] == 50.0         # and it says so


def test_funds_and_stocks_answer_on_the_same_axis(fake_book):
    book = [holding(STOCK_A, "AAA", 500.0), holding(FUND_A, "FFF", 500.0)]
    out = exposure.multiples(
        exposure._positions(book), funda(AAA={"pe": 10.0}),
        comp(FFF={"valuation": {"pe": 30.0}}), 1000.0)
    assert out["pe"] == 15.0
    assert out["pe_resolved_pct"] == 100.0


def test_a_book_with_no_multiples_reports_none_not_zero(fake_book):
    book = [holding(STOCK_A, "AAA", 1000.0)]
    out = exposure.multiples(exposure._positions(book), {}, {}, 1000.0)
    assert out["pe"] is None
    assert out["pe_resolved_pct"] == 0.0


# --------------------------------------------- shaping what Yahoo sends back

def test_fund_valuation_rows_are_inverted():
    """Yahoo ships these as yields. 0.04437 is 22.5x, and rendered raw it is a
    multiple off by three orders of magnitude that still looks like a number."""
    pandas = pytest.importorskip("pandas")

    class FakeFunds:
        top_holdings = None
        sector_weightings = {"technology": 1.0}
        asset_classes = {}
        fund_operations = pandas.DataFrame(
            {"XXX": [0.002]}, index=["Annual Report Expense Ratio"])
        equity_holdings = pandas.DataFrame(
            {"XXX": [0.04437, 0.18673]},
            index=["Price/Earnings", "Price/Book"])

    out = sources._shape_funds_data(FakeFunds())
    assert out["valuation"]["pe"] == 22.54
    assert out["valuation"]["pb"] == 5.36
    assert out["ter"] == 0.2


def test_a_zero_yield_is_absent_not_infinite():
    """Dividing by a reported zero would print a multiple of infinity for what
    is really a missing figure."""
    pandas = pytest.importorskip("pandas")

    class FakeFunds:
        top_holdings = None
        sector_weightings = {"technology": 1.0}
        asset_classes = {}
        fund_operations = None
        equity_holdings = pandas.DataFrame(
            {"XXX": [0.0]}, index=["Price/Earnings"])

    out = sources._shape_funds_data(FakeFunds())
    assert "pe" not in out["valuation"]


def test_a_fund_that_answers_with_nothing_shapes_to_none():
    class FakeFunds:
        top_holdings = None
        sector_weightings = {}
        asset_classes = {}
        fund_operations = None
        equity_holdings = None

    assert sources._shape_funds_data(FakeFunds()) is None


def test_every_accessor_can_raise_independently():
    """`.funds_data` is a set of lazy pandas accessors and a fund can answer
    with sectors while refusing holdings. One raising must not lose the rest."""
    class FakeFunds:
        sector_weightings = {"technology": 1.0}

        @property
        def top_holdings(self):
            raise RuntimeError("no holdings for you")

        @property
        def asset_classes(self):
            raise RuntimeError("nor these")

        @property
        def fund_operations(self):
            raise RuntimeError("nor this")

        @property
        def equity_holdings(self):
            raise RuntimeError("nor that")

    out = sources._shape_funds_data(FakeFunds())
    assert out["sectors"] == {"technology": 100.0}
    assert out["top_holdings"] == []


# ------------------------------------------------------------ cache contract

@pytest.fixture
def comp_cache_at(tmp_path, monkeypatch):
    path = tmp_path / "fund-composition.json"
    monkeypatch.setattr(C, "FUND_COMPOSITION_CACHE", path)
    return path


def test_a_refresh_asks_yahoo_for_no_compositions(comp_cache_at, monkeypatch):
    import json as _json
    comp_cache_at.write_text(_json.dumps({"fetched": "2026-09-19", "symbols": {
        "FFF": {"fetched": "2026-09-19", "fields": {"sectors": {"technology": 100.0}}}}}))

    def explode(*a, **k):
        raise AssertionError("a refresh must not call Yahoo")
    monkeypatch.setattr(sources, "_funds_data", explode)

    out, problems, pulled = sources.fund_composition(["FFF"], cached_only=True)
    assert out["FFF"]["fetched"] == "2026-09-19"
    assert pulled == 0
    assert not problems


def test_a_refresh_does_not_restamp_the_cache(comp_cache_at, monkeypatch):
    import datetime as dt
    import json as _json
    comp_cache_at.write_text(_json.dumps({"fetched": "2026-09-19", "symbols": {
        "FFF": {"fetched": "2026-09-19", "fields": {"sectors": {"technology": 100.0}}}}}))
    before = comp_cache_at.read_text()
    sources.fund_composition(["FFF"], today=dt.date(2026, 9, 20), cached_only=True)
    assert comp_cache_at.read_text() == before


def test_an_empty_answer_keeps_the_last_good_one(comp_cache_at, monkeypatch):
    """The fault already on this codebase's record twice: a vendor answering
    with LESS than it should, recorded as the fund having become empty."""
    import datetime as dt
    import json as _json
    comp_cache_at.write_text(_json.dumps({"fetched": "2026-09-19", "symbols": {
        "FFF": {"fetched": "2026-09-19",
                "fields": {"sectors": {"technology": 100.0}}}}}))
    monkeypatch.setattr(sources, "_funds_data", lambda *a, **k: None)

    out, problems, _ = sources.fund_composition(
        ["FFF"], today=dt.date(2026, 9, 20))
    assert out["FFF"]["fields"]["sectors"] == {"technology": 100.0}
    assert out["FFF"]["fetched"] == "2026-09-19"       # stale, and says so
    assert "2026-09-19" in problems["FFF"]


def test_a_fund_that_never_answers_is_cached_as_an_explicit_miss(comp_cache_at,
                                                                 monkeypatch):
    """So tomorrow's run reads it as asked-and-refused, not as never asked."""
    import datetime as dt
    monkeypatch.setattr(sources, "_funds_data", lambda *a, **k: None)
    out, problems, _ = sources.fund_composition(
        ["FFF"], today=dt.date(2026, 9, 20))
    assert out["FFF"] == {"fetched": "2026-09-20", "fields": None}
    assert "FFF" in problems


# -------------------------------------------------------------- the assembly

def test_look_through_is_pure(fake_book):
    book = [holding(STOCK_A, "AAA", 600.0), holding(FUND_A, "FFF", 400.0)]
    f = funda(AAA={"sector": "Technology", "country": "Finland", "pe": 10.0})
    c = comp(FFF={"sectors": {"healthcare": 100.0}, "ter": 0.2,
                  "top_holdings": [{"symbol": "MSFT", "pct": 25.0}]})
    first = exposure.look_through(book, f, c)
    second = exposure.look_through(book, f, c)
    assert first == second
    assert first["total_eur"] == 1000.0
    assert first["n_positions"] == 2


def test_the_fund_table_publishes_its_own_disclosure(fake_book):
    """The spread across this column is why every table carries coverage."""
    book = [holding(FUND_A, "FFF", 1000.0)]
    out = exposure.look_through(
        book, {}, comp(FFF={"sectors": {"technology": 100.0},
                            "top_holdings": [{"symbol": "MSFT", "pct": 12.2}]}))
    [fund] = out["funds"]
    assert fund["disclosed_pct"] == 12.2
    assert fund["n_disclosed"] == 1
    assert fund["has_sectors"] is True
