"""Shared classifier for the triage workspace.

Word-boundary keyword matching against reference/categories.csv, honouring the
Precedence column (lower number tested first, so specific categories beat broad
ones). Substring matching is deliberately NOT used -- it produces false hits
like "voice" inside "invoice".

Usage:
    from classify import load_reference, classify_category, match_master
"""

import csv
import re
from pathlib import Path

REF = Path(__file__).parent


def load_reference(ref_dir=REF):
    ref_dir = Path(ref_dir)
    cats = list(csv.DictReader(open(ref_dir / "categories.csv", encoding="utf-8")))
    cats.sort(key=lambda c: (int(c.get("Precedence", 50)), c["Category"]))
    masters = list(csv.DictReader(open(ref_dir / "master-tickets.csv", encoding="utf-8")))
    kbas = list(csv.DictReader(open(ref_dir / "kba-index.csv", encoding="utf-8")))
    return cats, masters, kbas


def load_root_causes(ref_dir=REF):
    rows = list(csv.DictReader(open(Path(ref_dir) / "root-causes.csv", encoding="utf-8")))
    rows.sort(key=lambda r: (int(r.get("Precedence", 50)), r["Root cause"]))
    return rows


def suggest_root_cause(short_desc, description, root_causes, jira_detail=""):
    """Suggest a root cause from the fixed picklist.

    Root cause is about WHY, and a support ticket usually reports only WHAT the
    user saw. So this is deliberately conservative: it returns 'Unknown Cause'
    unless the text or the JIRA history actually supports a specific cause, and
    it always returns its evidence so a human can overrule it.

    JIRA detail is weighted above the ticket text -- the cause is far more often
    established in the prior investigation than in the customer's report.
    """
    sd = strip_pipe_prefix(short_desc or "").lower()
    body = (description or "").lower()
    jira = (jira_detail or "").lower()

    scored = []
    for rc in root_causes:
        if rc["Root cause"] == "Unknown Cause":
            continue
        ev_j, ev_t = [], []
        for kw in _split(rc.get("Signals")):
            if jira and _matches_not_ruled_out(kw, jira):
                ev_j.append(kw)
            if _matches_not_ruled_out(kw, sd) or _matches_not_ruled_out(kw, body):
                ev_t.append(kw)
        if ev_j or ev_t:
            score = len(ev_j) * 3 + len(ev_t)
            scored.append((rc["Root cause"], score, ev_j, ev_t, int(rc["Precedence"])))

    if not scored:
        return {"root_cause": "Unknown Cause", "confidence": "n/a",
                "evidence": "", "alternatives": [],
                "reason": "No cause evidence in the ticket or its JIRA history. "
                          "Left as Unknown Cause rather than guessed."}

    scored.sort(key=lambda x: (x[4], -x[1]))
    scored.sort(key=lambda x: -x[1])
    top = scored[0]
    name, score, ev_j, ev_t = top[0], top[1], top[2], top[3]
    conf = "High" if (ev_j and score >= 4) else "Medium" if score >= 2 else "Low"
    ev = ("JIRA: " + ", ".join(ev_j[:3]) if ev_j else "") + \
         ("; " if ev_j and ev_t else "") + \
         ("ticket: " + ", ".join(ev_t[:3]) if ev_t else "")
    return {"root_cause": name, "confidence": conf, "evidence": ev,
            "alternatives": [s[0] for s in scored[1:3]],
            "reason": f"Matched on {ev}." +
                      (" Cause established in prior JIRA investigation."
                       if ev_j else " Inferred from the ticket wording only.")}


def load_groups(ref_dir=REF):
    ref_dir = Path(ref_dir)
    groups = {r["Category"]: r for r in
              csv.DictReader(open(ref_dir / "groups.csv", encoding="utf-8"))}
    signals = []
    for r in csv.DictReader(open(ref_dir / "group-signals.csv", encoding="utf-8")):
        for kw in _split(r["Signal keywords"]):
            signals.append((r["Group"], int(r.get("Weight", 1)), kw))
    return groups, signals


def strip_pipe_prefix(short_desc):
    """Drop the leading pipe segments of a ServiceNow short description.

    'Customer Portal | Invoicing Issue | Unable to change billing frequency'
    begins with an app label on essentially every ticket, so treating it as
    routing evidence makes the Portal signal fire universally and produces a
    false conflict on almost every row. Only the symptom text is evidence.
    """
    if not is_pipe_structured(short_desc):
        return short_desc or ""
    parts = [p.strip() for p in (short_desc or "").split("|")]
    return parts[-1] if len(parts) > 1 else (short_desc or "")


def is_pipe_structured(short_desc):
    """Does this short description actually follow 'App | Area | Symptom'?

    A pipe is only a field separator when the ticket was written to the
    convention. Free-form tickets pasted from email routinely contain one by
    accident -- 'Hello Team, Company Name: ... Type of Ticket: Customer | VO
    Standard' -- and splitting on it threw away the entire symptom, leaving
    'VO Standard', or nothing at all when the pipe was the last character.
    The test is the FIRST segment: in the convention it is a short app label
    ('Customer Portal', 'Team Hub', 'Printer'), never a paragraph.
    """
    s = short_desc or ""
    if "|" not in s:
        return False
    first = s.split("|")[0].strip()
    if len(first.split()) > 6 or len(first) > 60:
        return False
    return any(p.strip() for p in s.split("|")[1:])


# --- Surface-based routing -------------------------------------------------
# Agreed rule: route on the surface where the issue is VISIBLE to whoever
# reported it, not on where the eventual fix lands.
#   shown in Titan                     -> L2 - Titan
#   shown in Customer Portal / TeamHub -> L2 - Portal
#   login / OTP / email code           -> L2 - Proton
# The login rule outranks the surface rule: a login failure is an identity
# problem wherever the sign-in screen happens to be rendered.
SURFACE_TERMS = {
    "Titan": ["titan", "titanui", "titan ui", "titan db", "titan database", "dbo"],
    "Customer Portal": ["customer portal", "myregus", "my regus", "customer's portal",
                        "client portal", "online portal", "cp portal"],
    "TeamHub": ["teamhub", "team hub"],
}
LOGIN_TERMS = ["login", "log in", "logging in", "log-in", "sign in", "signin",
               "otp", "one time password", "verification code", "verification email",
               "email code", "sms code", "password reset", "reset password",
               "authentication", "unable to authenticate", "account activation",
               "account needs activation", "not receiving code", "2fa", "mfa"]
# Words that mark the surface as the place the failure is OBSERVED, rather than
# a system merely referenced as background.
OBSERVED_NEAR = ["error", "unable", "cannot", "can not", "can't", "fails", "failing",
                 "failed", "not showing", "not show", "not visible", "not present",
                 "not appearing", "does not appear", "shows", "showing", "displayed",
                 "displays", "greyed", "grayed", "blank", "spinning", "stuck",
                 "reverts", "missing", "issue", "problem", "wrong", "incorrect",
                 "went wrong", "pending", "not load", "won't load", "crash"]
SURFACE_TO_GROUP = {"Titan": "L2 - Titan",
                    "Customer Portal": "L2 - Portal",
                    "TeamHub": "L2 - Portal"}

# Surfaces that appear in real tickets but are NOT covered by the three-group
# rule. Detected and reported rather than guessed at, because inventing a
# mapping here would silently route work to a team that may not own it.
UNMAPPED_SURFACES = {
    "Public website (regus.com)": ["regus.com", "www.regus.com", "regus website",
                                   "booking-rd", "public site", "public website"],
    "ServiceNow": ["servicenow", "service now", "snow ticket"],
    "Dynamics / D365": ["d365", "dynamics 365", "dynamics f&o", "dynamics fo", "dyn"],
    "Printer / PrinterOn": ["printer", "printeron", "print anywhere"],
    "WorldKey / access hardware": ["worldkey", "world key", "wkp", "card reader",
                                   "card-reader"],
    "External tax authority portal": ["tax authority portal", "tax authority"],
}


def unmapped_surfaces(short_desc, description):
    """Return {surface: [terms]} for surfaces outside the three-group rule."""
    t = f"{strip_pipe_prefix(short_desc or '')} {description or ''}".lower()
    out = {}
    for name, terms in UNMAPPED_SURFACES.items():
        ev = [x for x in terms if _matches(x, t)]
        if ev:
            out[name] = ev
    return out


# Phrases that mark a system as BACKGROUND -- where data was set up or looked
# up, not where the user hit the problem. Checked in the words immediately
# BEFORE the system name, because direction matters: "configured on Titan but
# not present on MyRegus" observes the failure in the portal, not in Titan.
BACKGROUND_BEFORE = ["configured on", "configured in", "configured at", "set up on",
                     "set up in", "created in", "created on", "stored in", "exists in",
                     "available in", "available on", "we can see", "checking the",
                     "checking on", "checked in", "according to", "hotfix in",
                     "hotfix on", "as per", "raised in", "logged in the", "record in",
                     "records in", "data in", "present on titan", "visible in titan"]


def _score_surface_term(term, text, in_short_desc=False):
    """Score one system-name mention by the role it plays in the sentence.

    3 = the failure is observed here, 1 = neutral mention, 0 = background only.
    Short-description mentions count double: that is the reported symptom.
    """
    total = 0
    for m in re.finditer(_kw_pattern(term), text):
        before = text[max(0, m.start() - 30):m.start()]
        around = text[max(0, m.start() - 70):min(len(text), m.end() + 70)]
        if any(p in before for p in BACKGROUND_BEFORE):
            weight = 0
        elif any(w in before for w in OBSERVED_NEAR):
            weight = 3          # "not present on <surface>", "unable to ... in <surface>"
        elif any(w in around for w in OBSERVED_NEAR):
            weight = 1
        else:
            weight = 1
        total += weight * (2 if in_short_desc else 1)
    return total


def surface_group(short_desc, description, category=None):
    """Decide the group from the surface where the issue is visible.

    Returns a dict with the group, the surface, the evidence, and an
    `ambiguous` note when more than one surface is observed -- typically a
    sync problem such as "configured on Titan but not present on MyRegus",
    where the customer sees the failure in the portal even though Titan holds
    the data. The portal is the surface in that case; the note keeps it visible.
    """
    sd = strip_pipe_prefix(short_desc or "").lower()
    body = (description or "").lower()

    login_ev = [t for t in LOGIN_TERMS if _matches(t, sd) or _matches(t, body)]
    # The Login category is itself decisive -- more reliable than sniffing terms.
    # A ticket whose master sits under Login is an identity problem by definition.
    if category == "Login":
        login_ev = ["category = Login"] + login_ev

    scored, evidence, mentioned = {}, {}, {}
    for surface, terms in SURFACE_TERMS.items():
        score, ev = 0, []
        for t in terms:
            if _matches(t, sd) or _matches(t, body):
                ev.append(t)
            score += _score_surface_term(t, sd, in_short_desc=True)
            score += _score_surface_term(t, body)
        if ev:
            mentioned[surface] = ev
        if score:
            scored[surface], evidence[surface] = score, ev

    ranked = sorted(scored.items(), key=lambda kv: -kv[1])

    if login_ev:
        note = ""
        if ranked and ranked[0][0] == "Titan":
            note = (f"Login signals present ({', '.join(login_ev[:3])}) but Titan is also "
                    f"observed ({', '.join(evidence['Titan'][:3])}). The login rule sends this to "
                    f"L2 - Proton; historically these can need a Titan-side identity record fix "
                    f"(userProfileId in dbo.ContactUserProfile), so Proton may need to hand over.")
        return {"group": "L2 - Proton", "surface": "Login / authentication",
                "surface_evidence": ", ".join(login_ev[:5]),
                "surface_rule": "login rule -> L2 - Proton (outranks surface)",
                "surface_ambiguity": note}

    if not ranked:
        extra = ""
        if mentioned:
            extra = (" Systems were named only as background ("
                     + "; ".join(f"{s}: {', '.join(v[:2])}" for s, v in mentioned.items()) + ").")
        return {"group": None, "surface": None, "surface_evidence": "",
                "surface_rule": "no surface observed in the ticket",
                "surface_ambiguity": "No surface identified where the failure is observed."
                                     + extra + " Falls back to the category routing table."}

    top, top_score = ranked[0]
    note = ""
    others = [f"{s} ({', '.join(evidence[s][:2])}, score {sc})"
              for s, sc in ranked[1:] if sc > 0]
    if others:
        note = (f"More than one surface observed: chose {top} (score {top_score}); "
                f"also {'; '.join(others)}. Routed to where the failure is observed, "
                f"not where the data lives.")
    background_only = [s for s in mentioned if s not in scored]
    if background_only:
        note += (f" Named as background only: {', '.join(background_only)}.")
    return {"group": SURFACE_TO_GROUP[top], "surface": top,
            "surface_evidence": ", ".join(evidence[top][:5]),
            "surface_rule": f"{top} -> {SURFACE_TO_GROUP[top]}",
            "surface_ambiguity": note}


CANON_GROUPS = {
    "l2 portal": "L2 - Portal", "l2-portal": "L2 - Portal", "l2 - portal": "L2 - Portal",
    "portal": "L2 - Portal", "l2 customer portal": "L2 - Portal",
    "l2 proton": "L2 - Proton", "l2-proton": "L2 - Proton", "l2 - proton": "L2 - Proton",
    "proton": "L2 - Proton",
    "l2 titan": "L2 - Titan", "l2-titan": "L2 - Titan", "l2 - titan": "L2 - Titan",
    "titan": "L2 - Titan",
}
GROUP_COLUMN_NAMES = ("assignment group", "assignment_group", "assigned group",
                      "assignmentgroup", "group", "support group")

# Which JIRA project a group's work lands in -- used to scope the defect search.
GROUP_JIRA_PROJECT = {
    "L2 - Titan": "TTN",
    "L2 - Portal": None,   # portal work is spread across CP/CEN and others; leave unscoped
    "L2 - Proton": None,
}


def canon_group(value):
    """Normalise a supplied group label. Returns (canonical, was_recognised).

    Real exports write 'L2-Titan Support', 'L2 - Portal Support', 'L2-Proton
    Support'. Strip the trailing team word before matching, otherwise every row
    reads as an unrecognised group.
    """
    v = re.sub(r"\s+", " ", str(value or "").strip())
    if not v or v.lower() in ("nan", "none", "-"):
        return None, False
    key = re.sub(r"\s*(support|team|group|queue)\s*$", "", v, flags=re.I).strip()
    hit = CANON_GROUPS.get(key.lower())
    return (hit, True) if hit else (v, False)


def load_learned_groups(ref_dir=REF):
    """category -> group, learned from 623 resolved tickets. Empty dict if absent."""
    p = Path(ref_dir) / "group-by-category.csv"
    if not p.exists():
        return {}
    return {r["Category"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}


def load_rc_priors(ref_dir=REF):
    p = Path(ref_dir) / "root-cause-priors.csv"
    if not p.exists():
        return {}
    return {r["Category"]: r for r in csv.DictReader(open(p, encoding="utf-8"))}


# XC splits by sub-type, per the service owner:
#   telephony / OOMA / DID -> L2 - Proton
#   parking                -> L2 - Portal first, rerouted if needed
XC_PROTON = ["ooma", "did", "did number", "telephony", "telephone", "phone line",
             "extension", "extn", "voice", "cerebro"]
XC_PORTAL = ["parking", "parking space", "parking allocation", "parking permit",
             "parking bay", "car park", "car parking", "parking charge"]


def xc_subtype_group(short_desc, description):
    """Return (group, reason) for an XC ticket, or (None, '') if undecidable."""
    t = f"{strip_pipe_prefix(short_desc or '')} {description or ''}".lower()
    park = [k for k in XC_PORTAL if _matches(k, t)]
    tele = [k for k in XC_PROTON if _matches(k, t)]
    if park and not tele:
        return "L2 - Portal", f"XC sub-rule: parking ({', '.join(park[:3])}) goes to Portal first."
    if tele and not park:
        return "L2 - Proton", f"XC sub-rule: telephony/OOMA/DID ({', '.join(tele[:3])}) goes to Proton."
    if park and tele:
        return "L2 - Proton", (f"XC ticket mentions both parking ({park[0]}) and telephony "
                               f"({tele[0]}). Defaulted to Proton - confirm.")
    # Residual XC -- scanned pages, TeamHub services, credit requests and the
    # like. Measured: these went to Portal, not Proton. Only telephony belongs
    # to Proton, so defaulting the remainder to Proton cost 20 errors on the
    # 377 new-process tickets.
    return "L2 - Portal", ("XC ticket with no telephony or parking signal. Residual XC "
                           "services route to Portal; only telephony/OOMA/DID goes to Proton.")


def final_group(supplied, category, short_desc, description, learned, groups, signals):
    """THE group to use. If the sheet supplies one, that IS the answer.

    Measured against a human-reviewed batch of 24: every one of my 8 routing
    errors came from overriding a populated Assignment group. Keeping the sheet
    value verbatim scored 24/24; my learned table plus JIRA-evidence overrides
    scored 16/24. The sheet is not a hint to be second-guessed -- L1 has context
    the ticket text does not carry.

    The learned table is for BLANK cells only. Disagreements are still reported,
    but as information, never as a change.
    """
    sup, recognised = canon_group(supplied)
    if sup:
        rule = route_group_learned(category, short_desc, description, learned, groups, signals)
        # The ONLY sanctioned override: the service owner's explicit rule that
        # Login belongs to Proton. Measured, this is the one override that helped
        # (INC0767607). Every other override I attempted made routing worse, so
        # the exception is deliberately this narrow -- do not widen it without
        # measuring against a reviewed batch.
        if category == "Login" and sup != "L2 - Proton":
            return {"group": "L2 - Proton", "source": "owner rule: Login -> Proton (overrides sheet)",
                    "rule_said": rule["group"],
                    "note": f"Sheet said {sup}. Login category routes to Proton by standing rule."}
        # Second sanctioned override, added after the 14 Aug scorecard: OOMA and
        # DID tickets go to Proton even when the sheet says Portal. The reviewer
        # flipped both (INC0767819, INC0767855) from a populated Portal cell.
        # Deliberately NOT all telephony -- a Callstream ticket in the same batch
        # (INC0767995) was accepted as Portal, so the rule is scoped to the two
        # products named, not to the concept.
        if sup != "L2 - Proton" and _ooma_or_did(short_desc, description):
            return {"group": "L2 - Proton",
                    "source": "owner rule: OOMA/DID -> Proton (overrides sheet)",
                    "rule_said": rule["group"],
                    "note": f"Sheet said {sup}. OOMA and DID route to Proton by standing rule."}
        # Third sanctioned override. The owner's 13 Aug rule was "any mismatch
        # related to invoices and payment is SOA category AND Titan group" -- I
        # only built the category half, so INC0765337 (payment posted in D365,
        # missing from MyRegus) sat on the sheet's Portal and was corrected to
        # Titan on the 17 Aug scorecard. The rule was always a routing rule too.
        if category == "SOA" and sup != "L2 - Titan":
            return {"group": "L2 - Titan",
                    "source": "owner rule: SOA -> Titan (overrides sheet)",
                    "rule_said": rule["group"],
                    "note": f"Sheet said {sup}. Invoice/payment mismatch is SOA and routes to Titan."}
        return {"group": sup, "source": "sheet (authoritative)" if recognised
                                        else "sheet (unrecognised label)",
                "rule_said": rule["group"],
                "note": "" if rule["group"] == sup else
                        f"Learned rule would say {rule['group']} ({rule['basis']}). "
                        f"Sheet kept -- overriding it measured worse (8 of 10 overrides were wrong)."}
    rule = route_group_learned(category, short_desc, description, learned, groups, signals)
    return {"group": rule["group"], "source": f"inferred, sheet blank ({rule['basis']})",
            "rule_said": rule["group"], "note": ""}


OOMA_DID_TERMS = ("ooma", "did number", "did numbers", "wrong did", "incorrect did",
                  "did on profile", "did number on profile", "issues with did")


def _ooma_or_did(short_desc, description):
    """Is OOMA or a DID number the SUBJECT of the ticket?

    Read the short description first and the body only as backup, for the same
    reason category classification does: a body mention is often background.
    """
    sd = strip_pipe_prefix(short_desc or "").lower()
    if any(_matches(t, sd) for t in OOMA_DID_TERMS):
        return True
    body = f"{sd} {(description or '').lower()}"
    return any(_matches(t, body) for t in OOMA_DID_TERMS)


def route_group_learned(category, short_desc, description, learned, groups, signals):
    """Category-first routing, learned from resolved tickets, with surface tie-break.

    Chosen because it measures far better than the surface rule alone: 80.3%
    against 623 resolved tickets versus 48.4%. The surface rule remains the
    tie-break for categories that genuinely split, and the fallback for
    categories with no training evidence.
    """
    row = learned.get(category)
    if row:
        if category == "XC (Product and Services)":
            g, why = xc_subtype_group(short_desc, description)
            if g:
                return {"group": g, "basis": "learned table + XC sub-rule",
                        "purity": row["Purity"], "reason": why}
        if row.get("Use surface tie-break?") == "yes":
            sg = surface_group(short_desc, description, category=category)
            if sg["group"]:
                return {"group": sg["group"], "basis": "surface tie-break (category splits)",
                        "purity": row["Purity"],
                        "reason": f"Category {category} splits {row['Distribution']}; "
                                  f"surface says {sg['surface']}."}
        return {"group": row["Primary group"], "basis": "learned category table",
                "purity": row["Purity"],
                "reason": f"{row['Distribution']} across {row['Samples']} resolved tickets."}
    sg = surface_group(short_desc, description, category=category)
    if sg["group"]:
        return {"group": sg["group"], "basis": "surface rule (no training evidence)",
                "purity": "", "reason": sg["surface_rule"]}
    s = suggest_group(f"{strip_pipe_prefix(short_desc)} {description}", category, groups, signals)
    return {"group": s["group"], "basis": "groups.csv fallback", "purity": "",
            "reason": s["group_reason"]}


def suggest_root_cause_learned(short_desc, description, root_causes, category,
                               priors, jira_detail=""):
    """Root cause suggestion informed by what was actually chosen historically.

    Measured honestly on a 30% holdout of the 623 resolved tickets:
      always 'Data Corruption'      31.5%
      majority per category         42.4%
      naive bayes on description    42.9%
      my original conservative rule 12.2%

    ~43% is the ceiling from text alone, because the label reflects what the
    investigation found, not what the customer wrote. So this returns a
    suggestion with its evidence and the runner-up, and is explicit that an
    agent must confirm it. Signal evidence beats the category prior; the prior
    is the starting point, not the answer.
    """
    sig = suggest_root_cause(short_desc, description, root_causes, jira_detail)
    row = priors.get(category)
    prior_rc = row["Most common root cause"] if row else None
    prior_share = float(row["Share"]) if row else 0.0

    # Only JIRA-backed evidence overrides the category prior. Measured on the
    # holdout, ticket-wording signals alone are WORSE than the prior, so letting
    # them win dropped accuracy from 42% to 33%. Wording is kept as a runner-up.
    if sig["confidence"] == "High":
        out, basis = sig["root_cause"], "signal evidence (JIRA-backed)"
    elif prior_rc:
        out, basis = prior_rc, f"category prior ({row['Share']} of {row['Samples']} resolved {category} tickets)"
    else:
        out, basis = sig["root_cause"], "no evidence and no prior"

    alts = [x for x in ([sig["root_cause"]] if sig["root_cause"] != out else []) +
            ([prior_rc] if prior_rc and prior_rc != out else []) + sig["alternatives"]
            if x and x != out]
    conf = ("Medium" if sig["confidence"] in ("High", "Medium")
            else "Low" if prior_share >= 0.4 else "Very low")
    return {"root_cause": out, "confidence": conf, "basis": basis,
            "evidence": sig["evidence"], "alternatives": list(dict.fromkeys(alts))[:3],
            "prior_for_category": f"{prior_rc} ({row['Share']})" if row else "none",
            "caveat": "Root cause is only ~43% predictable from ticket text - confirm before saving."}


def route_group(supplied, short_desc, description, category, groups, signals):
    """Final group for a ticket. The sheet wins; disagreements are flagged.

    Agreed policy: the Assignment group on the uploaded sheet is authoritative
    and is never overwritten. The surface rule still runs on every row, and any
    disagreement is reported for review so mis-routed tickets are visible.
    """
    sup, recognised = canon_group(supplied)
    rule = surface_group(short_desc, description, category=category)

    if sup:
        mismatch = ""
        if rule["group"] and rule["group"] != sup:
            mismatch = (f"Sheet says {sup}; surface rule says {rule['group']} "
                        f"[{rule['surface']}: {rule['surface_evidence']}]. "
                        f"Kept {sup} as supplied.")
        return {
            "group": sup,
            "group_source": "sheet (authoritative)" if recognised
                            else "sheet (unrecognised label)",
            "rule_group": rule["group"] or "",
            "surface": rule["surface"] or "",
            "surface_evidence": rule["surface_evidence"],
            "surface_rule": rule["surface_rule"],
            "group_mismatch": mismatch,
            "surface_ambiguity": rule["surface_ambiguity"],
            "jira_project": GROUP_JIRA_PROJECT.get(sup),
            "unrecognised_note": "" if recognised else
                f"'{supplied}' is not one of L2 - Portal / L2 - Proton / L2 - Titan.",
        }

    # column missing or blank -- fall back to the rule, then the category table
    if rule["group"]:
        return {"group": rule["group"], "group_source": "surface rule (sheet blank)",
                "rule_group": rule["group"], "surface": rule["surface"],
                "surface_evidence": rule["surface_evidence"],
                "surface_rule": rule["surface_rule"], "group_mismatch": "",
                "surface_ambiguity": rule["surface_ambiguity"],
                "jira_project": GROUP_JIRA_PROJECT.get(rule["group"]),
                "unrecognised_note": ""}
    s = suggest_group(f"{strip_pipe_prefix(short_desc)} {description}", category, groups, signals)
    return {"group": s["group"], "group_source": "category table (no surface, sheet blank)",
            "rule_group": "", "surface": "", "surface_evidence": "",
            "surface_rule": rule["surface_rule"], "group_mismatch": "",
            "surface_ambiguity": rule["surface_ambiguity"],
            "jira_project": GROUP_JIRA_PROJECT.get(s["group"]), "unrecognised_note": ""}


def resolve_group(supplied, category, groups, signals, text=""):
    """The export's Assignment group is authoritative -- take it as given.

    Agreed policy: the group on the uploaded sheet is already correct, so it is
    never second-guessed and no conflict is raised against it. The category-based
    suggestion is kept only as a fallback for rows where the column is missing,
    blank, or holds a label outside the three known groups.
    """
    grp, recognised = canon_group(supplied)
    if grp and recognised:
        return {"group": grp, "group_source": "export (authoritative)",
                "group_confidence": "Given", "group_reason": "",
                "group_conflict": "", "jira_project": GROUP_JIRA_PROJECT.get(grp)}
    if grp and not recognised:
        return {"group": grp, "group_source": "export (unrecognised label)",
                "group_confidence": "Given",
                "group_reason": f"'{supplied}' is not one of L2 - Portal / L2 - Proton / L2 - Titan. "
                                f"Used as supplied; confirm it is a real group.",
                "group_conflict": "", "jira_project": None}
    s = suggest_group(text, category, groups, signals)
    return {"group": s["group"], "group_source": "inferred (column blank)",
            "group_confidence": s["group_confidence"], "group_reason": s["group_reason"],
            "group_conflict": s["group_conflict"],
            "jira_project": GROUP_JIRA_PROJECT.get(s["group"])}


def find_group_column(columns):
    for c in columns:
        if str(c).strip().lower() in GROUP_COLUMN_NAMES:
            return c
    return None


def suggest_group(text, category, groups, signals):
    """Suggest an assignment group: L2 - Portal, L2 - Proton, or L2 - Titan.

    Two independent inputs, deliberately kept separate:
      1. The category's routing default from groups.csv (structural).
      2. System-name signals in the ticket text (evidential).

    When the text points somewhere other than the category default, that is
    reported as a conflict rather than silently resolved -- a portal-worded
    ticket whose cause is a Titan database record is exactly the case a human
    should route.
    """
    t = (text or "").lower()
    hits, scores = {}, {}
    for grp, weight, kw in signals:
        if _matches(kw, t):
            hits.setdefault(grp, []).append(f"{kw}(w{weight})")
            scores[grp] = max(scores.get(grp, 0), weight)

    row = groups.get(category)
    default = row["Primary group"] if row else "NEEDS CONFIRMATION"
    secondary = (row or {}).get("Secondary group", "")
    conf = (row or {}).get("Confidence", "Low")
    why = (row or {}).get("Rationale", "No routing rule for this category.")

    # rank by strongest signal weight, then by number of matches
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], -len(hits[kv[0]])))
    text_pick, text_weight = (ranked[0][0], ranked[0][1]) if ranked else (None, 0)

    # Only weight >= 2 may contradict the category default. Weight-1 terms are
    # boilerplate ("MyRegus", "portal") that appear on nearly every ticket.
    conflict = ""
    if (text_pick and text_weight >= 2 and default not in ("NEEDS CONFIRMATION", "")
            and text_pick != default):
        conflict = (f"Category default is {default}, but the ticket text points at "
                    f"{text_pick} [{', '.join(hits[text_pick][:4])}]. Human routing call.")
    if default in ("NEEDS CONFIRMATION", "") and text_pick and text_weight >= 2:
        default, conf = text_pick, "Low"
        why = f"No category rule; inferred from text signals: {', '.join(hits[text_pick][:4])}."

    return {
        "group": default,
        "secondary_group": secondary,
        "group_confidence": conf,
        "group_reason": why,
        "group_text_signals": {g: v[:4] for g, v in hits.items()},
        "group_conflict": conflict,
    }


def _split(field):
    return [k.strip().lower() for k in (field or "").split(";") if k.strip()]


def _kw_pattern(keyword):
    """Word-boundary pattern that tolerates punctuation between words.

    Real tickets write "an error has occurred, please try again later" and
    "something went wrong. please try again later" for the same phrase. Exact
    matching missed the comma variant and lost a master's own ticket.
    """
    parts = [re.escape(p) for p in keyword.split()]
    body = r"[\s,;:.\-–—]+".join(parts) if len(parts) > 1 else parts[0]
    return r"(?<!\w)" + body + r"(?!\w)"


def _matches(keyword, text):
    """Word-boundary match. Handles keywords containing regex metacharacters
    such as ( ) [ ] & / - which appear in real category names."""
    return re.search(_kw_pattern(keyword), text) is not None


# Phrases that mark a symptom as RULED OUT by the agent's own troubleshooting.
# Support descriptions routinely list what was checked and found fine, e.g.
# "Checked one affected customer for a Statement of Account or balance mismatch
# issue; no mismatch found." Matching that text put a ticket under
# [SOA] Balance Mismatch and wrongly tagged it ChildTicket.
RULED_OUT = ["no mismatch", "no balance mismatch", "ruled out", "not found",
             "no issue found", "no issues found", "did not find", "nothing found",
             "no error found", "no errors found", "not related to", "confirmed no",
             "no problem found", "was not the cause", "is not the cause",
             "no discrepancy", "none found", "no such", "not the issue",
             # A component named as WORKING is not the fault either. A printer
             # ticket said "print jobs send successfully, WorldKey PIN
             # authentication works ... but nothing prints" and was classified
             # Login off the word that proves login was fine.
             "authentication works", "authentication is working", "login works",
             "login is working", "logs in successfully", "confirmed successful",
             "sent successfully", "send successfully", "works fine",
             "working correctly", "working as expected", "listed correctly",
             "correct and up to date", "no setup errors"]


def _matches_not_ruled_out(keyword, text, window=60):
    """True only for occurrences that are not inside a ruled-out statement."""
    found = False
    for m in re.finditer(_kw_pattern(keyword), text):
        lo, hi = max(0, m.start() - window), min(len(text), m.end() + window)
        if not any(p in text[lo:hi] for p in RULED_OUT):
            found = True
    return found


def classify_category(text, cats):
    """Return (category, matched_keyword). 'Unclassified' when nothing matches.

    Uses the same ruled-out guard as master matching. The two used to differ --
    masters ignored "no mismatch found" while categories did not -- which meant a
    phrase that could not win a master could still win a category. There is no
    reason for the layers to disagree about what counts as evidence.
    """
    t = (text or "").lower()
    for c in cats:
        for kw in _split(c.get("Match keywords")):
            if _matches_not_ruled_out(kw, t):
                return c["Category"], kw
    return "Unclassified", None


def match_master(text, masters):
    """Return (master_row, confidence, matched_keywords, runners_up).

    Deliberately NOT filtered by a keyword-derived category. A ticket's wording
    often points at a different category than the one the master is registered
    under -- e.g. "verification code via mobile phone" reads as Mobile, but the
    master lives under Login. Filtering by derived category hides the correct
    master. The registry's category is authoritative; see triage_ticket.

    Confidence is a keyword-count heuristic only -- a shortlist, not a verdict.
    Judge the symptom before applying a master name.
    """
    t = (text or "").lower()
    scored = []
    for m in masters:
        if m.get("Master ID", "").startswith("EXAMPLE"):
            continue
        # A master may require context: at least one of these terms must also
        # appear. Needed because some symptom keywords are generic strings that
        # occur all over the product -- "something went wrong. please try again
        # later" matched a call-handling ticket and an event-space booking to a
        # LOGIN master. Tightening the phrase instead broke the master's own
        # real tickets, so the generic keyword stays and the context gates it.
        ctx = _split(m.get("Context required"))
        if ctx and not any(_matches(c, t) for c in ctx):
            continue
        hits = [kw for kw in _split(m.get("Symptom keywords"))
                if _matches_not_ruled_out(kw, t)]
        if hits:
            scored.append((m, hits))
    if not scored:
        return None, "No match", [], []
    scored.sort(key=lambda x: -len(x[1]))
    m, hits = scored[0]
    tied = [s for s in scored[1:] if len(s[1]) == len(hits)]
    if tied:
        conf = "Low"          # ambiguous between masters -- needs a human
    elif len(hits) >= 2:
        conf = "High"
    else:
        conf = "Medium"
    return m, conf, hits, [(s[0]["Master Name"], s[1]) for s in scored[1:4]]


def build_tags(category, master_name, category_source="master", mst_tag=None):
    """Return (tags, blocker) for a triaged ticket.

    A child ticket carries FOUR tags, not three:
      1. TriagedTicket  -- every ticket that has been triaged
      2. ChildTicket    -- only when the ticket sits under a master
      3. MST-xxxxx      -- the master's own tag, when it has one
      4. <Category>     -- the category name, verbatim

    The fourth was learned from 623 resolved tickets: 190 carried both
    ChildTicket and an MST tag, and **zero** carried an MST tag without
    ChildTicket. The two travel together, so emitting ChildTicket without the
    master's MST tag leaves the ticket half-linked.

    A ticket with no category cannot be fully tagged, so it comes back with a
    blocker rather than an invented category.
    """
    tags = ["TriagedTicket"]
    blocker = None
    if master_name:
        tags.append("ChildTicket")
        if mst_tag:
            tags.append(mst_tag.strip())
        else:
            blocker = (f"Master '{master_name}' has no MST tag in the registry. "
                       f"ChildTicket applied without a master reference -- needs a tag.")
    if category and category != "Unclassified":
        tags.append(category)          # verbatim, spaces and parentheses intact
    else:
        msg = "No category -- cannot apply the category tag. Needs a category decision."
        blocker = f"{blocker} {msg}".strip() if blocker else msg
    return tags, blocker


def triage_ticket(text, cats, masters, kbas, kba_index=None):
    """Master-first triage of one ticket.

    Order matters: match the master, then take the category FROM the matched
    master. Keyword classification is only a fallback for tickets that match no
    master, and its result is a proposal, not an assignment.
    """
    master, conf, hits, runners = match_master(text, masters)
    if master is not None:
        category = master["Category"]        # registry is authoritative
        source = "master"
    else:
        category, kw = classify_category(text, cats)
        source = "keyword" if category != "Unclassified" else "none"
    return {
        "category": category,
        "category_source": source,
        "master": master["Master Name"] if master else None,
        "master_id": master["Master ID"] if master else None,
        "confidence": conf,
        "matched_keywords": hits,
        "runners_up": runners,
        # search on the ticket's own words, not the master's -- the ticket may
        # need an article the master as a whole doesn't point to
        "kbas": find_kbas(category, master["Master Name"] if master else None,
                          kbas, index=kba_index, query=text),
    }


def pipe_hint(short_desc, cats):
    """ServiceNow short descriptions often arrive as
    'Customer Portal | Accounts and Companies | Account inactive in Myregus'.
    The middle segment is the agent's own category hint -- worth using as a
    cross-check, though it is free text and may not match the list exactly.

    Returns (raw_hint, resolved_category_or_None).
    """
    if not is_pipe_structured(short_desc):
        return None, None
    parts = [p.strip() for p in (short_desc or "").split("|")]
    if len(parts) < 2:
        return None, None
    raw = parts[1]
    # A hint is a short label. 'Interface/Integration Issue/Please mark invoices
    # as PAID as they are already allocated in DYN' is a sentence that happened
    # to sit after a single pipe -- not a category, and matching it loosely
    # produces nonsense. Anything over five words is not a label.
    if len(raw.split()) > 5:
        return raw, None
    # An EMPTY hint must resolve to nothing. A free-form ticket truncated at a
    # trailing pipe ('... Type of Ticket: Customer |') yielded raw == '', and an
    # empty string prefix-matches every category name, so it silently resolved
    # to CSU. Empty is absence of evidence, not evidence.
    if not raw:
        return None, None
    names = {c["Category"].lower(): c["Category"] for c in cats}
    r = raw.lower().strip()
    if r in names:
        return raw, names[r]
    # Tolerate "Invoicing Issue" -> "Invoicing". Where several categories share
    # the prefix, take the CLOSEST in length, not the first tested: a bare
    # "Bookings" hint means the generic "Bookings (Products)", not the more
    # specific "Bookings (Products) - Short Stay", which precedence tests first.
    pref = [(abs(len(low) - len(r)), proper) for low, proper in names.items()
            if r.startswith(low) or low.startswith(r)]
    if pref:
        return raw, min(pref)[1]
    # Tolerate inflections only: "Invoices" -> "Invoicing" shares the stem
    # "invoic" with 2- and 3-character tails. A long shared prefix is not
    # enough on its own -- "ServiceNow Support" and "Services" share 7
    # characters yet ServiceNow is a product, not the Services category.
    for low, proper in names.items():
        n = min(len(r), len(low))
        common = 0
        while common < n and r[common] == low[common]:
            common += 1
        if common >= 6 and len(r) - common <= 3 and len(low) - common <= 3:
            return raw, proper
    # Loose token overlap only -- and only when it shares a real word. Without
    # this guard 'ServiceNow Support' resolved to an unrelated category.
    r_tok = set(_tokens(raw))
    best, best_n = None, 0
    for low, proper in names.items():
        n = len(r_tok & set(_tokens(low)))
        if n > best_n:
            best, best_n = proper, n
    return raw, (best if best_n >= 1 else None)


TRAILING_CLAUSE = re.compile(
    r"\s+(?:due to|because of|caused by|as a result of|resulting in)\b.*$", re.I)
LEADING_FILLER = re.compile(
    r"^(?:(?:kindly|please)\s+"
    r"(?:check|help|helps?|assist|investigate|advise|review|confirm|look\s+into)"
    r"(?:\s+(?:us|me|him|her|them|the\s+\w+))?"
    r"(?:\s+(?:to|why|if|whether|and\s+advise))?\s*"
    r"|issue\s*[-:]\s*|request\s*[-:]\s*|(?:kindly|please)\s+|why\s+)+", re.I)
# 'Company ID-13957405', 'Ac - 15847755', 'Account ID: 14073052'
LABELLED_ID = re.compile(
    r"\b(?:company|account|acct|ac|customer|booking|centre|center|invoice)\s*"
    r"(?:id|ref|reference|no|number|#)?\s*[-:#]?\s*\d{4,}\b", re.I)
TAIL_NOISE = re.compile(
    r"\s+(?:for\s+(?:the\s+)?(?:customer|client|user|centre|center)|"
    r"on\s+(?:the\s+)?(?:customer|client)'?s?\s+(?:behalf|account))\s*$", re.I)
ID_NOISE = re.compile(r"\b(?:\d{6,}|[\w.+-]+@[\w.-]+\.\w+)\b")
# Tickets pasted straight out of email open with a greeting and then a block of
# labelled fields before the actual symptom. Left in, the drafted name came out
# as 'Hello Team, - Nenad Radulovic 6-digits: 4-digits: 3442 Customer', which is
# not a description of anything.
SALUTATION = re.compile(
    r"^\s*(?:hi|hello|hey|dear|good\s+(?:morning|afternoon|evening))\b"
    r"[\s,!.]*(?:team|all|support|there|folks)?[\s,!.:-]*", re.I)
FIELD_LABELS = re.compile(
    r"\b(?:company\s+name|account\s+number|centre\s+name|center\s+name|"
    r"centre\s+number|center\s+number|type\s+of\s+ticket|type\s+of\s+request|"
    r"\d+-digits|logged-?in\s+email|cc\s+details|description)\s*:\s*", re.I)


def propose_master_name(short_desc, category, max_words=9):
    """Draft a master name for a ticket with no matching master.

    Format: [Category] Short description -- per naming-convention.md.

    ServiceNow short descriptions arrive as
    'Customer Portal | Invoicing Issue | Unable to change invoice billing
    frequency due to something went wrong'. The useful part is the last pipe
    segment; the leading segments are app and category prefixes that the
    [Category] tag already carries.

    This is a mechanical draft, not a final answer -- read it and refine the
    wording to the symptom before proposing it. Returns (name, draft_desc).
    """
    text = (short_desc or "").strip()
    if "|" in text:
        text = text.split("|")[-1].strip()

    # Some short descriptions are ALREADY in master-convention form, e.g.
    # "[Bookings (Products) - Short Stay] Issue with meeting room booking
    # reference". Prepending a category to that produces a doubled prefix.
    text = re.sub(r"^\s*\[[^\]]+\]\s*", "", text)
    text = SALUTATION.sub("", text)
    text = FIELD_LABELS.sub("", text)
    text = LABELLED_ID.sub("", text)      # before ID_NOISE, so no orphan "Company ID-"
    text = LEADING_FILLER.sub("", text)
    text = TRAILING_CLAUSE.sub("", text)
    text = TAIL_NOISE.sub("", text)
    text = ID_NOISE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -:,.")
    text = LEADING_FILLER.sub("", text).strip(" -:,.")
    # a dangling preposition left by filler removal: "On the parking allocation"
    text = re.sub(r"^(?:on|about|regarding|re|concerning|with|of|that)\s+(?:the\s+)?",
                  "", text, flags=re.I).strip(" -:,.")

    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])

    if text:
        text = text[0].upper() + text[1:]
    else:
        text = "Unspecified issue - needs manual description"

    cat = category if category and category != "Unclassified" else "UNCATEGORISED"
    return f"[{cat}] {text}", text


def build_master_index(masters):
    """Token index over masters, for near-miss candidates when keyword matching
    finds nothing. Prevents proposing a brand-new master when an existing one is
    a keyword gap away -- e.g. 'account is inactive' vs the registered
    '[Login] Account needs activation'."""
    shim = []
    for m in masters:
        if m.get("Master ID", "").startswith("EXAMPLE"):
            continue
        shim.append({
            "KB Number": m["Master ID"],
            "Title": re.sub(r"^\[[^\]]+\]\s*", "", m["Master Name"]),
            "Search text": m.get("Symptom keywords", "").replace(";", " "),
            "Audience": m["Category"],
            "_master": m,
        })
    return build_kba_index(shim)


def master_candidates(text, master_index, top_n=3, min_score=4.0):
    hits = search_kbas(text, master_index, top_n=top_n, min_score=min_score)
    return [(h[0]["_master"], h[1], h[2]) for h in hits]


TROUBLESHOOTING_BLOCK = re.compile(
    r"(?is)\btroubleshoot(?:ing|ed)\s*(?:attempted|performed|done|steps|so\s+far)?\s*:"
    r".*?(?=\n\s*(?:issue\s+start\s+time|expected\s+(?:result|behaviour|behavior)|"
    r"additional\s+(?:details|context|information|notes)|impact|error|issue|request|"
    r"action\s+requested|steps\s+to\s+reproduce|company\s+id|account\s+(?:id|number|name)|"
    r"cent(?:re|er)\s+(?:number|name)|team\s+hub\s+version)\s*:|\Z)")

FORM_FIELD_LINE = re.compile(
    r"(?im)^\s*\d*\.?\s*(?:company\s+id|account\s+(?:id|number)|cent(?:re|er)\s+(?:number|name)|"
    r"booking\s+reference(?:\s+number)?|team\s+hub\s+version|logged-?in\s+email|"
    r"email\s+address|type\s+of\s+(?:ticket|request))\s*:.*$")


def symptom_body(description):
    """The part of the body that describes the FAULT.

    Two sections actively mislead a keyword matcher and are removed:

    'Troubleshooting attempted:' lists what the agent checked and found FINE.
    Reading a symptom out of it inverts the meaning. Two real cases in one
    batch: 'Checked the customer portal for balance mismatch' matched the
    ticket to the [SOA] Balance Mismatch master when the ticket was about
    undelivered invoice emails, and 'Confirmed successful WorldKey login'
    classified a printer fault as Login -- the ticket says authentication
    works and nothing prints.

    Form-field lines ('Booking reference number: 170274728') are metadata, not
    symptom. One classified a TeamHub renewal error as Bookings (Products)
    purely because the template asks for a booking reference.
    """
    t = description or ""
    t = TROUBLESHOOTING_BLOCK.sub(" \n", t)
    t = FORM_FIELD_LINE.sub(" ", t)
    return t


def triage_row(short_desc, description, cats, masters, kbas,
               kba_index=None, master_index=None):
    """Triage one ticket row, weighting the short description over the body.

    The description body carries incidental words -- troubleshooting notes,
    environment details -- that hijack matching. One real ticket about failing
    to upload a TDS document was classified 'Mobile' purely because the body
    said 'Updated mobile app also'. So: match on the short description first,
    and only widen to the body if that yields nothing -- and when we do widen,
    read only the part of the body that describes the fault (see symptom_body).
    """
    short_desc = short_desc or ""
    description = description or ""
    description = symptom_body(description)
    full = f"{short_desc} {description}"

    master, conf, hits, runners = match_master(short_desc, masters)
    match_scope = "short description"
    if master is None:
        master, conf, hits, runners = match_master(full, masters)
        match_scope = "description body" if master is not None else "none"
        if master is not None and conf == "High":
            conf = "Medium"   # body-only evidence is weaker than a title match

    raw_hint, hint_cat = pipe_hint(short_desc, cats)

    if master is not None:
        # A confirmed master still wins: its name embeds a category in brackets,
        # so overriding it with the hint would make the master name contradict
        # the ticket's own category tag. Disagreement is reported, not resolved.
        category, source = master["Category"], "master"
    else:
        # SYMPTOM FIRST, hint only as fallback. Measured against a human-reviewed
        # batch: hint-first scored 71%, symptom-first 83%. Agents write the broad
        # AREA ("Accounts & Companies") while the ticket is a narrower ISSUE
        # ("error submitting renewal team request" -> Renewals). The hint is a
        # reasonable last resort, not a better signal.
        # Classify on the STRIPPED short description. The leading pipe segments
        # are the agent's area label, not symptom text -- leaving them in made
        # "Customer Portal | Accounts and Companies | Account inactive" classify
        # as Accounts and Companies when the symptom is a Login issue.
        sym_text = strip_pipe_prefix(short_desc)
        category, kw = classify_category(sym_text, cats)
        source = "symptom (short description)"
        if category == "Unclassified":
            category, kw = classify_category(f"{sym_text} {description}", cats)
            source = "symptom (description body)"
        if category == "Unclassified" and hint_cat:
            category, source = hint_cat, "pipe hint (fallback - symptom unclassifiable)"
        elif category == "Unclassified":
            source = "none"

    # Owner rule: booking issues split by the surface they surface on.
    #   TeamHub        -> Bookings (Products)
    #   Customer Portal -> Bookings (Products) - Short Stay
    # Direction-aware, so a system named as WORKING ("available on My Regus but
    # not on the Regus site") does not claim the ticket.
    if category in ("Bookings (Products)", "Bookings (Products) - Short Stay"):
        # For THIS rule the leading app label is the signal, so unlike routing we
        # look at the whole short description, prefix included. TeamHub wins when
        # both are named (a booking checked in TeamHub is a TeamHub booking).
        whole = f"{short_desc} {description}".lower()
        first_seg = str(short_desc or "").split("|")[0].lower()
        th = any(_matches(k, whole) for k in ("teamhub", "team hub"))
        cp_label = any(_matches(k, first_seg) for k in
                       ("customer portal", "myregus", "my regus", "cp"))
        # A portal named as WORKING must not claim the ticket:
        # "available on My Regus but not on the Regus site" is not a portal fault.
        sg = surface_group(short_desc, description, category=None)
        cp_failing = sg.get("surface") == "Customer Portal"
        if th:
            category, source = "Bookings (Products)", source + " + owner rule (TeamHub booking)"
        elif cp_label or cp_failing:
            category, source = ("Bookings (Products) - Short Stay",
                                source + " + owner rule (Customer Portal booking)")

    hint_agrees = (hint_cat == category) if hint_cat else None

    assign = conf in ("High", "Medium")
    mst = (master or {}).get("MST Tag") if assign else None
    tags, blocker = build_tags(category,
                               master["Master Name"] if (master and assign) else None,
                               source, mst_tag=mst)

    return {
        "category": category,
        "category_source": source,
        "pipe_hint": raw_hint,
        "pipe_hint_category": hint_cat,
        "pipe_hint_agrees": hint_agrees,
        "master": master["Master Name"] if master else None,
        "master_id": master["Master ID"] if master else None,
        "master_assigned": bool(master and assign),
        "match_scope": match_scope,
        "confidence": conf,
        "matched_keywords": hits,
        "runners_up": runners,
        "near_miss_masters": ([] if master else
                              master_candidates(short_desc or full, master_index)
                              if master_index else []),
        "kbas": find_kbas(category, master["Master Name"] if master else None,
                          kbas, index=kba_index, query=full),
        "tags": tags,
        "tag_blocker": blocker,
    }


def triage_ticket_tagged(text, cats, masters, kbas, kba_index=None,
                         apply_low_confidence=False):
    """triage_ticket plus the mandatory tag set.

    ChildTicket is only applied when the master is actually being assigned.
    A Low-confidence or No-match ticket has no agreed master yet, so tagging it
    ChildTicket would assert a parent relationship that nobody has approved.
    """
    r = triage_ticket(text, cats, masters, kbas, kba_index=kba_index)
    assign = r["confidence"] in ("High", "Medium") or (
        apply_low_confidence and r["confidence"] == "Low")
    master_for_tag = r["master"] if assign else None
    mst = None
    if master_for_tag:
        mst = next((m.get("MST Tag") for m in masters
                    if m["Master Name"] == master_for_tag), None)
    r["tags"], r["tag_blocker"] = build_tags(
        r["category"], master_for_tag, r["category_source"], mst_tag=mst)
    r["master_assigned"] = bool(master_for_tag)
    return r


STOP = set("""a an the and or but if of to in on for with without at by from as is are was were be
been being it its this that these those he she they them his her their you your i we our us not no
do does did done have has had having will would can could should may might must shall when while
where which who whom what why how all any both each few more most other some such only own same
than too very s t just don now customer client user please need needs able unable issue issues
error errors problem problems ticket case account myregus regus my""".split())


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP]


def build_kba_index(kbas):
    """Build an IDF-weighted token index over the KBA corpus.

    Needed because master symptom keywords are phrase-shaped ("verification code
    via email") while KBA bodies are prose ("verification code is not being
    delivered to their email"). Exact-phrase matching misses those; token
    overlap finds them.
    """
    import math
    docs = []
    df_counts = {}
    for k in kbas:
        title = k.get("Title", "")
        body = k.get("Search text", "")
        t_tok = _tokens(title)
        b_tok = _tokens(body)
        docs.append({"kba": k, "title_tokens": set(t_tok), "tokens": set(t_tok) | set(b_tok)})
        for tok in docs[-1]["tokens"]:
            df_counts[tok] = df_counts.get(tok, 0) + 1
    n = max(len(docs), 1)
    idf = {t: math.log(1 + n / c) for t, c in df_counts.items()}
    return {"docs": docs, "idf": idf}


def kba_strength(score):
    """Label a search score. Anything 'weak' should be reported as a KBA gap
    with the candidate noted -- not as a found article."""
    if score is None:
        return "mapped"
    if score >= 12:
        return "strong"
    if score >= 6:
        return "possible"
    return "weak"


def search_kbas(query, index, top_n=3, min_score=5.0):
    """Return [(kba_row, score, matched_terms)] best-first.

    Title hits are weighted 3x -- a term in the title is what the article is
    about, whereas a term in the body may be incidental.
    """
    q = set(_tokens(query))
    if not q or not index["docs"]:
        return []
    idf = index["idf"]
    out = []
    for d in index["docs"]:
        hits = q & d["tokens"]
        if not hits:
            continue
        score = sum(idf.get(t, 0) * (3 if t in d["title_tokens"] else 1) for t in hits)
        score /= (len(q) ** 0.5)
        if score >= min_score:
            out.append((d["kba"], round(score, 2),
                        sorted(hits & d["title_tokens"]) or sorted(hits)[:6]))
    out.sort(key=lambda x: -x[1])
    return out[:top_n]


KBA_REPORT_THRESHOLD = 12.0   # only "strong" reaches the output.
# Measured: of 15 articles I offered on a reviewed batch, the 13 scored
# "possible" (6-12) were ALL judged not useful. Offering that band is noise.


def find_kbas_best(category, master_name, kbas, index, short_desc, description,
                   top_n=3):
    """KBA search over BOTH the short description and the full symptom text,
    keeping each article's best score.

    The IDF overlap score is not normalised for query length, so a long query
    dilutes the right article. Measured on one batch: 'Worldkey pin is not
    working (Client)' scored 9.1 against the whole ticket and 17.9 against the
    short description alone -- the same article, the same index, one side of the
    reporting threshold and then the other. That dilution is why two batches in
    a row reported no article while the reviewer was marking 'Missed KB'.

    The reverse also happens: a free-form email pasted into ServiceNow has a
    useless title, and only the body carries the symptom. So neither query wins
    outright and running both dominates either alone.

    Ordering uses a length-normalised score (score / sqrt(query tokens)) because
    that is what makes the ranking stable across query lengths: on a hand-checked
    set of six tickets the correct article ranked 1st in 6 of 6 normalised versus
    5 of 6 raw. Reporting still thresholds on the RAW score, so the meaning of
    KBA_REPORT_THRESHOLD is unchanged and this cannot quietly widen what gets
    offered -- see BENCHMARK.md, the threshold needs owner recalibration.
    """
    import math
    sd = strip_pipe_prefix(short_desc or "")
    full = f"{sd} {symptom_body(description)}"
    best = {}
    for q in (sd, full):
        if not q.strip():
            continue
        norm = math.sqrt(max(1, len(_tokens(q))))
        for k, score, tags in (find_kbas(category, master_name, kbas, index,
                                        query=q, top_n=top_n * 3) or []):
            num = k["KB Number"]
            cand = (k, score, tags, (score or 0) / norm)
            if num not in best or cand[3] > best[num][3]:
                best[num] = cand
    out = sorted(best.values(), key=lambda x: -x[3])
    return [(k, s, t) for k, s, t, _n in out[:top_n]]


def find_kbas(category, master_name, kbas, index=None, query=None, top_n=3):
    """Registry mapping first, then token search as the fallback.

    The 'Covers master ticket' column is a curated hint; the search catches
    articles nobody has mapped yet.
    """
    mapped_nums = set()
    if master_name:
        for m_kba in kbas:
            if m_kba.get("Covers master ticket", "").strip() == master_name.strip():
                mapped_nums.add(m_kba["KB Number"])

    searched = search_kbas(query or master_name or "", index, top_n=25) if index else []
    scored = {k["KB Number"]: (k, s, t) for k, s, t in searched}

    out = []
    for num in mapped_nums:
        if num in scored:
            k, s, t = scored[num]
            out.append((k, s, t + ["mapped"]))
        else:
            k = next((x for x in kbas if x["KB Number"] == num), None)
            if k:
                out.append((k, 0.0, ["mapped, no term overlap with this ticket"]))
    # mapped articles still get ranked by relevance to THIS ticket, not by the
    # order they happen to sit in the CSV
    out.sort(key=lambda x: -(x[1] or 0))
    if out:
        return out[:top_n]
    return searched[:top_n]


if __name__ == "__main__":
    cats, masters, kbas = load_reference()
    print(f"{len(cats)} categories, "
          f"{len([m for m in masters if not m['Master ID'].startswith('EXAMPLE')])} real masters, "
          f"{len([k for k in kbas if 'Example row' not in k.get('Notes','')])} real KBAs")


def harmonise_root_causes(triaged):
    """Make tickets that share a master carry the same root cause.

    Two tickets reporting the identical issue must not end up with different
    causes just because the reporters worded them differently. One real pair --
    Bulgarian accounts present in D365 but absent from MyRegus -- came out as
    'Dependency Failure' and 'Unknown Cause' purely on phrasing.

    `triaged` is a list of dicts each carrying 'master_key', 'root_cause' and
    'rc_confidence'. Modified in place; returns the notes applied.
    """
    order = {"High": 3, "Medium": 2, "Low": 1, "n/a": 0}
    best = {}
    for t in triaged:
        k = t.get("master_key")
        if not k:
            continue
        if t["root_cause"] == "Unknown Cause":
            continue
        cur = best.get(k)
        if cur is None or order.get(t["rc_confidence"], 0) > order.get(cur[1], 0):
            best[k] = (t["root_cause"], t["rc_confidence"], t.get("ticket_id", ""))

    notes = []
    for t in triaged:
        k = t.get("master_key")
        if k in best and t["root_cause"] != best[k][0]:
            was = t["root_cause"]
            t["root_cause"], t["rc_confidence"] = best[k][0], best[k][1]
            note = (f"Harmonised from '{was}' to match the rest of "
                    f"'{k}' (best evidence on {best[k][2]}).")
            t["rc_reason"] = (t.get("rc_reason", "") + " " + note).strip()
            notes.append({"Ticket ID": t.get("ticket_id"), "Master": k,
                          "Was": was, "Now": t["root_cause"], "Why": note})
    return notes


# --- Priority (from Priority Mapping v0.2) ---------------------------------
# Priority = min(Urgency + Impact - 1, 4). NOT stated in the workbook: derived
# from the 20 worked examples across CP, Teamhub, Titan and Finance, which it
# fits exactly. The cap at 4 is what makes Finance urgency3 x impact3 = P4 work.
# Agreed with the service owner: use it, but FLAG every result as derived.
PRIORITY_MATRIX = {          # explicit grid, confirmed current by the service owner
    1: {1: "P1", 2: "P1", 3: "P2", 4: "P3"},
    2: {1: "P1", 2: "P2", 3: "P3", 4: "P4"},
    3: {1: "P2", 2: "P3", 3: "P4", 4: "P4"},
    4: {1: "P3", 2: "P4", 3: "P4", 4: "P4"},
}
# The worked examples inside Priority Mapping v0.2 disagree with this grid in 11
# of 12 cases, always one level LESS urgent. Confirmed: the grid is current and
# the examples are stale. Never re-derive a formula from those examples --
# min(U+I-1,4) was wrong in 9 of 16 cells.
PRIORITY_NOTE = "Priority from the confirmed Urgency x Impact matrix (v0.2 worked examples are stale)."

# Impact is deliberately NOT inferred. Agreed policy: the agent sets it, because
# tickets rarely state scope and guessing it silently moves priority a whole step.
# Impact scale, corrected against the worked examples in Priority Mapping v0.2.
# Impact 1 is reserved for GENERALIZED, whole-estate scope. A single centre --
# even all of its clients -- reads as impact 2 in every example. Reading
# "affecting all clients of the centre" as impact 1 produced false P1s.
IMPACT_EVIDENCE = {
    1: ["all centres", "all centers", "all users globally", "every centre", "every center",
        "system wide", "system-wide", "global outage", "generalized issue", "generalised issue",
        "all clients globally", "entire estate", "all regions"],
    2: ["multiple centres", "multiple centers", "several centres", "several centers",
        "3 centers", "3 centres", "all clients of the centre", "all clients of the center",
        "all customers of the centre", "customers of the centre", "widespread",
        "multiple customers", "multiple users", "all customers appear", "several accounts",
        "multiple invoices", "single centre", "single center", "centre-wide", "the centre"],
    3: ["few users", "few clients", "some users", "some clients", "some customers",
        "single user", "single client", "single customer", "one customer", "one client",
        "customer affected", "customer is affected", "not all users", "single bu", "vip",
        "affected customer account", "customer-related"],
    4: ["single invoice", "single booking", "single payment", "one invoice", "one booking"],
}

# P1 means the system is down or a major function is unusable. The matrix alone
# will hand out P1 for urgency 1-2 at impact 1, so a guard is required: without
# outage evidence the result is capped at P2. Agreed with the service owner.
P1_EVIDENCE = ["system is down", "system down", "outage", "unusable", "completely unavailable",
               "no workaround", "cannot be used at all", "all centres affected",
               "total failure", "service unavailable", "application is down",
               "nobody can", "no one can", "all users unable"]


def p1_allowed(short_desc, description):
    """True only when the ticket evidences an outage or an unusable major function."""
    t = f"{strip_pipe_prefix(short_desc or '')} {description or ''}".lower()
    ev = [k for k in P1_EVIDENCE if _matches(k, t)]
    return (bool(ev), ev)


def load_priority(ref_dir=REF):
    ref_dir = Path(ref_dir)
    urg = list(csv.DictReader(open(ref_dir / "priority-urgency.csv", encoding="utf-8")))
    cmap = list(csv.DictReader(open(ref_dir / "priority-category-map.csv", encoding="utf-8")))
    return urg, cmap


def priority_sheet(group, short_desc, description):
    """Which app urgency table applies. General is the fallback, not this."""
    if group == "L2 - Titan":
        return "Titan", "group is Titan"
    if group == "L2 - Proton":
        return None, "no Proton sheet in v0.2 - falls back to General"
    t = f"{strip_pipe_prefix(short_desc or '')} {description or ''}".lower()
    th = [k for k in ("teamhub", "team hub") if _matches(k, t)]
    cp = [k for k in ("customer portal", "myregus", "my regus", "client portal") if _matches(k, t)]
    if th and not cp:
        return "Teamhub", f"TeamHub surface ({th[0]})"
    if cp and not th:
        return "CP", f"Customer Portal surface ({cp[0]})"
    if th and cp:
        return "CP", f"both surfaces named ({cp[0]}, {th[0]}); defaulted to CP"
    return "CP", "no surface named; defaulted to CP for a Portal ticket"


def impact_evidence(short_desc, description):
    """Return {impact_value: [phrases found]} -- evidence only, never a decision."""
    t = f"{strip_pipe_prefix(short_desc or '')} {description or ''}".lower()
    out = {}
    for val, phrases in IMPACT_EVIDENCE.items():
        ev = [p for p in phrases if _matches(p, t)]
        if ev:
            out[val] = ev
    return out


def suggest_priority(category, group, short_desc, description, cmap):
    """Urgency from the app sheet, General as fallback, then the matrix.

    Impact stays with the agent, so this returns the priority for every impact
    value: pick the impact and read the priority straight off the row.
    """
    sheet, why = priority_sheet(group, short_desc, description)
    row = next((r for r in cmap if r["Category"] == category and r["Sheet"] == sheet
                and r["Urgency"]), None) if sheet else None
    basis = f"{sheet} sheet ({why})" if row else ""
    if not row:
        row = next((r for r in cmap if r["Category"] == category
                    and r["Sheet"] == "General" and r["Urgency"]), None)
        basis = (f"General fallback - {why}" if sheet is None
                 else f"General fallback - '{category}' has no equivalent in the {sheet} sheet")
    if not row:
        return {"sheet": "(none)", "basis": f"no urgency mapping for '{category}' in any sheet",
                "issue_type": "", "urgency": "", "priority_by_impact": {},
                "impact_evidence": impact_evidence(short_desc, description),
                "note": PRIORITY_NOTE, "flag": "MAPPING GAP"}
    u = int(row["Urgency"])
    allow_p1, p1_ev = p1_allowed(short_desc, description)
    # DEFAULT_PRIORITY: measured against a human-reviewed batch of 24 -- every
    # single ticket was P3. My matrix output said P2 nine times and blank eight
    # times, scoring 7/24. P3 is the working default; the matrix row is offered
    # as context, not as the answer.
    pbi = {}
    for i in (1, 2, 3, 4):
        p = PRIORITY_MATRIX[u][i]
        if p == "P1" and not allow_p1:
            p = "P2"          # capped: no outage / unusable-function evidence
        pbi[i] = p
    default = "P1" if allow_p1 else ("P4" if u == 4 else "P3")
    return {"sheet": row["Sheet"], "basis": basis, "issue_type": row["Issue type"], "urgency": u,
            "p1_allowed": allow_p1, "p1_evidence": ", ".join(p1_ev),
            "priority": default,
            "priority_basis": ("outage evidence -> P1" if allow_p1 else
                               "urgency 4 (consultation/request) -> P4" if u == 4 else
                               "standard default P3 (matches reviewed practice)"),
            "priority_by_impact": pbi,
            "impact_evidence": impact_evidence(short_desc, description),
            "note": PRIORITY_NOTE,
            "flag": "OK" if row["Sheet"] != "General" else "General fallback used"}


def load_tally(runs_dir="runs", sheet="Proposed Masters"):
    """Read the recurrence tally from the most recent run workbook.

    The workbook is the single source of truth -- there is deliberately no
    parallel CSV, because two copies of a running count drift apart. Each run
    reads the newest workbook that carries the sheet, adds to it, and writes the
    updated sheet into the new workbook.
    """
    import glob, os
    try:
        import pandas as pd
    except ImportError:
        return None
    files = sorted(glob.glob(os.path.join(str(runs_dir), "*.xlsx")),
                   key=os.path.getmtime, reverse=True)
    for f in files:
        if os.path.basename(f).startswith("~$"):
            continue
        try:
            if sheet in pd.ExcelFile(f).sheet_names:
                df = pd.read_excel(f, sheet_name=sheet)
                return df, f
        except Exception:
            continue
    return None
