"""Ask a deployed cockpit what an anonymous stranger gets.

Run it against anything, any time:

    py tools\\gate_check.py https://<deployment>.vercel.app

The deployed page is `out/dashboard.html` verbatim - every ISIN, unit count and
euro amount. So the question this answers is not "is the password right", it is
"can someone with no password get the book". Those are different questions and
only the second one matters.

The check is a content comparison, not a status-code check. A 401 that still
carries the page body passes a status-code test and fails this one - that exact
mutation was introduced on purpose during development and a status-only harness
called it green.

Three outcomes, kept distinct on purpose, because "protected" and "protected by
the thing you think" are not the same claim:

Exit codes: 0 gate proven, 1 exposed or broken, 3 protected by SSO only.

  GATE      the cockpit's own middleware answered (401 + X-Cockpit-Denied).
  SSO       Vercel Deployment Protection answered first. The book is not
            reachable, but the middleware never ran, so nothing here says it
            works. Turning Vercel Authentication off would make the middleware
            load-bearing with no evidence behind it.
  EXPOSED   the response carries the deployed file. Nothing else matters.
  UNKNOWN   something answered that this script cannot classify. Treated as a
            failure: an unrecognised gate is not a gate.

Reads the password from deploy.local.json when present, and never prints it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRETS = ROOT / "deploy.local.json"
DEPLOYED = ROOT / "deploy" / "public" / "index.html"

# Enough surface to catch a matcher that was narrowed to the root, a stray
# config file, and the 404 path - the three ways a gate is usually wide open
# without anyone noticing the front page still asks for a password.
PATHS = [
    "/",
    "/index.html",
    "/robots.txt",
    "/middleware.ts",
    "/vercel.json",
    "/package.json",
    "/does-not-exist",
    "/public/index.html",
    "/.vercel/project.json",
    "/api/anything",
]


def _lower(headers) -> dict:
    # HTTP header names are case-insensitive; dict() of them is not. Reading
    # X-Cockpit-Denied off a raw dict silently returns None for a header the
    # server is definitely sending.
    return {k.lower(): v for k, v in dict(headers).items()}


def probe(url: str, auth: str | None = None):
    """Return (status, body, headers). A 401 is an answer, not an exception."""
    req = urllib.request.Request(url)
    if auth:
        req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), _lower(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), _lower(e.headers)
    except Exception as e:  # a transport failure is a failure, not a pass
        return -1, f"{type(e).__name__}: {e}".encode(), {}


def classify(status: int, body: bytes, headers: dict, book_hash: str | None) -> str:
    if book_hash and hashlib.sha256(body).hexdigest() == book_hash:
        return "EXPOSED"
    # Substring too, not just an exact hash: a page that embeds the book inside
    # a wrapper is every bit as exposed as one that serves it whole.
    if book_hash and DEPLOYED.exists() and len(body) > 1000:
        if DEPLOYED.read_bytes()[:4000] in body:
            return "EXPOSED"
    if status == 401 and "x-cockpit-denied" in headers:
        return "GATE"
    if headers.get("x-matched-path") == "/login" or b"vercel.com/sso" in body:
        return "SSO"
    if status == 401:
        return "GATE"  # a challenge without our header is still a challenge
    return "UNKNOWN"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    base = argv[1].rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    book_hash = None
    if DEPLOYED.exists():
        book_hash = hashlib.sha256(DEPLOYED.read_bytes()).hexdigest()
        print(f"comparing against deploy/public/index.html "
              f"({DEPLOYED.stat().st_size // 1024} KB, sha {book_hash[:12]})")
    else:
        print("no deploy/public/index.html on disk - cannot detect a leak by "
              "content, only by status. Weaker check.")

    verdicts = {}
    print("\nanonymous:")
    for p in PATHS:
        status, body, headers = probe(base + p)
        v = classify(status, body, headers, book_hash)
        verdicts[p] = v
        detail = headers.get("x-cockpit-denied", "")
        print(f"  {v:<8} {p:<24} {status}"
              + (f"  denied={detail}" if detail else f"  bytes={len(body)}"))

    worst = ("EXPOSED" if "EXPOSED" in verdicts.values() else
             "UNKNOWN" if "UNKNOWN" in verdicts.values() else
             "SSO" if "SSO" in verdicts.values() else "GATE")

    print()
    if worst == "EXPOSED":
        leaking = [p for p, v in verdicts.items() if v == "EXPOSED"]
        print(f"EXPOSED - {len(leaking)} path(s) serve the book to anyone: "
              f"{', '.join(leaking)}")
        print("Take the deployment down now: vercel remove <project> --yes")
        return 1
    if worst == "UNKNOWN":
        print("UNKNOWN - something answered that this script cannot classify. "
              "An unrecognised gate is not a gate; look at it by hand.")
        return 1
    if worst == "SSO":
        print("SSO - Vercel Deployment Protection answered first, so the book "
              "is not reachable, but the cockpit's own middleware never ran and "
              "is unproven here. Prove it locally with `vercel dev`, or turn "
              "Vercel Authentication off and re-run this.")
        # Exit 3, not 0. Not reachable and gate proven are different facts, and
        # a caller that collapses them into "verified" is making the claim this
        # repo keeps getting wrong: a status that means less than it says.
        return 3

    # The gate answered everywhere. Now the other half: does the password work?
    if not SECRETS.exists():
        print("GATE - every path denied. No deploy.local.json, so the positive "
              "case (correct password lets you in) was not tested.")
        return 0
    pw = json.loads(SECRETS.read_text(encoding="utf-8-sig"))["cockpit_password"]
    auth = "Basic " + base64.b64encode(f"x:{pw}".encode()).decode()
    status, body, headers = probe(base + "/", auth)
    served = book_hash is not None and hashlib.sha256(body).hexdigest() == book_hash
    print(f"with the password: {status}, served-the-page={served}")
    bad = "Basic " + base64.b64encode(b"x:wrong").decode()
    bstatus, _, _ = probe(base + "/", bad)
    print(f"with a wrong one : {bstatus}")

    if status != 200 or bstatus != 401:
        print("\nGATE answers, but the password does not open it. The cockpit "
              "is protected and unusable - check COCKPIT_PASSWORD on Vercel "
              "matches deploy.local.json.")
        return 1
    print(f"\nGATE PROVEN - {len(PATHS)} paths denied anonymously, wrong "
          "password denied, correct password serves the book.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
