"""Exercise the live-price endpoint, against dev or against production.

    py tools\\quotes_check.py http://localhost:3311      (a running `vercel dev`)
    py tools\\quotes_check.py https://<deployment>.vercel.app

Neutral symbols only. Nothing in this file is a holding, and nothing in the
output names one - the endpoint's own health probe uses AAPL for exactly that
reason. It can therefore be run and pasted anywhere.

It checks the three things that would be wrong in a way that still looks right
on screen:

  1. FX DIRECTION. analyse.value_holdings() does `price * units * rate` and
     sources.fx_rates() is documented "Units of EUR per 1 unit of currency", so
     USD must arrive near 0.87. Frankfurter and Yahoo both return 1.15. The
     inverse is a ~32% overstatement of every dollar holding and looks entirely
     plausible.
  2. ABSENT IS NOT ZERO. A symbol the vendor cannot price must be named in
     `missing` and absent from `quotes` - never zero, never last night's close
     wearing today's date. CLAUDE.md rule 4.
  3. A PARSER THAT DROPS INPUT MUST SAY SO. `GBp` (London pence) has a
     lowercase p and was silently rejected by a /^[A-Z]{3}$/ filter, while the
     response reported nothing missing. Found by this harness, fixed in
     api/quotes.ts; the assertion stays so it cannot come back.

Exit codes: 0 all checks passed, 1 something failed, 2 bad usage.

Against production this ALSO answers the one question that cannot be settled
from a laptop: whether Yahoo serves Vercel's datacenter IPs. If the health
probe returns 503 the endpoint is fine and the upstream is refusing - the page
falls back to build-time prices and says so, which is a degradation, not an
outage.
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRETS = ROOT / "deploy.local.json"

# None of these are in the book. The last one is meant to fail.
NEUTRAL = ["AAPL", "MSFT", "VOD.L", "7203.T", "DEFINITELY-NOT-A-TICKER.XX"]
BOGUS = "DEFINITELY-NOT-A-TICKER.XX"
CCY = ["USD", "SEK", "DKK", "NOK", "GBp", "EUR"]

# Deliberately more than one upstream batch. Large-cap US names, none held -
# the only property that matters here is that there are enough of them to
# straddle the chunk boundary.
BATCH = [
    "AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "NFLX", "ADBE",
    "CRM", "ORCL", "INTC", "AMD", "QCOM", "TXN", "AVGO", "CSCO", "IBM", "NOW",
    "UBER", "PYPL", "SHOP", "PANW", "FTNT", "CRWD", "DDOG", "NET", "SNOW",
]

fails: list[str] = []


def _auth() -> str | None:
    if not SECRETS.exists():
        return None
    pw = json.loads(SECRETS.read_text(encoding="utf-8-sig"))["cockpit_password"]
    return "Basic " + base64.b64encode(f"x:{pw}".encode()).decode()


def call(base: str, method: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + "/api/quotes", data=data, method=method)
    auth = _auth()
    if auth:
        req.add_header("Authorization", auth)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"_raw": raw[:300].decode("utf-8", "replace")}
    except Exception as e:
        return -1, {"_raw": f"{type(e).__name__}: {e}"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    base = argv[1].rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    print(f"against {base}")
    print("\n=== health probe (does the upstream answer from THERE) ===")
    status, d = call(base, "GET")
    print(f"  {status}  {json.dumps(d)[:220]}")
    if status == 401:
        print("\n  401 - something is in front of this endpoint. If that is "
              "Vercel Deployment Protection, the gate and this endpoint both "
              "sit behind it and neither can be exercised. See tools/gate_check.py.")
        return 1
    check("upstream reachable from the deployment", status == 200 and d.get("ok") is True)
    if status == 503:
        print("\n  The endpoint works and Yahoo is refusing it. The page will "
              "fall back to build-time prices and label them. Degradation, not "
              "an outage - but live pricing is off until this clears.")

    print("\n=== quotes ===")
    status, d = call(base, "POST", {"symbols": NEUTRAL, "currencies": CCY})
    if status != 200:
        print(f"  status {status}: {json.dumps(d)[:400]}")
        return 1
    q = d.get("quotes") or {}
    fx = d.get("fx") or {}
    print(f"  counts  {d.get('counts')}")
    print(f"  missing {d.get('missing')}")
    print(f"  fx      {json.dumps(fx)}  source={d.get('fxSource')}")
    for s, row in sorted(q.items()):
        print(f"    {s:<16} price={row['price']}  prev={row['prevClose']}  "
              f"chg%={row['changePct']}  asOf={row['asOf']}")

    print("\n=== 1. FX direction (EUR per unit, the page's convention) ===")
    usd = fx.get("USD")
    check("USD in 0.7-1.0, not its inverse", usd is not None and 0.7 < usd < 1.0,
          f"got {usd}")
    sek = fx.get("SEK")
    check("SEK well under 0.2", sek is not None and 0.05 < sek < 0.2, f"got {sek}")
    check("EUR is exactly 1.0", fx.get("EUR") == 1.0, f"got {fx.get('EUR')}")
    gbp, gbx = fx.get("GBP"), fx.get("GBp")
    check("GBp is GBP/100",
          gbp is not None and gbx is not None and abs(gbx - gbp / 100) < 1e-12,
          f"GBP={gbp} GBp={gbx}")

    print("\n=== 2. absent is not zero ===")
    check("unpriceable symbol absent from quotes", BOGUS not in q)
    check("unpriceable symbol named in missing", BOGUS in (d.get("missing") or []))
    check("no quote carries a zero or null price",
          all(r.get("price") not in (0, None) for r in q.values()))
    check("counts.missing agrees with the list",
          d["counts"]["missing"] == len(d["missing"]))
    check("counts.priced agrees with the map", d["counts"]["priced"] == len(q))
    for s in ("AAPL", "MSFT", "VOD.L"):
        check(f"{s} priced", s in q and q[s]["price"] > 0)
    withpct = [s for s, r in q.items() if r["changePct"] is not None]
    check("day change% derived for priced symbols",
          len(withpct) >= max(1, len(q) - 1), f"{len(withpct)}/{len(q)}")

    print("\n=== 3. a parser that drops input must say so ===")
    status, d2 = call(base, "POST",
                      {"symbols": ["AAPL"], "currencies": ["GBp", "USD", "ZZZZ"]})
    f2 = (d2.get("fx") or {}) if status == 200 else {}
    print(f"  fx {json.dumps(f2)}")
    print(f"  fxMissing {d2.get('fxMissing')}  fxRejected {d2.get('fxRejected')}")
    check("GBp alone still yields GBP", f2.get("GBP") is not None)
    check("GBp alone still yields GBp = GBP/100",
          f2.get("GBp") is not None and f2.get("GBP") is not None
          and abs(f2["GBp"] - f2["GBP"] / 100) < 1e-12)
    check("unparseable code named in fxRejected",
          "ZZZZ" in (d2.get("fxRejected") or []))
    check("unparseable code also in fxMissing (asked, not delivered)",
          "ZZZZ" in (d2.get("fxMissing") or []))
    check("a delivered currency is NOT in fxMissing",
          "USD" not in (d2.get("fxMissing") or []))

    print("\n=== 4. batching past the upstream's limit ===")
    # Yahoo's spark endpoint answers 400 above 20 symbols, in its own words:
    # "Number of symbols needs to be less than or equal to 20". The endpoint
    # chunks for this. It chunked at 40 first, so the main batch failed on
    # every single call and only the short remainder came back - and because
    # unpriced symbols correctly keep their build-time price, the page looked
    # fine while being almost entirely not live.
    #
    # The old version of this harness asked for 5 symbols and could not
    # possibly have seen it. Anything that batches needs a test wider than one
    # batch.
    status, d3 = call(base, "POST", {"symbols": BATCH, "currencies": ["USD"]})
    if status != 200:
        check(f"{len(BATCH)}-symbol request succeeds", False, f"status {status}")
    else:
        c = d3.get("counts") or {}
        print(f"  counts {c}")
        print(f"  upstreamErrors {d3.get('upstreamErrors')}")
        if d3.get("missing"):
            print(f"  missing {d3['missing']}")
        check(f"asked for all {len(BATCH)} symbols", c.get("asked") == len(BATCH))
        # Allow a little slack: a delisted or renamed ticker in this list is
        # the harness's problem, not the endpoint's. A whole chunk vanishing
        # is not slack.
        check("priced count is not a single chunk's worth",
              c.get("priced", 0) >= len(BATCH) - 3,
              f"priced {c.get('priced')} of {len(BATCH)}")
        check("no upstream chunk errors", not d3.get("upstreamErrors"),
              str(d3.get("upstreamErrors")))

    print("\n=== bad input ===")
    status, _ = call(base, "POST", {"symbols": []})
    check("empty symbol list rejected", status == 400, f"got {status}")
    status, _ = call(base, "POST", {"nope": 1})
    check("missing symbols key rejected", status == 400, f"got {status}")

    print()
    if fails:
        print(f"{len(fails)} FAILED: {', '.join(fails)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
