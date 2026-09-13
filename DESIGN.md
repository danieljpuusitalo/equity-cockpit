# Design notes

`README.md` says how to use it. This says why it is shaped the way it is, so
that a change made in six months does not quietly undo a decision made
deliberately.

Built 2026-09-13. Listed in the dev portal (`~/dev-dashboard/index.html`) under
Personal Projects; the architecture diagram there is generated from
`buildEquityCockpit()` and the numbers are written by `sync.ps1`.

---

## Why it exists

Before building anything, the market was surveyed: Parqet, Getquin, Snowball
Analytics, Simply Wall St, Sharesight. They are all **performance** trackers.
Every one of them will tell you what a position is worth and what it has
returned. None of them stores the three things that actually decay:

- the **target** you wrote down,
- the **thesis** behind it,
- the **condition that would falsify it**.

Daniel's Notion Equity Log holds the target and the verdict as real fields. The
other two live inside one prose property, `Trigger` — there is **no thesis
field**. This was assumed when the cockpit was built and only checked
afterwards, which is how 88% of the book sat with nothing to falsify while three
layers were built on top of the Log. The correction is recorded here rather than
edited away: *check the board, do not describe it from memory*.

Still, storage was never the real gap — the gap is that nothing holds the Log
against reality. So the cockpit is a **join**, not a tracker: Nordnet says what
is owned, Yahoo says what it is worth, Notion says what was decided, and the
only output is *where the three disagree*.

Nordnet support was the second filter — none of the above imports it, and the
CSV export is the only interface to the broker that we control.

---

## The load-bearing decisions

### 1. Deterministic core, Claude only for judgement

The Python core reads, prices, joins, renders and notifies. It runs under
Windows Task Scheduler at **zero token cost** and does not need Claude to be
running. Re-running an *Equity Validity Check* — the part that requires reading
a filing and forming a view — stays a Claude skill, invoked when the core flags
something.

Machines watch, Claude thinks. Inverting this would make the whole thing cost
tokens every morning to tell you nothing changed.

### 2. ISIN is the join key, never the ticker

Tickers get renamed and relisted; ISINs do not. `config.py` maps ISIN → Yahoo
symbol in one place. A ticker table keyed on ticker would silently mismatch the
day an exchange changes a suffix.

### 3. The price-sanity cross-check

The Nordnet export carries its own `Markkina-arvo (EUR)` per lot. Comparing the
live valuation against it validates every ISIN → Yahoo mapping for free — no
second data source, no API key. `PRICE_DIVERGENCE_PCT = 12`.

This is what caught the bad WDEF mapping on the first live run. It is the single
highest-value check in the system and it cost nothing.

### 4. Triggers get two guards

Trigger fields are written in prose, so a parser has to be conservative:

- **unit reject** — `EUR 70M`, `$8bn`, `20%`, `3.0x` are not price levels
- **plausibility band** — a parsed level must land in `[0.4×, 2.5×]` of the
  reference price, or it is discarded

Both were added after real false CRITICALs on TNOM.HE and TTWO. A wrong level is
worse than no level: it trains you to ignore the alerts. 6 of 13 trigger strings
currently parse; the other 7 are deliberately left unparsed rather than guessed.

### 5. One vendored chart library, and only because it earned it

**Superseded 2026-09-13.** The original decision was *no chart library*: three
static bar charts did not justify ~1 MB of ECharts, and a CDN `<script>` tag is
a dependency that breaks **silently** three years from now when the URL moves.
That reasoning was right for what the page then was.

What changed is the page. It is now a three-pane terminal whose middle pane is
two years of daily OHLC with a target line and a trigger line on it, and
hand-rolling candles, a crosshair, a price axis and time ranges is not 120 lines
— it is a chart library, just a worse one. The wheel became load-bearing.

The choice is **TradingView Lightweight Charts v4.2.3**, Apache-2.0, 160 KB,
zero dependencies. Two constraints survive from the old decision and both are
enforced:

- **Vendored, not linked.** The file sits in `assets/` and `render.py` inlines
  it into the output. There is no network call at view time, so the page still
  opens on a plane and still works in five years. Updating it means replacing
  one file; there is still no build step.
- **It must fail loudly.** `selftest` asserts the file is present and over
  100 KB, and `render.write()` refuses to produce a page without it. A missing
  chart library is the exact silent half-render this repo is built to prevent.

Price history is fetched once a day per symbol and cached in
`state/price-history.json`, so the 07:40 run asks Yahoo for two years of bars
only when it does not already hold today's. `1M/3M/6M/1Y/ALL` are slices of that
one cache, not five more fetches.

### 5b. The plotted colours are computed, not chosen

Four colours are drawn: candle up, candle down, target line, trigger line. Each
pair was run through the dataviz validator in **both** light and dark mode —
lightness band, chroma floor, CVD separation, normal-vision floor, contrast
against that mode's surface. All pass; the values are recorded in a comment at
the top of the template. Do not hand-tune them, and re-run the validator if you
change one.

Target and trigger also differ by **line style** (solid vs dashed) and both
carry an axis label with the word on it, so the two are never told apart by
colour alone.

### 5c. The repo is publishable; the book is not

Added 2026-09-13, when this became a git repo. The constraint is that the code
can be public while the holdings never are, and the way to hold both is that
exactly **one** gitignored file — `portfolio.local.json` — knows what is owned.
Everything else works off ISINs read from the broker export at run time.

A symbol map is a holdings list. It discloses the composition of the book even
without the sizes, so it cannot sit in `config.py`. What stayed in `config.py`
is thresholds, paths and the Notion property schema — none of which says
anything about the portfolio.

The load-bearing part is that this is a property of the **file layout**, not of
the code, so nothing in the language stops a later edit from pasting a symbol
map back into a committed file. A public commit cannot be unpublished. So
`selftest` scans every committable file for ISINs and account numbers on every
run and fails by filename. It found a real leak the first time it ran: the test
fixtures asserted against the real `ACCOUNTS` and `YAHOO` maps, which put live
account numbers into `tests/` *and* meant the suite could only pass on this one
machine. Both were fixed by giving the tests fixture identifiers.

### 5d. Funds are judged by allocation, stocks by thesis

Of 23 holdings, 11 are index or thematic funds. Asking "what would falsify your
thesis on a world ex-US tracker" produces a warning that can never be cleared,
and a permanent warning is indistinguishable from no warning. So `class` in
`portfolio.local.json` splits them: a **stock** owes a target, a trigger and a
reason; a **fund** owes a target weight and stays inside a drift band
(`WEIGHT_DRIFT_PCT = 3.0`).

`target_weight_pct` starts as `null` rather than seeded from the current weight.
Seeding it from today's number would make every drift check trivially pass on
day one — a policy that agrees with whatever you already did is not a policy.
Unset weights are reported as an open gap.

### 6. Every source degrades; none raises

`sources.py` is the only file that touches the outside world, and a failing
source marks itself stale rather than aborting the run. A morning where Yahoo is
down should still produce a dashboard that says "Yahoo is down", not nothing.

### 7. The Notion read has two backends

Live REST (`POST /v1/data_sources/{id}/query`, `Notion-Version: 2025-09-03`)
when `NOTION_TOKEN` is set; otherwise the `state/equity-log.json` cache that
Claude refreshes over MCP. **Neither path blocks the other.** The cache path is
fully supported, not a fallback to apologise for.

No paid Notion plan is required — an internal integration token works on the
Free plan. (The docs note PAT creation is *restricted* on Business and
Enterprise, which is the opposite of a paywall.) **Live since 2026-09-13**:
token in `.env`, verified 13 rows via live with the schema check passing.

Building the cache path first was not wasted work. It is what the run falls back
to when a token is rotated or the integration is disconnected, and it is why
adding the token was a one-line change rather than a rewrite.

### 8. Telegram only on change

`critical` and `warning` only, once per alert, with a 7-day cooldown before the
same alert may repeat. A system that messages you every morning gets muted
inside a fortnight, and a muted alarm is worse than no alarm. Verified live: the
second run of the day sent nothing and logged "8 already known".

### 9. `run.ps1` probes rather than trusts

This machine has several Pythons and only `Python312-arm64` has yfinance.
`run.ps1` tests each candidate with `import yfinance` and picks the one that
works, instead of hardcoding a path that will be wrong after the next upgrade.
`selftest` checks this first, because it is the failure the scheduler is most
likely to hit.

---

## What is deliberately not built

- **Any trade execution or money movement.** Not a missing feature; a rule.
  The cockpit reports that a condition you wrote down has been met. The decision
  and the order stay with Daniel.
- **Tax-loss harvesting suggestions.** The OST makes it moot.
- **A hosted/shared version.** Holdings, cost basis and account numbers are
  personal financial data and stay on this machine.
- **Performance attribution, benchmarking, factor analysis.** Those are the
  things every other tracker already does well.

---

## Where it can rot, and what stands in the way

| What rots | What catches it |
|---|---|
| Yahoo renames or drops a ticker | per-symbol fetch; the position goes stale, the run completes |
| A ticker maps to the wrong company | cross-check against Nordnet's own market value, 12% |
| Nordnet changes its CSV columns | the 16-column header is asserted by name |
| A Notion property is renamed | `notion_schema_ok()` names the field that went empty |
| The scheduled task stops firing | heartbeat in `state/last_run.json`; page and Telegram both say so |
| The CSV export goes stale | age shown every run, warned past 30 days |
| A prose trigger is misread | unit reject + plausibility band |
| History is silently corrupted | `state/history.jsonl` is append-only, never rewritten |
| The vendored chart library goes missing | `selftest` checks it; `render.write()` refuses to build without it |
| The price-history cache is corrupted | a cache that will not parse is discarded, not trusted; the run refetches |
| Yahoo stops returning bars for a symbol | the last good series is kept and counted in `history_problems`; the chart is a day old, not gone |
| Holdings creep back into a committable file | `selftest` greps every non-ignored file for ISINs and account numbers and fails by filename |
| `portfolio.local.json` goes missing on a fresh clone | `config.py` exits with instructions naming the example file, not a `KeyError` |

`selftest` is 18 offline checks over exactly these. `doctor` answers "what is
wrong" in English. Both are cheaper to run than to read the code.

---

## Verified at build time

- `run.ps1 selftest` → 18/18
- `pytest tests -q` → 23 passed, with no real ISIN or account number in any of them
- `git grep --cached` over the staged tree → no account number, no ISIN, no token
- `node tests/smoke.mjs out/dashboard.html` → SMOKE OK
- the chart palette validated in both modes, every check PASS
- the page opened in a browser and looked at in light **and** dark — which is
  how the two bugs below were found, neither of which any test would have caught:
  a `1Y` button that showed fifteen months (it sliced 365 *rows*, and rows are
  trading days), and a pane height built from `calc(100% - 52px - 37px)` when the
  banner's height depends on how many problems there are that morning
- second run of the day pulled **0** symbols from Yahoo and read 30 from the
  history cache — the cache is doing its job, not just existing
- Scheduled task `EquityCockpit` fired twice manually, `LastTaskResult 0` both
  times; first run messaged once, second sent nothing — dedupe proven live
- 30/30 symbols priced across 23 positions / 56 lots / two accounts
- ~1,800 lines of Python/PowerShell/JS across the repo, plus one vendored
  160 KB library that nobody here maintains

The tests are built from real strings out of the Equity Log and real rows out of
the Nordnet export, including the ones that produced false alerts on day one. A
test that is not about something that actually broke is decoration.
