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

Login outranks surface. A system named as *background* does not count: read the words
immediately before each system name — `configured on`, `set up in`, `we can see` mark background;
`not present on`, `unable to … in`, `error on` mark the observed failure.

**Symptom beats the pipe hint.** Most category errors came from trusting the agent's area label
over the actual issue.

**Priority is a grid lookup, never a formula** — `reference/priority-matrix.csv`, urgency ×
impact. Default to P3. A single centre is impact **2**, not 1. P1 requires outage evidence;
without it, cap at P2. Leave priority blank when the ticket doesn't state scope — impact is a
human decision.

**Never conclude from a JIRA resolution label alone — read the comments.** Two tickets closed
with identical labels had opposite causes; the labels alone gave exactly the wrong routing.

**Root cause is a suggestion.** It measures ~41% and has a ceiling around 43% from ticket text
alone, because the label records what the investigation found, not what the customer wrote.
Confirm before saving.

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
