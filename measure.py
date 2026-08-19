"""Regression harness. Run after ANY change to categories.csv, master-tickets.csv
or classify.py, and report every line -- including when a change costs nothing.

    python measure.py

Four independent ground-truth sets, in rough order of how much they should be
trusted:

  human scorecards      what the desk actually decided, on live batches
  190 MST-tagged        master matching, from the tags on resolved tickets
  377 resolved (tagged) category, from the tags on resolved tickets
  623 routing           the Assignment group the desk itself used

A change that improves a scorecard while costing the resolved sets is usually
worth taking -- the scorecards reflect current practice and the resolved set
includes older labelling. A change that costs a scorecard almost never is.
"""
import sys, os, re, glob
sys.path.insert(0, "reference")
import pandas as pd
import classify as C

U = os.environ.get("TRIAGE_UPLOADS", "/sessions/stoic-brave-cori/mnt/uploads")


def _p(name):
    return os.path.join(U, name)


cats, masters, kbas = C.load_reference()
groups, signals = C.load_groups()
L = C.load_learned_groups()
kidx, midx = C.build_kba_index(kbas), C.build_master_index(masters)
names = {c["Category"] for c in cats}


def tagcat(t):
    """The category recorded in a resolved ticket's Tags column, if any."""
    if not isinstance(t, str):
        return None
    for p in [x.strip() for x in t.split(",")]:
        if p in names:
            return p
        for n in names:
            if p.replace(" ", "").lower() == n.replace(" ", "").lower():
                return n
    return None


def cat_of(row):
    return C.triage_row(row["Short description"], row.get("Description"),
                        cats, masters, kbas, kidx, midx)


print(f"{len(cats)} categories, {len(masters)} masters, {len(kbas)} KBAs\n")
res = pd.read_excel(_p("resolved and closed for training.xlsx"))

# ---- category on the tagged resolved tickets
ok = tot = 0
for _, r in res.iterrows():
    truth = tagcat(r.get("Tags"))
    if not truth:
        continue
    tot += 1
    ok += cat_of(r)["category"] == truth
print(f"  377 resolved, category      : {ok}/{tot} = {100*ok/tot:.1f}%")

# ---- master matching on the MST-tagged resolved tickets
tag2 = {m["MST Tag"].strip().replace(" ", ""): m["Master Name"]
        for m in masters if m.get("MST Tag", "").strip()}
MST = re.compile(r"MST\s*-?\s*[\w-]+")
a = b = c2 = t2 = 0
for _, r in res.iterrows():
    m = MST.search(str(r.get("Tags", "")))
    if not m:
        continue
    truth = tag2.get(m.group(0).replace(" ", ""))
    if not truth:
        continue
    t2 += 1
    got = cat_of(r)["master"]
    if got == truth:
        a += 1
    elif got is None:
        b += 1
    else:
        c2 += 1
print(f"  190 MST-tagged, master      : {a}/{t2} = {100*a/t2:.1f}% correct, {b} gaps, {c2} wrong")

# ---- routing, with the desk's own Assignment group as truth
rg = C.find_group_column(res.columns)
ok3 = tot3 = 0
for _, r in res.iterrows():
    sup = str(r.get(rg, "")).strip()
    if not sup or sup == "nan":
        continue
    cat = cat_of(r)["category"]
    g = C.final_group(sup, cat, r["Short description"], r.get("Description"),
                      L, groups, signals)["group"]
    tot3 += 1
    ok3 += g == C.canon_group(sup)[0]
print(f"  623 resolved, routing       : {ok3}/{tot3} = {100*ok3/tot3:.1f}%")

# ---- human scorecards. Batch exports are matched by ticket ID across all of
# them, so a new scorecard is picked up without touching this file.
batches = {}
for f in glob.glob(_p("triage*.xlsx")):
    try:
        d = pd.read_excel(f)
    except Exception:
        continue
    if "Number" not in d.columns:
        continue
    for k, v in d.set_index("Number").iterrows():
        batches.setdefault(k, v)

for sf in sorted(glob.glob(_p("*Scorecard*.xlsx")), key=os.path.getmtime, reverse=True)[:1]:
    raw = pd.read_excel(sf, sheet_name="Evaluation Log", header=None)
    hdr = [str(x) for x in raw.iloc[2].tolist()]
    d = raw.iloc[3:].copy()
    d.columns = hdr
    d = d[d["Incident ID"].astype(str).str.startswith("INC0")]
    d = d[d["Incident ID"] != "INC0000001"]
    print(f"\n  scorecard: {os.path.basename(sf)}")
    for date, grp in d.groupby(d["Date"].astype(str).str[:10]):
        S = {"cat": [0, 0], "route": [0, 0], "pri": [0, 0]}
        for _, r in grp.iterrows():
            tid = r["Incident ID"]
            if tid not in batches:
                continue
            s = batches[tid]
            t = cat_of(s)
            hc = str(r.get("Human · Category", "")).strip().strip("[]")
            if hc not in ("nan", ""):
                got = t["category"] if t["category"] != "Unclassified" else "UNCATEGORISED"
                S["cat"][1] += 1
                S["cat"][0] += got == hc
            hr = str(r.get("Human · Assignment", "")).strip()
            if hr not in ("nan", ""):
                gcol = C.find_group_column(s.index)
                g = C.final_group(s.get(gcol), t["category"], s["Short description"],
                                  s.get("Description"), L, groups, signals)["group"]
                S["route"][1] += 1
                S["route"][0] += g == hr
        bits = [f"{k} {v[0]}/{v[1]}" for k, v in S.items() if v[1]]
        if bits:
            print(f"    {date:<12} " + "   ".join(bits))
