---
name: ticket-triage-master
description: Triage a ServiceNow ticket export against the master-ticket registry, categories, KBAs, routing rules and priority matrix, producing a run workbook. Use when asked to run triage, triage tickets, process a ServiceNow export, match tickets to master tickets, or propose new masters.
---

# Ticket triage

Triages an incoming ServiceNow export against the reference registry in this workspace and
writes one workbook per run into `runs/`.

Run everything from the **workspace root** — the folder holding `reference/` and `runs/`.
The scripts resolve `reference/` and `runs/` relative to the working directory.

## Running a triage

```
python run_triage.py "path/to/export.xlsx" [output.xlsx]
```

Output defaults to `runs/Triage_<today>.xlsx`. Requires `pandas` and `openpyxl`.

After changing **any** file in `reference/`, run `python measure.py` — it re-checks accuracy
against the benchmark set so a reference edit can't silently degrade matching.

`measure.py` needs the ground-truth workbooks, which are not committed. It looks in
`$TRIAGE_UPLOADS`, then `reference/truth/`, then `runs/`, and stops with the filenames it
wants if they are absent — see `reference/truth/README.md`. **If it cannot run, say so and
do not claim a reference change was measured.**

## Order of work per ticket

1. **Match to a master ticket** in `reference/master-tickets.csv` — this happens first.
2. **Take the category from the matched master.** The registry is authoritative; the master's
   name embeds its category in brackets, so overriding it would make the name contradict the tag.
3. Only if no master matches, fall back to the agent's pipe hint (when it resolves to a real
   category), then to keyword classification — short description first, body only as a last resort.
4. Look up a **KBA** in `reference/kba-index.csv`. Offer one only at strong confidence.
5. Search **JIRA** once per master and note whether a defect fixed it.

Disagreements between the pipe hint and a matched master are flagged for review, never silently
resolved.

## Rules that are easy to get wrong

**The assignment group on the export wins.** Take it as supplied and never overwrite it. Labels
normalise (`L2-Titan`, `l2 titan`, `Titan` → `L2 - Titan`). Still run the routing rule on every
row and flag disagreements on the Group Mismatches sheet — mis-routed tickets stay visible
without anything being reassigned. Every routing error measured came from overriding the sheet.

**Route on where the issue is shown**, not on which systems are mentioned:

| Where the issue is visible | Group |
|---|---|
| Titan | L2 - Titan |
| Customer Portal or TeamHub | L2 - Portal |
| Login — OTP, verification email, activation, password reset | L2 - Proton |

Login outranks surface, **but only when signing in is the fault** — an OTP, verification email,
activation, password reset, blocked or inactive account. A passing mention does not count:
"outage affecting Finland centres after reinstall and login" is a TeamHub outage where login is
remediation the reporter already tried, and the reviewer routed it to Portal. Of the 22 Login
keywords only the bare word `login` can match an incidental mention; every other names a failure.

A system named as *background* does not count either: read the words immediately before each
system name — `configured on`, `set up in`, `we can see` mark background; `not present on`,
`unable to … in`, `error on` mark the observed failure.

**Symptom beats the pipe hint.** Most category errors came from trusting the agent's area label
over the actual issue.

**Priority is a grid lookup, never a formula** — `reference/priority-matrix.csv`, urgency ×
impact. Default to P3. P1 requires outage evidence; without it, cap at P2. Leave priority blank
when the ticket doesn't state scope — impact is a human decision.

**A single centre is a LOW-impact issue.** There are a few thousand centres, so one of them being
affected is not widespread, and a supplied `4 - Low` is correct even when the body says "all
customers at this centre". Do not raise impact from body text. (The older note that a single
centre is impact 2 distinguishes 2 from 1 — all centres — and does not make one centre high.)

**Never conclude from a JIRA resolution label alone — read the comments.** Two tickets closed
with identical labels had opposite causes; the labels alone gave exactly the wrong routing.

**Root cause is a suggestion.** It measures ~44% on the graded rows, because the label records
what the investigation found, not what the customer wrote. A rebuild of the category priors
scores 67% on those rows but is **not independently verified** — no export carries a resolution
code to check it against. Confirm before saving.

## Category rulings

These are the service owner's decisions. They override the resolved-ticket benchmark where the
two disagree — the benchmark carries older labelling that the owner is correcting.

| Ticket says | Category |
|---|---|
| Adding, registering or setting up a payment method — any instrument, including direct debit | **Payments Registration** |
| A payment that failed, declined, was not authorised, or a card that is wrong or invisible | **Payments - Credit Card** |
| A national e-invoicing authority rejecting or holding invoices — Edicom, Pagero, KSeF, EFRIS, ETA | **Invoicing** |
| Tax or fiscal configuration — GST, CIN, VAT, stamp duty, CGST/SGST | **Invoicing** |
| A printer that authenticates but does not print | **XC (Product and Services)** |
| Unable to amend an agreement in TeamHub | **Renewals** |
| Getting *to* a printer or a door — WiFi authentication code, WorldKey PIN, access card | **Quick Access** |

The e-invoicing tickets carry `EI-xxxxx` and "Pending EI team" tags and no category of their own.
That marks a workstream, not a missing category — they are Invoicing.

**Non-English tickets are cancelled.** Only English is accepted, so a body in another language
needs no special handling; classify from whatever English the title carries and flag it.

## Mandatory details, and the MissingInformation tag

Owner rule, 16 Sep 2026. What a ticket must carry depends on the kind of issue:

| Kind | Must include |
|---|---|
| **Bookings** | Company, Centre, Booking reference |
| **Payments** | Company, Centre, card first 6 + last 4 — and an invoice number **if the ticket is about paying an invoice** |
| **Invoices** | Company, Centre, Invoice number |
| **Internal / Staff** | Email of the affected user |

**SOA is exempt** (owner, 16 Sep) — statement and balance reconciliation does not
always cite an invoice. Categories outside these four kinds carry no mandatory
requirement and are never flagged.

A ticket missing any of these is **tagged `MissingInformation`** and appears on
the **`Missing Information`** sheet with its kind, what is absent, and a drafted
comment.

**Do NOT cancel.** The owner reviews the tagged set first; cancellation follows
only once they have checked it. The run never posts a comment and never cancels —
both are ServiceNow actions a person performs, and cancellation is irreversible
from the requester's side.

**Company and centre are matched by NAME as well as number** (owner, 16 Sep). A
legal-entity suffix is the reliable marker for a company — `Ltd`, `LLC`, `GmbH`,
`B.V.`, `S.r.l.`, `Corporation`, `株式会社` — and appears in 21% of tickets; centres
are matched on a brand (`Regus`, `Spaces`, `HQ`, `Signature`), the word centre
next to a number, or a named centre such as *"Nof HaGalil Center"*. Adding name
detection recovered 24 of the 58 tickets previously flagged for a missing company.

**Measured on 238 tickets:** 55% fall under one of the four kinds, and 87% of
those are missing at least one mandatory detail — 48% of all tickets tagged.

**Centre is the binding constraint** — 90 of the 131 in-scope tickets do not name
one, against 34 missing a company. Sampled by hand: the remaining company flags
are bulk e-invoicing tickets that genuinely name no customer, and the centre
flags carry a company and card but no centre at all. The figure is the rule
biting, not a detector fault.

## The short description must EXPLAIN the issue

One line saying what went wrong — not the opening words of the ticket. `propose_master_name()`
only trims: it strips filler, IDs and trailing clauses and then truncates. On a pipe-structured
ticket that works, because the last pipe segment already states the fault. On free-form email or
a pasted error dump there is no such sentence to recover, and it returns something like
*"CROATIAERROR: Upload FailedINVOICES:7247-26-…"*.

**Hand-written names are the normal case for free-form tickets, not an exception.** Add them to
`MANUAL_NAME` in `run_triage.py`, written from the body. A run of 35 needed 27.

Children of a master keep the master's name even when it is generic — `[Retainers] Retainer
issues` covers every retainer fault by design. That is not a conflict with this rule.

## Verifying a reference change

Three checks, in this order, and **all three before shipping**:

1. **Probe the keyword against the benchmark first.** Count how many tickets contain it and which
   categories they are tagged. A term that splits across categories is a coin toss, not a rule —
   `authentication code` is Login 10 / Quick Access 7, `marked as paid` is Invoicing 5 / Payments
   3 / SOA 2. Both were rejected on that evidence.
2. **`python measure.py`** — the 3,716-ticket resolved benchmark.
3. **`python score_against_scorecard.py <scorecard.xlsx>`** — the reviewer's graded rows.

A change can improve one and cost the other. `unable to add` lifted the scorecard and cost 14
benchmark rows, because it fires on document and service tickets too; card-scoped forms kept the
gain and returned the loss. **Report both numbers, including when a change costs nothing.**

Prefer terms that are **zero-hit in the benchmark but specific to the symptom** — they cannot
steal an existing row. Avoid bare nouns a ticket merely mentions: `wallet`, `staff mode`,
`callstream`, `network device` and `balance mismatch` all mis-matched live tickets as master
keywords. `audit_master_keywords.py` finds that shape.

## Anything that reads `runs/` reads this pipeline's own opinions

Three self-poisoning loops have been found and fixed; expect more.

- Triaged names are written back into ServiceNow, so a re-exported ticket arrives titled with the
  bracket this pipeline gave it. The category is now recovered from that bracket, but only as a
  last resort, so fresh evidence still wins.
- `MANUAL_NAME` was unreachable behind `PRIOR`, so a hand-written correction was discarded for any
  ticket a previous run had already named.
- `prior_names` read the same day's earlier passes, carrying a bad name from pass one into pass
  three. It now skips workbooks whose filename shares the output's date.

## New masters: the 10-ticket rule

A new master is created only once the same issue has been seen **more than 10 times**. Do not
propose a new master each run.

The running count lives in the **Proposed Masters** sheet inside a run workbook. Each run reads
that sheet, adds the batch's counts, and writes the updated sheet into the new workbook. There
is deliberately no parallel CSV — two copies of a running count drift apart.

It reads the **last run you signed off**, not the newest file — a superseded run would inject
retracted clusters into every future one. That pin is `TRIAGE_TALLY_FROM`, defaulting to the
constant in `run_triage.py`. **Advance it whenever a run is signed off.** Leaving it behind
silently resets every cluster to the older count, which reads as ordinary output; the run now
prints a warning listing newer workbooks, and that warning must be resolved, not ignored.

Until a cluster passes 10: tag `TriagedTicket` + category, no `ChildTicket`, and leave the
Master Ticket column **empty**. No master exists to be a child of.

When a cluster passes 10, raise it as a heads-up with the count, the ticket IDs and a proposed
`[Category] Short Description` name — the human approves it and allocates the MST tag.

## Per-run config

The `CLUSTERS` and `MANUAL_NAME` dicts at the top of `run_triage.py` are hand-maintained on
purpose. A cluster is a claim that several tickets are the same issue; a manual name is a
judgement about a free-form ticket. Do not generate either automatically.

## Output

First sheet is `Finished Triage` — exactly nine columns, the triage as done:

```
TicketID | Short Description | Master Ticket | Assigned Group (should be) | Tags | Category | Root Cause | KBA | Priority
```

Working detail lives in later sheets of the same file: `Triage Detail (full)`,
`Proposed Masters`, `Priority Matrix`, `Group Summary`, `Master Summary`, `Group Mismatches`,
`Unmapped Surfaces`, `Review`, `Tags`, `Priority Category Map`.

## Reference

`reference/BENCHMARK.md` holds the measured accuracy, the reasoning behind each rule, and every
approach that was tried and rejected. Read it before changing a rule.
