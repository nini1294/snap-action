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


def _snap_command(raw_args: str, **kwargs):
    """`/snap` — recent items + stats snapshot."""
    try:
        arg = (raw_args or "").strip().lower()
        if arg in ("stats", "summary"):
            payload = store.stats()
        elif arg.startswith("id "):
            payload = store.get(_int({"id": arg.split()[1]}))
        else:
            kind = arg if arg else None
            payload = store.list_items(kind=kind)
        lines = [f"```json\n{json.dumps(payload, ensure_ascii=False, indent=1)[:3000]}```"]
        return "\n".join(lines)
    except Exception as e:
        return f"snap command failed: {e}"


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

    ctx.register_command(name="snap", handler=_snap_command,
                         description="snap-action ledger: /snap [stats | kind | id N]",
                         args_hint="[stats|kind|id N]")

    skill_path = Path(__file__).parent / "skills" / "workflow" / "SKILL.md"
    if skill_path.exists():
        ctx.register_skill(name="workflow", path=skill_path,
                           description="Screenshot-to-action workflow: classify an incoming image, extract fields, save, and offer numbered quick actions")

    logger.info("snap-action registered: 6 tools, /snap command, workflow skill")
