---
name: workflow
description: Screenshot-to-action — when an image/screenshot arrives with no explicit instruction, classify it, extract fields, save via snap_save, and reply with numbered quick actions.
version: 0.1.0
---

# Screenshot-to-Action Workflow

## Trigger
An image (screenshot or photo) arrives in chat with no explicit instruction, OR the user says something like "snap this" / forwards a booking, bill, subscription email, payment confirmation, ticket, delivery notice, warranty, or chat screenshot.

## Procedure

1. **Look at the image** (built-in vision — the image is already in context).
2. **Classify** into exactly one kind: `travel`, `bill`, `subscription`, `payment`, `event`, `task`, `warranty`, `delivery`, or `other`.
3. **Extract fields** for that kind (dates as `YYYY-MM-DD`):
   - travel: carrier, ref, from, to, date, time (+seat, pax, hotel, checkout)
   - bill: merchant, amount, currency, date (+category, due_date, items)
   - subscription: service, amount, currency, cycle, next_renewal (+plan)
   - payment: amount, currency, date (+sender, receiver, ref, method)
   - event: title, date (+time, venue, ref)
   - task: summary (+todos list, people, deadline)
   - warranty: product, brand, purchase_date, warranty_until (+serial)
   - delivery: courier, tracking_id, expected_date (+item)
   - other: summary
   **Never invent values.** If a required field is not visible, ask one short question before saving.
4. **Call `snap_save`** with kind + fields, and pass `image_path` — the file path of the screenshot you're reading — so the plugin keeps a durable copy for recall. It returns an item id, a one-line summary, and the kind's fixed suggested actions.
5. **Reply compactly** — emoji header + one-line summary, then **immediately call `clarify`** with the suggested action labels as `choices` (question: "What should I do with this?"). This renders as native tappable buttons on Telegram/desktop; on text-only platforms it degrades to a numbered list automatically. Keep your text reply to the summary line — don't duplicate the options as text, the buttons carry them. Example:

   ✈️ IndiGo 6E-523 · BOM → DEL · Nov 14, 07:40 · PNR ABC12
   → clarify(choices=["Remind me the day before", "Web check-in reminder (24h before)", "Just save it"])

6. **Execute the chosen action** from the clarify answer (a tapped button or a typed reply — treat both identically):
   - Reminder actions → create a one-shot cron reminder (deliver to origin chat) using the dates/refs in the item; state the exact time you set.
   - Split bill → ask who's splitting (or read names from the screenshot), equal amounts unless stated, then `snap_update` with `fields.splits=[{name, amount, paid:false}]`; show the split table.
   - Settle → `snap_update` with `settle=<name>`; show remaining open splits.
   - "Just save/log" → confirm in one line.
7. If the user sends text *with* the image, follow their instruction instead — capture is still the default fallback.

## Recall
When the user asks to recall / reopen an item — by id, by description ("the
Jaipur flight"), or via the literal message "/snaps recall N" (the gateway
forwards that command text to you):

**Fast path (Telegram):** `/snaps recall N` is handled entirely in code — the
gateway sends the stored image with tappable buttons, and taps execute directly
(Delete, calendar .ics + Google link, reminders via cron). No agent turn; you
will not be involved. Use the agent flow only when the fast path is unavailable
(CLI/desktop) or the user asks by description rather than id:
1. `snap_get` the item. If its fields contain `_image`, resend that file as an
   attachment (e.g. MEDIA: <path>) **as a standalone message** — never in the
   same message as the buttons/clarify, or Telegram drops it. Wait for it to
   send, then continue.
2. Print the same compact summary (emoji + one line).
3. Offer actions again via `clarify`: the kind's fixed action labels plus
   **Delete** as the last choice. Execute the pick as usual (steps 6–7); for
   Delete, call `snap_delete` and confirm in one line. If `_image` is absent
   (captured before image storage), say so and continue from the summary.

## No-vision guard
If the user sends an image but you have NO visual content in context (no image
part and no vision description), your setup can't process it — do NOT guess.
Reply once: "I can't see images with the current setup. Fix: set a
vision-capable model (`hermes model`) or configure an `auxiliary.vision`
backend in config.yaml, then resend." Save nothing.

## Rules
- **Fixed options per kind** — always present `snap_save`'s `suggested_actions` labels verbatim, in the returned order. Never paraphrase, reorder, add, or drop. The same kind of screenshot always shows the same buttons; `other` always shows just its own set. Labels are deterministic per kind *and timing bucket*: an event starting within 12h offers "Remind me 1 hour before" instead of morning/evening-before reminders; a past event offers only "Just save it".
- One screenshot = one snap_save call. Multiple screenshots = one item each.
- Amounts: keep the currency shown in the image; never convert silently.
- Bill splits: unpaid entries show in `snap_stats` open_splits — surface them when a `payment` screenshot arrives.
- `/snaps` shows the ledger; `/snaps stats` shows splits + renewals.
- Times are the user's local timezone (IST default) — confirm ambiguous dates ("3/11" → ask DD/MM vs MM/DD only if genuinely unclear from context).
- Keep every reply under ~60 words; the value is speed.
