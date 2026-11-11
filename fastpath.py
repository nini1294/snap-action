"""Code-side fast path: recall keyboards + button actions, no LLM involved.

The gateway dispatches '/snaps recall N' to the plugin command handler; if the
surface is Telegram we render the stored image with an inline keyboard straight
over the Bot API, and button taps come back through the plugin callback
registry (prefix 'snap:') where they are executed against the store directly.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, time, timedelta, timezone

from . import store
from .timing import actions_for

AUTH_TTL = timedelta(hours=24)
SAVE_TTL = timedelta(hours=1)
_sent_auth: dict[int, tuple[str, datetime]] = {}  # item_id -> (chat_id, sent_at)
_pending_saves: dict[str, tuple[str, str, "object", datetime]] = {}  # snapnew:<n> -> (chat_id, path, submit-callback, ts)


# ---------------------------------------------------------------- Bot API

def _token() -> str:
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    if tok:
        return tok
    env = os.path.expanduser("~/.hermes/.env")
    with open(env, "r") as f:
        for line in f:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("TELEGRAM_BOT_TOKEN not found")


def _api(method: str, fields: dict, file_field: str | None = None,
         file_path: str | None = None, timeout: int = 30) -> dict:
    """Blocking Bot API POST (multipart when a file rides along)."""
    url = f"https://api.telegram.org/bot{_token()}/{method}"
    if not file_field or not file_path:
        req = urllib.request.Request(
            url, data=urllib.parse.urlencode({k: str(v) for k, v in fields.items()}).encode())
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    with open(file_path, "rb") as fh:
        content = fh.read()
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n".encode()
            + str(v).encode() + b"\r\n")
    parts.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
         f"filename=\"{os.path.basename(file_path)}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
        + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


async def _api_async(method: str, fields: dict, file_field: str | None = None,
                     file_path: str | None = None) -> dict:
    return await asyncio.to_thread(_api, method, fields, file_field, file_path)


# ---------------------------------------------------------------- keyboard

def _buttons(item_id: int, kind: str, fields: dict) -> list[list[dict]]:
    rows: list[list[dict]] = []
    row: list[dict] = []
    labels = [a["label"] for a in actions_for(kind, fields)] + ["Delete"]
    for i, label in enumerate(labels):
        row.append({"text": label, "callback_data": f"snap:{item_id}:{i}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


async def send_recall(item_id: int, chat_id: str) -> str:
    """Send the stored image (or a text card) with the tappable action keyboard.
    Returns a short confirmation for the command reply."""
    r = store.get(item_id)
    if not r.get("ok"):
        return f"❌ {r.get('error', 'not found')}"
    item = r["item"]
    fields = item["fields"]
    img = fields.get("_image")
    caption = f"{item['summary']}"
    note = item.get("note")
    if note:
        caption += f"\n{note}"
    keyboard = {"inline_keyboard": _buttons(item_id, item["kind"], fields)}
    _sent_auth[item_id] = (chat_id, datetime.now())
    # prune stale auth entries
    for k in [k for k, (_, t) in _sent_auth.items() if datetime.now() - t > AUTH_TTL]:
        _sent_auth.pop(k, None)
    if img and os.path.exists(img):
        resp = await _api_async("sendPhoto", {
            "chat_id": chat_id, "caption": caption[:1000],
            "reply_markup": json.dumps(keyboard)},
            file_field="photo", file_path=img)
    else:
        resp = await _api_async("sendMessage", {
            "chat_id": chat_id, "text": caption[:4000],
            "reply_markup": json.dumps(keyboard)})
    if not resp.get("ok"):
        return f"❌ send failed: {resp.get('description', 'unknown')}"
    return ""  # the photo+keyboard IS the reply — no confirmation text needed


def fastpath_sync_recall(item_id: int, chat_id: str) -> str:
    """Sync entry for the command handler (runs on the gateway executor thread)."""
    return asyncio.run(send_recall(item_id, chat_id))


# ---------------------------------------------------------------- actions

def _fmt_utc(day: str, hm: str, offset_h: float = 0.0) -> datetime | None:
    """Parse IST date+time into a UTC datetime, shifted by offset hours."""
    from .timing import at_time, parse_date
    start = at_time(parse_date(day), hm)
    if start is None:
        return None
    return (start - timedelta(hours=offset_h)).astimezone(timezone.utc)


def _fire_time(kind: str, fields: dict, label: str):
    """IST datetime when the reminder for `label` should fire, or None."""
    from .timing import at_time, event_start, parse_date
    low = label.lower()
    start = event_start(fields)
    if "1 hour" in low:
        return start - timedelta(hours=1) if start else None
    if "24h" in low:
        return start - timedelta(hours=24) if start else None
    if "3 days" in low:  # subscription renewal
        day = parse_date(fields.get("next_renewal"))
        return at_time(day - timedelta(days=3) if day else None, fallback=time(9, 0))
    if "30 days" in low:  # warranty expiry
        day = parse_date(fields.get("warranty_until"))
        return at_time(day - timedelta(days=30) if day else None, fallback=time(9, 0))
    if "morning" in low:  # event morning-of
        return at_time(parse_date(fields.get("date")), fallback=time(9, 0))
    if "evening before" in low:
        day = parse_date(fields.get("date"))
        return at_time(day - timedelta(days=1) if day else None, fallback=time(19, 0))
    if "due date" in low:  # bill — 2 days before due
        day = parse_date(fields.get("due_date"))
        return at_time(day - timedelta(days=2) if day else None, fallback=time(9, 0))
    if "delivery day" in low:
        return at_time(parse_date(fields.get("expected_date")), fallback=time(10, 0))
    if "follow up" in low:  # not delivered — chase next day
        day = parse_date(fields.get("expected_date"))
        return at_time(day + timedelta(days=1) if day else None, fallback=time(12, 0))
    return None


def _settle_open_split(item_id: int, fields: dict) -> str:
    """Match a payment against open bill splits; settle the unambiguous one."""
    pay_amt = fields.get("amount")
    pay_cur = fields.get("currency", "")
    open_splits = []
    for r in store.list_items(kind="bill", status="active", limit=100).get("items", []):
        for s in r["fields"].get("splits", []):
            if not s.get("paid", False):
                open_splits.append((r["id"], r["fields"].get("merchant", ""), s))
    if not open_splits:
        return "✓ No open splits — nothing to settle."
    cands = open_splits
    if len(open_splits) > 1 and pay_amt is not None:
        exact = [x for x in open_splits
                 if str(x[2].get("amount")) == str(pay_amt)
                 and x[2].get("currency", "INR") == pay_cur]
        if len(exact) == 1:
            cands = exact
    if len(cands) != 1:
        names = ", ".join(x[2].get("name", "?") for x in cands)
        return (f"“Mark a split as settled” needs the agent — {len(cands)} open splits "
                f"({names}); say which one this payment settles.")
    item_id_bill, merchant, s = cands[0]
    res = store.update(item_id_bill, settle=s.get("name", ""))
    if not res.get("ok"):
        return f"❌ Settle failed: {res.get('error', 'unknown')}"
    return (f"✓ Settled {s.get('name', '?')}'s {s.get('amount', '?')} "
            f"{s.get('currency', pay_cur)} on bill {merchant or item_id_bill}.")


def _expense_month_total() -> str:
    """This month's bill totals per currency, for 'Log as expense'."""
    from collections import defaultdict
    ym = datetime.now().strftime("%Y-%m")
    totals: dict[str, float] = defaultdict(float)
    count = 0
    for r in store.list_items(kind="bill", status="active", limit=100).get("items", []):
        if str(r["fields"].get("date", "")).startswith(ym):
            try:
                totals[r["fields"].get("currency", "INR")] += float(r["fields"].get("amount", 0))
                count += 1
            except (TypeError, ValueError):
                pass
    if not count:
        return "✓ Expense logged (item already in ledger). No other bills this month."
    breakdown = ", ".join(f"{v:,.2f} {c}" for c, v in sorted(totals.items()))
    return f"✓ Expense logged. This month: {count} bill(s), {breakdown}."


def _google_link(title: str, start: datetime, end: datetime,
                 details: str = "", location: str = "") -> str:
    q = urllib.parse.urlencode({
        "action": "TEMPLATE", "text": title,
        "dates": f"{start.strftime('%Y%m%dT%H%M%S')}/{end.strftime('%Y%m%dT%H%M%S')}",
        "details": details, "location": location,
    })
    return "https://calendar.google.com/calendar/render?" + q


def _ics(title: str, start: datetime, end: datetime, details: str = "",
         location: str = "") -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//snap-action//EN\r\n"
            "BEGIN:VEVENT\r\nUID:" + uuid.uuid4().hex + "@snap-action\r\n"
            f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}\r\n"
            f"DTSTART:{start.strftime(fmt)}\r\nDTEND:{end.strftime(fmt)}\r\n"
            f"SUMMARY:{title}\r\n" +
            (f"LOCATION:{location}\r\n" if location else "") +
            (f"DESCRIPTION:{details}\r\n" if details else "") +
            "END:VEVENT\r\nEND:VCALENDAR\r\n")


def _calendar_payload(kind: str, fields: dict) -> tuple[str, str, str] | None:
    """(ics_text, google_link, title) or None if the item has no usable time."""
    if kind == "travel":
        title = f"Flight {fields.get('carrier', '')} {fields.get('ref', '')}: {fields.get('from', '')} to {fields.get('to', '')}".strip()
        start = _fmt_utc(fields.get("date"), fields.get("time"))
        arr = _fmt_utc(fields.get("date"), fields.get("arrives")) if fields.get("arrives") else None
        end = arr or (start + timedelta(hours=2) if start else None)
        location = fields.get("from", "")
    elif kind == "event":
        title = fields.get("title", "Event")
        start = _fmt_utc(fields.get("date"), fields.get("time"))
        end = start + timedelta(hours=2) if start else None
        location = fields.get("venue") or fields.get("location", "")
    else:
        return None
    if not start or not end:
        return None
    details = f"Ref: {fields.get('ref', '')}\nPax: {', '.join(fields.get('pax', []))}" \
        if kind == "travel" else fields.get("ref", "")
    ics = _ics(title, start, end, details=str(details), location=str(location))
    link = _google_link(title, start, end, details=str(details), location=str(location))
    return ics, link, title


# ---------------------------------------------------------------- auto-capture

async def handle_photo(event, source, image_paths, submit) -> None:
    """Gateway photo hook: offer a code-side 'Save to snaps?' keyboard for bare images.
    Zero LLM — the classification turn only runs if the user taps Save."""
    if len(image_paths) != 1:
        return  # multi-image dumps: skip, the user is probably just sharing
    chat_id = getattr(source, "chat_id", None)
    if not chat_id:
        return
    n = uuid.uuid4().hex[:8]
    now = datetime.now()
    _pending_saves[f"snapnew:{n}"] = (str(chat_id), image_paths[0], submit, now)
    for k in [k for k, (_, _, _, t) in _pending_saves.items() if now - t > SAVE_TTL]:
        _pending_saves.pop(k, None)
    keyboard = {"inline_keyboard": [[
        {"text": "💾 Save to snaps", "callback_data": f"snapnew:{n}:1"},
        {"text": "Ignore", "callback_data": f"snapnew:{n}:0"},
    ]]}
    try:
        await _api_async("sendMessage", {"chat_id": chat_id,
                                         "text": "Save this screenshot to snaps?",
                                         "reply_markup": json.dumps(keyboard)})
    except Exception:
        _pending_saves.pop(f"snapnew:{n}", None)


async def handle_new_callback(query, data: str, chat_id: str | None) -> None:
    """Tap on a 'Save to snaps?' offer keyboard."""
    try:
        await query.answer()
        parts = data.split(":")
        if len(parts) != 3 or not chat_id:
            return
        key, save = ":".join(parts[:2]), parts[2] == "1"
        entry = _pending_saves.pop(key, None)
        if not entry or entry[0] != chat_id or datetime.now() - entry[3] > SAVE_TTL:
            try:
                await query.edit_message_text("⌛ This offer expired — send the screenshot again.")
            except Exception:
                pass
            return
        if not save:
            try:
                await query.edit_message_text("👍 Ignored — nothing saved.")
            except Exception:
                pass
            return
        path, submit = entry[1], entry[2]
        prompt = ("The user tapped 💾 Save on a screenshot auto-capture offer — the original "
                  "image is attached. Run the snap-action workflow on it: classify the kind, "
                  "extract the fields, snap_save it with image_path set, then call snap_keyboard "
                  "with the new item id so the action buttons appear. Keep your final reply to "
                  "one short line confirming what was saved.")
        try:
            submit(prompt, [path])
        except Exception as e:
            await _api_async("sendMessage", {"chat_id": chat_id,
                                             "text": f"❌ Could not start the save flow: {e}"})
    except Exception:
        try:
            await query.answer(text="Something went wrong.", show_alert=True)
        except Exception:
            pass


async def handle_callback(query, data: str, chat_id: str | None) -> None:
    """Button tap on a snap recall keyboard: execute the action in code."""
    logger = __import__("logging").getLogger("hermes_plugins.snap_action")
    logger.info("snap callback: %s chat=%s", data, chat_id)
    try:
        answer = getattr(query, "answer")
        try:
            await answer()
        except TypeError:
            await answer(text="One moment…")
        parts = data.split(":")
        if len(parts) != 3 or not parts[2].lstrip("-").isdigit() or not chat_id:
            await _toast_edit(query, "❌ Bad button data.")
            return
        item_id, idx = int(parts[1]), int(parts[2])
        auth = _sent_auth.get(item_id)
        if not auth or auth[0] != chat_id or datetime.now() - auth[1] > AUTH_TTL:
            await _toast_edit(query, "🔒 This keyboard has expired — run /snaps recall again.")
            return
        r = store.get(item_id)
        if not r.get("ok"):
            await _toast_edit(query, f"❌ Snap {item_id} not found.")
            return
        item = r["item"]
        fields = item["fields"]
        labels = [a["label"] for a in actions_for(item["kind"], fields)] + ["Delete"]
        label = labels[idx] if idx < len(labels) else ""
        msg = f"Nothing to do — {label}" if not label else None
        if not label:
            await _toast_edit(query, msg)
            return
        low = label.lower()
        if low == "delete":
            store.delete(item_id)
            _sent_auth.pop(item_id, None)
            await _edit(query, f"🗑 Snap {item_id} deleted.")
            return
        if "calendar" in low:
            payload = _calendar_payload(item["kind"], fields)
            if not payload:
                await _toast_edit(query, "❌ No usable date/time on this item.")
                return
            ics, link, title = payload
            path = f"/tmp/snap_{item_id}.ics"
            with open(path, "w") as f:
                f.write(ics)
            resp = await _api_async("sendDocument", {
                "chat_id": chat_id, "caption": f"📅 {title}",
                "document": "attach://ics"},
                file_field="ics", file_path=path)
            if resp.get("ok"):
                await _api_async("sendMessage", {"chat_id": chat_id,
                                                 "text": "Google Calendar: " + link,
                                                 "reply_markup": json.dumps({"inline_keyboard": [[
                                                     {"text": "Open Google Calendar", "url": link}]]})})
                await _edit(query, f"📅 Calendar entry sent for snap {item_id}.")
            else:
                await _toast_edit(query, f"❌ {resp.get('description', 'send failed')}")
            return
        if "settled" in low:  # payment → settle a bill split
            await _edit(query, _settle_open_split(item_id, fields))
            return
        if "expense" in low:  # bill → it's already in the ledger; show month total
            await _edit(query, _expense_month_total())
            return
        if "split this bill" in low or "commitment" in low:
            await _toast_edit(query,
                              f"“{label}” needs the agent — just say it in chat.")
            return
        if any(w in low for w in ("remind", "prep", "check-in", "follow up")):
            fire = _fire_time(item["kind"], fields, label)
            if not fire:
                if "due date" in low:
                    await _edit(query, "ℹ️ No due date on this bill — nothing to remind about.")
                else:
                    await _toast_edit(query, "❌ No usable date on this item.")
                return
            from .timing import now_ist
            if fire <= now_ist():
                await _toast_edit(query, "⏱ That reminder time has already passed.")
                return
            when = fire.strftime("%Y-%m-%dT%H:%M:%S+05:30")
            prompt = (f"Reminder (snap-action item {item_id}): {label}. {item['summary']}. "
                      + (f"Note: {item['note']}." if item.get("note") else "")).strip()
            def _create():
                from tools.cronjob_tools import cronjob
                return cronjob(action="create", name=f"snap-{item_id}-{uuid.uuid4().hex[:6]}",
                               prompt=prompt, schedule=when, deliver=f"telegram:{chat_id}")
            res = await asyncio.to_thread(_create)
            logger.info("snap %s reminder cron result: %s", item_id, str(res)[:120])
            ok = "success" in str(res) and "false" not in str(res)[:200].lower() \
                and not str(res).lower().startswith("error")
            await _edit(query, (f"⏰ Reminder set for {fire.strftime('%b %d, %H:%M IST')} "
                                f"(snap {item_id})." if ok else f"❌ Reminder failed: {res}"))
            return
        if "just save" in low or "log it" in low or "track it" in low:
            await _edit(query, f"✓ Snap {item_id} saved — no further action.")
            return
        await _toast_edit(query, f"“{label}” needs the agent — just say it in chat.")
    except Exception:
        logger.exception("snap callback %s failed", data)
        try:
            await query.answer(text="Something went wrong.", show_alert=True)
        except Exception:
            pass


async def _edit(query, text: str) -> None:
    """Replace the recalled message with an outcome (handles photo + text)."""
    try:
        if getattr(query, "message", None) and getattr(query.message, "photo", None):
            await query.edit_message_caption(caption=text)
        else:
            await query.edit_message_text(text)
    except Exception:
        pass


async def _toast_edit(query, text: str) -> None:
    try:
        await query.answer(text=text)
    except Exception:
        pass
