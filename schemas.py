"""JSON schemas for snap-action tools."""

SAVE = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": [
            "travel", "bill", "subscription", "payment", "event",
            "task", "warranty", "delivery", "other"]},
        "fields": {"type": "object", "description":
                   "Extracted fields per kind spec (see snap-action skill). "
                   "Dates as YYYY-MM-DD. For bills may include "
                   "splits=[{name, amount, paid}] after the user confirms."},
        "note": {"type": "string", "description": "Optional free-text context"},
        "image_path": {"type": "string", "description":
                       "Path of the screenshot this item was captured from. "
                       "The plugin keeps a durable copy so it can be recalled later."},
    },
    "required": ["kind", "fields"],
}

LIST = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "status": {"type": "string", "enum": ["active", "done", "cancelled"],
                   "description": "Default: active. Pass empty string to include all."},
        "limit": {"type": "integer", "default": 20},
    },
}

KEYBOARD = {
    "type": "object",
    "properties": {
        "id": {"type": "integer", "description": "Item id to show the action keyboard for"},
    },
    "required": ["id"],
}

GET = {
    "type": "object",
    "properties": {"id": {"type": "integer"}},
    "required": ["id"],
}

UPDATE = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "fields": {"type": "object", "description": "Field merges (e.g. splits)"},
        "status": {"type": "string", "enum": ["active", "done", "cancelled"]},
        "settle": {"type": "string", "description": "Name of a split participant to mark paid"},
        "note": {"type": "string"},
    },
    "required": ["id"],
}

STATS = {"type": "object", "properties": {}}

DELETE = {
    "type": "object",
    "properties": {"id": {"type": "integer"}},
    "required": ["id"],
}
