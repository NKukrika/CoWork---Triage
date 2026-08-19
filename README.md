# Triage Workspace

Workspace for triaging incoming ServiceNow tickets against master tickets, categories, KBAs, and JIRA history.

## Folders

```
reference/          Files I read on every triage run. Keep these current.
  master-tickets.csv    The master ticket registry (authoritative names) - 46 loaded
  categories.csv        The fixed category list - 24 confirmed
  kba-index.csv         The KB base, searchable - 396 articles
  naming-convention.md  Naming rules and worked examples
  classify.py           Shared matching logic
runs/               One output workbook per triage run
  archive/            Older runs and dated reference backups
```

## How a run works

1. Drop the ServiceNow export (.xlsx or .csv) anywhere I can reach it.
2. Say `run triage` (or invoke the `ticket-triage-master` skill).
3. I read the reference files, then for each ticket:
   - match to a **master ticket** in `master-tickets.csv` — this happens first
   - take the **category** from the matched master (the registry is authoritative)
   - only if no master matches, classify by keyword and treat it as a proposal
   - look up any **KBA** in `kba-index.csv` that covers it
   - search **JIRA** once per master for prior issues, and note whether one was fixed by a defect/bug
4. Output lands in `runs/Triage_<date>.xlsx`, with a review sheet for anything ambiguous.

## Output format

Every run produces a workbook in `runs/`. The **first sheet is `Finished Triage`** and holds exactly eight columns — the triage as done, nothing else:

```
TicketID | Short Description | Master Ticket | Assigned Group (should be) | Tags | Category | Root Cause | KBA | Priority
```

All the working detail lives in the later sheets of the same file: `Triage Detail (full)`, `Proposed Masters` (the 10-ticket tally), `Priority Matrix`, `Group Summary`, `Master Summary`, `Group Mismatches`, `Unmapped Surfaces`, `Review`, `Tags`, `Priority Category Map`.

Priority is blank where the ticket doesn't state scope — impact is a human decision, and the detail sheet lists what the priority would be at each impact value.

## Priority

Urgency × Impact → the grid in `reference/priority-matrix.csv`. Urgency comes from the app sheet (CP / Teamhub / Titan) by surface, with **General as the fallback** — which is what covers Proton and CSU.

**The grid is a lookup, never a formula.** A derived `min(U+I−1,4)` was wrong in 9 of 16 cells. And the worked examples inside Priority Mapping v0.2 disagree with the grid in 11 of 12 cases: the grid is current, the examples are stale.

**Impact scale** — corrected against those examples:

| Impact | Scope |
|---|---|
| 1 | Generalised, whole-estate only ("all centres", system-wide) |
| 2 | Multiple centres, **or all clients of a single centre** |
| 3 | Few/some users, single user, single client, single BU, VIP |
| 4 | A single invoice, booking or payment |

A single centre is impact **2**, not 1. Reading "affecting all clients of the centre" as impact 1 produced false P1s.

**P1 requires outage evidence** — the system down or a major function unusable. Without it the matrix result is capped at P2, because P1s trigger a promotion process.

Priority is the one field with **no ground truth** — no priority, urgency or impact column exists in any export — so unlike routing it is reasoned from your definitions, not measured.

## Measured accuracy

Benchmarked against the 377 tickets triaged under the current process. The other 246 in the training file predate tagging, so they are excluded from training and reported separately. Full detail in `reference/BENCHMARK.md`.

| What | Human-reviewed batch (24) | 377 resolved tickets |
|---|---|---|
| Category | **96%** | 88.7% |
| Assignment group | **96%** | 97.6% |
| Priority | **100%** | no ground truth |
| Root cause | not graded | 41.4% — a suggestion, confirm before saving |

The human review changed four policies. **The sheet's Assignment group is authoritative** — all 8 routing errors came from overriding it. **Priority defaults to P3** — every ticket in the reviewed batch was P3. **KBAs are offered only at strong confidence** — all 13 "possible" suggestions were judged useless. **Symptom beats the pipe hint** — 6 of 7 category errors came from trusting the agent's area label over the actual issue. Full detail in `reference/BENCHMARK.md`.

Routing went from 48.4% to 84.6% by moving from surface-based to category-first, plus an XC sub-rule. Root cause has a ~43% ceiling from ticket text alone, because the label records what the investigation found rather than what the customer wrote.

**Masters are linked by name, not by PRB.** The `Problem` column exists but is not a reliable master link; `[Category] Short Description` stays authoritative, with `MST-xxxxx` tags as a secondary cross-reference.

## Assignment group

**The group on your export wins.** I take it as supplied and never overwrite it. Labels are normalised, so `L2-Titan`, `l2 titan` and `Titan` all resolve to `L2 - Titan`.

I still run the routing rule on every row and **flag any disagreement** on a Group Mismatches sheet, so mis-routed tickets are visible without anything being silently re-assigned.

### The rule: route on where the issue is shown

| Where the issue is visible | Group |
|---|---|
| Titan | **L2 - Titan** |
| Customer Portal or TeamHub | **L2 - Portal** |
| Login — OTP, verification email, activation, password reset | **L2 - Proton** |

Login outranks surface: a login failure is an identity problem wherever the sign-in screen is rendered. The `Login` category alone triggers it.

**A system named as background doesn't count.** "Payment method is configured on Titan but not present on MyRegus" is **L2 - Portal** — the customer sees the failure in the portal, and it doesn't matter that the record was configured in Titan. This is done by reading the words immediately *before* each system name: `configured on`, `set up in`, `checking the`, `we can see`, `hotfix in` mark background and score zero, while `not present on`, `unable to … in`, `error on` mark the observed failure and score highest. Direction is what distinguishes them — a wide context window cannot.

Note the knock-on: confirming a master under `Login` moves the category to `Login`, which moves the rule's group to `L2 - Proton`.

The group also scopes the JIRA search — `L2 - Titan` → project `TTN`. Portal and Proton work spans several projects, so those stay unscoped.

`reference/groups.csv` is a **last-resort fallback**, used only where no surface is observed and the sheet is blank. Those rows are mostly `PROPOSED`; CSU and Network devices are confirmed (both `L2 - Portal`).

## Category precedence

1. **A matched master wins.** Its name embeds a category in brackets, so overriding it would make the name contradict the ticket's tag.
2. **Then the agent's pipe hint**, when it resolves to a real category. "Invoices" resolves to `Invoicing`.
3. **Then keyword classification** — short description first, body only as a last resort.

Disagreements between the hint and a matched master are flagged for review, not silently resolved.

## Reading JIRA resolutions

**Never conclude from a resolution label alone — read the comments.** Two tickets on the same symptom were both closed `Rejected / will not be scheduled`: one because the customer had changed the setting themselves, the other because a fix had shipped and it was closed awaiting a customer retry. Reading only the labels gave "rejected twice, standing gap, escalate"; the comments showed a probable regression against a delivered fix. Opposite conclusion, opposite routing.

## New masters: the 10-ticket rule

**A new master is only created once the same issue has been seen more than 10 times.** Recurring symptoms are tracked cumulatively on the **Proposed Masters** sheet inside the run workbook — I do not propose a new master each triage.

Everything lives in one file. Each run reads the `Proposed Masters` sheet from the newest workbook in `runs/`, adds this batch's counts, and writes the updated sheet into the new workbook. There is deliberately no parallel CSV: two copies of a running count drift apart.

Until a cluster passes 10, its tickets get `TriagedTicket` + category, no `ChildTicket`, and the **Master Ticket column stays empty**. That is accurate: no master exists to be a child of.

When a cluster does pass 10, I raise it as a heads-up with the count, the ticket IDs and a proposed `[Category] Short Description` name for you to approve and allocate an MST tag to.

Current standing after the 14 Aug run:

| Cluster | Seen |
|---|---|
| Cannot add or register a credit card on MyRegus | **6** |
| TeamHub centre/client search failure | 5 |
| WorldKey PIN rejected | 5 |
| Unable to renew or amend an agreement in TeamHub | 2 |
| Renewal team request submit error | 2 |
| Booking cannot be confirmed in Staff Mode | 2 |
| Accounts in D365 missing from MyRegus | 2 |
| Invoices paid in D365 still unpaid in MyRegus | 2 |
| Service configured but not shown in Add Service | 1 |
| Autopayment not pulling from a registered card | 1 |

## Naming: rule 2 across runs, not just within one

Same issue, identical name, character for character. That needs a precedence chain, because drafting a name per ticket breaks the rule the moment two tickets describe one issue differently:

1. **A matched master** — its name already *is* the agreed name for that issue.
2. **A tracked cluster** — the same issue seen repeatedly. Every ticket in a cluster carries the cluster's name even while it sits below the 10-ticket threshold and has no master.
3. **An earlier run** — a carried-over ticket keeps the name it was already issued. Redrafting it caused the same ticket to be called two different things on consecutive days.
4. **Drafted from the text** — mechanical, and only for genuinely new single tickets.

Any deliberate rename is logged on the Review sheet rather than applied silently.

## Mandatory tags

A child ticket carries **four** tags:

| Tag | Applies to |
|---|---|
| `TriagedTicket` | Every ticket that has been triaged, without exception |
| `ChildTicket` | Only tickets sitting under a master |
| `MST-xxxxx` | The matched master's own tag, from `master-tickets.csv` |
| `<Category>` | The category name verbatim — e.g. `Bookings (Products)` |

The MST tag is not optional alongside `ChildTicket`. Across 623 resolved tickets, 190 carried both and **zero** carried an MST tag without `ChildTicket` — they travel together, so emitting `ChildTicket` alone leaves the ticket half-linked. All 45 supplied tags validated against the registry with no name mismatches and no duplicates.

`[SOA] Balance Mismatch` has no MST tag, so a ticket matching it raises a blocker rather than being tagged incompletely.

Two tag formats are in use and both are preserved verbatim: `MST-71218` and `MST - 002-25`.

The category tag keeps its exact spelling from `categories.csv` — spaces, parentheses, hyphens and ampersands intact. Never slugified.

Two edge cases:

- **`ChildTicket` waits for a confirmed master.** Low-confidence and no-match tickets have no agreed parent, so they get `TriagedTicket` + category now and `ChildTicket` once the master is approved on the review sheet. Tagging them as children early would assert a relationship nobody signed off.
- **A ticket with no category can't be fully tagged.** `Unclassified` isn't a real category, so there's no valid third tag. Those tickets get `TriagedTicket`, a recorded blocker, and a place on the review sheet awaiting a category decision — rather than an invented category to make the count work.

The output workbook has a dedicated **Tags** sheet with one column per tag, for bulk application in ServiceNow.

## How KBA lookup works

Token overlap weighted by IDF, not phrase matching. Master keywords are phrase-shaped ("verification code via email") while article bodies are prose ("verification code is not being delivered to their email") — phrase matching misses those. Title terms count 3x body terms.

Scores are labelled: **strong** (>= 12) is almost certainly the right article, **possible** (6–12) needs confirming, **weak** (< 6) is term coincidence. If every candidate is weak, I report a KBA gap rather than dressing up a coincidence as a match.

## Why master-first

A ticket's wording routinely points at a different category than its master's. "Verification code via mobile phone" reads as `Mobile`, but that master lives under `Login`. "Configured on Titan but not present on MyRegus" reads as `Payments - Credit Card`, but that master lives under `Payments Registration`. Narrowing candidate masters by a keyword-guessed category hides the correct master, so I don't do it.

## Rules I follow

- Master ticket names are **exactly** `[Category] Short Description` — see `naming-convention.md`.
- Tickets with the same underlying issue get the **identical** master name, character for character.
- I never rename an existing master. If a name looks wrong I flag it, I don't change it.
- New masters are proposals only, never auto-created.
- Below High confidence goes to the review sheet.
- I never invent a KBA number, JIRA key, or fix version.

## Status

- **Categories** — 24, confirmed. Match keywords are my seeded drafts; they improve as runs surface gaps.
- **Masters** — 46 loaded. All bracket prefixes validate against the category list. Symptom keywords are seeded drafts.
- **KBAs** — 396 articles loaded from `kb_knowledge.xlsx`, HTML stripped and indexed for search: L1 (200), Customer Support (108), End User (61), L2 (18), Centre Support (7), Known Errors (2). 17 masters have a high-confidence article auto-linked; the remaining candidate pairs are in `runs/kba-master-mapping-review.csv` for confirmation.
- **Ticket input** — Excel/CSV export. ServiceNow connector to follow.
- **JIRA** — Atlassian connector timed out on handshake; needs a retry or reauth. Until it works, the JIRA column reports `Not checked — connector unavailable` rather than guessing.
- **13 categories have zero masters** — CSU, Center setup, Contract API/Agreements, Documents, Help and Inbox, Memberships, Mobile, Payments - Direct Debit, Quick Access, Renewals, Roles and Permissions, Services, Staff - Attendance and Timeoff. Expect new-master proposals there.
