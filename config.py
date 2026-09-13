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
# The three new ones are here because they are empty on all 13 rows TODAY. That
# is a migration state, not a permanent one: once a handful of names have been
# re-checked, move them out so the selftest starts guarding them again.
NOTION_PROPS_OPTIONAL = {"Previous verdict", "Net debt/EBITDA", "P/E", "Moat",
                         "Thesis", "Inflection date", "Inflection event"}

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
