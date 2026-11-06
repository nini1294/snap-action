"""snap-action — screenshot-to-action plugin.

The agent supplies the eyes (built-in vision reads the screenshot); this plugin
supplies the memory: a typed ledger of captured items and per-kind smart
actions, persisted via plugin_db so it survives plugin updates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import schemas, store

logger = logging.getLogger(__name__)


def _j(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _int(args: dict, key: str = "id"):
    try:
        return int(args.get(key))
    except (TypeError, ValueError):
        return None


def snap_save(args: dict, **kwargs) -> str:
    try:
        kind = str(args.get("kind", "")).strip()
        err = store.validate_kind(kind)
        if err:
            return _j({"ok": False, "error": err})
        fields = args.get("fields") or {}
        if not isinstance(fields, dict):
            return _j({"ok": False, "error": "fields must be an object"})
        return _j(store.save(kind, fields, args.get("note")))
    except Exception as e:  # never raise
        logger.exception("snap_save failed")
        return _j({"ok": False, "error": f"snap_save failed: {e}"})


def snap_list(args: dict, **kwargs) -> str:
    try:
        return _j(store.list_items(args.get("kind") or None,
                                   args.get("status", "active") or None,
                                   int(args.get("limit", 20))))
    except Exception as e:
        logger.exception("snap_list failed")
        return _j({"ok": False, "error": f"snap_list failed: {e}"})


def snap_get(args: dict, **kwargs) -> str:
    try:
        item_id = _int(args)
        if item_id is None:
            return _j({"ok": False, "error": "id must be an integer"})
        return _j(store.get(item_id))
    except Exception as e:
        logger.exception("snap_get failed")
        return _j({"ok": False, "error": f"snap_get failed: {e}"})


def snap_update(args: dict, **kwargs) -> str:
    try:
        item_id = _int(args)
        if item_id is None:
            return _j({"ok": False, "error": "id must be an integer"})
        fields = args.get("fields")
        if fields is not None and not isinstance(fields, dict):
            return _j({"ok": False, "error": "fields must be an object"})
        return _j(store.update(item_id, fields=fields,
                               status=args.get("status"),
                               settle=args.get("settle"),
                               note=args.get("note")))
    except Exception as e:
        logger.exception("snap_update failed")
        return _j({"ok": False, "error": f"snap_update failed: {e}"})


def snap_stats(args: dict, **kwargs) -> str:
    try:
        return _j(store.stats())
    except Exception as e:
        logger.exception("snap_stats failed")
        return _j({"ok": False, "error": f"snap_stats failed: {e}"})


def snap_delete(args: dict, **kwargs) -> str:
    try:
        item_id = _int(args)
        if item_id is None:
            return _j({"ok": False, "error": "id must be an integer"})
        return _j(store.delete(item_id))
    except Exception as e:
        logger.exception("snap_delete failed")
        return _j({"ok": False, "error": f"snap_delete failed: {e}"})


def _fmt_item(item: dict) -> str:
    from .kinds import KINDS
    emoji = KINDS.get(item["kind"], {}).get("emoji", "📎")
    flag = "" if item["status"] == "active" else f" ({item['status']})"
    line = f"{item['id']}. {emoji} {item.get('summary') or item['kind']}{flag}"
    extras = []
    f = item.get("fields", {})
    splits = f.get("splits")
    if splits:
        parts = ", ".join(
            f"{s.get('name')}: {s.get('amount')} {'✓' if s.get('paid') else 'pending'}"
            for s in splits)
        extras.append(f"   └ splits — {parts}")
    if f.get("due_date"):
        extras.append(f"   └ due {f['due_date']}")
    if item.get("note"):
        extras.append(f"   └ {item['note']}")
    return "\n".join([line] + extras)


def _snap_command(raw_args: str, **kwargs):
    """`/snaps` — human-readable ledger view."""
    try:
        arg = (raw_args or "").strip().lower()
        if arg in ("stats", "summary"):
            s = store.stats()
            lines = ["📊 snap-action stats"]
            open_splits = s.get("open_splits") or []
            if open_splits:
                by_name = {}
                for sp in open_splits:
                    key = (str(sp.get("name")), str(sp.get("currency") or ""))
                    by_name.setdefault(key, []).append(sp.get("amount"))
                lines.append("💸 Open splits: " + "; ".join(
                    f"{n} {sum(float(a or 0) for a in amt):g}{(' ' + cur) if cur else ''}"
                    for (n, cur), amt in sorted(by_name.items())))
            else:
                lines.append("💸 No open splits")
            renewals = s.get("subscriptions_next_renewals") or []
            if renewals:
                lines.append("🔁 Renewals: " + "; ".join(
                    f"{r['service']} {r.get('amount')} {r.get('currency')} on {r['next_renewal']}"
                    for r in renewals))
            by_kind = s.get("active_by_kind") or {}
            if by_kind:
                lines.append("🗂 Active: " + ", ".join(f"{k} ×{v}" for k, v in sorted(by_kind.items())))
            return "\n".join(lines)

        if arg.startswith("id "):
            item_id = _int({"id": arg.split()[1]})
            if item_id is None:
                return "❌ usage: /snaps id <number>"
            r = store.get(item_id)
            if not r.get("ok"):
                return f"❌ {r.get('error', 'not found')}"
            import json as _json
            it = r["item"]
            lines = [_fmt_item(it), "```json\n" + _json.dumps(it["fields"], ensure_ascii=False, indent=1)[:1200] + "```"]
            return "\n".join(lines)

        kind = arg if arg else None
        r = store.list_items(kind=kind)
        if not r.get("ok"):
            return f"❌ {r.get('error')}"
        if not r["items"]:
            return "📒 Ledger is empty — send a screenshot to capture something."
        scope = f" ({arg})" if arg else ""
        lines = [f"📒 snap ledger{scope} — {r['count']} active", ""]
        lines += [_fmt_item(it) for it in r["items"]]
        lines.append("")
        lines.append("📊 /snaps stats · /snaps <kind> · /snaps id <n>")
        return "\n".join(lines)
    except Exception as e:
        return f"snaps command failed: {e}"


def register(ctx):
    ctx.register_tool(name="snap_save", toolset="snap", schema=schemas.SAVE,
                      handler=snap_save, description="Save a screenshot-derived item (booking, bill, subscription, payment, event, task, warranty, delivery) and get suggested quick actions")
    ctx.register_tool(name="snap_list", toolset="snap", schema=schemas.LIST,
                      handler=snap_list, description="List captured snap-action items")
    ctx.register_tool(name="snap_get", toolset="snap", schema=schemas.GET,
                      handler=snap_get, description="Get one snap-action item by id")
    ctx.register_tool(name="snap_update", toolset="snap", schema=schemas.UPDATE,
                      handler=snap_update, description="Update an item: merge fields, settle a split by name, or change status")
    ctx.register_tool(name="snap_stats", toolset="snap", schema=schemas.STATS,
                      handler=snap_stats, description="Snapshot: active items by kind, open bill splits, upcoming subscription renewals")
    ctx.register_tool(name="snap_delete", toolset="snap", schema=schemas.DELETE,
                      handler=snap_delete, description="Delete a snap-action item by id")

    # NOTE: '/snap' is a built-in Hermes command (screenshot) — plugin commands
    # with that name are rejected at registration. The ledger command is /snaps.
    ctx.register_command(name="snaps", handler=_snap_command,
                         description="snap-action ledger: /snaps [stats | kind | id N]",
                         args_hint="[stats|kind|id N]")

    skill_path = Path(__file__).parent / "skills" / "workflow" / "SKILL.md"
    if skill_path.exists():
        ctx.register_skill(name="workflow", path=skill_path,
                           description="Screenshot-to-action workflow: classify an incoming image, extract fields, save, and offer numbered quick actions")

    logger.info("snap-action registered: 6 tools, /snap command, workflow skill")
