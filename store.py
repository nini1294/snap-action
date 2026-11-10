"""snap-action storage: sqlite via plugin_db (survives plugin updates)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .kinds import KINDS, SPLIT_STATUSES

PLUGIN_NAME = "snap-action"


def _db() -> sqlite3.Connection:
    try:
        from plugins.plugin_storage import plugin_db
        return plugin_db(PLUGIN_NAME)
    except Exception:
        # Fallback: never crash registration/tool calls if the host helper moves.
        import os
        path = os.path.expanduser(f"~/.hermes/plugin-data/{PLUGIN_NAME}/data.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return sqlite3.connect(path)


def _init() -> None:
    db = _db()
    with db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                fields TEXT NOT NULL DEFAULT '{}',
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_item(row) -> dict:
    return {
        "id": row[0], "kind": row[1], "status": row[2],
        "fields": json.loads(row[3] or "{}"), "note": row[4],
        "created_at": row[5], "updated_at": row[6],
    }


_INITED = False


def _ensure() -> None:
    global _INITED
    if not _INITED:
        _init()
        _INITED = True


def validate_kind(kind: str):
    if kind not in KINDS:
        return f"unknown kind {kind!r}; valid: {', '.join(sorted(KINDS))}"
    return None


def _images_dir() -> str:
    import os
    path = os.path.expanduser(f"~/.hermes/plugin-data/{PLUGIN_NAME}/images")
    os.makedirs(path, exist_ok=True)
    return path


def _store_image(item_id: int, src: str) -> str | None:
    """Copy the source screenshot into plugin-data so recalls outlive cache pruning."""
    try:
        import os, shutil
        src = os.path.expanduser(str(src))
        if not os.path.isfile(src):
            return None
        ext = os.path.splitext(src)[1].lower() or ".jpg"
        dst = os.path.join(_images_dir(), f"{item_id}{ext}")
        shutil.copyfile(src, dst)
        return dst
    except Exception:
        return None


def save(kind: str, fields: dict, note: str | None, image_path: str | None = None) -> dict:
    _ensure()
    spec = KINDS[kind]
    missing = [f for f in spec["fields"] if not fields.get(f)]
    if missing:
        return {"ok": False, "error": f"missing required field(s): {', '.join(missing)}"}
    now = _now()
    db = _db()
    with db:
        cur = db.execute(
            "INSERT INTO items (kind, fields, note, created_at, updated_at) VALUES (?,?,?,?,?)",
            (kind, json.dumps(fields, ensure_ascii=False), note, now, now),
        )
        item_id = int(cur.lastrowid or 0)
    if image_path:
        stored = _store_image(item_id, image_path)
        if stored:
            fields["_image"] = stored
            with db:
                db.execute("UPDATE items SET fields=? WHERE id=?",
                           (json.dumps(fields, ensure_ascii=False), item_id))
    placeholder = {f: "" for f in spec["fields"] + spec.get("optional", [])}
    try:
        summary = spec["summary"].format(**{**placeholder, **fields})
    except Exception:
        summary = str(fields)
    actions = [
        {"n": i + 1, "label": a["label"],
         "hint": (a["hint"].format(**{**placeholder, **fields}) if fields else a["hint"])}
        for i, a in enumerate(spec["actions"])
    ]
    return {"ok": True, "id": item_id, "kind": kind, "label": spec["label"],
            "emoji": spec["emoji"], "summary": summary, "suggested_actions": actions}


def list_items(kind: str | None = None, status: str | None = "active", limit: int = 20) -> dict:
    _ensure()
    q, params = "SELECT * FROM items", []
    clauses = []
    if kind:
        err = validate_kind(kind)
        if err:
            return {"ok": False, "error": err}
        clauses.append("kind=?"); params.append(kind)
    if status:
        if status not in SPLIT_STATUSES:
            return {"ok": False, "error": f"invalid status; valid: {', '.join(SPLIT_STATUSES)}"}
        clauses.append("status=?"); params.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY id DESC LIMIT ?"; params.append(max(1, min(int(limit or 20), 100)))
    rows = _db().execute(q, params).fetchall()
    items = [_row_to_item(r) for r in rows]
    for it in items:
        it["summary"] = _summary(it)
    return {"ok": True, "count": len(items), "items": items}


def get(item_id: int) -> dict:
    _ensure()
    row = _db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return {"ok": False, "error": f"no item #{item_id}"}
    item = _row_to_item(row)
    item["summary"] = _summary(item)
    return {"ok": True, "item": item}


def update(item_id: int, fields: dict | None = None, status: str | None = None,
           settle: str | None = None, note: str | None = None) -> dict:
    _ensure()
    db = _db()
    row = db.execute("SELECT fields, status FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        return {"ok": False, "error": f"no item #{item_id}"}
    cur_fields = json.loads(row[0] or "{}")
    if settle:
        splits = cur_fields.get("splits") or []
        hit = [s for s in splits if s.get("name", "").lower() == settle.lower()]
        if not hit:
            return {"ok": False, "error": f"no open split for {settle!r}",
                    "open_splits": [s for s in splits if not s.get("paid")]}
        for s in hit:
            s["paid"] = True
        cur_fields["splits"] = splits
    if fields:
        cur_fields.update(fields)
    new_status = status if status in SPLIT_STATUSES else row[1]
    with db:
        db.execute("UPDATE items SET fields=?, status=?, note=COALESCE(?, note), updated_at=? WHERE id=?",
                   (json.dumps(cur_fields, ensure_ascii=False), new_status, note, _now(), item_id))
    return get(item_id)


def delete(item_id: int) -> dict:
    _ensure()
    row = _db().execute("SELECT fields FROM items WHERE id=?", (item_id,)).fetchone()
    if row:
        img = (json.loads(row[0] or "{}")).get("_image")
        if img:
            import os
            try:
                os.remove(os.path.expanduser(img))
            except OSError:
                pass
    db = _db()
    with db:
        cur = db.execute("DELETE FROM items WHERE id=?", (item_id,))
    if cur.rowcount == 0:
        return {"ok": False, "error": f"no item #{item_id}"}
    return {"ok": True, "deleted": item_id}


def stats() -> dict:
    _ensure()
    rows = _db().execute(
        "SELECT kind, status, fields FROM items ORDER BY id DESC"
    ).fetchall()
    by_kind: dict = {}
    open_splits = []
    renewals = []
    for kind, status, fj in rows:
        if status != "active":
            continue
        f = json.loads(fj or "{}")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        for s in f.get("splits") or []:
            if not s.get("paid"):
                open_splits.append({"name": s.get("name"),
                                    "amount": s.get("amount"),
                                    "currency": f.get("currency")})
        if kind == "subscription" and f.get("next_renewal"):
            renewals.append({"service": f.get("service"), "amount": f.get("amount"),
                             "currency": f.get("currency"), "next_renewal": f["next_renewal"]})
    renewals.sort(key=lambda r: r["next_renewal"])
    monthly_sub = sum(float(r["amount"] or 0) for r in renewals)
    return {"ok": True, "active_by_kind": by_kind,
            "open_splits": open_splits, "open_split_total_names": sorted({s["name"] for s in open_splits if s.get("name")}),
            "subscriptions_next_renewals": renewals[:5],
            "note": "subscription monthly total assumes one renewal per cycle entry; verify cycle field for exact math."}


def _summary(item: dict) -> str:
    spec = KINDS.get(item["kind"])
    if not spec:
        return str(item["fields"])
    placeholder = {f: "" for f in spec["fields"] + spec.get("optional", [])}
    try:
        return spec["summary"].format(**{**placeholder, **item["fields"]})
    except Exception:
        return str(item["fields"])
