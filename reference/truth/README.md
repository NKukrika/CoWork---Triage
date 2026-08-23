# Ground truth for `measure.py`

`measure.py` is the regression harness. The skill requires it after **any** edit to
`reference/` — it re-scores four independent ground-truth sets so a reference change
cannot silently degrade matching.

The workbooks below hold real ServiceNow ticket data, so they are **gitignored**.
Only this README is committed. Drop the files here, or point `TRIAGE_UPLOADS` at
whatever folder already holds them.

## Files the harness looks for

| File | Feeds | Required columns |
|---|---|---|
| `resolved and closed for training.xlsx` | category, master matching, routing | `Short description`, `Description`, `Tags`, and one of `Assignment group` / `Assigned group` / `Group` / `Support group` |
| `triage*.xlsx` (one per batch export) | joins scorecard rows back to the ticket text | `Number` (ticket ID), plus the same columns as above |
| `*Scorecard*.xlsx` | human grading — the most trusted set | sheet `Evaluation Log`, header on row 3, columns `Incident ID`, `Date`, `Human · Category`, `Human · Assignment` |

Only the newest scorecard is read. Batch exports are matched by ticket ID across all
of them, so adding a new one needs no code change.

## What the `Tags` column has to contain

Truth for two of the four sets is read straight out of `Tags`:

- **Category** — a tag matching a `Category` in `categories.csv` (whitespace and case
  are normalised, so `xc (product and services)` matches).
- **Master** — a tag of the form `MST-12345`, matched against the `MST Tag` column of
  `master-tickets.csv`.

A row with neither is skipped, not counted wrong. That means a thin `Tags` column
shrinks the measurable set without ever showing up as a failure — check the
denominators the harness prints, not just the percentages.

## Root cause

Root cause is graded on the scorecard, not read from `Tags`. It must come from the
29-value picklist. Free text or a **category name** pasted into the root-cause column
makes the row unusable — this cost the whole 21 Aug batch, where ten of ten root
causes held category names. A data-validation dropdown on that column prevents it.

## Columns the current export is missing

`training 2.xlsx` (3,716 rows) supplies category and master truth but **cannot** measure three
things. If a re-export is possible, adding these closes all three gaps:

| Add | Unlocks |
|---|---|
| `Assignment group` | the routing check — currently `SKIPPED` entirely, not merely smaller |
| `Impact` | priority. The matrix is urgency × impact; `Severity` is the constant `3 - Low` on every row and is not a substitute |
| resolution code / close notes | root cause at volume — today it is scorecard-only, ~44% on 72 graded rows |

Batch exports (`triage*.xlsx`, with a `Number` column) are also absent. Without them the
scorecard can only be scored on the 26 graded tickets that happen to appear in the training
export, instead of all 139.
