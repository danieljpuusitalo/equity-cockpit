"""Tests for the indicator toolkit.

The governing rule of this repo's suite is that a test should be about something
that actually broke, or something that would break silently. Indicators are
unusually good at breaking silently: a wrong RSI still plots a smooth line
between 0 and 100 and looks entirely reasonable, which is why the checks below
are anchored in arithmetic that can be done on paper rather than in a golden
file someone generated with the same code they were testing.

Deliberately NOT here: a table of "expected" values copied off a charting site.
See the `## How this is verified` section of `indicators.py` for why - the
widely-circulated Wilder table could not be sourced, and pinning to numbers of
unknown provenance manufactures confidence instead of testing anything.
"""
import math

import indicators as I

# The standard 33-close example used throughout the RSI literature. Its value
# here is that the first fourteen changes are small enough to add up by hand,
# which is exactly what test_rsi_seed_is_hand_computable does.
CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84,
          46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41,
          46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03,
          44.18, 44.22, 44.57, 43.42, 42.66, 43.13]


def bars_from(closes, volume=1000):
    """OHLCV bars with a plausible intraday range around each close."""
    return [[f"d{i:03d}", c, c + 0.5, c - 0.5, c, volume]
            for i, c in enumerate(closes)]


def wiggle(n, start=100.0):
    """A long, non-monotonic series - enough bars to seed a 26-period EMA."""
    return [start + i * 0.3 + (4.0 if i % 3 == 0 else -2.5 if i % 5 else 1.0)
            for i in range(n)]


# ------------------------------------------------------------------- alignment

def test_every_series_is_aligned_to_its_input():
    """The load-bearing convention: output length == input length, always.

    If this slips, every number on the page is off by one day at the right-hand
    edge - the only edge anybody reads.
    """
    n = len(CLOSES)
    assert len(I.sma(CLOSES, 10)) == n
    assert len(I.ema(CLOSES, 10)) == n
    assert len(I.wilder(CLOSES, 10)) == n
    assert len(I.stdev_pop(CLOSES, 10)) == n
    assert len(I.rsi(CLOSES, 14)) == n
    assert len(I.realised_vol(CLOSES, 10)) == n
    assert len(I.atr(bars_from(CLOSES), 14)) == n
    for series in I.bollinger(CLOSES, 20):
        assert len(series) == n


def test_warm_up_is_none_not_a_partial_value():
    """A half-converged average is worse than no average: it looks like data."""
    assert I.sma(CLOSES, 10)[:9] == [None] * 9
    assert I.sma(CLOSES, 10)[9] is not None
    assert I.rsi(CLOSES, 14)[:14] == [None] * 14
    assert I.rsi(CLOSES, 14)[14] is not None


def test_sma_rolling_sum_matches_the_naive_definition():
    """The rolling-sum optimisation must not drift from mean-of-window."""
    for period in (2, 5, 20):
        fast = I.sma(CLOSES, period)
        for i in range(period - 1, len(CLOSES)):
            window = CLOSES[i - period + 1:i + 1]
            assert abs(fast[i] - sum(window) / period) < 1e-9


# ------------------------------------------------------------------------- rsi

def test_rsi_seed_is_hand_computable():
    """The seed, done on paper.

    The first 14 changes of CLOSES contain gains summing to 3.34 and losses
    summing to 1.40. So avg_gain = 3.34/14, avg_loss = 1.40/14, RS = 2.385714,
    and RSI = 100 - 100/(1 + RS) = 70.4641. Nothing here is taken on trust.
    """
    changes = [CLOSES[i] - CLOSES[i - 1] for i in range(1, 15)]
    gains = sum(c for c in changes if c > 0)
    losses = -sum(c for c in changes if c < 0)
    assert abs(gains - 3.34) < 1e-9
    assert abs(losses - 1.40) < 1e-9

    rs = (gains / 14) / (losses / 14)
    expected = 100.0 - 100.0 / (1.0 + rs)
    assert abs(expected - 70.4641) < 1e-4
    assert abs(I.rsi(CLOSES, 14)[14] - expected) < 1e-12


def test_rsi_matches_an_independently_written_implementation():
    """Same definition, different code. Guards against a clever refactor."""
    def naive(closes, period=14):
        out = [None] * len(closes)
        ups, downs = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i - 1]
            ups.append(d if d > 0 else 0.0)
            downs.append(-d if d < 0 else 0.0)
        au = sum(ups[:period]) / period
        ad = sum(downs[:period]) / period
        out[period] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
        for i in range(period, len(ups)):
            au = au + (ups[i] - au) / period      # written as an increment,
            ad = ad + (downs[i] - ad) / period    # not as the (n-1)/n form
            out[i + 1] = 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)
        return out

    for mine, theirs in zip(I.rsi(CLOSES, 14), naive(CLOSES, 14)):
        assert (mine is None) == (theirs is None)
        if mine is not None:
            assert abs(mine - theirs) < 1e-9


def test_rsi_limits():
    assert I.rsi([100.0 + i for i in range(40)])[-1] == 100.0
    assert I.rsi([200.0 - i for i in range(40)])[-1] == 0.0


def test_rsi_of_a_flat_series_is_neutral_not_overbought():
    """The bug this file was written to catch.

    `avg_loss == 0` alone used to return 100, so a price that had not moved read
    as maximally overbought. Eleven of the twenty-three holdings on this board
    are funds and several repeat a NAV for days, so this is not a corner case
    here - it is Tuesday.
    """
    assert I.rsi([50.0] * 40)[-1] == 50.0
    assert I.rsi_state(I.rsi([50.0] * 40)[-1]) == "neutral"


def test_rsi_stays_in_bounds_on_real_prices():
    values = [v for v in I.rsi(CLOSES, 14) if v is not None]
    assert values, "no RSI produced at all"
    assert all(0.0 <= v <= 100.0 for v in values)


# ---------------------------------------------------------------------- wilder

def test_wilder_is_an_ema_with_alpha_one_over_n():
    values = [float(v) for v in
              [5, 3, 8, 9, 2, 7, 4, 6, 1, 10, 11, 3, 5, 8, 2, 9]]
    got = I.wilder(values, 5)
    prev = sum(values[:5]) / 5
    expected = [None] * 4 + [prev]
    for v in values[5:]:
        prev = prev + (v - prev) / 5
        expected.append(prev)
    for a, b in zip(got[4:], expected[4:]):
        assert abs(a - b) < 1e-12


def test_wilder_is_not_the_same_as_ema_of_the_same_period():
    """The classic silent substitution. If these ever agree, RSI reads hot."""
    values = [float(v) for v in
              [5, 3, 8, 9, 2, 7, 4, 6, 1, 10, 11, 3, 5, 8, 2, 9]]
    spread = max(abs(a - b) for a, b in
                 zip(I.wilder(values, 5)[4:], I.ema(values, 5)[4:]))
    assert spread > 0.1, "wilder() has been replaced by an EMA of period n"


# ------------------------------------------------------------------- bollinger

def test_bollinger_uses_population_stdev():
    """Sample stdev (n-1) is the common wrong variant; it widens the bands."""
    closes = [10.0, 12.0, 14.0, 16.0, 18.0]
    upper, middle, lower, pct_b, width = I.bollinger(closes, 5, k=2.0)
    mean = sum(closes) / 5
    pop_sd = math.sqrt(sum((c - mean) ** 2 for c in closes) / 5)
    assert abs(middle[-1] - mean) < 1e-12
    assert abs(upper[-1] - (mean + 2 * pop_sd)) < 1e-12
    assert abs(lower[-1] - (mean - 2 * pop_sd)) < 1e-12


def test_bollinger_percent_b_locates_the_close():
    closes = [10.0, 12.0, 14.0, 16.0, 18.0]
    upper, _, lower, pct_b, _ = I.bollinger(closes, 5, k=2.0)
    assert abs(pct_b[-1] - (closes[-1] - lower[-1])
               / (upper[-1] - lower[-1])) < 1e-12


def test_bollinger_flat_series_does_not_explode():
    """Zero variance: bands collapse onto the mean, %B is defined, no crash."""
    upper, middle, lower, pct_b, width = I.bollinger([7.0] * 30, 20)
    assert abs(upper[-1] - lower[-1]) < 1e-12
    assert pct_b[-1] == 0.5
    assert abs(width[-1]) < 1e-12


def test_stdev_pop_never_returns_nan_on_a_flat_series():
    """Catastrophic cancellation can make the variance -1e-15 and sqrt() throw."""
    for v in I.stdev_pop([3.14159] * 50, 20):
        assert v is None or (v >= 0.0 and not math.isnan(v))


# ------------------------------------------------------------------------ macd

def test_macd_histogram_is_line_minus_signal():
    line, sig, hist = I.macd(wiggle(80))
    seen = 0
    for m, s, h in zip(line, sig, hist):
        if m is not None and s is not None:
            assert abs(h - (m - s)) < 1e-12
            seen += 1
    assert seen > 0, "signal line never seeded"


def test_macd_returns_aligned_series_when_too_short_to_seed():
    short = CLOSES[:20]
    line, sig, hist = I.macd(short)
    assert len(line) == len(sig) == len(hist) == len(short)
    assert all(s is None for s in sig)


# ------------------------------------------------------------------------- atr

def test_atr_true_range_includes_the_overnight_gap():
    """A gap up with a narrow intraday range must register as a wide true range.

    Day two trades in a one-point band, so high-low alone reports 1.0. The true
    range is measured from the PREVIOUS CLOSE - 110.5 - 100.0 = 10.5 - which is
    the whole point of the word "true" and the thing a plain high-low misses.
    """
    bars = [["d1", 100.0, 100.5, 99.5, 100.0, 1],
            ["d2", 110.0, 110.5, 109.5, 110.0, 1]]
    trs = I.atr(bars, period=1)
    assert trs[0] is None                   # no previous close to gap from
    assert abs(trs[1] - 10.5) < 1e-12       # 110.5 - 100.0, not 110.5 - 109.5


def test_atr_pct_is_relative_to_price():
    snap = I.snapshot(bars_from(CLOSES))
    assert snap["atr"] is not None
    assert abs(snap["atr_pct"] - snap["atr"] / snap["close"] * 100.0) < 1e-9


# -------------------------------------------------------------- vol & drawdown

def test_realised_vol_scales_by_sqrt_time():
    closes = [100.0 * (1.01 ** i) if i % 2 else 100.0 * (0.99 ** i)
              for i in range(60)]
    got = I.realised_vol(closes, 30)[-1]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    window = rets[-30:]
    mean = sum(window) / 30
    sd = math.sqrt(sum((r - mean) ** 2 for r in window) / 30)
    assert abs(got - sd * math.sqrt(I.TRADING_DAYS) * 100.0) < 1e-9


def test_max_drawdown_finds_the_worst_peak_to_trough():
    closes = [100.0, 120.0, 60.0, 90.0, 110.0]
    dd, peak_i, trough_i = I.max_drawdown(closes)
    assert abs(dd - (-50.0)) < 1e-9        # 120 -> 60
    assert (peak_i, trough_i) == (1, 2)


def test_max_drawdown_of_a_monotonic_rise_is_zero():
    dd, _, _ = I.max_drawdown([1.0, 2.0, 3.0, 4.0])
    assert dd == 0.0


# ---------------------------------------------------------------------- volume

def test_volume_absent_is_none_not_zero():
    """Five-element bars mean 'nobody told us', which is not 'nothing traded'."""
    five = [[f"d{i}", 1.0, 1.0, 1.0, 1.0] for i in range(30)]
    assert I.volume_profile(five) is None


def test_volume_relative_to_its_own_average():
    bars = bars_from(CLOSES, volume=1000)
    bars[-1][5] = 3000
    prof = I.volume_profile(bars, period=20)
    assert prof["last"] == 3000
    assert prof["relative"] > 1.5


def test_zero_volume_day_is_kept_as_real_information():
    bars = bars_from(CLOSES, volume=1000)
    bars[-1][5] = 0
    prof = I.volume_profile(bars, period=20)
    assert prof["last"] == 0
    assert prof["relative"] == 0.0


# -------------------------------------------------------------------- snapshot

def test_snapshot_returns_none_for_too_little_data():
    assert I.snapshot([]) is None
    assert I.snapshot(bars_from([10.0])) is None


def test_snapshot_survives_a_short_series_without_raising():
    """A newly-listed name has 30 bars, not 500. Long averages are absent."""
    snap = I.snapshot(bars_from([100.0 + i * 0.1 for i in range(30)]))
    assert snap is not None
    assert snap["sma200"] is None
    assert snap["ma_spread_pct"] is None
    assert snap["rsi"] is not None


def test_snapshot_never_emits_a_recommendation():
    """This board belongs to a value investor. Numbers and states, never a verb.

    The moment a technical reads 'SELL' it starts making the decision the thesis
    is supposed to make - and DESIGN.md lists trade advice as a rule, not a
    missing feature.
    """
    snap = I.snapshot(bars_from(CLOSES))
    banned = {"buy", "sell", "hold", "strong", "signal", "recommend"}
    for key, value in snap.items():
        if isinstance(value, str):
            assert value.lower() not in banned, f"{key} reads as advice"


def test_snapshot_all_skips_symbols_without_bars():
    history = {
        "GOOD": {"bars": bars_from(CLOSES)},
        "EMPTY": {"bars": []},
        "NULL": None,
    }
    out = I.snapshot_all(history)
    assert set(out) == {"GOOD"}


def test_rsi_state_thresholds():
    assert I.rsi_state(70.0) == "overbought"
    assert I.rsi_state(30.0) == "oversold"
    assert I.rsi_state(50.0) == "neutral"
    assert I.rsi_state(None) is None
