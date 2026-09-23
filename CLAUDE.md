# equity-cockpit: standing instructions

Daniel's **personal** Nordnet portfolio monitor — not the 4Impact book. It joins a
Nordnet CSV lot export with Yahoo data and the Notion Equity Log, renders a local
dashboard, and sends a Telegram alert on weekdays only when something changed.

**This is a public repo holding a private portfolio.** That contradiction is held
together by a leak scan, not by care. See rule 1.

## Verify

`.\run.ps1 selftest` (PowerShell).

**Always go through `run.ps1`, never a bare interpreter.** It probes a candidate
list of Python installs and picks the first that can `import yfinance`
(Python312-arm64 first), exiting 3 if none qualifies. A bare `py` or `python` may
find an interpreter without yfinance and fail in a way that looks like a code bug.

`selftest` also runs `_leak_scan()` (`cockpit.py:595`), which fails if any ISIN,
account number, or the Notion data-source id appears in a committable file. **That
scan is the thing keeping this repo publishable.** If it fires, the data leaked into
the wrong file — fix the file, never the scan.

No CI at all. `selftest` is the only signal.

## Where state lives

`CHECKPOINT.local.md`, including its "Do not undo" section.

It is **gitignored** (`*.local.md`) because it quotes real positions. Two
consequences: git will not recover a bad write to it, and it exists on this machine
only — a fresh clone has no idea how this project works.

## Hard rules

1. **Never commit portfolio data.** No ISINs, account numbers, position sizes or
   the Notion data-source id in code, tests, fixtures, commit messages or docs.
   `.gitignore` covers `*.csv`, `out/`, `state/`, `*.local.*`, `.env`.
2. **The input directory is READ-ONLY.**
   `~/Documents/Claude/Projects/Equity Portfolio Assistant` holds the Nordnet
   exports (`config.py:20` marks it "never write here"). Read, never write.
3. **Never overwrite a recorded figure with a live one.** The recorded figure is the
   evidence that a write-up is stale. Overwriting destroys the only signal that
   something needs revisiting.
4. **A vendor answering with less than it should is not the same as saying
   nothing.** A thin yfinance `.info` once silently blanked good cached multiples.
   Absent is not zero and is not empty — distinguish them explicitly.

## Stop-points

- **`run` sends to Telegram for real.** When testing, use `refresh` (never contacts
  Telegram at all) or `run --quiet` (dry-run preview, sends nothing).
- Anything that would write to Notion. Today the Notion integration is a **read-only
  query** — there are no write calls anywhere. Adding one is a decision, not a step.
- Allocation judgements. `target_weight_pct` and any held/expected disagreement are
  Daniel's calls, not a session's; leave them unset rather than guessing.

## Traps

- **`OST` and `AOT` are Finnish account types** — *osakesäästötili* and
  *arvo-osuustili* — **not file formats**. `ostoerittäin` is the Nordnet lot view
  both accounts export from, and the filename adjacency has already caused one
  misreading. Identity is `isin|account_no`; a sale in OST and a purchase of the
  same name in AOT net to zero at book level.
- The Nordnet CSV is **tab-delimited**, with encodings tried in order
  `utf-16` → `utf-8-sig` → `cp1252`. Reading it as comma-separated silently yields
  one column.
- **Join the broker to the board on the Yahoo symbol, never a stripped stem.**
  Nordnet writes `ERIC B`; Yahoo wants `ERIC-B.ST`.
- `TELEGRAM_BOT_TOKEN` is read from **outside the repo**
  (`~/.claude/channels/telegram/.env`). `NOTION_TOKEN` comes from the repo's own
  gitignored `.env`. `TELEGRAM_CHAT_ID` is a literal in `config.py`.
- Two scheduled tasks exist, not one: `EquityCockpit` (weekdays 07:40, `run`) and
  `EquityCockpitRefresh` (weekdays every 30 min, 09:30–22:00, `refresh`).
- `portfolio.local.json` is required and gitignored; `portfolio.example.json` is the
  committed schema.
- Long or scheduled runs must survive the session — launch detached with output to a
  log file, never as a session-bound background shell.
