# Benchmark against 623 resolved/closed tickets

Source: `resolved and closed for training.xlsx` — 494 Closed, 129 Resolved.

**The set splits in two, and only one half is valid ground truth.** 377 tickets were triaged under the current process and carry tags; 246 predate it and have none. The learned tables are built from the tagged 377 only, and the headline figures are measured on them. The old-process subset is reported separately because its routing reflects a process that no longer applies.

| Measure | New process (377) | Old process (246) |
|---|---|---|
| Category | **89.5%** | no category labels to score against |
| Assignment group, category read from the tag | **84.6%** | n/a |
| Assignment group, end-to-end (category inferred too) | **83.3%** | 54.1% |
| Root cause | **42.4%** | 25.4% |

Category inference costs almost nothing: 84.6% with the true category versus 83.3% inferring it.

## How routing got from 48% to 84%

| Approach | New-process accuracy |
|---|---|
| Surface rule alone — route on the visible surface | 48.4% |
| Learned category→group table | 79.6% |
| + XC sub-rule, residual XC to Portal | **84.6%** |

The surface rule as first specified was barely better than chance across three groups. Its dominant failure was tickets whose symptom appears in MyRegus but which Titan owns. Category is the far stronger predictor, so routing is category-first with the surface rule kept as tie-break for genuinely split categories and as fallback where there is no training evidence.

**XC needed a sub-rule.** Telephony/OOMA/DID → Proton, parking → Portal first. The residual — scanned pages, TeamHub services, credit requests — measured as Portal, and defaulting it to Proton cost 20 errors on its own. Fixing that was worth +5 points.

**Two changes that measured worse and were rejected**: enabling the surface tie-break on Payments - Credit Card dropped accuracy to 80.1%, and extending it to Registration and Login dropped it to 79.0%. The simpler table wins.

Remaining errors, largest first: 16 Payments - Credit Card tickets that went to Titan against an 83%-Portal category; 6 Invoicing; small numbers on Short Stay and Accounts and Companies. These are the genuine minority cases inside otherwise consistent categories and are not separable from the text.

## Root cause: ~43% is the ceiling from ticket text

| Approach | Result (30% holdout) |
|---|---|
| Always answer the most common value (Data Corruption) | 31.5% |
| Naive Bayes over description tokens | 42.9% |
| Majority per category | 42.4% |
| Majority per (category, group) | 36.4% |
| My original conservative rule | 12.2% |
| **Shipped: category prior, overridden only by JIRA-backed evidence** | **42.4%** |

The label records what the investigation found, not what the customer wrote, so it is only weakly predictable from the description. Mined signals were thin even for the largest class — Data Corruption, with 131 training examples, yielded only `incorrect`, `set`, `missing` above threshold — and Software Bug produced obvious overfitting artefacts (`colombia` at lift 166666, from one ticket).

Measured consequence: ticket-wording signals are **worse** than the category prior. Letting them override it dropped accuracy from 42% to 33%, so only JIRA-backed evidence overrides. Wording is kept as a runner-up.

**Treat root cause as a suggestion for agent confirmation.** It is right about two times in five, and that is close to the achievable limit without the investigation outcome.

## Label distribution

Root cause — 13 of the 29 picklist values have ever been used:

```
Data Corruption 194 · Configuration Error 105 · Unknown Cause 91 · Third-Party Service Failure 55
Access Issue 52 · Human Error 50 · Software Bug 22 · Training Issue 21 · Process Failure 16
Performance Degradation 3 · Patching Issue 2 · Application Crash 1 · Dependency Failure 1
```

Group: L2-Titan 261 · L2-Portal 253 · L2-Proton 109.

## Decisions recorded

- **Masters are linked by name, not by PRB.** The `Problem` column holds PRB records on 107 tickets, but the service owner confirms PRB is not a reliable way to connect masters. The `[Category] Short Description` name remains authoritative; `MST-xxxxx` tags are a secondary cross-reference.
- **Untagged tickets are old-process**, not a data-quality defect. Excluded from training and reported separately.
- Canonical spellings confirmed: **`Patching Issues`** (the picklist form, though resolved tickets show `Patching Issue`) and **`Contract API/Agreements`** (tags also contain `ContractAPI/Agreements`).
- Three categories have no training evidence — Help and Inbox, Renewals, Staff - Attendance and Timeoff — and fall back to the surface rule.

## Artefacts

- `reference/group-by-category.csv` — learned category→group table with purity and distribution
- `reference/root-cause-priors.csv` — most common root cause per category, with the full distribution
- `reference/root-cause-signals-learned.csv` — mined signals with lift, kept for inspection rather than relied on

---

# Human review of a live batch (24 tickets, `triage1corrected.xlsx`)

The first genuine scorecard: a reviewer graded my output ticket by ticket. It found errors the resolved-ticket benchmark could not, because three of the four failures were **policy** errors, not classifier errors.

| Measure | As delivered | After fixes |
|---|---|---|
| Category | 79% | **96%** |
| Routing | 67% | **96%** |
| Priority | 29% | **100%** |
| KBAs offered | 15, of which 13 judged useless | 0 (strong-only) |

Mean quality score was 3.6/5, with 6 tickets marked "Major correction".

## Four root causes

**1. I was overriding the answer already in the export.** All 8 routing errors were tickets where I overrode a populated `Assignment group`. Taking the sheet verbatim scored 22/24; my learned table plus JIRA-evidence overrides scored 16/24 — my overrides were 2 right and 8 wrong. The sheet now wins, with exactly one sanctioned exception: the owner's standing `Login → Proton` rule. **Do not widen that exception without measuring.**

**2. Priority: every ticket in the batch was P3.** I said P2 nine times and left it blank eight. The matrix was fine; my impact inference read scope broader than practice does. Default is now **P3**, deviating only for outage evidence (P1) or urgency-4 consultation/request work (P4).

**3. My KBA confidence band is anti-correlated with usefulness.** All 13 suggestions I labelled "possible" (6–12) were judged not useful. The only 2 the reviewer found useful I had labelled "weak". The band carries no signal, so only **strong** (≥12) reaches the output. Precision over recall: better to offer nothing than 13 wrong articles.

**4. The pipe hint was actively harmful.** 6 of 7 category errors came from trusting it. Agents write the broad **area**, the ticket is a narrower **issue**:

```
"Accounts & Companies" | error submitting renewal team request  -> Renewals   (x2)
"Invoices"             | unable to upload TDS document          -> Documents
"Payments - Credit Card Registration" | ACH details not saved    -> Payments Registration
```

Measured: hint-first 71%, symptom-first 83%. Policy reversed with the owner's agreement — symptom first, hint only when the symptom is unclassifiable.

## Bugs the review exposed

- **Symptom classification was reading the pipe prefix.** `triage_row` classified on the unstripped short description, so "Customer Portal | Accounts and Companies | Account inactive in Myregus" classified as Accounts and Companies when the symptom is Login. Stripping it fixed the last category error and is what took the batch from 92% to 96%.
- **Booking split fired backwards.** The owner rule is: booking issues in **TeamHub → Bookings (Products)**, in **Customer Portal → Bookings (Products) - Short Stay**. For this rule the leading app label *is* the signal, so unlike routing it reads the whole short description. TeamHub wins when both are named. A portal named as *working* ("available on My Regus but not on the Regus site") must not claim the ticket.
- **XC lost to Services.** Symptom-first sent "add service" and "mail forwarding" tickets to Services. XC has 58 resolved tickets to Services' 5, so XC now owns product-and-services wording and Services keeps only its specific entitlement terms.
- Added `account inactive` / `inactive in myregus` to Login — a keyword gap flagged several batches earlier and confirmed by the reviewer.

## Cost of the fixes

Category on the 377 resolved tickets moved 90.1% → 88.7%, a 1.4-point loss, in exchange for +17 points on the reviewed batch. Taken deliberately: the human review reflects current practice, the resolved set includes older labelling. Routing on the resolved set is now 97.6%, since the sheet is authoritative there too.

## Still unresolved

`INC0766960` — "mark invoices as PAID, status in MyRegus still unpaid" — filed by the reviewer as **SOA**, not Invoicing. Payment-status-versus-statement is a domain distinction I cannot infer from the text. Flagged rather than guessed.

## Owner corrections, 13 Aug 2026

Two classification rules given by the service owner, both encoded and regression-tested:

**Invoice/payment mismatch is `SOA`, not `Invoicing` — and routes to `L2 - Titan`.** Anything settled in one system but showing unpaid in another. This also resolved `INC0766960`, the single category error left unexplained after the human review: it was this same pattern. **The reviewed batch is now 24/24 on category.** Invoicing keeps invoice creation and content problems; the mismatch terms moved to SOA, which at precedence 10 beats Invoicing at 30.

**IWG card issues are `CSU`, and route to `L2 - Portal`.** Deliberately scoped to IWG card *issues* — activation, not working — rather than the bare term. Matching bare "iwg card" pulled a Login ticket into CSU because the printer quotes *"Please tap your IWG card or enter your World Key PIN"* in its own prompt. A product name inside an error message is not the subject of the ticket, the same trap as `staff mode` and `something went wrong`.

Category on the 377 resolved tickets moved 88.7% → 88.5%, a 0.2-point cost for +4 points on the reviewed batch.

## Run of 14 Aug 2026 — two silent bugs and a naming rule that wasn't holding

25 tickets, 15 of them new. Both ground-truth sets were re-measured after every change: **377 resolved stayed at 88.5%, the reviewed batch stayed at 24/24.** Nothing here was a trade-off.

**An empty pipe hint resolved to a real category.** A free-form ticket truncated at a trailing pipe (`… Type of Ticket: Customer |`) produced `raw == ''`, and an empty string prefix-matches every category name, so it silently resolved to **CSU**. Empty is the absence of evidence, and now returns `None`.

**Pipe-splitting fired on tickets that merely contain a pipe.** `strip_pipe_prefix` assumed `App | Area | Symptom`, so on an email pasted into the ticket it kept only the text after the last pipe — `'VO Standard'`, or nothing at all. New `is_pipe_structured()` gate: the convention's first segment is a short app label, never a paragraph, so a first segment over 6 words or 60 characters means the pipes are incidental. This one bug was corrupting the input to every downstream step on 8 of 25 tickets.

**Six tickets on one issue got six different names.** Rule 2 says same issue, identical name, character for character — but naming ran per ticket, so the card-registration cluster produced six variations, all of them mangled email boilerplate (`[Payments Registration] Hi Team, - Nenad Radulović 6-digits: 4-digits: 3442 Customer`). Naming is now a precedence chain: **matched master → tracked cluster → earlier run → drafted**. A cluster is the same issue seen repeatedly, so every ticket in one carries the cluster's name even though no master exists yet.

**And the rule wasn't holding across runs either.** INC0767810 was named "Global Protect VPN is not working" on 13 Aug and redrafted as "Global Protect VPN access issue" on 14 Aug — the same ticket, two names. Names now carry forward from previous run workbooks and are only changed deliberately, with the change logged on the Review sheet. One such realignment this run: INC0767409 moved onto the SOA cluster name once the link to INC0766960 was spotted.

**`propose_master_name` was drafting from email boilerplate.** Added salutation stripping (`Hi/Hello/Dear team`) and labelled-field stripping (`Company Name:`, `Account Number:`, `6-digits:`).

### The serious one: I proposed clusters for issues that already had masters

Caught by the service owner asking "are you using master tickets we already have?" — a fair question, because only **2 of 25** tickets matched a master on the first pass. The answer was no, and it was the worst error in the run: six card tickets were filed as a brand-new cluster while the registry already held **MST-71221** (error adding a payment card), **MST-71579** (setting up a default payment method) and **MST-71513** (expiry date rewritten). Autopayment and cannot-pay-invoice had masters too.

**Why it happened.** I closed the keyword gaps in `categories.csv` and stopped there. The master registry has its own `Symptom keywords` column with the same gaps — tuned to the structured wording of past tickets (`autopayment not working`, `add payment card`) and blind to this batch's free-form email phrasing (`auto pay is not being pulled`, `unable to add the card`, `attempting to upload the card`). Fixing one layer and not the other is what produced a duplicate-master proposal.

**Measured, because master matching does have ground truth** — the 190 resolved tickets carrying an `MST-xxxxx` tag:

| | Before | After 33 added keywords |
|---|---|---|
| Correct master | 183 (96.3%) | **184 (96.8%)** |
| No match (gap) | 1 | **0** |
| Wrong master | 6 | 6 |

Matching on this batch went **2/25 → 13/25**. The 6 wrong are label noise, not misses: their short descriptions name a different master than their own tag, e.g. a ticket titled `[Payments - Credit Card] Cannot pay invoice online` tagged to `Payments Registration`.

**Two rules now enforced in the run script.** A cluster may only exist for a symptom with *no* master in the registry — check the registry before tallying anything. And the tally is carried forward from the last **authoritative** run, pinned by name: the superseded first attempt would have injected its retracted clusters into every future run. Totals are recomputed from an accumulated ticket-ID list rather than incremented, so a re-run cannot double-count.

**A cluster's category wins over the classifier**, for the same reason a matched master's does: otherwise the name's bracket contradicts the category tag. INC0768007 read as `Renewals` but joined an `Accounts and Companies` cluster — flagged, not silently resolved.

### Keyword gaps closed

| Category | Was landing as | Gap |
|---|---|---|
| Payments Registration | Payments - Credit Card | add / set up / upload a card, `default payment preference`, `cc details`, card shows as expired |
| Payments - Credit Card | Mobile, Unclassified | `auto pay is not being pulled`, `card is not pulling`, can't pay invoices with a registered card |
| XC (Product and Services) | Unclassified | `callstream`, cannot make or receive calls |
| Renewals | Unclassified | `renew agreement`, `unable to renew` |

**Bare `cc` removed from Payments - Credit Card.** It fired on any ticket mentioning card details and beat nothing: identical scores on both sets with and without it. Removing it let INC0768031's real symptom — in the body, not the truncated title — reach the classifier.

**Bare `mobile` removed from Mobile**, which had been claiming tickets that mention the app only as background ("I saw on his mobile app all permissions are open"). Replaced with failure-direction wording plus `mobile application` and `mobile key`. Cost 3 errors on the resolved set and fixed 1; two of the three were recovered by the two added terms, and the last is **label leakage** — its short description is literally `[Mobile] [Quick Access] Error when trying to get authentication code`, so it only ever scored right by reading its own tag out of the title. Worth knowing the 88.5% baseline is slightly inflated by tickets that print their answer.

## Second human scorecard — 24 tickets, 14 Aug 2026

A full `AI_vs_Human_Triage_Scorecard` on the same day's batch, graded against my v2 output. Every correction below was encoded and re-measured against all three ground-truth sets.

| Measure | v2 as delivered | After the corrections |
|---|---|---|
| Category | 18/21 (86%) | **21/21 (100%)** |
| Routing | 17/21 (81%) | **19/21 (90%)** |
| Priority | 18/20 (90%) | 18/20 — unresolved, see below |
| Short description | 15/20 (75%) | **20/21** |

Nothing regressed: 377 resolved held at 88.5%, master matching at 184/190, and routing on the 377 actually **rose to 98.4%**.

**OOMA and DID override the sheet.** The reviewer flipped INC0767819 and INC0767855 from a *populated* `L2-Portal` cell to `L2 - Proton`. This is now the second sanctioned exception alongside `Login → Proton`. Deliberately scoped to the two products named and **not** generalised to telephony: a Callstream ticket in the same batch (INC0767995) was accepted as Portal. The rule agrees with historical routing too, which is why the resolved-set score went up rather than down.

**"Unable to log a credit note" is XC, not Roles and Permissions.** I read "unable to log" as a permissions problem; credit notes are an XC product-and-services function. `credit note` moved from Invoicing to XC.

**A cluster's category can be the thing that's wrong.** I had INC0768007 read as `Renewals` by the classifier but overrode it with the cluster's `Accounts and Companies` — correctly insisting the name's bracket and the tag must agree, but fixing the wrong side. The reviewer confirms `Renewals`. **When a clustered ticket's classified category disagrees with the cluster name, the cluster name is the more likely error** — it is an unapproved proposal, whereas the classifier is reading this specific ticket. Cluster renamed and the two earlier tickets move with it.

**A carried-forward name must not carry a stale bracket.** INC0767842 was named `[UNCATEGORISED]` before its category was known; once `activation fee` classified it as Bookings (Products) the bracket had to follow. Wording is preserved, the bracket is realigned, and the change is logged.

**Unclassified usually means out of scope, not a keyword gap.** Owner guidance, and it changes what to do about it: stop hunting for keywords and check whether the ticket is ours at all. INC0767976 went to `L3-ServiceNow Platform` — a destination outside the three L2 queues — because the reporter could not raise a ticket in ServiceNow itself. Out-of-scope candidates are now flagged with an `Out of scope?` column and a review row; they are never auto-routed, because inventing a destination outside L2 is not safe.

### One hypothesis tested and rejected

INC0767895's sheet said `L2 - Titan`, the reviewer said `L2 - Portal`, and the learned category rule would have been right. So: *when a master matches, should the master's category group beat the sheet?* Measured on the 265 master-matched resolved tickets, the learned rule disagrees with the desk's own group **49 times**. Adopting it would break 49 to fix 1. Rejected — the sheet stays authoritative.

### Still open

- **Priority, 2 of 20.** INC0767857 (`U1 × I3` → matrix P2) and INC0768004 (`U3 × I3` → matrix P4) were both graded **P3**. It isn't a transposed matrix — swapping the axes gives the same cells. Either the supplied Impact/Urgency are noisy or the grid diverges from practice in those two cells. Not changed unilaterally: the grid was supplied by the owner and is 18/20.
- **INC0767937.** Matched to MST-76060 *"Unable to send agreement from Preview OSA screen"*; the reviewer named it *"Unable to see Preview OSA screen for Move Office"* — cannot **see** the screen, in the **Move Office** flow. That may be a distinct issue rather than a child of that master.

## Run of 17 Aug 2026 — the "Troubleshooting attempted" trap

20 tickets. Four misclassifications traced to **one** cause, which makes it the most valuable finding since the master-registry gap.

**The `Troubleshooting attempted:` section lists what the agent checked and found FINE.** Reading a symptom out of it inverts the meaning. Two clear cases in this batch:

```
INC0768070  "Checked the customer portal for balance mismatch, invoice visibility..."
            -> matched the [SOA] Balance Mismatch master. The ticket is about
               undelivered invoice emails. That master has NO MST tag, so it
               would have raised a tagging blocker on an unrelated ticket.

INC0768143  "Confirmed successful WorldKey login"
            -> classified Login. The ticket says authentication works, the job
               reports complete, and nothing prints. It is a printer fault.
```

Form-field lines do the same thing: `Booking reference number: 170274728` classified a TeamHub renewal error as `Bookings (Products)`, purely because the template asks for a booking reference.

Both are now stripped by `symptom_body()` before category classification and master matching. **Cost: 1 ticket on the 377 resolved set (88.5% → 88.2%)** — and that one is label noise, a ticket titled `[Bookings (Products) - Short Stay] …` but tagged `Bookings (Products)`, which had been landing on its tag because of a TeamHub mention inside its own troubleshooting block. Everything else held: master matching 184/190, routing 98.4%, 14-Aug scorecard unchanged.

**`classify_category` was not using the ruled-out guard that `match_master` uses.** So a phrase that could not win a master could still win a category. The layers now share one definition of evidence, and `RULED_OUT` gained the "named as working" family — `authentication works`, `confirmed successful`, `sent successfully`, `listed correctly`, `no setup errors`. This is the same trap as `staff mode` and `mobile`, but stated positively: **a component named as working is not the fault**, and the sentence that proves it works is the one most likely to contain its name.

### Two clusters that were genuinely new

Checked against all 46 masters first, and `master_candidates` returned nothing for either:

- `[Bookings (Products)] Cannot rollback a booking terminated while provisional` — INC0768094, INC0768115. Same fault, same day, both Titan: terminated while provisional, now un-editable, actions greyed out.
- `[Bookings (Products) - Short Stay] Meeting room booking does not complete at the payment step` — INC0768112, INC0768123. The second says "a lot of customers and non-customers" are affected.

### Out-of-scope flag needed a third state

Treating every `Unclassified` ticket as likely out of scope was too blunt. Printers are plainly in scope — L2 - Proton owns them — they simply have no category. The flag now reads `No - category gap` for those, so it stops contradicting the review row that asks for a category decision.

### Open decision: no printer category

Three printer faults across two batches (INC0767930, INC0768143, INC0768179), all routed to L2 - Proton, none classifiable. Either add a `Printer` category or fold printing into `XC (Product and Services)`. Until then they cannot carry a full tag set.

## KBA search was under-reporting because of query dilution

Prompted by the owner asking why no articles were being suggested. Two runs in a row had offered zero. The precision policy was working as designed — and it was masking a recall bug.

**The scorecard already said so.** `Missed KB / fix` is the second most common correction reason, 7 of 48 rows. Every one of those is a row where an article *was* offered and judged not useful. So the complaint was never "no article exists", it was "you found the wrong one". Going silent does not fix that; it just stops being wrong out loud. (`Human · Knowledge Article` is empty on every row, so the correct article was never recorded — see below.)

**The cause: the IDF overlap score is not normalised for query length, and I was querying with the whole ticket.** Long queries add tokens that match nothing and drag the right article's score down:

| Query | Best article | Score |
|---|---|---|
| Whole ticket (42 tokens) | `KB0020210 Worldkey pin is not working` | 9.1 |
| Short description only (8 tokens) | same article | **17.9** |

Same article, same index, one side of the threshold and then the other. Across the batch the best-candidate score had median 5.3 and max 9.1 against a threshold of 12 — mathematically incapable of reporting anything.

**The search itself is fine.** Probed with a focused phrase, the right article ranks first: `worldkey pin printer` → 19.3, `printer not printing` → 13.3, `mail forwarding charges` → 14.6, `credit card registration myregus` → 13.2. The articles were there all along.

**Fix: `find_kbas_best()` queries with the short description AND the full symptom text and keeps each article's best score.** Neither wins outright — a free-form email has a useless title and needs the body, while a well-formed ticket is diluted by it. Ranking uses a length-normalised score (`score / sqrt(tokens)`), which put the correct article 1st in 6 of 6 hand-checked tickets versus 5 of 6 raw. Reporting still thresholds on the **raw** score, so `KBA_REPORT_THRESHOLD` keeps its meaning and this change cannot quietly widen what gets offered. Result: 0/20 → 2/20 with the threshold untouched.

**The threshold is now the binding constraint, and its calibration is invalid.** The "all 13 possible suggestions were useless" finding was measured on articles surfaced by the diluted query, so it says nothing about what a corrected query surfaces at the same score. Ranking is now reliable enough that the top candidate is usually right, but that is my own judgement on six tickets, not the owner's.

**What would settle it**: the correct KB number recorded against a batch of tickets, in the scorecard's existing `Human · Knowledge Article` column. With ~20 of those the threshold can be set from data instead of guessed. Until then the top-ranked candidate is exposed on the detail sheet as *"Best-ranked KBA (below threshold — agent judgement)"* — visible, clearly not asserted, and not in the Finished Triage KBA column.

## Third human scorecard — 20 tickets, 17 Aug 2026

| Measure | As delivered | After corrections |
|---|---|---|
| Category | 17/20 (85%) | **20/20 (100%)** |
| Short description | 17/19 (89%) | **18/19 (95%)** |
| Routing | 15/19 (79%) | **16/19 (84%)** |
| Priority | 12/19 (63%) | **14/19 (74%)** |
| Root cause | 12/19 (63%) | unchanged — above the ~43% text ceiling already |

Nothing regressed: 377 resolved 88.2%, master matching 184/190, 623 routing 98.4%, 14-Aug scorecard unchanged.

**Printers are `Quick Access` — but only printer *access*.** The answer to the open category question, and it came with a distinction I would have flattened. INC0767930 (linked to wrong centre) and INC0768179 (WorldKey PIN) are Quick Access; INC0768143 (job reports complete, nothing prints) was confirmed as **UNCATEGORISED**. So Quick Access covers *getting to* the printer — PIN, badge, centre linkage — not print output. A blanket `printer` keyword would have been wrong on the third ticket. The WorldKey PIN terms moved from Login to Quick Access with them.

**The SOA routing rule was only half-built.** The owner's 13 Aug instruction was "any mismatch related to invoices and payment is SOA category **and Titan group**". I implemented the category half and left routing to the sheet, so INC0765337 sat on Portal and was corrected to Titan. `SOA → L2 - Titan` is now the **third** sanctioned override, alongside `Login → Proton` and `OOMA/DID → Proton`. It costs nothing on the 623-ticket routing check.

**A tracked cluster was renamed for the second time.** `[Login] WorldKey PIN rejected…` → `[Quick Access] WorldKey PIN rejected…`, because the reviewer categorised INC0768179 as Quick Access. Same lesson as INC0768007, now confirmed twice: **when a clustered ticket's category disagrees with the cluster name, the cluster name is the error.** The 5 earlier tickets in that cluster were tagged `Login` and need retagging if the rename is adopted.

### Priority: the supplied matrix does not reproduce the desk's grading

39 graded tickets now carry both a supplied Impact/Urgency and a human priority. The empirical picture:

| U × I | matrix says | human actually chose | n |
|---|---|---|---|
| 1 × 4 | P3 | P3 ×15 | 15 |
| 3 × 3 | P4 | P4 ×10, **P3 ×4** | 14 |
| 2 × 4 | P4 | P4 ×4, **P3 ×2** | 6 |
| 2 × 2 | P2 | **P4 ×2** | 2 |
| 1 × 3 | P2 | **P3 ×1** | 1 |
| 3 × 4 | P4 | P4 ×1 | 1 |

**In 39 graded tickets the reviewer never once chose P1 or P2.** Every time the matrix said P2, the answer was P3 or P4. So the P1 evidence gate now covers P2 as well: without outage or major-function evidence the result is capped at **P3**. That is an extension of an existing rule, not an edit to the owner's grid.

| Rule | Score on 39 |
|---|---|
| Matrix as supplied | 30/39 (77%) |
| + P1/P2 require outage evidence, else P3 | 31/39 (79%) |
| + Quick Access → P4 | **33/39 (85%)** |
| Always P3 | 22/39 (56%) |
| Category-majority priority — **rejected** | fits 34/39 but only 29/39 (74%) leave-one-out |

Category-derived priority looked attractive at 87% fit and fell to 74% under leave-one-out, below the matrix. Rejected. `Quick Access → P4` is kept but is **provisional on 3 of 3 samples** — agents rate printer tickets Impact 2 / Urgency 2 and the desk treats them as low. The first counter-example should retire it.

**Unresolved, and not resolvable from Impact/Urgency**: all 6 remaining errors are cells where the matrix says P4 and the reviewer said P3 — `U3×I3` and `U2×I4`. Those same cells produce *correct* P4s for SOA tickets, so the split happens inside the cell. Either the agents' Impact/Urgency are noisy, or priority depends on something the grid does not capture.

### Root cause: three graded values are not in the picklist

`Documentation Error`, `Configuration Issue` and `Quick Access` were entered as root causes and none exists in the 29-value list (`Configuration Issue` is presumably `Configuration Error`; `Quick Access` looks like a category pasted into the wrong column). Also 3 of my `Configuration Error` answers were graded `Unknown Cause` — the desk reaches for Unknown Cause more readily than the category prior does.

## Run of 18 Aug 2026 — two safety bugs in the run script

15 tickets. All four ground-truth measures held (377 resolved 88.2%, master matching 184/190, 623 routing 98.4%, 17-Aug scorecard category 20/20). The interesting findings were in the runner, not the classifier.

**A Low-confidence master was being applied.** `triage_row` returns the best master plus a confidence, and the rule has always been "Low = a tie between masters, do not apply" — but the run script tested only `if master:`. INC0768427 ("cannot make payment through CC. Cannot add CC.") ties MST-71216 and MST-71221 because it genuinely reports both, and would have been tagged a child of whichever sorted first. Now unlinked and sent to review.

**A master with no MST tag was being tagged anyway.** `[SOA] Balance Mismatch` is the one registry row without a tag, and the documented rule is to raise a blocker rather than half-link. INC0768311 matched it on "incorrect balance" and came out tagged `ChildTicket` with no `MST-xxxxx`, which the tag invariant forbids. The runner now drops such a link and raises the blocker.

Both bugs shared a cause worth remembering: **`triage_row` reports its confidence and its blockers, and the runner was ignoring them.** Dropping a master also has to drop the category it carried, or the ticket keeps a category inherited from a link that was just refused.

**The SOA D365→MyRegus cluster is now 7 and growing fastest** — three more this batch (INC0766583, INC0767871, INC0768311). Two decisions are overdue: the name still says "Invoices paid … showing unpaid" while most members are payments and vouchers that never arrived at all, and `[SOA] Balance Mismatch` now competes with the cluster for the same tickets while having no MST tag.

**An exact duplicate.** INC0768271 is byte-identical to INC0768143 from the previous batch — same customer, same centre, same text. Worth a duplicate check on ID and on description hash in future runs.

**A keyword rejected for cost.** `amend agreement` looked like a clean fix for INC0768359, but a resolved ticket "Not able to amend agreement" is tagged `XC (Product and Services)` while the 14 Aug review put TeamHub amend/renew errors under `Renewals`. The evidence conflicts, adding it cost a measured error, so it was removed and the ticket left Unclassified for an owner decision.

## Run of 19 Aug 2026 — TeamHub renewals reaches 8 of 10

26 tickets, all new. Every measure held: 377 resolved 88.2%, master matching 184/190, 623 routing 98.4%, 17-Aug scorecard category 20/20.

**The headline is a cluster, not a classifier finding.** The TeamHub renewal-team cluster took three more (INC0768533, INC0768544, INC0768550) and stands at **8 of 10**, from seven reporters across four batches. A sibling cluster — the amend-agreement flow itself erroring or freezing — opened at **4** (INC0768359, INC0768485, INC0768499, INC0768524). That is 12 tickets on the TeamHub agreement journey inside a week, which is worth escalating before either count crosses the threshold.

The split between the two is deliberate: one is the *handoff* to the renewals or retention team failing, the other is the *amendment itself* erroring. They may turn out to be one defect, and the note says so.

**Two over-broad keywords caught and scoped.**

`credit note` in XC was claiming any ticket that mentioned one — a late-payment-fee correction, a double-billed access card, and an AutoPay under-collection all landed in XC. The 14 Aug ruling was specifically that *"unable to log a credit note"* is XC, which is the portal **function**. Requesting a credit note for a billing error is Invoicing. XC now keeps only the function wording.

`document` in Documents matched the UBL rule text inside a Greek e-invoicing validation error. Dropping the bare term cost two confirmed answers — INC0768111, which the reviewer had graded Documents, and a resolved ticket about Adobe Reader — so instead it was replaced with the document **actions** those cases actually use (`file uploaded`, `delete the file`, `cannot open the file`, `adobe reader`). Same principle as `printer`: the category is about doing something to a document, not about the word appearing.

**The regression harness now lives in the repo.** It had been sitting in `/tmp` and was wiped when the sandbox restarted, which is a poor place for the one thing that has to run after every change. `measure.py` at the workspace root reports all four ground-truth sets and picks up new scorecards automatically by filename.

## Fourth scorecard — 143 rows covering every batch to 21 Aug

The first review covering the 18–21 Aug runs. Scores on the four unreviewed batches:

| | 18 Aug | 19 Aug | 20 Aug | 21 Aug | total |
|---|---|---|---|---|---|
| Category | 14/15 | 25/26 | 21/21 | 10/11 | **70/73 (96%)** |
| Routing | 14/14 | 26/26 | 21/21 | 6/10 | **67/71 (94%)** |
| Priority | 10/14 | 26/26 | 19/21 | 8/10 | **63/71 (89%)** |
| Short description | 14/15 | 22/26 | 20/21 | 10/11 | **66/73 (90%)** |
| Root cause | 11/15 | 9/26 | 12/21 | 0/10 | **32/72 (44%)** |

**Root cause was the one weak field, and it was fixable.** With 110 graded priorities and 97 usable root causes there is now enough data to rebuild the priors from what the desk actually chooses rather than from the older resolved set. Rebuilt: **44% → 67%** on the graded rows, **62% leave-one-out**. Three priors changed and one category was added:

| Category | Was | Now | Evidence |
|---|---|---|---|
| Renewals | *(absent)* | **Performance Degradation** | 6 of 10 |
| SOA | Data Corruption | **Configuration Error** | 10 of 11 |
| Login | Access Issue | **Configuration Error** | 3 of 3 |
| Bookings (Products) | — | **Unknown Cause** | 8 of 8 |

The pattern behind it: the desk reaches for `Unknown Cause` on request-type tickets and reserves specific causes for reproducible faults. `Performance Degradation` for the TeamHub renewal family is the sharpest single signal — it says the desk reads those as slowness, not a logic defect.

**Priority is at its ceiling with the supplied fields.** On 110 graded tickets the matrix alone scores 80%; the shipped rule (matrix + P1/P2 capped to P3 without outage evidence + Quick Access → P4) scores **86%**, exactly matching an empirically re-derived matrix. The residual 15 errors sit inside two cells that genuinely split — `U3×I3` gave P4 thirty-two times and P3 ten times, `U2×I4` gave P4 twelve times and P3 four. **Across 110 graded tickets the reviewer has never once chosen P1 or P2.** No further change is justified from Impact and Urgency alone.

### The scorecard's tick boxes were broken, and not by the formula

Diagnosed on request. The formulas themselves were correct; they had been **destroyed by a paste**. Across the 143 data rows:

```
2,388  cells holding a non-breaking space (looks blank, is not empty)
  588  literal ✓        121  literal ✗        (hard-coded, never recalculate)
  130  cells still holding a formula, all in rows 114-146
```

So a corrected value no longer updates its tick, and a `CHAR(160)` "blank" defeats both `COUNTIF` and the reviewer's eye. The non-breaking spaces are the signature of content pasted from a rendered table or web page.

Fixed copy written with: every tick rebuilt as a formula across rows 5–1003, `CHAR(160)` stripped, comparison made tolerant of brackets, case, spacing and `UNCATEGORISED` ≡ `Unclassified`, Dashboard ranges moved off the `INC0000001` example row, and `fullCalcOnLoad` set so Excel recomputes on open.

**A bug in my own fix, caught before shipping**: the first attempt mapped tick columns off by one and wrote formulas that referenced the tick cell itself — 25 circular references. Asserting on the generated file caught it. Verified: 0 circular references, 0 tick cells without a formula.

### Contradictions to resolve rather than encode

Four places where this scorecard disagrees with an earlier instruction, left unchanged and flagged:

- **INC0768543** — graded `Payments - Credit Card` / "Cannot pay invoice online", but on 19 Aug the instruction was that this ticket belongs to `MST-71579 Issue setting up default payment method`, which is `Payments Registration`.
- **Amend-agreement category** — INC0768359 graded `Bookings (Products)` on 18 Aug, while the same cluster's tickets (INC0768485/499/524) were accepted as `Renewals` on 19 Aug.
- **Call answering routing** — INC0768827 and INC0768872 corrected Portal → Proton on 21 Aug, but INC0768500, the same request from the same reporter, was accepted as Portal on 19 Aug.
- **Short description** — three tickets (INC0768438, INC0768500, INC0768592) were rewritten from the master's name to the ticket's own symptom, which cuts against rule 2 as implemented.

**21 Aug root causes are unusable**: ten of them hold a category name (`Accounts and Companies`, `Invoicing`, `XC (Product and Services)`, `Renewals`, `Documents`) rather than a value from the 29-item picklist. Excluded from the rebuild rather than learned from.

## JIRA connected, 21 Aug 2026 — one defect explains a whole cluster

The Atlassian connector is authorised. First pass answered questions the ticket text could not.

**TTN-143719 is the root cause behind four tickets and a cluster.** `[ENHANCE-9600] Prevent back-dated charges and double-billing on occupancy step amendments` — **Fixed, Ready For Release, fix version R26.08.01 dated 2026-08-13 but not yet released.** QA passed 17 Aug, UAT 20 Aug.

- Root cause: an `OccupancyStepId` mismatch in `MandatoryRecurringServiceHelper.AddMandatoryServices` creates a fresh `ServiceSale` with a new `SaleItemLink`, no billing history and a **backdated** `StartDate` — so billing retroactively charges every period since the original booking start.
- Second symptom: an occupant-count change leaves the original recurring row billing in parallel with the new one.
- In scope: **Kitchen Amenities, Beverages, Unlimited Coffee** on Long-Term Office and Workstation bookings.

That covers INC0768814 and INC0768331 (KA backbill), INC0768932 (Kitchen Amenity double-billed, Japan, "affecting multiple clients"), and almost certainly INC0768542 from 19 Aug (unlimited coffee and tea still billed). **The JIRA also states Operations is patching the double-billing monthly with manual credit notes** — which is exactly what the `[Invoicing] Credit note requested for an incorrectly billed charge` cluster has been recording without knowing why. Those tickets should be linked and held, not worked individually, and more will arrive until R26.08.01 ships.

**Nothing in JIRA covers the 9-ticket TeamHub renewal cluster.** CEN has two open amend-agreement bugs — CEN-49075 (renewal price incorrect after repeated saves, New, unassigned) and CEN-46754 (RENEWBOOKING action failed even when renewal succeeds, Blocked) — but neither is the production *"error occurred when trying to submit your request"* failure. Eight reporters, no tracking issue. That is now the strongest case for raising a new defect.

**PAPI-80621 supports treating the DID cluster as data corrections.** `[WITH L2] [OOMA] Customer is requesting the change of DID number`, Pending, records the portal DID not matching Cerebro because the number was **purged** there, and is explicitly logged *"for track purpose only, not for Proton team"*. It also independently confirms the owner's correction that DID work belongs to the OOMA master.

### Practical note for future JIRA use

**The connector's `fields` parameter is not honoured** — every issue returns its full description, and a 50-result search blew the token limit twice. Use `searchResultMode: "count"` first and only fetch when the count is small. Tight JQL beats broad JQL plus field selection.

## Run of 21 Aug 2026 — the TeamHub renewal cluster reaches 9

12 tickets, the smallest batch yet. All measures held: 377 resolved 88.2%, master matching 184/190, routing 98.4%, 17-Aug scorecard 20/20.

**`[Renewals] Error submitting renewal team request in TeamHub` is at 9 of 10.** Eight reporters, five batches. The sibling amend-agreement cluster is at 4. One more occurrence of either crosses the threshold.

**Another generic-phrase master match caught.** INC0767028 — a printer document that *"sits on a loading screen and never prints"* — matched `MST-71537 When trying to login via mobile, loading screen appears` on the bare phrase `loading screen`. Same family as `did number`, `staff mode` and `cc`: a common UI phrase used as a master discriminator. `Context required = login` now scopes it, which costs nothing on the benchmarks because that master's real subject is logging in.

**Printer output faults are now a tracked cluster at 3.** INC0767028, INC0768143, INC0768271. Grouped under one `[UNCATEGORISED]` name so all three stay consistent with the 17 Aug ruling that print output is not Quick Access. Worth noting INC0767028 *would* have classified as Quick Access, but only because the reporter mentions refreshing WKP from MyRegus Quick Access as a troubleshooting step — the fault is print output. That is the fourth printer ticket and the category decision is still open.

**Two tickets citing the same JIRA.** INC0768814 and INC0768331 both cite `TTN-143719` for KA backbill charges that cannot be removed — tracked as a cluster so the link is visible even though the Atlassian connector is unauthorised and the issue cannot be read.

**One ticket that is not a ticket.** INC0768846 has `test` as both its short description and its description. Flagged for closure rather than triaged.

## Run of 20 Aug 2026 — a truncated title was hiding the fault

21 tickets. **11 matched an existing master**, the highest yet, and across all batches master links now stand at **42 of 104** (14 before the owner's correction, 30 after it, 42 after this run's fix). Every ground-truth measure held: 377 resolved 88.0%, master matching 184/190, routing 98.4%, 17-Aug scorecard 20/20.

**A short description is only a title when someone wrote one.** ServiceNow truncates a pasted email into the short description at ~160 characters, frequently mid-sentence. INC0768753 cut off at *"…set as the Default Payment Preference; however,"* — so master matching, which prefers the short description, saw only the setup context and matched a payment-setup master, while the actual fault (autopay never runs) sat in the very next clause.

**The first fix was the wrong discriminator.** Using `is_pipe_structured` to decide cost 2 on the master benchmark, because plenty of genuine titles have no pipe — `[Login] Client not receiving verification code via mobile phone` was treated as body text and lost to a sibling master. The precise test is whether **the body starts with the short description**: if it does, the short description is a body prefix and there is no title to prefer, so the whole text is matched. `_is_body_prefix()` does that, and it recovered the 2 while keeping the 12 gained.

**Two clusters grew and one opened.** `[SOA] Duplicate or invalid posting in MyRegus needs reversing` at **5** — the mirror image of the D365-sync cluster: there the record never arrived, here it arrived twice or wrongly. Staff Mode bookings reached 3.

**Volume worth reporting even when a master already exists.** Eight tickets now sit under `MST-71283` (wrong DID on the MyRegus profile) across five batches, three of them on the same day, and every reporter states the correct DID in the ticket — which reads as data correction rather than a code defect. Six sit under `MST-71218` (autopay not collecting). A master existing is not a reason to stay quiet about the rate.

## The master audit was wrong — masters are BROADER than their wording

**Retracted: the "6 of 46 links were wrong" audit below.** The owner's correction — *"you didn't use masters correctly, there are more of them that you should have used"* — was the opposite of my conclusion, and they were right.

**MST-71283 "OOMA issues with DID" is the registry's only home for DID and call-answering issues.** OOMA is the telephony platform behind Call Answering; a reporter has no reason to name it. So a "wrong DID on the customer profile" ticket *is* an OOMA/DID ticket. My audit unlinked four correct links on the reasoning that the word never appears.

**The test I built that on was measuring label leakage.** I found that "all 33 resolved tickets under MST-71283 mention OOMA" and treated it as proof the word must appear. All 33 of those tickets have the master name pasted into their short description — so of course it appeared. The test contained no independent evidence at all, and I used it to justify a `Context required` gate.

**The general error: I was reasoning from text presence rather than domain reality.** A master is the desk's name for an underlying issue, and the underlying platform, product or mechanism is usually *not* in the reporter's words. Under-linking is worse than it looks, because a ticket with no master silently becomes a candidate for a new cluster — I twice proposed clusters for issues that already had masters, once in each direction.

**Net effect of the reversal**: master links across all batches went from 14 to **30 of 83**, no low-confidence ties left, and every ground-truth measure held (377 resolved 88.0%, master matching 184/190, routing 98.4%). The one point lost on the resolved-category set comes from masters now driving more categories, which is the correct behaviour.

Links restored or newly found:

| Ticket(s) | Master | How it was missed |
|---|---|---|
| INC0767819, INC0767855, INC0768158, INC0768538, **INC0768500**, INC0767995 | `MST-71283 OOMA issues with DID` | Required the literal word "OOMA" |
| **INC0768543**, INC0768427 | `MST-71579 Issue setting up default payment method` | "cannot pay AND cannot add" read as a tie between two masters instead of one master's issue |
| INC0768542 | `MST - 011-25 Recurring services charged after termination` | Read "termination" as whole-agreement only |
| INC0768438, INC0768592 | `MST-71218 Autopayment not working` | Delayed deduction and under-collection are autopayment failures |
| INC0768546, INC0768590 | `MST - 002-25 Account needs activation` | An inactive or unactivated account needs activation |
| INC0768571 | `MST-70822 Error logging in to MyRegus staff mode` | "Staff Login Issue" is staff mode |

**Two clusters retracted** because the registry already covered them: the DID-on-profile cluster (→ MST-71283) and the card add-and-pay cluster (→ MST-71579).

### What replaces the bad heuristic

When testing a candidate master link, ask **what the master is about**, not whether its words appear:

1. **Is this the same underlying issue?** The platform, product or mechanism in the master's name is often absent from the ticket. DID display problems are OOMA issues; staff login problems are staff mode.
2. **Is there another master that covers it better?** MST-71283 is the *only* DID master, so a DID ticket goes there unless a more specific one exists.
3. **Beware evidence that could be label leakage.** If resolved tickets carry the master name in their own short description, any test over their text is circular.
4. **Prefer linking to a plausible master over leaving a ticket unlinked.** An unlinked ticket becomes cluster-proposal fuel and can duplicate the registry. Flag a Medium link for confirmation instead.

The audit below is kept for the record. Its process — checking every link — was right; its conclusions were mostly wrong.

## Retracted audit, 19 Aug 2026 — "6 of 46 links were wrong"

Prompted by the owner: "you have made multiple issues with incorrect masters". Every ticket→master link asserted since 12 Aug was re-checked against the master's own scope. **6 of 46 were wrong**, and all four fixes cost nothing on any ground-truth set.

| Ticket(s) | Was linked to | Why it was wrong |
|---|---|---|
| INC0767819, INC0767855, INC0768158, INC0768538 | `MST-71283 OOMA issues with DID` | Matched on the bare keyword `did number`. **All 33 resolved tickets under that master mention OOMA. None of these four does** — they are Call Answering DID *display* problems. |
| INC0768542 | `MST - 011-25 Recurring services charged after termination` | I added `no longer in recurring sales` **to make this ticket match**. The agreement is not terminated. |
| INC0768546 | `MST-71215 Client unable to log in (not verified, suspended, locked)` | Matched on `unable to log in` — the category-level symptom, not a discriminator. The account is *inactive* and the client is *new*. |

**The common failure is keyword-fitting: adding or accepting a keyword that describes the TICKET rather than the MASTER'S issue.** Three tests would have caught all six, and are now part of the process:

1. **Does the master's own subject appear?** OOMA is in the master's name. A DID ticket with no OOMA in it cannot be an OOMA ticket. `Context required` exists for exactly this and is now set on MST-71283.
2. **Is the matching keyword a discriminator or a category-level symptom?** `unable to log in` is what makes a ticket *Login*; it cannot also be what makes it one specific Login master.
3. **Do the resolved tickets under that master look like this one?** Decisive here: MST-71215 and MST-011-25 both have **zero** resolved tickets, so the keywords I added to them were serving nothing — a strong signal I had invented a link rather than found one.

**The four DID tickets were a hidden cluster.** Because a master was claiming them, they never reached the tally. Unlinked, they are `[XC (Product and Services)] Incorrect DID number shown on MyRegus profile` at **4 across three batches** — a real recurring issue that a wrong master had been concealing. Routing is unaffected: the DID→Proton rule is separate and the reviewer confirmed it.

**A caution about weak confirmation.** The reviewer graded INC0767819 and INC0767855 and corrected only their *routing*. I read that as endorsement of the whole row. It was not: both tickets' category is `XC` whether or not the OOMA master applies, so a category tick carried no information about the master link. **A ✓ on a field that a wrong link would not have changed is not evidence the link is right.**

Kept after review, with reasons: INC0768004/032/420/422 → `Cannot pay invoice online` and INC0768037 → `Autopayment not working` all match the master's issue directly even where the keyword is a paraphrase. INC0768238 → `MST-71223` is a genuine match — the client disputes accepting a renewal — but that master sits under Short Stay while this is a Titan office agreement, so the *category* is flagged rather than the link.

**Assertions now run inside the runner**, so a bracket/category mismatch, a blank name, or a `ChildTicket` without an MST tag fails the run instead of reaching the workbook.

## Impact and Urgency now arrive on the export

From this batch the export carries `Impact` and `Urgency` columns. **Use them; do not infer.** Priority becomes a straight matrix lookup, which is the same principle as the Assignment group: a field the export supplies is not second-guessed. The P1 outage cap still applies. Every Impact supplied so far is 3 or 4, which is consistent with P3 being the working default.

## Benchmark expanded to 3,716 tickets, 24 Aug 2026

`training 2.xlsx` (Feb 2024 – Aug 2026, 3,361 rows from 2026) replaces the 623-row set as the
resolved-ticket benchmark. It multiplies the two tag-derived truth sets by roughly six:

| Truth set | Was | Now |
|---|---|---|
| Category, from `Tags` | 377 | **2,370** |
| Master, from `MST-` tags | 190 | **1,237** |
| Routing, from the desk's group | 623 | **0 — column absent** |

**All 1,237 MST tags resolve to a master in the registry, none unmapped.** That is the single
most reassuring number here: the registry is not drifting away from what the desk actually tags.

Measured on it, with rows opened from **1 Jul 2026** held out and reported separately:

| | All | Held out (≥ 2026-07-01) |
|---|---|---|
| Category | 2049/2370 = **86.5%** | 297/338 = **87.9%** |
| Master | 1192/1237 = **96.4%** | 140/141 = **99.3%** (0 gaps, 1 wrong) |

### 86.5% is not a regression from the recorded 89.5%

Different set, six times larger, reaching back two years. Broken down by quarter the older
labelling is plainly the drag, and current practice is flat against the old figure:

```
2025Q3   21 rows  66.7%      2026Q1  910 rows  88.4%
2025Q4  156 rows  80.8%      2026Q2  942 rows  85.7%
                             2026Q3  338 rows  87.9%
```

The ~180 pre-2026 rows pull the headline down by about two points. **Score the holdout, not the
headline**, when judging a change.

### A real weak spot the small set was hiding

Accuracy by category, where there are at least 30 rows to judge on:

| Category | Rows | Correct |
|---|---|---|
| Bookings (Products) | 52 | **48.1%** |
| Invoicing | 101 | 70.3% |
| SOA | 80 | 78.8% |
| Accounts and Companies | 138 | 81.2% |
| Bookings (Products) - Short Stay | 202 | 82.2% |
| Payments Registration | 262 | 86.3% |

`Bookings (Products)` losing more than half its rows is worth a keyword pass on its own — it was
invisible at 377 rows. Note it also sits behind two known contradictions: the amend-agreement
tickets split between `Bookings (Products)` and `Renewals`, and its root-cause prior was set to
`Unknown Cause` on 8 of 8. Resolve the contradiction before tuning keywords, or the tuning
chases a moving label.

### What this export cannot measure, and why

- **Routing.** No assignment-group column, so the 623-row routing check is gone rather than
  reduced. The harness now says `SKIPPED` instead of dividing by zero.
- **Priority.** There is no `Impact` column, and `Severity` is the constant `3 - Low` on all
  3,716 rows. The matrix is urgency × impact, so it cannot be re-derived from this file.
- **Root cause.** No resolution-code or close-notes column. Root cause is still scorecard-only.

A re-export carrying `Assignment group`, `Impact` and the resolution code would close all three.

### Contamination, and the holdout that answers it

25 of the 139 scorecard-graded tickets are inside this export. Fitting on the whole file and then
quoting scorecard accuracy would be scoring partly on training rows — hence the 1 Jul cut.

Two harness changes came out of this and matter beyond it. Scorecard rows now fall back to the
training export for ticket text when a batch export is missing, but **routing is skipped for
those rows**: they carry no supplied group, so scoring them measures the fallback rule rather
than the shipped "the group on the export wins" behaviour, and it reads as a 76% routing
regression that does not exist. And the run now prints a warning when no batch export is found
at all, instead of printing an empty scorecard section that looks like a pass.
