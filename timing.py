"""Timing-aware action selection.

Actions stay deterministic per (kind, timing bucket): same data always
produces the same labels, but an event happening tonight should not offer
"Remind me that morning".

All stored dates/times are IST (Asia/Kolkata) — the host clock may be UTC,
so every comparison happens against IST "now".
"""
from datetime import datetime, timedelta, timezone

from .kinds import KINDS

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def _parse_hhmm(s):
    s = str(s).strip()
    for fmt in ("%H:%M", "%H%M", "%I:%M %p", "%I %p", "%I:%M%p"):
        try:
            return datetime.strptime(s.upper().replace(".", ""), fmt).time()
        except ValueError:
            continue
    return None


def parse_date(s):
    """Best-effort date parse -> IST datetime at midnight, else None."""
    d = str(s or "").strip()
    if not d:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(d, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def at_time(day, hhmm=None, fallback=None):
    """IST datetime for `day` at parsed hh:mm (or fallback time)."""
    if day is None:
        return None
    t = _parse_hhmm(hhmm) if hhmm else None
    t = t or fallback
    return day.replace(hour=t.hour, minute=t.minute) if t else day


def event_start(fields):
    """Best-effort start datetime (IST) from fields (date, time). None if unparseable."""
    return at_time(parse_date(fields.get("date")), fields.get("time"))


def actions_for(kind, fields, now=None):
    """Return the action list for an item: kind defaults, adjusted for timing.

    - event starting within 12h: swap morning/evening-before reminders for a
      1-hour-before reminder, but only while that reminder can still fire;
      slot 3 becomes 'Just save it'
    - event already past: archive-style single action
    """
    spec = KINDS[kind]
    actions = [dict(a) for a in spec["actions"]]
    if kind != "event":
        return actions
    now = now or now_ist()
    start = event_start(fields)
    title = fields.get("title") or "the event"
    t = fields.get("time") or ""
    if start is not None and start < now:
        actions = [{"label": "Just save it",
                    "hint": "The event has already passed; item is already stored."}]
    elif start is not None and timedelta(0) <= start - now <= timedelta(hours=12):
        actions = [a for a in actions if a["label"].startswith("Add to calendar")]
        if start - now > timedelta(hours=1):
            actions.append({"label": "Remind me 1 hour before",
                            "hint": f"One-shot cron reminder 1 hour before: {title} at {t}."})
        actions.append({"label": "Just save it",
                        "hint": "No further action; item is already stored."})
    return actions
