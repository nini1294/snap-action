"""Timing-aware action selection.

Actions stay deterministic per (kind, timing bucket): same data always
produces the same labels, but an event happening tonight should not offer
"Remind me that morning".
"""
from datetime import datetime, timedelta

from .kinds import KINDS


def _parse_hhmm(s):
    s = str(s).strip()
    for fmt in ("%H:%M", "%H%M", "%I:%M %p", "%I %p", "%I:%M%p"):
        try:
            return datetime.strptime(s.upper().replace(".", ""), fmt).time()
        except ValueError:
            continue
    return None


def event_start(fields):
    """Best-effort start datetime from fields (date, time). None if unparseable."""
    d = str(fields.get("date") or "").strip()
    if not d:
        return None
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            day = datetime.strptime(d, fmt)
        except ValueError:
            continue
        t = _parse_hhmm(fields.get("time") or "") if fields.get("time") else None
        return day.replace(hour=t.hour, minute=t.minute) if t else day
    return None


def actions_for(kind, fields, now=None):
    """Return the action list for an item: kind defaults, adjusted for timing.

    - event starting within 12h: swap morning/evening-before reminders for a
      1-hour-before reminder; slot 3 becomes 'Just save it'
    - event already past: archive-style single action
    """
    spec = KINDS[kind]
    actions = [dict(a) for a in spec["actions"]]
    if kind != "event":
        return actions
    now = now or datetime.now()
    start = event_start(fields)
    title = fields.get("title") or "the event"
    t = fields.get("time") or ""
    if start is not None and start < now:
        actions = [{"label": "Just save it",
                    "hint": "The event has already passed; item is already stored."}]
    elif start is not None and timedelta(0) <= start - now <= timedelta(hours=12):
        actions[1] = {
            "label": "Remind me 1 hour before",
            "hint": f"One-shot cron reminder 1 hour before: {title} at {t}.",
        }
        actions[2] = {"label": "Just save it",
                      "hint": "No further action; item is already stored."}
    return actions
