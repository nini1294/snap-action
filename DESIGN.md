# Design notes

Decisions, caveats, and open questions for snap-action. Feedback welcome —
change anything here and the code follows.

## Philosophy

The chat **is** the UI. Zero typing is the goal: user sends a screenshot with
no context, agent classifies it, and replies with tappable actions. Works on
any gateway platform; Telegram is the reference client.

## Architecture

```
screenshot ──▶ agent vision (built-in)  ──▶ classify + extract fields
           ──▶ snap_save                ──▶ ledger (plugin_db, SQLite)
           ──▶ reply: summary + native buttons (clarify)
user taps  ──▶ agent executes (cron reminder / snap_update / nothing)
```

- The plugin owns **memory** (the ledger); the agent owns **actions**
  (reminders go through Hermes cron, so they fire on any platform).
- Vision is Hermes' built-in image handling — the plugin ships no OCR, no
  models, no API calls. The session's main model reads the image natively;
  a non-vision main model falls back to the configured `auxiliary.vision`
  backend (`agent.image_input_mode: auto` → "text" mode). If neither exists,
  the workflow's no-vision guard tells the user how to fix their setup rather
  than guessing.
- **Data-driven kinds** (`kinds.py`): a new use case is one dict entry —
  `label`, `emoji`, required/optional fields, summary template, fixed action
  list. No code changes anywhere else.

## UX decisions

### Fixed options per kind
Every kind returns the same action labels in the same order, every time
(e.g. a receipt is always: Log as expense · Split this bill · Remind me
before due date). Enforced twice:
1. `snap_save` derives actions mechanically from `kinds.py`.
2. The bundled skill has a hard rule: labels verbatim, never paraphrased.

### Native buttons via `clarify`
After saving, the agent calls the built-in `clarify` tool with the action
labels — Telegram/desktop render them as inline keyboard buttons, with an
"✏️ Other (type answer)" row for free-form input. Text-only platforms
degrade to a numbered list automatically.

Caveat: stock Hermes renders clarify buttons as bare numbers (`1`, `2`, `3`)
with the text only in the message body. We patch the local checkout
(`plugins/platforms/telegram/adapter.py`, `send_clarify`) to put the action
text on the button itself (truncated at 46 chars, numbered prefix only when
truncated). `callback_data` is still the index, so tap handling is untouched.
This patch is **core-side, not part of this repo** — delete it once upstream
ships the generic message-buttons API (producer `metadata["buttons"]`).

### Never invent data
Dates not on the screenshot → agent asks one short question before saving.
Currencies kept exactly as printed — no silent conversion. Ambiguous dates
(3/11) resolved only from context, otherwise asked.

## Data model

One `items` table in `plugin-data/snap-action/data.db` (survives plugin
updates/removals):

| column | notes |
|--------|-------|
| id | autoincrement |
| kind | one of the `kinds.py` keys |
| status | `active` / `done` / `cancelled` |
| fields | JSON blob, schema per kind; `splits=[{name, amount, paid}]` on bills |
| note | free text |
| created_at / updated_at | UTC ISO |

Bill splits settle via `snap_update(settle="name")`; open splits surface in
`snap_stats` and a later `payment` screenshot offers to settle them.

## Calendar support

Travel and event kinds expose an "Add to calendar" action that produces two
things with no API keys or OAuth:
1. an **.ics file** sent as a chat attachment (Apple/Outlook/anything),
2. a **Google Calendar one-tap link** (`calendar.google.com/calendar/render?action=TEMPLATE&...`).

## Kinds (v1)

travel · bill · subscription · payment · event · task · warranty · delivery · other

Adding one = one entry in `kinds.py` (fields + actions). Candidates for v2:
parking, hotel folios, prescriptions, invoices receivable (follow up on
unpaid client invoices), exam/interview invites, class schedules.

## Testing

- `hermes plugins validate` ✓
- `hermes plugins doctor --ci` ✓
- Store layer exercised live: save (travel/bill/subscription), split, settle,
  stats, delete, delete-missing ✓
- End-to-end over Telegram: bill screenshots → buttons → split → settle flow ✓

## Known limitations

- Reminder execution depends on the agent following the skill (LLM, not code)
  — acceptable for v1; a hook could enforce it later.
- Subscription "monthly spend" in `snap_stats` sums one renewal per entry;
  ignores cycle length.
- Split names default to placeholders (P2, P3) when the screenshot doesn't
  name the diners; relabel by sending names in chat.
