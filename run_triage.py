"""Triage runner for the IWG/Regus ServiceNow batches.

All matching logic lives in reference/classify.py -- this script only assembles
the workbook. The process is documented in README.md and the
`ticket-triage-master` skill; the reasoning behind each rule, and every approach
that was measured and rejected, is in reference/BENCHMARK.md.

    python run_triage.py "path/to/triage export.xlsx" [output.xlsx]
    python measure.py          # ALWAYS run this after changing any reference file

PER-RUN CONFIG is the CLUSTERS and MANUAL_NAME dicts below. Both are
deliberately hand-maintained: a cluster is a claim that several tickets are the
same issue, and a manual name is a judgement about a free-form ticket. Neither
should be generated automatically.
"""
import sys, os, re, glob, datetime
sys.path.insert(0, "reference")
import pandas as pd
import classify as C

SRC = sys.argv[1] if len(sys.argv) > 1 else None
if not SRC:
    sys.exit("usage: python run_triage.py <ticket-export.xlsx> [output.xlsx]\n"
             "       run from the workspace root (the folder holding reference/ and runs/)")
OUT = sys.argv[2] if len(sys.argv) > 2 else \
    f"runs/Triage_{datetime.date.today():%Y-%m-%d}.xlsx"
JIRA_NOTE = "Not checked - Atlassian connector requires authorization"

cats, masters, kbas = C.load_reference()
groups, signals = C.load_groups()
rcs = C.load_root_causes()
L = C.load_learned_groups()
priors = C.load_rc_priors()
kidx, midx = C.build_kba_index(kbas), C.build_master_index(masters)
mst = {m["Master Name"]: m.get("MST Tag", "") for m in masters}

src = pd.read_excel(SRC)
gcol = C.find_group_column(src.columns)


def lvl(v):
    m = re.match(r"\s*(\d)", str(v))
    return int(m.group(1)) if m else None


# Rule 2 has to hold ACROSS runs, not just within one. A carried-over ticket
# keeps the name it was already issued -- redrafting produced "Global Protect VPN
# is not working" on 13 Aug and "...access issue" on 14 Aug for the same ticket.
def prior_names(runs_dir="runs", exclude=()):
    out = {}
    for f in sorted(glob.glob(os.path.join(runs_dir, "*.xlsx")), key=os.path.getmtime):
        if os.path.basename(f).startswith("~$") or os.path.abspath(f) in exclude:
            continue
        try:
            d = pd.read_excel(f, sheet_name="Finished Triage")
        except Exception:
            continue
        col = next((c for c in d.columns if "hort" in c and "escription" in c), None)
        if not col or "TicketID" not in d.columns:
            continue
        for _, r in d.iterrows():
            v = str(r[col]).strip()
            if v and v.lower() != "nan":
                out[r["TicketID"]] = v
    return out


PRIOR = prior_names(exclude={os.path.abspath(OUT)})

# A cluster may ONLY exist for a symptom with no master in the registry. Check
# every unmatched ticket against all 46 masters first -- one run proposed a new
# cluster for six card tickets that already had masters.
CLUSTERS = {
    "[SOA] Invoices paid in D365 still showing unpaid in MyRegus": {
        "cat": "SOA", "ids": [],
        "terms": "mark invoices as paid; showing as unpaid; already allocated in dyn; still shows unpaid after settlement; not reflecting in myregus; already reflected in dyn; payment adjustment",
        "note": "AT 7 AND GROWING. TWO DECISIONS OVERDUE: (1) the name says 'Invoices paid ... showing unpaid' but most members are payments and vouchers that never arrived at all - rename or split; (2) the registry master [SOA] Balance Mismatch competes for these tickets and has NO MST tag - allocate one and fold the cluster in, or scope the master's keywords.",
    },
    "[Renewals] Error submitting renewal team request in TeamHub": {
        "cat": "Renewals", "ids": [],
        "terms": "submit your request; renewal team; send to customer; error occurred when trying to submit; an error occured while trying to submit your request; central renewal support; crt ticket",
        "note": "NOW 8 OF 10, from seven reporters across four batches. Escalate to the TeamHub team rather than waiting for the count.",
    },
    # Sibling of the above but a distinct symptom: the amendment ITSELF errors or
    # freezes, rather than the handoff to the renewals team failing.
    "[Renewals] Error when amending an agreement in TeamHub": {
        "cat": "Renewals",
        "ids": [],
        "terms": "error occured when performing amend agreement; error occurred when performing amend agreement; unable to send renewal osa; teamhub freezes; something went wrong, please log an it ticket via teamhub; move agreement",
        "note": "CATEGORY IS AN OPEN QUESTION - bracketed [Renewals] provisionally. A resolved ticket worded 'Not able to amend agreement' is tagged XC (Product and Services), while the 14 Aug review put TeamHub amend/renew errors under Renewals. Also spans renewal amendments (INC0768485, INC0768499) and office/country moves (INC0768359, INC0768524) - may want splitting.",
    },
    # Five tickets asking for a duplicate or invalid posting in MyRegus to be
    # reversed or zeroed out. Distinct from the D365-sync cluster: there the
    # record never arrived, here it arrived twice or wrongly. The registry master
    # [SOA] Balance Mismatch competes for these and still has no MST tag.
    "[SOA] Duplicate or invalid posting in MyRegus needs reversing": {
        "cat": "SOA",
        "ids": ["INC0761524", "INC0767564", "INC0768203", "INC0768754", "INC0768105"],
        "terms": "duplicate posting; duplicate payment in myregus; reversing the invalid; invalid refund posting; duplicate refund; zero-out the amount; remove or zero-out; reflecting twice; posted twice",
        "note": "Five across three batches, all finance corrections in MyRegus. Sibling of the D365-sync cluster but the opposite direction - the record arrived twice or wrongly rather than not at all. If you would rather treat these as routine finance requests than defects, they can come off the tally.",
    },
    "[Bookings (Products)] Cannot rollback a booking terminated while provisional": {
        "cat": "Bookings (Products)", "ids": [],
        "terms": "rollback the termination; cannot rollback; unable to rollback; terminated while provisional; terminated while it was still provisional; greyed out; grayed out; edit/roll back option",
        "note": "",
    },
    "[Bookings (Products) - Short Stay] Meeting room booking does not complete at the payment step": {
        "cat": "Bookings (Products) - Short Stay", "ids": [],
        "terms": "freeze at the payment step; freezes at the payment step; booking could not be finished; unable to complete meeting room booking; reservation does not complete",
        "note": "INC0768123 reports 'a lot of customers and non-customers' affected. INC0768224 may be the same fault one step earlier but presents as a card rejection, so it is not counted here.",
    },
    # Owner ruling, 14 Aug: NOT a child of MST-76060. Being unable to SEE the
    # Preview OSA screen is a different fault from being unable to SEND from it.
    "[Bookings (Products)] Unable to confirm booking in Staff Mode": {
        "cat": "Bookings (Products)", "ids": ["INC0768738"],
        "terms": "confirm booking; cannot be confirmed; booking cannot be completed; event space booking; after-hours meeting room; staff mode",
        "note": "INC0768738 is an event space booking failing in Customer Portal Staff Mode - the same flow this cluster tracks.",
    },
    "[Bookings (Products)] Unable to see Preview OSA screen for Move Office": {
        "cat": "Bookings (Products)", "ids": [],
        "terms": "preview osa screen; move office; confirmation screen did not appear; unable to see preview",
        "note": "Owner confirmed this is separate from MST-76060.",
    },
    # RENAMED 17 Aug from [Login]. The reviewer categorised INC0768179 as Quick
    # Access, so the cluster bracket follows -- when a clustered ticket's category
    # disagrees with the cluster name, the cluster name is the likely error.
    "[Quick Access] WorldKey PIN rejected as invalid on HP Cloud Printing portal": {
        "cat": "Quick Access", "ids": [],
        "terms": "world key pin; worldkey pin; wkp; credentials invalid; worldkey pin not working",
        "note": "RENAMED from [Login] on 17 Aug. The 5 earlier tickets were tagged Login and need retagging if you adopt the rename.",
    },
    "[Invoicing] Credit note requested for an incorrectly billed charge": {
        "cat": "Invoicing", "ids": [],
        "terms": "issuance of the corresponding credit note; assistance with a credit note; billed twice; late payment fee; incorrectly generated; authorization from the franchise owner",
        "note": "Both carry franchise-owner authorisation and both correct an incorrect charge rather than report a portal fault. If these are routine finance requests they may not belong on this tally - your call.",
    },
}
CLUSTER_OF = {t: name for name, c in CLUSTERS.items() for t in c["ids"]}

# Free-form tickets pasted from email carry no usable symptom line, so the name
# is written from the body rather than drafted mechanically. UNCATEGORISED marks
# a name that cannot be finalised until the category is decided.
MANUAL_NAME = {
    # 20 Aug
    "INC0768632": "[Roles and Permissions] TeamHub access removed - Deputy City Manager needs City Manager permissions",
    "INC0768650": "[Contract API/Agreements] OSA not autoloaded in Titan after acceptance",
    "INC0768680": "[Accounts and Companies] Customer records missing from the ServiceNow client list",
    "INC0768701": "[Memberships] Incorrect membership visit shown in the Regus portal",
    "INC0768764": "[Contract API/Agreements] Unable to upload signed paper agreement in OSA Detail",
    # 13-14 Aug
    "INC0767810": "[UNCATEGORISED] Global Protect VPN is not working",
    "INC0767842": "[UNCATEGORISED] Titan activation fee mismatch between booking and summary",
    "INC0767930": "[UNCATEGORISED] Printer linked to wrong centre and print release tracking check",
    "INC0767965": "[UNCATEGORISED] MyRegus getTranslations availability test failing (automated P1 alert)",
    "INC0767976": "[Memberships] Account not visible after login and unable to book with membership usage",
    "INC0767995": "[XC (Product and Services)] Callstream office number cannot make or receive calls",
    # 17 Aug
    "INC0767111": "[Quick Access] Access Control username displayed in Japanese Kanji instead of English",
    "INC0768070": "[Invoicing] Customer not receiving invoices after additional recipient email added",
    "INC0768105": "[SOA] Duplicate payment posted in MyRegus needs zeroing out",
    "INC0768111": "[Documents] Delete confidential file uploaded to MyRegus account in error",
    "INC0768136": "[Renewals] Renewal reminder email not sent to office client",
    "INC0768143": "[UNCATEGORISED] Printer reports job completed but nothing prints",
    "INC0768150": "[XC (Product and Services)] Incorrect one-off Mail Forwarding charges on active weekly service",
    "INC0768224": "[Payments - Credit Card] Payment portal rejects Mastercard preventing meeting room booking",
    # 18 Aug
    "INC0768242": "[Contract API/Agreements] Tax ID rejected as incorrect when uploading Internal Service Agreement",
    "INC0768253": "[Invoicing] Credit notes tagged as internal need posting",
    "INC0768271": "[UNCATEGORISED] Printer reports job completed but nothing prints",
    "INC0768275": "[Invoicing] Sales invoices not found in Titan",
    "INC0768311": "[SOA] Dynamics voucher not posted to MyRegus SOA causing incorrect balance",
    "INC0768331": "[Invoicing] Remove unnecessary KA one-off fee from customer account",
    "INC0768376": "[Invoicing] Invoices generated but not sent to the client's registered email",
    # 19 Aug
    "INC0768438": "[Payments - Credit Card] Delayed card deduction caused a late payment fee",
    "INC0768469": "[Invoicing] Customer set to e-invoicing only is also receiving invoices by email",
    "INC0768480": "[Invoicing] MyRegus invoice covers five months with no account changes",
    "INC0768486": "[Memberships] Cancel membership button missing in Customer Portal",
    "INC0768500": "[XC (Product and Services)] Cannot enable self-service Premium Call Answering settings on MyRegus",
    "INC0768505": "[Invoicing] Greek e-invoice rejected - invoice ID must match a valid TIN number",
    "INC0768540": "[Bookings (Products) - Short Stay] MyRegus booking not working for customer",
    "INC0768542": "[Invoicing] Customer still billed for a service no longer in recurring sales",
    "INC0768546": "[Login] New client unable to log in - account marked as inactive",
    "INC0768571": "[Login] Staff unable to access MyRegus and TeamHub",
    "INC0768590": "[Login] MyRegus account activation and access not working",
    "INC0768592": "[Payments - Credit Card] AutoPay did not collect the full invoice amount after a credit note was applied",
    "INC0768596": "[Payments - Credit Card] Card payment shows as succeeded in MyRegus but the client disputes it",
}

# Systems that are not IWG customer-facing products at all.
OUT_OF_SCOPE_TERMS = ("global protect", "globalprotect", "vpn", "service now",
                      "servicenow", "snow ticket", "raise it ticket on service now")
# ...but Unclassified does not always mean out of scope. Printers are in scope
# (L2 - Proton owns them) and simply have no category for print OUTPUT faults.
IN_SCOPE_NO_CATEGORY = ("printer", "printing", "print job", "printeron",
                        "print release", "nothing prints")

rows, detail, review, mism = [], [], [], []

for _, s in src.iterrows():
    tid = s["Number"]
    sd, desc = s["Short description"], s.get("Description")
    r = C.triage_row(sd, desc, cats, masters, kbas, kidx, midx)
    cat, master = r["category"], r["master"]

    # A LOW-confidence match is a tie between masters; the rule is do not apply.
    if master and r.get("confidence") == "Low":
        review.append((tid, "Master match too weak to apply",
                       f"Tied between masters at low confidence (best: '{master}'). "
                       f"Not linked and not tagged ChildTicket - pick the parent by hand."))
        master = None
    # A master with no MST tag cannot produce a complete tag set, and the rule is
    # to raise a blocker rather than half-link.
    if master and not mst.get(master, "").strip():
        review.append((tid, "BLOCKER - master has no MST tag",
                       f"Matches '{master}', which carries no MST tag, so a ChildTicket tag "
                       f"would leave the ticket half-linked. Left unlinked. Allocate that "
                       f"master an MST tag, or scope its keywords."))
        master = None
    # Dropping a master drops the category it carried with it.
    if master is None and r.get("master"):
        sym = C.strip_pipe_prefix(sd)
        cat = C.classify_category(sym, cats)[0]
        if cat == "Unclassified":
            cat = C.classify_category(f"{sym} {C.symptom_body(desc)}", cats)[0]

    g = C.final_group(s[gcol], cat, sd, desc, L, groups, signals)

    # --- priority: matrix lookup on the SUPPLIED Impact/Urgency
    u, i = lvl(s.get("Urgency")), lvl(s.get("Impact"))
    if u and i:
        pri = C.PRIORITY_MATRIX[u][i]
        psrc = f"matrix U{u} x I{i} (supplied)"
        allowed, why = C.p1_allowed(sd, desc)
        # P1 AND P2 both require outage evidence: across 39 graded tickets the
        # reviewer never chose either, and every matrix P2 was corrected down.
        if pri in ("P1", "P2") and not allowed:
            pri, psrc = "P3", (f"matrix U{u} x I{i} = {C.PRIORITY_MATRIX[u][i]}, "
                               f"capped to P3 (no outage or major-function evidence)")
        # PROVISIONAL, 3 samples: Quick Access graded P4 in 3 of 3 while the sheet
        # gave Impact 2 / Urgency 2. First counter-example should retire this.
        if cat == "Quick Access" and pri != "P4":
            pri, psrc = "P4", (f"matrix U{u} x I{i} = {C.PRIORITY_MATRIX[u][i]}; "
                               f"Quick Access graded P4 in 3 of 3 reviewed cases (provisional)")
    else:
        pri, psrc = "", "no impact/urgency supplied"

    # --- naming. Rule 2 - identical issue, identical name - drives the order.
    if master:
        new_sd, name_src = master, "master name (agreed)"
        if tid in PRIOR and PRIOR[tid] != new_sd:
            review.append((tid, "Name realigned to master",
                           f"Named '{PRIOR[tid]}' earlier, before the registry match was found. "
                           f"Now a child of '{master}' ({mst.get(master,'no MST tag')})."))
    elif tid in CLUSTER_OF:
        new_sd, name_src = CLUSTER_OF[tid], "cluster name (shared by all tickets on this issue)"
        ccat = CLUSTERS[new_sd]["cat"]
        if ccat != cat:
            review.append((tid, "Category set by cluster",
                           f"Read as '{cat}' from the wording but joins cluster '{new_sd}' "
                           f"(category '{ccat}'). Taking the cluster's so the bracket and the "
                           f"tag agree. If '{cat}' is the better reading, rename the cluster."))
            cat = ccat
        if tid in PRIOR and PRIOR[tid] != new_sd:
            review.append((tid, "Name realigned",
                           f"Named '{PRIOR[tid]}' earlier. Now part of a tracked cluster, so it "
                           f"takes the shared name - rule 2 requires one issue, one name."))
    elif tid in PRIOR:
        new_sd, name_src = PRIOR[tid], "carried forward from an earlier run (unchanged)"
        want = "UNCATEGORISED" if cat == "Unclassified" else cat
        m_br = re.match(r"^\[([^\]]+)\]\s*(.*)$", new_sd)
        if m_br and m_br.group(1) != want:
            new_sd = f"[{want}] {m_br.group(2)}"
            name_src = "carried forward, bracket realigned to the category"
            review.append((tid, "Bracket realigned",
                           f"Kept the wording from '{PRIOR[tid]}' but the category is now "
                           f"'{cat}', so the bracket was corrected to match."))
    elif tid in MANUAL_NAME:
        new_sd, name_src = MANUAL_NAME[tid], "written by hand - free-form ticket"
    else:
        new_sd, name_src = C.propose_master_name(sd, cat)[0], "drafted from short description"

    # --- KBA. Strong only in the main sheet; best-ranked exposed in the detail
    # sheet because the threshold's calibration is still open.
    hits = C.find_kbas_best(cat, master, kbas, kidx, sd, desc) or []
    strong = [(k, sc) for k, sc, _t in hits if (sc or 0) >= C.KBA_REPORT_THRESHOLD]
    kba = "; ".join(f"{k['KB Number']} ({sc:.0f})" for k, sc in strong[:2])
    all_kba = "; ".join(f"{k['KB Number']} ({(sc or 0):.0f}) {str(k.get('Title',''))[:44]}"
                        for k, sc, _t in hits[:3])
    kba_top = f"{hits[0][0]['KB Number']} - {str(hits[0][0].get('Title',''))[:60]}" if hits else ""

    # --- root cause: a suggestion with a ~43% ceiling from text alone
    rcd = C.suggest_root_cause_learned(sd, desc, rcs, cat, priors)
    rc, rc_conf, rc_basis = rcd["root_cause"], rcd["confidence"], rcd["basis"]

    # --- scope
    sym_all = f"{C.strip_pipe_prefix(sd)} {desc or ''}".lower()
    oos = [t for t in OUT_OF_SCOPE_TERMS if C._matches(t, sym_all)]
    in_scope_gap = any(C._matches(t, sym_all) for t in IN_SCOPE_NO_CATEGORY)
    out_of_scope = ("Yes" if oos else "No - category gap" if in_scope_gap
                    else "Likely" if cat == "Unclassified" else "")
    if oos:
        review.append((tid, "Likely out of scope",
                       f"Mentions {', '.join(oos)} - corporate IT or the ticketing platform "
                       f"itself, not an IWG customer-facing product. The destination may be "
                       f"outside L2 entirely."))
    elif cat == "Unclassified" and not in_scope_gap:
        review.append((tid, "Unclassified - check scope",
                       "No category fits. Per standing guidance these are usually outside our "
                       "support scope rather than a keyword gap."))

    # --- tags
    tags = ["TriagedTicket"]
    if master:
        tags.append("ChildTicket")
        t = mst.get(master, "")
        if t:
            tags.append(t)
    if cat != "Unclassified":
        tags.append(cat)
    else:
        review.append((tid, "No category",
                       "Unclassified - cannot be fully tagged until a category is decided."))

    rows.append({
        "TicketID": tid, "Short Description": new_sd, "Master Ticket": master or "",
        "Assigned Group (should be)": g["group"], "Tags": ", ".join(tags),
        "Category": cat, "Root Cause": rc, "KBA": kba, "Priority": pri,
    })
    detail.append({
        "TicketID": tid, "Original short description": sd,
        "New short description": new_sd, "Name source": name_src,
        "Category": cat, "Category source": r.get("source", ""),
        "Master": master or "", "Master confidence": r.get("confidence", ""),
        "Group on export": s[gcol], "Group assigned": g["group"],
        "Group source": g.get("source", ""),
        "Impact (supplied)": s.get("Impact"), "Urgency (supplied)": s.get("Urgency"),
        "Priority": pri, "Priority source": psrc,
        "Root cause (suggested)": rc, "Root cause confidence": rc_conf,
        "Root cause basis": rc_basis, "Out of scope?": out_of_scope,
        "KBA (strong only)": kba,
        "Best-ranked KBA (below threshold - agent judgement)": "" if kba else kba_top,
        "All KBA candidates": all_kba, "JIRA": JIRA_NOTE,
        "Tags": ", ".join(tags), "State": s.get("State"),
    })
    if g.get("suggested") and C.canon_group(str(g["suggested"])) != C.canon_group(g["group"]):
        mism.append({"TicketID": tid, "On export": s[gcol], "Rule suggests": g["suggested"],
                     "Kept": g["group"], "Category": cat})

fin = pd.DataFrame(rows)
det = pd.DataFrame(detail)

# ---------------------------------------------------------------- tally
# Pin this to the last run you have SIGNED OFF, not simply the newest file, or a
# superseded run injects retracted clusters into every future one.
prev_file = os.environ.get("TRIAGE_TALLY_FROM", "runs/Triage_2026-08-18.xlsx")
prev = pd.read_excel(prev_file, sheet_name="Proposed Masters").copy()
namecol = prev.columns[0]
for old, new, newcat in [
        ("[Invoicing] Invoices paid in D365 still showing unpaid in MyRegus",
         "[SOA] Invoices paid in D365 still showing unpaid in MyRegus", "SOA"),
        ("[Accounts and Companies] Error submitting renewal team request in TeamHub",
         "[Renewals] Error submitting renewal team request in TeamHub", "Renewals"),
        ("[Login] WorldKey PIN rejected as invalid on HP Cloud Printing portal",
         "[Quick Access] WorldKey PIN rejected as invalid on HP Cloud Printing portal",
         "Quick Access")]:
    prev[namecol] = prev[namecol].replace(old, new)
    prev.loc[prev[namecol] == new, "Category"] = newcat

IDCOL = "Ticket IDs (all runs)"
if IDCOL not in prev.columns:
    prev[IDCOL] = prev["Ticket IDs (current batch)"].fillna("")
prev["Current-batch count"] = 0
prev["Ticket IDs (current batch)"] = ""

for name, c in CLUSTERS.items():
    if (prev[namecol] == name).any():
        idx = prev.index[prev[namecol] == name][0]
        prior_ids = [x.strip() for x in str(prev.at[idx, IDCOL]).split(";") if x.strip()]
        prev.at[idx, "Current-batch count"] = len(c["ids"])
        prev.at[idx, "Ticket IDs (current batch)"] = "; ".join(c["ids"])
        prev.at[idx, IDCOL] = "; ".join(sorted(set(prior_ids) | set(c["ids"])))
        if c["note"]:
            prev.at[idx, "Note"] = c["note"]
    else:
        prev = pd.concat([prev, pd.DataFrame([{
            namecol: name, "Category": c["cat"], "Resolved-history count": 0,
            "Current-batch count": len(c["ids"]),
            "JIRA master already exists?": JIRA_NOTE, "Status": "",
            "Ticket IDs (current batch)": "; ".join(c["ids"]),
            "Ticket IDs (resolved history)": "", IDCOL: "; ".join(c["ids"]),
            "Match terms": c["terms"], "Note": c["note"],
        }])], ignore_index=True)

# Recomputed from the ID list rather than incremented, so a re-run cannot
# double-count.
prev["Resolved-history count"] = prev["Resolved-history count"].fillna(0).astype(int)
prev["Total seen"] = prev.apply(
    lambda r: r["Resolved-history count"]
    + len([x for x in str(r[IDCOL]).split(";") if x.strip()]), axis=1)
prev["Threshold (10)"] = prev["Total seen"].apply(
    lambda n: "OVER THRESHOLD - propose master" if n > 10 else f"{11-int(n)} more needed")
prev["Status"] = prev["Total seen"].apply(
    lambda n: "READY - needs your approval + MST tag" if n > 10
    else "below threshold - tracking")
prev = prev.sort_values("Total seen", ascending=False)

# ---------------------------------------------------------------- master audit
# Every ticket->master link asserted since 12 Aug was re-checked on 19 Aug. Six
# were wrong. If ChildTicket / MST tags were already applied in ServiceNow for
# these, they need removing.
# The 19 Aug master audit and its reversal are recorded in the 19 Aug workbook
# and in BENCHMARK.md. Nothing to correct this run.
CORRECTIONS = []
corr = pd.DataFrame(CORRECTIONS, columns=[
    "TicketID", "Was", "MST tag involved", "Should be", "Reason"])
if corr.empty:
    corr = pd.DataFrame([{"TicketID": "-", "Was": "-", "MST tag involved": "-",
                          "Should be": "-",
                          "Reason": "No master links corrected this run. The 19 Aug audit and its reversal are in Triage_2026-08-19_v3.xlsx and reference/BENCHMARK.md."}])

# ---------------------------------------------------------------- other sheets
gsum = fin.groupby("Assigned Group (should be)").size().reset_index(name="Tickets")
csum = fin.groupby("Category").size().reset_index(name="Tickets").sort_values(
    "Tickets", ascending=False)
psum = fin.groupby("Priority").size().reset_index(name="Tickets")
tagsheet = pd.DataFrame([{
    "TicketID": r["TicketID"], "Tag 1": "TriagedTicket",
    "Tag 2": "ChildTicket" if "ChildTicket" in r["Tags"] else "",
    "Tag 3": next((t for t in r["Tags"].split(", ") if t.startswith("MST")), ""),
    "Tag 4": r["Category"] if r["Category"] != "Unclassified" else "",
} for _, r in fin.iterrows()])

REVIEW_EXTRA = [
    ("DID", "Wrong DID on MyRegus profile is now 8 tickets", "INC0768679, INC0768686 and INC0768687 are three more in one day, all 'wrong DID showing' on the MyRegus profile, all asking explicitly for Proton. With INC0767819, INC0767855, INC0768158, INC0768500 and INC0768538 that is 8 children of MST-71283 across five batches. The master exists so no new one is needed, but the volume is worth raising - and all three reporters state the correct DID in the ticket, so these look like data corrections rather than a code defect."),
    ("AUTOPAY", "Autopay not collecting is 6 tickets", "INC0768746, INC0768753 and INC0768756 all report a registered default card where automatic payment never runs, joining INC0768037, INC0768438 and INC0768592 under MST-71218. INC0768746 adds that no payment-failure notice was sent either, so the customer could not tell the collection had failed."),
    ("INC0768754", "BLOCKER - master has no MST tag", "Matches [SOA] Balance Mismatch, which still carries no MST tag. That master has now competed for tickets in three consecutive batches. It needs a tag or narrower keywords."),
    ("INC0768680", "Scope call needed", "Customer records missing from the ServiceNow client list. The flag reads 'out of scope' because it names ServiceNow, but the missing data is IWG customer records and the reporter confirmed the customers are linked correctly in the Customer Portal. The sheet routes it to L2 - Proton. On 14 Aug you sent a similar ServiceNow ticket to L3-ServiceNow Platform - confirm which applies here."),
    ("INC0768745", "Master match to confirm", "The credit card entry form never appears - no error, the form is simply absent. Linked to MST-71221 'Something went wrong Error when trying to add Payment Card' because it is the only add-a-card master, but the failure mode differs. INC0768759 is the same symptom."),
    ("INC0768759", "Master match to confirm", "As INC0768745 - the online card entry form did not appear."),
    ("INC0768764", "OSA upload stuck on a spinner", "Renewal in the grace period, signed paper agreement upload hangs with no action triggered. With INC0768650 (OSA not autoloaded) and INC0768242 from 18 Aug, that is three OSA agreement faults in three days - no master covers OSA handling."),
    ("INC0768703", "Master match to confirm", "Linked to MST-71510 'Retainer issues' at Medium. That master is broad; this is specifically the Return of Retainer button missing for an eligible client."),
    ("INC0768632", "Permissions request, not a fault", "A Deputy City Manager asking for access aligned to City Manager permissions. Reads as an access request rather than a defect - worth checking whether it should be a service request instead of an incident."),
    ("INC0767909", "Master match to confirm", "Wi-Fi connectivity at centre 1521, linked to MST-71542 'Network devices registration/login'. The ticket says the connection works but is on 192.168.11.245, which reads as an addressing or VLAN problem rather than registration or login."),
]
rev = pd.DataFrame([{"TicketID": t, "Issue": k, "Detail": d}
                    for t, k, d in list(review) + REVIEW_EXTRA],
                   columns=["TicketID", "Issue", "Detail"])

with pd.ExcelWriter(OUT, engine="openpyxl") as xl:
    fin.to_excel(xl, sheet_name="Finished Triage", index=False)
    det.to_excel(xl, sheet_name="Triage Detail (full)", index=False)
    prev.to_excel(xl, sheet_name="Proposed Masters", index=False)
    corr.to_excel(xl, sheet_name="Master Corrections", index=False)
    pd.read_csv("reference/priority-matrix.csv").to_excel(
        xl, sheet_name="Priority Matrix", index=False)
    rev.to_excel(xl, sheet_name="Review", index=False)
    gsum.to_excel(xl, sheet_name="Group Summary", index=False)
    csum.to_excel(xl, sheet_name="Category Summary", index=False)
    psum.to_excel(xl, sheet_name="Priority Summary", index=False)
    (pd.DataFrame(mism) if mism else pd.DataFrame(
        columns=["TicketID", "On export", "Rule suggests", "Kept", "Category"])
     ).to_excel(xl, sheet_name="Group Mismatches", index=False)
    tagsheet.to_excel(xl, sheet_name="Tags", index=False)

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
wb = load_workbook(OUT)
hdr = Font(bold=True, color="FFFFFF")
fill = PatternFill("solid", fgColor="2F5597")
for ws in wb:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for c in ws[1]:
        c.font, c.fill = hdr, fill
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for col in ws.columns:
        w = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(w + 2, 12), 55)
wb.save(OUT)

# ---------------------------------------------------------------- assertions
bad = []
for _, r in fin.iterrows():
    m = re.match(r"^\[([^\]]+)\]", str(r["Short Description"]))
    want = "UNCATEGORISED" if r["Category"] == "Unclassified" else r["Category"]
    if not m or m.group(1) != want:
        bad.append((r["TicketID"], r["Short Description"], r["Category"]))
kids = fin[fin["Tags"].str.contains("ChildTicket")]
assert not bad, f"bracket/category mismatch: {bad}"
assert fin["Short Description"].notna().all(), "blank name"
assert all("MST" in t for t in kids["Tags"]), "ChildTicket without an MST tag"

print(f"WROTE {OUT}  ({len(fin)} tickets)   [assertions passed]")
print("\n--- group ---")
print(gsum.to_string(index=False))
print("\n--- priority ---")
print(psum.to_string(index=False))
print("\n--- category ---")
print(csum.to_string(index=False))
print("\n--- tally ---")
print(prev[[namecol, "Total seen", "Threshold (10)"]].to_string(index=False))
print(f"\nmismatches: {len(mism)}   review rows: {len(rev)}   master corrections: {len(corr)}")
