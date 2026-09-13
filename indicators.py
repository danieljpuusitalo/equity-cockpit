"""Technical indicators, computed here rather than in the browser.

The house rule from `render.py` applies: nothing is computed in the page that
could have been computed in Python. The page displays, it does not decide. The
one deliberate exception is the chart's moving-average overlay, which has to be
recomputed as you zoom.

## Two conventions that everything here depends on

**1. Output is aligned to input.** Every series function returns a list the same
length as what it was given, left-padded with `None` through the warm-up period.
`rsi(closes)[i]` is the RSI *of* `closes[i]`. No silent trimming, no offset to
remember at the call site. This is not the most compact representation, and it is
chosen on purpose: the alternative - returning a short list and asking the caller
to line it up - is exactly the shape that produces off-by-one bugs which look
plausible on a chart and are wrong by one day at the right-hand edge, which is
the only edge anybody reads.

**2. Wilder's smoothing is not an EMA with a different period.** RSI and ATR use
Wilder's recursive average (`prev * (n-1)/n + new/n`), seeded with a simple mean
of the first `n` values. It is *equivalent* to an EMA of period `2n-1`, and a
great many implementations quietly substitute a standard EMA of period `n`,
which is wrong and reads several points hotter. `test_indicators.py` asserts
that `wilder(5)` and `ema(5)` disagree, so that substitution cannot be made
silently.

## How this is verified, and what it is NOT verified against

An earlier draft of this docstring claimed the suite pinned RSI against
"Wilder's own published worked example". It does not, and the claim was removed
rather than quietly softened. The widely-circulated table attributed to Wilder's
1978 book could not be sourced to a copy of the book, and our output sits about
0.05 away from it with a non-monotonic error pattern - which is the signature of
a transcription variant, not of a seed bug. Pinning tests to numbers of unknown
provenance would have manufactured false confidence.

What the suite does instead, all of which is checkable from first principles:

- the **seed is verified by hand** - over the standard 33-close example the
  first 14 changes give gains summing to 3.34 and losses to 1.40, so the seed
  RSI is `100 - 100/(1 + (3.34/14)/(1.40/14))` = 70.4641, which is what `rsi()`
  returns to fourteen decimal places;
- a **second, independently written implementation** of the same definition
  agrees to 1.4e-14;
- `wilder(n)` is asserted identical to an EMA with `alpha = 1/n`, and distinct
  from `ema(n)`;
- the algebraic limits (all-up -> 100, all-down -> 0, flat -> 50) hold.

## Sourcing

- RSI - J. Welles Wilder, *New Concepts in Technical Trading Systems* (1978).
- Bollinger Bands - John Bollinger. **Population** standard deviation (divide by
  n, not n-1). Bollinger is explicit about this; sample stdev is a common and
  subtly wrong variant that widens the bands on short windows.
- MACD - Gerald Appel, 12/26/9 on EMAs.
- ATR - Wilder, true range including the previous close.
"""

import math

# The number of trading days in a year, used to annualise volatility. 252 is the
# convention: 365 less weekends and about nine holidays.
TRADING_DAYS = 252


# ------------------------------------------------------------------ primitives

def _closes(bars):
    """Closing prices from OHLCV bars."""
    return [b[4] for b in bars]


def sma(values, period):
    """Simple moving average, aligned to input, as a rolling sum.

    One pass: 500 values cost 500 additions rather than 500 * period.
    """
    if period <= 0:
        return [None] * len(values)
    out, total = [], 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        out.append(total / period if i >= period - 1 else None)
    return out


def ema(values, period):
    """Exponential moving average, aligned to input, seeded with an SMA.

    Seeding matters and is not standardised in the wild. Three options exist:
    start from the first value, start from an SMA of the first `period` values,
    or recurse from the very beginning with no warm-up. We use the SMA seed,
    which is what Appel's MACD and most charting packages use, and we emit
    `None` before the seed rather than a partially-converged number.
    """
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    k = 2.0 / (period + 1.0)
    out = [None] * (period - 1)
    prev = sum(values[:period]) / period
    out.append(prev)
    for v in values[period:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def wilder(values, period):
    """Wilder's smoothed average, aligned to input.

    `prev * (period - 1) / period + new / period`, seeded with a simple mean.
    Used by RSI and ATR. NOT interchangeable with `ema(values, period)`.
    """
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    out = [None] * (period - 1)
    prev = sum(values[:period]) / period
    out.append(prev)
    for v in values[period:]:
        prev = (prev * (period - 1) + v) / period
        out.append(prev)
    return out


def stdev_pop(values, period):
    """Rolling POPULATION standard deviation, aligned to input.

    Divides by n. This is what Bollinger Bands use. Computed from the rolling
    sum of squares, with a clamp at zero because catastrophic cancellation can
    otherwise produce a variance of -1e-15 and a math domain error on a flat
    series - which is exactly what a fund that has not moved for a week looks
    like.
    """
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    out = [None] * (period - 1)
    total = sum(values[:period])
    total_sq = sum(v * v for v in values[:period])
    out.append(math.sqrt(max(total_sq / period - (total / period) ** 2, 0.0)))
    for i in range(period, len(values)):
        old, new = values[i - period], values[i]
        total += new - old
        total_sq += new * new - old * old
        out.append(math.sqrt(max(total_sq / period - (total / period) ** 2, 0.0)))
    return out


# ------------------------------------------------------------------ indicators

def rsi(closes, period=14):
    """Wilder's Relative Strength Index, aligned to input.

    `RSI = 100 - 100 / (1 + avg_gain / avg_loss)` on Wilder-smoothed averages of
    the up and down closes.

    Two zero cases, and they are not the same case:

    - **No losses, some gains** -> 100. An instrument that has not fallen once in
      the window genuinely is at the top of the scale; 100 is the defined limit,
      not a sentinel.
    - **No losses and no gains** -> 50. A price that has not moved at all is
      neutral, not maximally overbought. Treating `avg_loss == 0` alone as the
      test reports 100 for a flat series, which is the single most likely way
      this module could have lied on this particular board: eleven of the
      twenty-three holdings are funds, several are thinly-priced UCITS lines
      that repeat a NAV for days at a time, and "RSI 100, overbought" on a
      holding that has not moved is a number a person might act on.
    """
    n = len(closes)
    if period <= 0 or n < period + 1:
        return [None] * n

    gains, losses = [], []
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = wilder(gains, period)
    avg_loss = wilder(losses, period)

    # gains[i] describes closes[i+1], so shift by one to realign to the input.
    out = [None]
    for g, l in zip(avg_gain, avg_loss):
        if g is None or l is None:
            out.append(None)
        elif l == 0:
            # Flat series: no losses AND no gains. Neutral, not overbought.
            out.append(50.0 if g == 0 else 100.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + g / l))
    return out


def bollinger(closes, period=20, k=2.0):
    """Bollinger Bands. Returns (upper, middle, lower, percent_b, bandwidth).

    `percent_b` locates the price within the bands: 0 is the lower band, 1 the
    upper, and values outside [0, 1] mean the close is outside the bands. It is
    the number worth reading - an "upper band touch" is `%B >= 1`, not an
    eyeballed chart.

    `bandwidth` is (upper - lower) / middle, the standard squeeze measure.
    """
    middle = sma(closes, period)
    sd = stdev_pop(closes, period)
    upper, lower, pct_b, width = [], [], [], []
    for close, m, s in zip(closes, middle, sd):
        if m is None or s is None:
            upper.append(None); lower.append(None)
            pct_b.append(None); width.append(None)
            continue
        up, low = m + k * s, m - k * s
        upper.append(up); lower.append(low)
        span = up - low
        pct_b.append((close - low) / span if span else 0.5)
        width.append(span / m if m else None)
    return upper, middle, lower, pct_b, width


def macd(closes, fast=12, slow=26, signal=9):
    """MACD. Returns (macd_line, signal_line, histogram), all aligned to input.

    The signal line is an EMA of the MACD line, which only exists after the slow
    EMA has seeded. We therefore run the signal EMA over the *defined* part of
    the MACD line and pad it back out, rather than feeding it a list with holes
    in it.
    """
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [None if f is None or s is None else f - s
            for f, s in zip(fast_ema, slow_ema)]

    defined = [v for v in line if v is not None]
    if len(defined) < signal:
        return line, [None] * len(closes), [None] * len(closes)

    offset = len(line) - len(defined)
    sig = [None] * offset + ema(defined, signal)
    hist = [None if m is None or s is None else m - s for m, s in zip(line, sig)]
    return line, sig, hist


def atr(bars, period=14):
    """Average True Range, Wilder-smoothed, aligned to input.

    True range is the greatest of: today's high-low, |high - previous close|,
    and |low - previous close|. The previous close is what makes it a *true*
    range - it captures the overnight gap that a plain high-low misses.
    """
    n = len(bars)
    if n < 2:
        return [None] * n
    trs = []
    for i in range(1, n):
        high, low = bars[i][2], bars[i][3]
        prev_close = bars[i - 1][4]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return [None] + wilder(trs, period)


def realised_vol(closes, period=30):
    """Annualised realised volatility from log returns, aligned to input.

    Population stdev of daily log returns times sqrt(252), as a percentage.
    Log returns rather than simple returns because they are additive over time,
    which is what makes the sqrt-of-time scaling valid.
    """
    n = len(closes)
    if n < 2:
        return [None] * n
    rets = []
    for i in range(1, n):
        prev, now = closes[i - 1], closes[i]
        rets.append(math.log(now / prev) if prev > 0 and now > 0 else 0.0)
    sd = stdev_pop(rets, period)
    return [None] + [None if s is None else s * math.sqrt(TRADING_DAYS) * 100.0
                     for s in sd]


def max_drawdown(closes):
    """Worst peak-to-trough fall in the series, as a negative percentage.

    Returns (drawdown_pct, peak_index, trough_index) or (None, None, None).
    """
    if len(closes) < 2:
        return None, None, None
    peak, peak_i = closes[0], 0
    worst, worst_peak, worst_trough = 0.0, 0, 0
    for i, c in enumerate(closes):
        if c > peak:
            peak, peak_i = c, i
        elif peak > 0:
            draw = (c / peak - 1.0) * 100.0
            if draw < worst:
                worst, worst_peak, worst_trough = draw, peak_i, i
    if worst == 0.0:
        return 0.0, 0, 0
    return worst, worst_peak, worst_trough


def volume_profile(bars, period=20):
    """Latest volume against its own recent average.

    Returns a dict, or None when the feed carries no volume at all - which is
    the normal case for European mutual funds and some UCITS ETF lines, and is
    reported as absent rather than as zero. Zero would be a lie: it would read
    as "nothing traded" instead of "nobody told us".
    """
    vols = [b[5] for b in bars if len(b) >= 6 and b[5] is not None]
    if len(vols) < 2:
        return None
    recent = vols[-period:] if len(vols) >= period else vols
    avg = sum(recent) / len(recent)
    last = vols[-1]
    return {
        "last": last,
        "avg": avg,
        "period": len(recent),
        # 1.0 means an average day. 2.0 means twice the recent norm.
        "relative": (last / avg) if avg else None,
    }


def range_position(bars, window=TRADING_DAYS):
    """Where the last close sits in its own high-low range over `window` bars.

    0 is the low of the range, 100 the high. Uses intraday highs and lows, not
    closing extremes, so it agrees with the "52-week high" a broker quotes.
    """
    tail = bars[-window:] if len(bars) > window else bars
    if not tail:
        return None
    high = max(b[2] for b in tail)
    low = min(b[3] for b in tail)
    close = tail[-1][4]
    if high == low:
        return None
    return {"high": high, "low": low,
            "pct": (close - low) / (high - low) * 100.0,
            "days": len(tail)}


# -------------------------------------------------------------------- snapshot

def _last(series):
    """Most recent non-None value, or None. The tail of an aligned series."""
    for v in reversed(series):
        if v is not None:
            return v
    return None


def rsi_state(value):
    """Wilder's own thresholds. Descriptive, not advice."""
    if value is None:
        return None
    if value >= 70:
        return "overbought"
    if value <= 30:
        return "oversold"
    return "neutral"


def snapshot(bars, rsi_period=14, bb_period=20):
    """Every indicator's latest value for one symbol, or None if too little data.

    Deliberately returns numbers and plain descriptive states, never a buy or
    sell. This board belongs to a value investor: RSI at 72 is context for a
    thesis, not a reason to trade, and the moment it renders as "SELL" it starts
    making decisions the thesis is supposed to make.
    """
    if not bars or len(bars) < 2:
        return None
    closes = _closes(bars)

    up, mid, low, pct_b, width = bollinger(closes, bb_period)
    line, sig, hist = macd(closes)
    rsi_now = _last(rsi(closes, rsi_period))
    dd, _, _ = max_drawdown(closes)

    last_close = closes[-1]
    sma50, sma200 = _last(sma(closes, 50)), _last(sma(closes, 200))
    atr_now = _last(atr(bars))

    return {
        "asof": bars[-1][0],
        "close": last_close,
        "bars": len(bars),

        "rsi": rsi_now,
        "rsi_state": rsi_state(rsi_now),
        "rsi_period": rsi_period,

        "bb_upper": _last(up),
        "bb_mid": _last(mid),
        "bb_lower": _last(low),
        "bb_pct_b": _last(pct_b),
        "bb_width": _last(width),
        "bb_period": bb_period,

        "macd": _last(line),
        "macd_signal": _last(sig),
        "macd_hist": _last(hist),

        "atr": atr_now,
        # ATR as a percentage of price is the comparable form: 3 dollars of
        # daily range means nothing until you know whether the share is 20 or
        # 500, and this board holds both.
        "atr_pct": (atr_now / last_close * 100.0
                    if atr_now is not None and last_close else None),

        "vol_30d": _last(realised_vol(closes, 30)),
        "max_drawdown_pct": dd,

        "sma50": sma50,
        "sma200": sma200,
        # Positive means the short average is above the long one. Reported as a
        # spread in percent rather than as a "golden cross" flag, because the
        # distance carries information the boolean throws away.
        "ma_spread_pct": ((sma50 / sma200 - 1.0) * 100.0
                          if sma50 and sma200 else None),
        "above_sma200_pct": ((last_close / sma200 - 1.0) * 100.0
                             if sma200 else None),

        "volume": volume_profile(bars),
        "range": range_position(bars),
    }


def snapshot_all(history):
    """`{symbol: snapshot}` for every symbol with usable bars."""
    out = {}
    for symbol, series in (history or {}).items():
        bars = (series or {}).get("bars")
        if not bars:
            continue
        snap = snapshot(bars)
        if snap:
            out[symbol] = snap
    return out
