# snap-action

**Screenshot-to-action plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent)** — send any screenshot to your agent with no explanation, and get a one-line summary plus numbered smart actions you can trigger by replying with the number.

```
You:  [screenshot of IndiGo boarding pass]
Bot:  ✈️ IndiGo 6E-523 · BOM → DEL · Nov 14, 07:40 · PNR ABC12
      1️⃣ Remind me the day before
      2️⃣ Web check-in reminder (24h before)
      3️⃣ Just save it
You:  1
Bot:  ⏰ Reminder set for Nov 13, 6:00 PM — ref ABC12.
```

## Use cases (kinds)

| Kind | Captures | Smart actions |
|------|----------|---------------|
| `travel` | Flight/train/bus/hotel bookings | Day-before reminder, web check-in reminder |
| `bill` | Receipts, bills, invoices | Expense logging, **split bill** with per-person settle tracking, due-date reminder |
| `subscription` | Renewal/pricing emails | Reminder 3 days before renewal (cancel/keep decision) |
| `payment` | UPI/bank transfer confirmations | Settle an open bill split |
| `event` | Tickets, appointments, invites | Morning-of reminder, evening-before prep reminder |
| `task` | Chat screenshots with commitments | One reminder per commitment |
| `warranty` | Purchase receipts | Reminder 30 days before warranty expires |
| `delivery` | Shipment notices | Delivery-day reminder, not-delivered follow-up |
| `other` | Anything else | Free-form note |

## Install

```bash
hermes plugins install YOURUSER/snap-action
hermes plugins enable snap-action
```

Or manually: clone into `~/.hermes/plugins/snap-action/`, then `hermes plugins enable snap-action`.

## How it works

Your agent's built-in vision reads the screenshot; this plugin supplies the **memory and actions**:

- **Data-driven kind registry** (`kinds.py`) — a new use case is one dict entry, no code changes
- **SQLite ledger** via Hermes `plugin_db()` — survives plugin updates and removals (`~/.hermes/plugin-data/snap-action/`)
- **Bundled workflow skill** — teaches any Hermes session the classify → extract → save → offer-actions → execute loop
- **`/snap` command** — list the ledger; `/snap stats` shows open bill splits and upcoming renewals

Reminder actions are executed through Hermes cron, so they work on any platform your gateway runs on (Telegram, Discord, Slack, WhatsApp, …).

## Tools

`snap_save` · `snap_list` · `snap_get` · `snap_update` · `snap_stats` · `snap_delete`

## Notes

- Amounts and currencies are kept exactly as shown in the screenshot — never converted silently
- All data stays local in your Hermes home directory
- No external API calls, no credentials required

## Status

v0.1.0 — validated with `hermes plugins validate` and `hermes plugins doctor --ci`.
