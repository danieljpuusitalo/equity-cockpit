"""The book over time: curve, TWR, benchmark, risk, attribution.

Fixture identifiers and hand-built bars throughout. Every expected number is
recomputed here from the definition, never pinned from memory.

Two negative controls carry the weight: moving one lot's price must move the
curve, the TWR, the risk contribution and the attribution; and taking the
benchmark's bars away must produce "no benchmark", not a zero excess.
"""

import datetime as dt
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import performance as P                                         # noqa: E402

ISIN_A, ISIN_B, ISIN_C = "XX0000000001", "XX0000000002", "XX0000000003"
PAIRS = {"USD": "EURUSD=X"}
BENCH = {"symbol": "BENCH.X", "label": "Test benchmark", "ccy": "EUR"}


def days(n, start="2025-01-01"):
    d0 = dt.date.fromisoformat(start)
    return [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]


def series(closes, start="2025-01-01"):
    return {"fetched": "x", "bars": [[d, c, c, c, c, 0]
                                     for d, c in zip(days(len(closes), start), closes)
                                     if c is not None]}


def lot(isin, units, cost, bought, ccy="EUR"):
    return {"isin": isin, "units": units, "cost_eur": cost, "bought": bought,
            "ccy": ccy, "name": "Name " + isin[-1]}


def curve_of(lots, history, fx_history=None, symbol_of=None):
    fx = P.fx_series(fx_history or {}, PAIRS)
    return P.book_curve(lots, symbol_of or {ISIN_A: "AAA", ISIN_B: "BBB",
                                             ISIN_C: "CCC"}, history, fx)


# ------------------------------------------------------------------- curve

def test_hand_built_three_day_twr():
    history = {"AAA": series([10, 11, 9.9])}
    c = curve_of([lot(ISIN_A, 2, 20, "2025-01-01")], history)
    assert c["value"] == pytest.approx([20, 22, 19.8])
    r = P.daily_returns(c["value"], c["flow"])
    assert r[0] is None
    assert r[1:] == pytest.approx([0.10, -0.10])
    assert P.twr_index(r)[-1] == pytest.approx(100 * 1.1 * 0.9)


def test_a_purchase_moves_the_value_not_the_return():
    history = {"AAA": series([10, 10, 12, 12])}
    lots = [lot(ISIN_A, 1, 10, "2025-01-01"), lot(ISIN_A, 1, 10, "2025-01-02")]
    c = curve_of(lots, history)
    assert c["value"] == pytest.approx([10, 20, 24, 24])
    assert c["flow"] == pytest.approx([0, 10, 0, 0])
    r = P.daily_returns(c["value"], c["flow"])
    # day 2: value doubles, but all of it is new money -> 0% return
    assert r[1] == pytest.approx(0.0)
    assert r[2] == pytest.approx(0.2)


def test_curve_starts_on_first_held_day_as_opening_capital():
    history = {"AAA": series([10, 10, 10, 11])}
    c = curve_of([lot(ISIN_A, 1, 10, "2025-01-03")], history)
    assert c["dates"][0] == "2025-01-03"
    assert c["flow"][0] == 0.0          # opening capital, not a flow


def test_fx_converts_and_missing_fx_excludes():
    history = {"AAA": series([10, 10]), "BBB": series([5, 5])}
    fxh = {"EURUSD=X": series([2.0, 2.0])}     # 1 USD = 0.5 EUR
    lots = [lot(ISIN_A, 1, 5, "2025-01-01", "USD"),
            lot(ISIN_B, 1, 5, "2025-01-01", "SEK")]
    c = curve_of(lots, history, fxh)
    assert c["value"] == pytest.approx([5.0, 5.0])
    assert [e["reason"] for e in c["excluded"]] == ["no FX history for SEK"]
    assert c["n_included"] == 1
    assert c["cost_covered_pct"] == 50.0


def test_unpriced_lot_is_excluded_and_counted_never_zero():
    history = {"AAA": series([10, 10])}
    lots = [lot(ISIN_A, 1, 10, "2025-01-01"), lot(ISIN_B, 3, 30, "2025-01-01")]
    c = curve_of(lots, history, symbol_of={ISIN_A: "AAA", ISIN_B: "MISSING"})
    assert c["value"] == pytest.approx([10, 10])
    assert c["excluded"] == [{"symbol": "Name 2", "reason": "no public price feed",
                              "n_lots": 1, "cost_eur": 30}]
    assert c["cost_covered_pct"] == 25.0


def test_a_lot_older_than_its_bars_pushes_the_start():
    # BBB only lists from day 3 but was bought on day 1: the curve cannot value
    # it before day 3, so the curve starts there rather than pretending.
    history = {"AAA": series([10] * 5), "BBB": series([None, None, 4, 4, 4])}
    lots = [lot(ISIN_A, 1, 10, "2025-01-01"), lot(ISIN_B, 1, 4, "2025-01-01")]
    c = curve_of(lots, history)
    assert c["dates"][0] == "2025-01-03"
    assert c["value"][0] == pytest.approx(14)


def test_no_lots_no_curve():
    c = curve_of([], {})
    assert c["dates"] == [] and c["cost_covered_pct"] is None


# ----------------------------------------------------------------- periods

def test_period_before_the_curve_is_none_not_since_start():
    dates = days(20, "2025-03-01")
    assert P.base_index(dates, "1Y") is None
    assert P.base_index(dates, "YTD") is None
    assert P.base_index(dates, "ALL") == 0
    assert P.base_index(dates, "1D") == 18
    assert dates[P.base_index(dates, "1W")] == "2025-03-13"


def test_months_back_clamps_the_day():
    assert P._months_back(dt.date(2025, 3, 31), 1) == dt.date(2025, 2, 28)
    assert P._months_back(dt.date(2024, 3, 31), 1) == dt.date(2024, 2, 29)
    assert P._months_back(dt.date(2025, 1, 15), 3) == dt.date(2024, 10, 15)


def _book(closes_a, n_bench=None, bench=None):
    n = len(closes_a)
    history = {"AAA": series(closes_a)}
    fxh = {} if bench is None else {"BENCH.X": series(bench[:n_bench or n])}
    return P.build([lot(ISIN_A, 1, closes_a[0], "2025-01-01")],
                   {ISIN_A: "AAA"}, history, fxh, PAIRS, BENCH)


def wave(n, amp=0.02, phase=0.0, base=100.0):
    out, level = [], base
    for i in range(n):
        level *= 1 + amp * math.sin(i * 0.7 + phase)
        out.append(round(level, 6))
    return out


def test_excess_is_book_minus_benchmark():
    a, b = wave(40), wave(40, 0.01, 1.0)
    out = _book(a, bench=b)
    all_ = out["periods"]["ALL"]
    assert all_["twr_pct"] == pytest.approx((a[-1] / a[0] - 1) * 100, abs=0.01)
    assert all_["bench_pct"] == pytest.approx((b[-1] / b[0] - 1) * 100, abs=0.01)
    assert all_["excess_pp"] == pytest.approx(all_["twr_pct"] - all_["bench_pct"],
                                              abs=0.02)
    assert all_["beta"] is not None and all_["vol_pct"] is not None


def test_no_benchmark_bars_is_no_benchmark_not_zero():
    out = _book(wave(40))
    assert out["benchmark"]["absent"] == "no benchmark bars"
    for stats in out["periods"].values():
        if stats:
            assert stats["bench_pct"] is None
            assert stats["excess_pp"] is None
            assert stats["beta"] is None


def test_short_window_has_no_vol():
    out = _book(wave(10))
    assert out["periods"]["ALL"]["vol_pct"] is None


def test_shadow_buys_the_benchmark_with_the_same_flows():
    value, flow = [100.0, 210.0, 220.0], [0.0, 100.0, 0.0]
    bench = [10.0, 11.0, 12.0]
    s = P.shadow(value, flow, bench)
    units = 100 / 10 + 100 / 11
    assert s == pytest.approx([100.0, units * 11, units * 12])
    assert P.shadow(value, flow, [None, 11.0, 12.0]) is None


def test_drawdown_is_on_the_index_not_the_value():
    # The price falls 10% on the same day new money arrives, so the VALUE
    # rises (10 -> 99) and a value-based drawdown would read zero.
    history = {"AAA": series([10, 10, 9] + [9] * 25)}
    lots = [lot(ISIN_A, 1, 10, "2025-01-01"), lot(ISIN_A, 10, 90, "2025-01-03")]
    out = P.build(lots, {ISIN_A: "AAA"}, history, {}, PAIRS, BENCH)
    assert out["curve"]["value"][1:3] == [10, 99]
    assert out["periods"]["ALL"]["mdd_pct"] == pytest.approx(-10.0)


# ------------------------------------------------------ attribution & risk

def test_attribution_sums_to_the_book_change_less_flows():
    history = {"AAA": series(wave(30)), "BBB": series(wave(30, 0.03, 2.0, 50))}
    lots = [lot(ISIN_A, 2, 200, "2025-01-01"), lot(ISIN_B, 3, 150, "2025-01-10")]
    c = curve_of(lots, history)
    for period in ("1W", "ALL"):
        b = P.base_index(c["dates"], period)
        rows = P.attribution(c, period)
        expected = c["value"][-1] - c["value"][b] - sum(c["flow"][b + 1:])
        assert sum(r["eur"] for r in rows) == pytest.approx(expected, abs=0.02)


def test_attribution_pct_is_the_names_own_price_return():
    # Two holdings of the same name bought on different days: the EUR figure
    # depends on units and timing, the percentage must not.
    closes = wave(30)
    history = {"AAA": series(closes)}
    small = curve_of([lot(ISIN_A, 1, 100, "2025-01-01")], history)
    large = curve_of([lot(ISIN_A, 7, 700, "2025-01-01")], history)
    for period in ("1W", "ALL"):
        b = P.base_index(small["dates"], period)
        want = (closes[-1] / closes[b] - 1) * 100
        ps = P.attribution(small, period)[0]["pct"]
        pl = P.attribution(large, period)[0]["pct"]
        assert ps == pytest.approx(want, abs=0.01)
        assert ps == pl


def test_attribution_pct_is_none_when_the_window_predates_the_listing():
    c = _risk_book()
    rows = {r["symbol"]: r for r in P.attribution(c, "ALL")}
    # CCC has no bar on the window's first day: no return, not a flat 0%.
    assert rows["CCC"]["pct"] is None
    assert rows["CCC"]["eur"] is not None
    assert rows["AAA"]["pct"] is not None


def _risk_book(extra_b=0.0, n=120):
    a = wave(n, 0.02)
    b = [x * (1 + extra_b * math.sin(i)) for i, x in enumerate(wave(n, 0.015, 2.0, 50))]
    history = {"AAA": series(a), "BBB": series(b),
               "CCC": series([None] * (n - 30) + [20.0] * 30)}
    lots = [lot(ISIN_A, 2, 200, "2025-01-01"), lot(ISIN_B, 3, 150, "2025-01-01"),
            lot(ISIN_C, 1, 20, dt.date.fromisoformat("2025-01-01")
                .__add__(dt.timedelta(days=n - 30)).isoformat())]
    return curve_of(lots, history)


def test_risk_contributions_sum_to_100_and_short_history_is_counted():
    c = _risk_book()
    r = P.risk(c)
    assert sum(x["rc_pct"] for x in r["contribution"]) == pytest.approx(100, abs=0.05)
    assert [e["symbol"] for e in r["excluded"]] == ["CCC"]
    assert r["excluded"][0]["n_obs"] < P.MIN_RISK_OBS
    assert r["weight_covered_pct"] < 100
    assert r["corr"][0][0] == 1.0


# -------------------------------------------------------- negative control

def test_perturbing_one_price_moves_every_derived_figure():
    base, moved = _risk_book(), _risk_book(extra_b=0.05)
    assert base["value"] != moved["value"]
    rb, rm = P.risk(base), P.risk(moved)
    assert [x["rc_pct"] for x in rb["contribution"]] != \
           [x["rc_pct"] for x in rm["contribution"]]
    ab = {r["symbol"]: r["eur"] for r in P.attribution(base, "1M")}
    am = {r["symbol"]: r["eur"] for r in P.attribution(moved, "1M")}
    assert ab["BBB"] != am["BBB"]
    assert ab["AAA"] == am["AAA"]           # the untouched name does not move
    pb = {r["symbol"]: r["pct"] for r in P.attribution(base, "1M")}
    pm = {r["symbol"]: r["pct"] for r in P.attribution(moved, "1M")}
    assert pb["BBB"] != pm["BBB"]
    assert pb["AAA"] == pm["AAA"]
    tb = P.twr_index(P.daily_returns(base["value"], base["flow"]))
    tm = P.twr_index(P.daily_returns(moved["value"], moved["flow"]))
    assert tb[-1] != tm[-1]


# ------------------------------------------------------- listing & records

def test_listing_currency_counts_unvalued_apart_and_folds_pence():
    rows = [{"ccy": "EUR", "value_eur": 60}, {"ccy": "GBp", "value_eur": 40},
            {"ccy": "USD", "value_eur": None}]
    out = P.listing_currency(rows)
    assert out["rows"] == [{"ccy": "EUR", "eur": 60, "pct": 60.0},
                           {"ccy": "GBP", "eur": 40, "pct": 40.0}]
    assert out["n_unvalued"] == 1


def test_recorded_points_keep_the_last_reading_per_day():
    rows = [{"date": "2025-01-02", "value_eur": 1}, {"date": "2025-01-02", "value_eur": 2},
            {"date": "2025-01-01", "value_eur": 5}, {"date": "2025-01-03"}]
    assert P.recorded_points(rows) == [{"date": "2025-01-01", "value_eur": 5},
                                       {"date": "2025-01-02", "value_eur": 2}]


def test_build_packs_dates_and_flows():
    history = {"AAA": series([10, 10, 11])}
    lots = [lot(ISIN_A, 1, 10, "2025-01-01"), lot(ISIN_A, 1, 10, "2025-01-03")]
    out = P.build(lots, {ISIN_A: "AAA"}, history, {"BENCH.X": series([5, 5, 5])},
                  PAIRS, BENCH)
    assert out["curve"]["d0"] == "2025-01-01"
    assert out["curve"]["dd"] == [0, 1, 1]
    assert out["curve"]["flows"] == [[2, 10.0]]
    assert out["basis"] == "held-lots"
    assert out["benchmark"]["shadow"] == pytest.approx([10, 10, 20])
