"""Thresholds, paths and schema. Deliberately says nothing about what you own.

Everything personal lives in `portfolio.local.json`, which is gitignored: the
account numbers, the ISIN -> Yahoo symbol map, the buckets, and the Notion data
source id. This file and the rest of the repo are publishable as they stand.

That split is not cosmetic. A symbol map is a holdings list - it discloses the
composition of the book even without the sizes - so it cannot live in a file
that gets committed. `portfolio.example.json` documents the schema and is safe.
"""
import json
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
OUT = ROOT / "out"

# --- READ-ONLY. The daily markets briefing depends on this folder. Never write here. ---
PROJECT_DIR = HOME / "Documents" / "Claude" / "Projects" / "Equity Portfolio Assistant"
NORDNET_GLOB = "nordnet-ostoerittain*.csv"

# --- The private half ------------------------------------------------------
PORTFOLIO_FILE = ROOT / "portfolio.local.json"
PORTFOLIO_EXAMPLE = ROOT / "portfolio.example.json"


def _load_portfolio():
    """Read portfolio.local.json, or explain exactly how to create it.

    A missing file is the normal state of a fresh clone, so the error has to
    read like instructions rather than a stack trace. A malformed one is worse
    than missing - it would silently drop holdings - so it raises too.
    """
    if not PORTFOLIO_FILE.exists():
        raise SystemExit(
            f"\n{PORTFOLIO_FILE.name} is missing.\n\n"
            "It holds everything personal - accounts, the ISIN -> Yahoo symbol\n"
            "map, and the Notion data source id - and is deliberately not in\n"
            f"the repo. Copy {PORTFOLIO_EXAMPLE.name} to {PORTFOLIO_FILE.name}\n"
            "and fill it in; that file documents every field.\n")
    try:
        raw = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"\n{PORTFOLIO_FILE.name} is not valid JSON: {exc}\n")
    if not isinstance(raw.get("holdings"), dict) or not raw["holdings"]:
        raise SystemExit(
            f"\n{PORTFOLIO_FILE.name} has no 'holdings' object. Every ISIN in "
            f"your export needs an entry - see {PORTFOLIO_EXAMPLE.name}.\n")
    return raw


_P = _load_portfolio()

# Broker account number -> our label
ACCOUNTS = _P.get("accounts", {})

# ISIN -> Yahoo symbol. None means "no public feed; carry at the broker's value".
# Every one of these is verified against Nordnet's own market value on each run
# by the divergence check (see analyse.price_sanity), so a wrong mapping
# announces itself instead of silently corrupting the book.
YAHOO = {isin: h.get("symbol") for isin, h in _P["holdings"].items()}

# Broad bucket for concentration reporting. Falls back to "Unclassified".
BUCKETS = {isin: h.get("bucket", "Unclassified")
           for isin, h in _P["holdings"].items()}

NAMES = {isin: h.get("name", "") for isin, h in _P["holdings"].items()}

# 'stock' is judged by thesis - a target, a trigger, a written reason to hold.
# 'fund' is judged by allocation - a target weight and a drift band. Demanding
# a falsifiable thesis from a world index tracker produces a permanent, useless
# warning, which is how a monitoring system teaches you to ignore it.
ASSET_CLASS = {isin: (h.get("class") or "stock").lower()
               for isin, h in _P["holdings"].items()}

# Funds only. None means "no policy written yet", which is reported as an open
# gap rather than filled in with the current weight - seeding a target from
# today's number would turn every drift check into a tautology.
TARGET_WEIGHT = {isin: h.get("target_weight_pct")
                 for isin, h in _P["holdings"].items()}

FX_PAIRS = {"USD": "EURUSD=X", "SEK": "EURSEK=X", "DKK": "EURDKK=X",
            "NOK": "EURNOK=X", "GBP": "EURGBP=X"}

# --- Notion ---
# Live reads need NOTION_TOKEN (a Notion internal integration token) in the
# environment or in .env next to this file. Without it the cockpit falls back
# to state/equity-log.json, which Claude refreshes over MCP on request.
EQUITY_LOG_DATA_SOURCE = _P.get("equity_log_data_source", "")
EQUITY_LOG_CACHE = STATE / "equity-log.json"

# Allocation drift: how far a fund may sit from its target weight before the
# cockpit says so. Only meaningful for holdings that have a target weight set.
WEIGHT_DRIFT_PCT = 3.0

# --- Price history (the charts) ---
# Fetched once a day per symbol and kept on disk, so the page has a real series
# without asking Yahoo for two years of bars on every run. Two years is what the
# ALL range shows; 1Y/6M/3M/1M are slices of the same cache, not extra fetches.
PRICE_HISTORY_CACHE = STATE / "price-history.json"
PRICE_HISTORY_PERIOD = "2y"

# --- Fundamentals (the multiples, live) ---
# P/E, Fwd P/E and Net debt/EBITDA are typed into Notion by hand at eval time
# and then decay silently - the board showed a P/E from June with nothing to say
# it was from June. Yahoo returns all three free, so the page can show the
# recorded figure next to today's and let you see the gap.
#
# Measured 2026-09-18 rather than assumed: .info answers in 0.24-0.56s per
# symbol (18/18 fields on NOKIA.HE, 17/18 on QTCOM.HE and HAYPP.ST), so the
# whole board costs about seven seconds. Funds return nothing - XAIX.DE 0/18,
# IMAE.AS 2/18 - which is why they are not asked; a tracker has no multiple and
# the coverage model already judges it by weight instead.
FUNDAMENTALS_CACHE = STATE / "fundamentals.json"
# How far the recorded multiple may sit from the live one before the cockpit
# says the valuation case is stale. A P/E is a fast-moving number; this is
# deliberately wide, because the alert is about a figure nobody has revisited,
# not about a day's move.
MULTIPLE_DRIFT_PCT = 25.0

# --- Fund composition (the look-through) ---
# What a fund is actually made of, so the book can be read by sector and by
# underlying name rather than by the ticker that happens to wrap it. Separate
# cache from fundamentals because it is the exact inverse population: funds
# only, and fetched through yfinance's `.funds_data` rather than `.info`.
#
# Measured 2026-09-20 across all eight exchange-traded funds in the book, not
# assumed:
#   sector_weightings  8/8, and in the SAME 11-sector taxonomy `.info` returns
#                      for a stock - so the two compose with no mapping layer
#   top_holdings       8/8, but capped at TEN ROWS by Yahoo, which is the whole
#                      reason RESOLVED_* below exist. Ten rows is 82.8% of
#                      WDEF.MI and 12.2% of EXUS.DE. A look-through that did not
#                      publish that spread would quietly read a concentrated
#                      thematic as the whole market.
#   fund_operations    7/8 carry a TER (WDEF.MI returns NA)
#
# Two traps found in the same measurement, both this repo's signature bug class:
#   - The `equity_holdings` valuation rows are YIELDS, not ratios. Yahoo returns
#     P/E 0.04437 for XAIX.DE, which is 22.5x inverted. Rendered raw it is a
#     multiple off by three orders of magnitude that still looks like a number.
#   - `Annual Holdings Turnover` reads 0.0 for seven of the eight, including a
#     defence thematic that certainly trades. That is "not reported" served as
#     zero. It is NOT read here, and it should not be added later without a
#     source that distinguishes absent from nil.
FUND_COMPOSITION_CACHE = STATE / "fund-composition.json"

# Reporting record and the next scheduled date, per directly-held stock.
# Funds are excluded at the caller: Yahoo answers a fund with a 404 for this
# endpoint, measured, so asking would buy eleven guaranteed failures a run.
EARNINGS_CACHE = STATE / "earnings.json"

# How far ahead the reporting calendar looks. Set to a full quarter after 28
# days was tried and measured: on 2026-09-20 it showed ZERO prints across
# thirteen holdings, because Q3 season had not started and the nearest date was
# 33 days out. A calendar that is empty for six weeks of every quarter is a
# calendar nobody opens. The estimated-date flag is what guards the far end,
# not a short horizon.
EARNINGS_HORIZON_DAYS = 120
# A report inside this window is worth a line on the board. Seven days is the
# span in which a position can still be trimmed before the print.
EARNINGS_SOON_DAYS = 7
# Below this, a beat or a miss is rounding and consensus noise, not news.
EARNINGS_SURPRISE_PTS = 10.0

# Property names we read out of the Equity Log, exactly as Notion spells them.
# If Notion renames one of these, selftest fails loudly and by name rather than
# silently returning None forever. (Verified against the live board 2026-09-13:
# the date column is "Last evaluated", not "Last eval".)
NOTION_PROPS = ["Ticker", "Company", "Verdict", "Tier", "Held", "Currency",
                "Price at eval", "Target", "Last evaluated", "Next check",
                "Trigger", "Market", "Moat", "P/E", "Fwd P/E",
                "Net debt/EBITDA", "Previous verdict", "Evaluations",
                # Added 2026-09-13, empty on every legacy row. Trigger used to
                # carry all three of these plus the falsifying condition in one
                # paragraph, which is why only 6 of 13 rows parsed as a price
                # level and why the inflection dates written in that prose
                # ("late Oct 2026") were unreadable. They fill in as each name
                # is next checked; the ledger is Equity Checks.
                "Thesis", "Inflection date", "Inflection event"]

# Properties that are allowed to be empty on every row without that counting as
# a schema break (they are genuinely optional on the board).
#
# "Thesis", "Inflection date" and "Inflection event" sat here from 2026-09-13
# until 2026-09-18 because they were empty on all 13 legacy rows and a
# non-optional property that is None everywhere reads as a rename. That was a
# migration state and it is over: the board now carries 23 rows, 10 of them
# with a thesis and a real inflection date, so the guard can do its job. If one
# of the three ever goes missing in Notion, the selftest says which - which is
# the whole reason this list exists.
NOTION_PROPS_OPTIONAL = {"Previous verdict", "Net debt/EBITDA", "P/E", "Moat"}

# --- Telegram (reuses the existing bot; no new credential) ---
TELEGRAM_ENV = HOME / ".claude" / "channels" / "telegram" / ".env"
TELEGRAM_CHAT_ID = "931151446"

# --- Thresholds: what counts as worth telling you about ---
CSV_STALE_DAYS = 30          # nag to re-export from Nordnet after this
RUN_STALE_DAYS = 3           # heartbeat: the cockpit itself has gone quiet
PRICE_DIVERGENCE_PCT = 12.0  # live price vs Nordnet's own value -> bad mapping
TRIGGER_NEAR_PCT = 10.0      # "approaching a written trigger"
CHECK_SOON_DAYS = 14         # "catalyst coming up"
DECAY_ALERT_PTS = 8.0        # upside moved this many points since the eval
