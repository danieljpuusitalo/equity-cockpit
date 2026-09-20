# Equity cockpit

A dashboard that holds three things against each other and reports where they
disagree:

- **Nordnet** knows what you actually own (the `ostoerittain` CSV export).
- **Yahoo** knows what it is worth today.
- **The Notion Equity Log** knows what you decided — the verdict, the target,
  and a `Trigger` paragraph carrying the reasoning and the condition that would
  change your mind.

Every portfolio tracker on the market does the first two. The third — the part
that decays silently — falls in a gap: the products that track a written thesis
(Helm, MyThesis, and a handful of 2025–26 startups) are **US tickers only**, and
the products that cover Helsinki and Stockholm do performance accounting, not
conviction. Nor does any of them sync Nordnet; the external API has been closed
to new customers for years, so every one is a CSV round-trip. This exists for
that intersection.

One caveat, measured rather than assumed: the Log has **no separate thesis
field**. `Trigger` is doing four jobs at once — falsifying condition, metric,
date and reasoning, in one block of prose averaging 186 characters. That is why
only 6 of 13 rows parse into a price level, and why the inflection dates already
written there ("late Oct 2026", "December pre-close update") are invisible to
the machine. Splitting it is on the list, not done.

It runs itself on a schedule, at no token cost, and messages you only when
something changed.

---

## Daily use

You do not need to do anything. A scheduled task runs on weekday mornings,
regenerates `out/dashboard.html`, and sends a Telegram message **only if
something is new**. Open the dashboard when you want it:

```
%USERPROFILE%\equity-cockpit\out\dashboard.html
```

### Reading the page

It is one screen in three panes, and picking a name on the left drives the other
two.

| Pane | What it is for |
|---|---|
| **Left** | every name you hold or watch. Filter by `All / Held / Watch / Flagged`, or type in the box. A coloured dot means that name has a flag. Arrow keys walk the list. |
| **Middle** | two years of daily candles, with your **target** drawn as a solid green line and your **trigger** as a dashed amber one, both labelled on the price axis. `1M 3M 6M 1Y ALL` reframe it. The strip underneath is every position sized by weight — click a block to jump to it. |
| **Right** | what you decided. Verdict, tier, target, upside now against upside at the time you wrote it, how far the thesis has drifted, the trigger in your own words, and any flags on that name. |

The top bar carries the whole book: value, P/L, how many names, how many flags,
how old the CSV is, and whether Notion was read live or from cache. A row under
it appears only when something needs attention.

**Data** (top right) opens every number on the page as plain tables — holdings,
the Equity Log, flags, and where each figure came from. **Dark** flips the theme.

Manual commands, from this folder:

```powershell
.\run.ps1              # full run: read, price, analyse, render, notify
.\run.ps1 run --quiet  # same, but never message Telegram
.\run.ps1 refresh      # re-price and re-render only — no Notion, no Telegram
.\run.ps1 selftest     # offline wiring checks — does anything still hold?
.\run.ps1 doctor       # what is stale, missing or drifting, in English
```

Always go through `run.ps1`, never bare `python`. This machine has several
Pythons and only one of them has `yfinance`; `run.ps1` finds the one that works
and fails loudly if none does.

---

## The one thing you have to keep doing

**Re-export the Nordnet CSV.** Everything else is automatic. Units and cost
basis are frozen at the export date, so a trade made after it is invisible to
the whole system.

In Nordnet: *Salkku → Osakkeet ostoerittäin → export*, and save into

```
~\Documents\Claude\Projects\Equity Portfolio Assistant\
```

replacing `nordnet-ostoerittain.csv` (OST) and `nordnet-ostoerittain (1).csv`
(AOT). The dashboard shows the export age on every run and raises a warning past
30 days.

> `OST` and `AOT` are the two **accounts**, not the file format: *osakesäästötili*
> (the equity savings account) and *arvo-osuustili* (the book-entry account).
> `ostoerittäin` is only the name of the lot-level Nordnet view both are exported
> from. The filenames put the two words next to each other and they have been
> misread as the same thing.

> That project folder is also read by the scheduled daily markets briefing.
> Do not move, rename or restructure it.

---

## Keeping the Equity Log fresh

The Notion board is read one of two ways.

**Live (current, since 2026-09-13).** A Notion internal integration token sits
in `.env` beside this file:

```
NOTION_TOKEN=ntn_...
```

The board is read directly on every run, with no Claude in the loop, and the
result is written to the cache as a side effect. Nothing to maintain.

**Cache (fallback).** `state/equity-log.json` holds the last snapshot. If the
live read fails the run uses it and says so rather than stopping. It can also be
refreshed by hand through Claude, which has Notion access over MCP:

> refresh the equity cockpit's Notion cache

The health banner always says which mode was in force. No paid Notion plan is
needed — an integration token works on the Free plan.

**If live reads start failing**, it is almost always one of two things: the
token was rotated, or the Equity Log database got disconnected from the
integration (Notion page → **⋯** → **Connections**). `run.ps1 selftest` names
which.

---

## What it will tell you, and when

| Alert | Fires when |
|---|---|
| Trigger hit | the live price crossed a level written in a Trigger field |
| Trigger near | within 10% of that level |
| Check due | a `Next check` date inside 14 days |
| Thesis decay | upside moved 8+ points from what the board still claims |
| Held mismatch | Notion and the broker disagree about what you own |
| Health | a source failed, the export went stale, or the task stopped running |

Telegram carries `critical` and `warning` only, once per alert, with a 7-day
cooldown before the same alert can repeat. A system that messages you every
morning gets muted inside a fortnight.

**It never suggests a trade.** It tells you a condition you wrote down has been
met. The decision, and the order, stay yours.

---

## When something looks wrong

Run `.\run.ps1 doctor` first — it is written to answer this question in English.

The design assumption is that **every input will eventually break**, so each one
is checked rather than trusted:

| What rots | What catches it |
|---|---|
| Yahoo drops or renames a ticker | per-ticker fetch; the position is marked stale and the run still completes |
| A ticker is mapped to the *wrong* company | live valuation is compared to Nordnet's own `Markkina-arvo`; 12%+ divergence is flagged |
| Nordnet changes its CSV columns | the 16-column header is asserted by name |
| A Notion property gets renamed | `selftest` names the property that went empty |
| The scheduled task silently stops | heartbeat in `state/last_run.json`; the page and Telegram both say so |
| The CSV export goes stale | age is shown on every run, warned past 30 days |
| A trigger written in prose is misread | unit guard (`EUR 70M` is not a price) plus a plausibility band against the live price |

Run history is appended to `state/history.jsonl` and never rewritten, so you can
always see what the system believed on a given day.

---

## Files

```
portfolio.local.json  PRIVATE, gitignored — accounts, ISIN→ticker map, buckets, asset class
portfolio.example.json  the committed schema for the above. Safe. No real holdings
config.py       thresholds, paths, Notion schema. Says nothing about what you own
sources.py      every external boundary. A source that fails degrades; it never raises
analyse.py      pure computation. No I/O. Everything worth testing lives here
render.py       builds the data blob and writes the dashboard
notify.py       Telegram, with dedupe and cooldown
cockpit.py      the entry point: run | refresh | selftest | doctor | sync-notion
run.ps1         interpreter-pinned wrapper — what the scheduler calls
install-task.ps1  registers/removes the two scheduled tasks
assets/         the dashboard template + the vendored chart library
state/          caches, heartbeat, run log, history, alerts already seen
out/            the generated dashboard and its JSON
tests/          23 offline tests, plus a DOM smoke harness for the page
```

`assets/lightweight-charts.standalone.production.js` is TradingView's chart
library (Apache-2.0), **vendored on purpose**: it is inlined into the output, so
the dashboard makes no network call when you open it and will still draw in five
years. To update it, replace that one file — there is no build step. If it goes
missing, `selftest` says so and the render refuses rather than quietly
publishing a page with an empty middle.

Price history is cached in `state/price-history.json` — two years of daily bars
per symbol, refetched once a day. The time-range buttons slice that cache; they
do not fetch. Deleting the file costs one slower run, nothing else.

### Adding a new holding

Buy it, re-export the CSV, run `.\run.ps1 selftest`. It will fail by name with
the unmapped ISIN. Add one entry to `holdings` in `portfolio.local.json`. That
is the whole procedure.

```json
"US0378331005": {"symbol": "AAPL", "name": "Apple",
                 "bucket": "US hardware", "class": "stock"}
```

`class` decides how the cockpit judges it. A **stock** is judged by thesis — it
wants a target, a trigger and a written reason, and the page says so when one is
missing. A **fund** is judged by allocation — give it a `target_weight_pct` and
it is measured against that instead. Demanding a falsifiable thesis from a world
index tracker produces a permanent warning you will learn to ignore.

### Target weights you have not decided yet

A fund with `"target_weight_pct": null` reads as an open gap, which is correct
but leaves the allocation columns empty and the feature hard to look at. The
third state fills them without pretending:

```json
"IE00B4L5Y983": {"symbol": "IWDA.AS", "name": "iShares Core MSCI World",
                 "bucket": "Broad equity - world", "class": "fund",
                 "target_weight_pct": 7, "target_basis": "placeholder"}
```

`"placeholder"` means *a rule put this here, not a decision*. The drift is still
computed and drawn, but the holding stays **uncovered**, the page labels the
number as a placeholder in both places it appears, and it never reaches
Telegram — an alert says something needs attention, and drifting from a number
nobody chose is not that. Omitting `target_basis` means `policy`, so a weight
you actually decided needs no extra key and every file written before this
reads correctly.

`py tools/placeholder_targets.py` prints a set of them — equal weight per
bucket inside a core/satellite frame, which is the absence of a view rather
than a recommendation — and `--write` fills in every null it finds. It never
overwrites a weight you wrote yourself.

---

## Privacy

**The repo is publishable; the book is not.** One gitignored file —
`portfolio.local.json` — holds the account numbers, the ISIN→ticker map, the
buckets and the Notion data source id. Nothing else in the repo knows what you
own; the rest works off ISINs read from the broker export at run time.

Also never committed: `.env` (the Notion token), `state/` (the Notion mirror and
the day-by-day run history), `out/` (the dashboard, which embeds the whole book)
and every `*.csv` (units, cost basis, account numbers).

That is a property of the current file layout, not of the code, so it is
asserted rather than trusted: `selftest` scans every committable file for ISINs
and account numbers on every run and fails by filename if one appears. It caught
a real leak the first time it ran — the test fixtures had live account numbers
in them.

---

## The scheduled tasks

```powershell
.\install-task.ps1                 # both (re-run to change)
.\install-task.ps1 -At 18:10       # move the daily run
.\install-task.ps1 -NoRefresh      # daily run only
.\install-task.ps1 -Remove         # unregister both
Get-ScheduledTaskInfo -TaskName EquityCockpit
Get-ScheduledTaskInfo -TaskName EquityCockpitRefresh
```

Two tasks, because they are two jobs:

| Task | When | Does |
|---|---|---|
| `EquityCockpit` | weekdays 07:40 | reads every source, re-checks the Equity Log, messages Telegram, writes the day's history line |
| `EquityCockpitRefresh` | weekdays, every 30 min, 09:30–22:00 | re-prices and re-renders. Nothing else |

The refresh exists because Yahoo is ~15 minutes delayed even at 07:40, so by the
afternoon the page shows a price eight hours old while looking exactly as
authoritative as it did at breakfast. The tape carries a **Priced HH:MM** chip
and the data sheet a **Run** row, so a refreshed page never passes itself off as
a re-read board.

What the refresh deliberately does *not* do is as much the point as what it
does. It never reads Notion, never messages Telegram, never re-fetches daily
bars or multiples — none of those move between 10:00 and 10:30, and `.info` is
the call that answers *thin* under a rate limit, which this repo went to some
trouble to stop mistaking for a fund. It also writes neither `last_run.json` nor
`history.jsonl`: the heartbeat has to keep meaning "the board was last read
then", or a dead daily task would hide behind 26 healthy refreshes a day.

The window is 09:30–22:00 because Helsinki and Stockholm run 10:00–17:30 CET and
New York closes at 22:00. Nothing in this book trades outside it.

`LastTaskResult` of `0` means the run succeeded. Anything else, read
`state/run.log`.

---

## Tests

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312-arm64\python.exe" -m pytest tests -q
node tests\smoke.mjs out\dashboard.html
```

Every test case is a real string from the Equity Log or a real row from the
Nordnet export, including the ones that produced false alerts on the first live
run. A test that isn't about something that actually broke is decoration.
