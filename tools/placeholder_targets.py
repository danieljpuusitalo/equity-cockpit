"""Fill every empty fund `target_weight_pct` with a placeholder, and say so.

WHAT THIS IS NOT
----------------
Not advice, and not a recommendation. Every number it writes is marked
`"target_basis": "placeholder"`, which the cockpit reads as *not a policy*: the
holding still counts as uncovered, the rail still says the target is undecided,
and the drift never reaches Telegram. The point is to give the allocation
column something to draw so the shape of the feature is visible before the real
numbers exist - and to leave an obvious seam where they go.

THE RULE
--------
Naive diversification inside a core-satellite frame. Equal weight is the
*absence* of a view, which is exactly what makes it usable here: nothing below
expresses an opinion about which fund deserves more money.

  1. The fund sleeve is anchored at SLEEVE_PCT of the book. A round number,
     chosen for being round. It is deliberately NOT read off the current fund
     total - seeding a target from today's weight is what `config.TARGET_WEIGHT`
     already refuses, because it turns the drift check into a tautology.
  2. That splits CORE_PCT / (100 - CORE_PCT) between core and satellite, the
     conventional core-satellite structure.
  3. Core versus satellite is decided from the `bucket` string already in the
     file - no new taxonomy, no judgement call per holding.
  4. Within each tier, equal weight **per sleeve**, where a sleeve is a bucket
     rather than a line. Three Nordnet Nordic index funds are one sleeve and
     split one share between them; equal-weighting them as three would put a
     4-point target on a EUR 140 position.

Change the three constants and re-run - that is the whole knob. Run:

    py tools/placeholder_targets.py            # show what it would write
    py tools/placeholder_targets.py --write    # write it

`--write` only ever fills targets that are currently null, and only ever
touches holdings with `"class": "fund"`. A written policy is never overwritten,
whatever this file thinks of it.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import config as C        # noqa: E402

SLEEVE_PCT = 50.0     # of the whole book, in funds
CORE_PCT = 70.0       # of the sleeve, in broad-market and index funds
CORE_MARKERS = ("broad equity", "index")


def tier(bucket):
    """Core or satellite, from the bucket string the file already carries."""
    low = (bucket or "").lower()
    return "core" if any(m in low for m in CORE_MARKERS) else "satellite"


def plan(holdings, asset_class):
    """-> {isin: pct}, plus the sleeve table the caller prints.

    Takes the book as arguments rather than reading config, so the rule can be
    tested against a fixture instead of against Daniel's real file.
    """
    funds = {isin: h for isin, h in holdings.items()
             if asset_class.get(isin) == "fund"}
    sleeves = {}
    for isin, h in funds.items():
        sleeves.setdefault((tier(h.get("bucket")), h.get("bucket")), []).append(isin)

    budget = {"core": SLEEVE_PCT * CORE_PCT / 100,
              "satellite": SLEEVE_PCT * (100 - CORE_PCT) / 100}
    counts = {t: sum(1 for k in sleeves if k[0] == t) for t in budget}

    targets, table = {}, []
    for (t, bucket), isins in sorted(sleeves.items()):
        if not counts[t]:
            continue
        per_sleeve = budget[t] / counts[t]
        per_line = round(per_sleeve / len(isins), 2)
        for isin in isins:
            targets[isin] = per_line
        table.append({"tier": t, "bucket": bucket, "sleeve_pct": per_sleeve,
                      "lines": len(isins), "per_line_pct": per_line,
                      "isins": isins})
    return targets, table


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="write the placeholders into the holdings file")
    args = ap.parse_args()

    raw = json.loads(C.PORTFOLIO_FILE.read_text(encoding="utf-8"))
    holdings = raw["holdings"]
    targets, table = plan(holdings, C.ASSET_CLASS)

    print(f"Sleeve {SLEEVE_PCT:g}% of the book, {CORE_PCT:g}/"
          f"{100 - CORE_PCT:g} core/satellite, equal weight per sleeve.\n")
    print(f"{'tier':<10} {'bucket':<28} {'sleeve':>7} {'lines':>6} {'each':>7}")
    for row in table:
        print(f"{row['tier']:<10} {row['bucket']:<28} "
              f"{row['sleeve_pct']:>6.2f}% {row['lines']:>6} "
              f"{row['per_line_pct']:>6.2f}%")
    print(f"{'':<10} {'TOTAL':<28} "
          f"{sum(t for t in targets.values()):>6.2f}%")

    skipped = [i for i in targets if holdings[i].get("target_weight_pct") is not None]
    fill = [i for i in targets if i not in skipped]
    print(f"\n{len(fill)} placeholders to write, {len(skipped)} written "
          f"policies left alone.")

    if not args.write:
        print("\nDry run. Pass --write to apply.")
        return

    # A text edit, not a JSON round-trip. The holdings file is hand-formatted
    # into aligned columns with blank lines between sections; `json.dumps`
    # would reflow all 3.8KB of it and bury an eleven-value change inside a
    # whole-file diff. Each line is edited in place instead, and the result is
    # re-parsed below to prove it is still valid JSON.
    text = C.PORTFOLIO_FILE.read_text(encoding="utf-8")
    edited = text
    for isin in fill:
        needle = f'"{isin}": {{'
        line = next((l for l in edited.splitlines() if needle in l), None)
        if line is None or '"target_weight_pct": null' not in line:
            sys.exit(f"{isin}: could not find a null target on its own line")
        edited = edited.replace(line, line.replace(
            '"target_weight_pct": null',
            f'"target_weight_pct": {targets[isin]:g}, '
            f'"target_basis": "placeholder"'))

    reparsed = json.loads(edited)["holdings"]
    for isin in fill:
        assert reparsed[isin]["target_weight_pct"] == targets[isin], isin
        assert reparsed[isin]["target_basis"] == "placeholder", isin
    assert len(reparsed) == len(holdings), "a holding went missing"

    # newline="" or Python translates every LF to CRLF on the way out, and an
    # eleven-value change arrives as a 39-line whole-file diff. Caught by
    # diffing the file after the first run; `write_text` has no newline
    # argument before 3.10 and silently does the wrong thing here either way.
    with C.PORTFOLIO_FILE.open("w", encoding="utf-8", newline="") as fh:
        fh.write(edited)
    print(f"Wrote {len(fill)} placeholders to {C.PORTFOLIO_FILE.name}, "
          f"{len(edited) - len(text)} bytes added, formatting untouched.")


if __name__ == "__main__":
    main()
