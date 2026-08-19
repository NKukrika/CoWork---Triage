# Master Ticket Naming Convention

## Format

```
[Category] Short Description
```

- The category sits in square brackets, spelled **exactly** as it appears in `categories.csv`.
- One space after the closing bracket.
- Short description in sentence case, no trailing punctuation.
- Keep the description to roughly 3–8 words — specific enough to distinguish it from a neighbouring issue, short enough to scan in a list.

## The identical-name rule

Every ticket describing the same underlying issue carries the **same master name, character for character**. No variations in wording, casing, pluralisation, or spacing. This is what makes the master grouping countable.

If an incoming ticket is the same issue as an existing master, reuse that master's name verbatim from `master-tickets.csv` — do not re-derive it from the ticket's own wording.

## Writing a good short description

Describe the **symptom the user experiences**, not the suspected cause. Causes change during investigation; symptoms are how the next agent will recognise a duplicate.

| Prefer | Avoid | Why |
|---|---|---|
| `Autopayment not deducted from saved card` | `Worldpay tokenisation failure` | Cause may be wrong; symptom is recognisable |
| `Card not visible in MyRegus after Titan setup` | `Card sync issue` | Too vague to distinguish from other card issues |
| `Unable to book meeting room outside business hours` | `Booking problem` | Not specific enough to be findable |

Include the system name where it disambiguates (MyRegus, Dynamics, Titan, mobile app).

Do not include: ticket numbers, customer names, centre names, account IDs, dates. Those live on the child ticket, not the master.

## Worked examples

```
[Autopayment Not Working] Autopayment not deducted from saved card
[Card Not Visible / Titan-MyRegus Sync] Card configured in Titan not showing in MyRegus
[Login & Account Access] Verification code not received at login
[Booking Issues] Unable to book meeting room outside business hours
[Invoicing Issues] Payment not reflecting against invoice in MyRegus
```

## When to propose a new master

Propose a new master only when the ticket's symptom is genuinely distinct from every existing master — not merely worded differently. Same symptom, different words means reuse the existing master.

A proposed new master must include:

- the name in the format above
- the category it belongs to
- which existing masters it is closest to, and why it is nonetheless distinct
- the ticket IDs that motivated it
- a note that it needs an `MST-xxxxx` tag allocated before child tickets can be tagged

## MST tags

Each master carries an `MST` tag in the `MST Tag` column of `master-tickets.csv`, and child tickets are tagged with it. Two formats are in use, both preserved exactly as supplied:

- `MST-71218` — five digits
- `MST - 002-25` — spaced, sequence and year

A new master has no tag until one is allocated. Until then a matching ticket gets `TriagedTicket`, `ChildTicket` and its category, plus a recorded blocker for the missing tag.

New masters are never auto-created. They go on the review sheet for approval.
