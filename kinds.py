"""snap-action use-case registry.

Each kind is data-driven so new use cases are a dict entry, not code.
Actions are hints FOR THE AGENT: label is shown to the user, hint tells the
agent what executing that numbered reply means (cron reminder, snap_update, …).
"""

KINDS = {
    "travel": {
        "label": "Travel booking",
        "emoji": "\u2708\ufe0f",
        "fields": ["carrier", "ref", "from", "to", "date", "time"],
        "optional": ["seat", "pax", "hotel", "checkout"],
        "summary": "{carrier} {ref}: {from} \u2192 {to}, {date} {time}",
        "actions": [
            {"label": "Add to calendar (.ics + Google link)",
             "hint": "Build a calendar entry: title 'Flight {carrier} {ref}: {from} to {to}', start {date} {time}, end at the arrival time if present else start plus 2h, details include ref {ref} and pax, location {from}. Send (1) an .ics file for it as an attachment, and (2) a Google Calendar one-tap link: https://calendar.google.com/calendar/render?action=TEMPLATE with text, dates in YYYYMMDDTHMMSS/YYYYMMDDTHMMSS UTC-offset-free format, details and location params filled from the same values."},
            {"label": "Web check-in reminder (24h before)", "hint": "Flights only. One-shot cron reminder 24h before departure: web check-in opens, ref {ref}."},
            {"label": "Just save it", "hint": "No further action; item is already stored."},
        ],
    },
    "bill": {
        "label": "Bill / receipt",
        "emoji": "\U0001f9fe",
        "fields": ["merchant", "amount", "currency", "date"],
        "optional": ["category", "due_date", "items"],
        "summary": "{merchant} \u2014 {amount} {currency} ({date})",
        "actions": [
            {"label": "Log as expense", "hint": "Confirm expense entry is stored (item already saved); reply with running month total if a budget ledger exists."},
            {"label": "Split this bill", "hint": "Ask who is splitting (or read names from the screenshot), then call snap_update with splits=[{{name, amount, paid:false}}] (equal split unless amounts given)."},
            {"label": "Remind me before due date", "hint": "If fields.due_date is missing, reply that there's no due date on this bill (skip). Otherwise create a one-shot cron reminder 2 days before the due date."},
        ],
    },
    "subscription": {
        "label": "Subscription",
        "emoji": "\U0001f501",
        "fields": ["service", "amount", "currency", "cycle", "next_renewal"],
        "optional": ["plan"],
        "summary": "{service} \u2014 {amount} {currency}/{cycle}, renews {next_renewal}",
        "actions": [
            {"label": "Remind me 3 days before renewal (cancel/keep)", "hint": "One-shot cron reminder 3 days before {next_renewal}: decide cancel or keep, price {amount} {currency}."},
            {"label": "Just track it", "hint": "No further action; shows up in snap_stats subscription spend."},
        ],
    },
    "payment": {
        "label": "Payment confirmation",
        "emoji": "\U0001f4b3",
        "fields": ["amount", "currency", "date"],
        "optional": ["sender", "receiver", "ref", "method", "note"],
        "summary": "{amount} {currency} {sender} \u2192 {receiver} ({date})",
        "actions": [
            {"label": "Mark a split as settled", "hint": "Call snap_list(kind=bill, status=active), show open splits, let user pick which person this payment settles, then snap_update."},
            {"label": "Just log it", "hint": "No further action."},
        ],
    },
    "event": {
        "label": "Event / appointment",
        "emoji": "\U0001f4c5",
        "fields": ["title", "date"],
        "optional": ["time", "venue", "ref", "prep"],
        "summary": "{title} \u2014 {date} {time} @ {venue}",
        "actions": [
            {"label": "Add to calendar (.ics + Google link)",
             "hint": "Build a calendar entry: title {title}, start {date} {time or all-day}, location {venue}, details include ref and prep notes if present. Send (1) an .ics file for it as an attachment, and (2) a Google Calendar one-tap link: https://calendar.google.com/calendar/render?action=TEMPLATE with text, dates in YYYYMMDDTHMMSS/YYYYMMDDTHMMSS format, details and location params filled from the same values."},
            {"label": "Remind me that morning", "hint": "One-shot cron reminder the morning of {date} with venue, time and ref."},
            {"label": "Prep reminder the evening before", "hint": "One-shot cron reminder the evening before {date}."},
        ],
    },
    "task": {
        "label": "Chat / commitments",
        "emoji": "\U0001f4dd",
        "fields": ["summary"],
        "optional": ["todos", "people", "deadline"],
        "summary": "{summary}",
        "actions": [
            {"label": "Create reminders for each commitment", "hint": "For each item in todos, offer/create a cron reminder (confirm timing with user if no deadline is visible)."},
            {"label": "Save as note only", "hint": "No further action."},
        ],
    },
    "warranty": {
        "label": "Warranty",
        "emoji": "\U0001f6e1\ufe0f",
        "fields": ["product", "brand", "purchase_date", "warranty_until"],
        "optional": ["serial", "merchant"],
        "summary": "{brand} {product} \u2014 warranty until {warranty_until}",
        "actions": [
            {"label": "Remind me 30 days before it ends", "hint": "One-shot cron reminder 30 days before {warranty_until}: warranty on {product} ending, file a claim if faulty."},
            {"label": "Just save it", "hint": "No further action."},
        ],
    },
    "delivery": {
        "label": "Delivery / shipment",
        "emoji": "\U0001f4e6",
        "fields": ["courier", "tracking_id", "expected_date"],
        "optional": ["item"],
        "summary": "{courier} {tracking_id} \u2014 expected {expected_date}",
        "actions": [
            {"label": "Remind me on delivery day", "hint": "One-shot cron reminder the morning of {expected_date} with tracking id."},
            {"label": "Follow up if not delivered", "hint": "One-shot cron reminder the day after {expected_date}: not delivered? chase courier with {tracking_id}."},
        ],
    },
    "other": {
        "label": "Note",
        "emoji": "\U0001f5ce\ufe0f",
        "fields": ["summary"],
        "optional": ["details"],
        "summary": "{summary}",
        "actions": [
            {"label": "Just save it", "hint": "No further action."},
        ],
    },
}

SPLIT_STATUSES = ("active", "done", "cancelled")
