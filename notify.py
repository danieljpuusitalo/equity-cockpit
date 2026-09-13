"""Telegram notification, with the one property that decides whether an alert
system survives contact with daily use: it only speaks when something changed.

A system that messages you every morning gets muted inside a fortnight. This
one keeps a record of what it has already told you and stays silent otherwise.
"""
from __future__ import annotations

import json
import datetime as dt
import urllib.request
import urllib.parse

import config as C
import sources

SEEN = C.STATE / "alerts-seen.json"
NOTIFY_LEVELS = ("critical", "warning")
# Health problems worth waking you for; the rest just colour the dashboard.
ALWAYS_NOTIFY_PREFIXES = ("trigger-hit:", "run-stale", "source-", "mapping-")


def _token():
    return sources._load_env_file(C.TELEGRAM_ENV).get("TELEGRAM_BOT_TOKEN")


def _load_seen():
    if not SEEN.exists():
        return {}
    try:
        return json.loads(SEEN.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save_seen(seen):
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(seen, indent=1), encoding="utf-8")


def new_alerts(alerts, seen=None, today=None, cooldown_days=7):
    """Alerts not already sent, or last sent longer ago than the cooldown."""
    today = today or dt.date.today()
    seen = _load_seen() if seen is None else seen
    fresh = []
    for alert in alerts:
        if alert["level"] not in NOTIFY_LEVELS:
            continue
        last = seen.get(alert["key"])
        if last:
            try:
                age = (today - dt.date.fromisoformat(last)).days
            except ValueError:
                age = cooldown_days + 1
            if age < cooldown_days:
                continue
        fresh.append(alert)
    return fresh


def compose(fresh, data):
    """Plain text. No markdown - a stray underscore in a ticker should never
    cost you the message."""
    lines = [f"Equity cockpit - {len(fresh)} item"
             f"{'' if len(fresh) == 1 else 's'} need attention"]
    totals = data["totals"]
    lines.append(f"Book EUR {totals['value_eur']:,.0f} "
                 f"({totals['pl_pct']:+.1f}% vs cost)")
    lines.append("")
    for alert in fresh:
        mark = "!!" if alert["level"] == "critical" else "*"
        lines.append(f"{mark} {alert['title']}")
        if alert.get("detail"):
            lines.append(f"   {alert['detail'][:240]}")
    lines.append("")
    lines.append("Dashboard: " + str((C.OUT / "dashboard.html")))
    return "\n".join(lines)


def send(text, token=None, chat_id=None):
    """Returns (ok, problem). Never raises - a silent phone must not kill a run."""
    token = token or _token()
    if not token:
        return False, f"no TELEGRAM_BOT_TOKEN in {C.TELEGRAM_ENV}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id or C.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=20) as resp:
            payload = json.loads(resp.read().decode())
        return bool(payload.get("ok")), None if payload.get("ok") else str(payload)[:200]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def notify(alerts, data, dry_run=False):
    """Send what is new. Returns a summary dict for the run log."""
    seen = _load_seen()
    fresh = new_alerts(alerts, seen)
    if not fresh:
        return {"sent": 0, "skipped": len(alerts), "problem": None}
    text = compose(fresh, data)
    if dry_run:
        return {"sent": 0, "skipped": len(alerts) - len(fresh),
                "problem": None, "preview": text}
    ok, problem = send(text)
    if ok:
        today = dt.date.today().isoformat()
        for alert in fresh:
            seen[alert["key"]] = today
        # Forget keys that have not reappeared in 90 days, so the file
        # cannot grow forever.
        cutoff = (dt.date.today() - dt.timedelta(days=90)).isoformat()
        seen = {k: v for k, v in seen.items() if v >= cutoff}
        _save_seen(seen)
    return {"sent": len(fresh) if ok else 0,
            "skipped": len(alerts) - len(fresh), "problem": problem}
