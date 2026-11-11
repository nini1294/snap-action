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

## Callback fast path (code-side actions)

`register_callback_handler("snap", …)` in fastpath.py: `/snaps recall N` on
Telegram sends the image + inline keyboard straight over the Bot API (no agent
turn); taps with callback_data `snap:<id>:<idx>` route through the gateway's
plugin-callback registry and execute in code — Delete (store.delete), Add to
calendar (.ics sendDocument + Google TEMPLATE link), reminders (one-shot cron
via the cronjob tool), Just save it (toast). Chat authorization: the keyboard
records the sending chat; taps from any other chat (or after 24h) are refused.
Labels stay deterministic via timing.py. All actions execute in code: reminders
map each label to a fire time (1h/24h before, 3d before renewal, 30d before
warranty end, morning-of, evening-before, 2d before due date, delivery day,
next-day follow-up) and create a one-shot cron (IST); payments settle the
unambiguous open bill split (amount+currency match, else agent); bills log with
a month total; 'Split this bill' and multi-commitment tasks stay agent-deferred.
The agent flow remains the fallback for description-based recalls and
non-Telegram surfaces. All stored times are IST; timing.py compares in IST even
when the host clock is UTC.

## Future work (researched from docs, 2026-11-11)
Sequenced roadmap — nothing implemented yet:
1. ctx.llm classification in the photo hook — one structured LLM call in-plugin
   (host credentials, images supported) instead of spawning an agent turn; agent
   stays out unless the user asks a question.
2. dashboard/plugin_api.py (FastAPI, mounted at /api/plugins/snap-action, reads
   data.db) + desktop/plugin.js page — unified package, shared backend, ledger
   GUI for desktop + web dashboard (tabs/slots: cron:top, analytics:bottom).
3. config_schema (reminder hour, default currency, lead times) + requires_env
   (TELEGRAM_BOT_TOKEN) in plugin.yaml.
4. Gateway startup event hook (~/.hermes/hooks/) to auto-run reload-plugins,
   killing the boot-ordering workaround.
5. Upstream issues: callback-fallback routing and photo-hook seams don't exist
   officially — docs invite requests for missing public hooks.
Also available: Telegram rich messages (Bot API 10.1 native tables/details/
task-lists) for recall+stats output; web_app inline button → VPS-hosted
mini-app ledger; deep-link t.me/<bot>?start=snap_<id> on reminder messages.

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
