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

# Ground-truth workbooks hold real ticket data, so they are deliberately NOT
# committed. They are looked for in each of these directories in turn, so the
# harness runs on any machine without editing this file:
#
#   $TRIAGE_UPLOADS   an explicit override, checked first
#   reference/truth/  the expected home -- gitignored, see the README there
#   runs/             where scorecards have historically been dropped
#
# A missing file is a hard stop with instructions, never a silent skip: a
# regression harness that quietly measures nothing is worse than none at all.
def _dirs():
    cand = [os.environ.get("TRIAGE_UPLOADS"), "reference/truth", "runs"]
    return [d for d in cand if d and os.path.isdir(d)]


def _missing(what):
    where = ", ".join(_dirs()) or "(no candidate directory exists)"
    sys.exit(f"""
measure.py: cannot find {what}
  looked in: {where}

  Drop the ground-truth workbooks into reference/truth/, or point
  TRIAGE_UPLOADS at the folder holding them. See reference/truth/README.md
  for the exact filenames and columns required.
""")


def _p(name):
    for d in _dirs():
        f = os.path.join(d, name)
        if os.path.exists(f):
            return f
    _missing(name)


def _glob(pat):
    """Every match across all candidate directories, nearest first."""
    hits = []
    for d in _dirs():
        hits += glob.glob(os.path.join(d, pat))
    return hits


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


def _training():
    """Every resolved/closed training workbook present, concatenated and
    de-duplicated on ticket number. Adding another export needs no code change --
    drop it in reference/truth/ with 'training' or 'resolved and closed' in the
    name. Row counts are printed because a thin Tags column shrinks the
    measurable set silently: watch the denominators, not just the percentages."""
    files = sorted(set(_glob("*training*.xlsx") + _glob("resolved and closed*.xlsx")))
    if not files:
        _missing("a training workbook (name it '*training*.xlsx')")
    frames = []
    for f in files:
        d = pd.read_excel(f)
        print(f"  training set: {os.path.basename(f):<44} {len(d):5d} rows")
        frames.append(d)
    res = pd.concat(frames, ignore_index=True)
    if "Number" in res.columns:
        res = res.drop_duplicates(subset="Number", keep="first")
    if "Opened" in res.columns:
        res["_opened"] = pd.to_datetime(res["Opened"], errors="coerce")
    else:
        res["_opened"] = pd.NaT
    print(f"  {'':<58}{len(res):5d} unique\n")
    return res


res = _training()

# Rows opened on or after this date are reported SEPARATELY as a holdout. The
# desk's labelling drifts, and 25 of the scorecard-graded tickets sit inside the
# training export -- scoring them together would flatter every number.
HOLDOUT = "2026-07-01"
recent = res["_opened"] >= HOLDOUT


def _split(mask_fn, label):
    """Score a metric over the whole set and over the holdout separately."""
    out = []
    for name, sub in (("all", res), (f"held out >= {HOLDOUT}", res[recent])):
        ok, tot = mask_fn(sub)
        out.append(f"{name}: {ok}/{tot} = {100*ok/tot:.1f}%" if tot else f"{name}: no rows")
    print(f"  {label:<28}" + "   |   ".join(out))


# ---- category on the tagged resolved tickets
def _cat(sub):
    ok = tot = 0
    for _, r in sub.iterrows():
        truth = tagcat(r.get("Tags"))
        if not truth:
            continue
        tot += 1
        ok += cat_of(r)["category"] == truth
    return ok, tot


_split(_cat, "category (tagged)")

# ---- master matching on the MST-tagged resolved tickets
tag2 = {m["MST Tag"].strip().replace(" ", ""): m["Master Name"]
        for m in masters if m.get("MST Tag", "").strip()}
MST = re.compile(r"MST\s*-?\s*[\w-]+")
def _master(sub):
    a = b = c2 = t2 = 0
    for _, r in sub.iterrows():
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
    _master.last = (b, c2)
    return a, t2


_split(_master, "master (MST-tagged)")
print(f"  {'':<28}{_master.last[0]} gaps, {_master.last[1]} wrong (holdout slice)")

# ---- routing, with the desk's own Assignment group as truth
rg = C.find_group_column(res.columns)
if rg is None:
    print(f"  {'routing':<28}SKIPPED -- no assignment-group column in the training set.")
    print(f"  {'':<28}Re-export with 'Assignment group' to measure routing at all.")
else:
    def _route(sub):
        ok3 = tot3 = 0
        for _, r in sub.iterrows():
            sup = str(r.get(rg, "")).strip()
            if not sup or sup == "nan":
                continue
            cat = cat_of(r)["category"]
            g = C.final_group(sup, cat, r["Short description"], r.get("Description"),
                              L, groups, signals)["group"]
            tot3 += 1
            ok3 += g == C.canon_group(sup)[0]
        return ok3, tot3

    _split(_route, "routing")

# ---- human scorecards. Batch exports are matched by ticket ID across all of
# them, so a new scorecard is picked up without touching this file.
batches = {}
for f in _glob("triage*.xlsx"):
    try:
        d = pd.read_excel(f)
    except Exception:
        continue
    if "Number" not in d.columns:
        continue
    for k, v in d.set_index("Number").iterrows():
        batches.setdefault(k, v)
_from_batches = len(batches)

# The training export also carries Short description and Description, so it can
# supply the text for any graded ticket whose batch export is absent. Batch
# exports still win -- they are what the run actually saw.
if "Number" in res.columns:
    for k, v in res.set_index("Number").iterrows():
        batches.setdefault(k, v)

if not _from_batches:
    print(f"\n  ! no batch exports found (triage*.xlsx). Scorecard rows are being")
    print(f"    scored off the training export instead, which covers only part of")
    print(f"    them -- any date below with a small denominator is missing its export.")

for sf in sorted(_glob("*Scorecard*.xlsx"), key=os.path.getmtime, reverse=True)[:1]:
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
            gcol = C.find_group_column(s.index)
            # Skip rows with no supplied group rather than score them. The shipped
            # rule is "the group on the export wins"; scoring a row that has no
            # such column measures the fallback rule alone and reads as a
            # regression that is not there.
            if hr not in ("nan", "") and gcol is not None:
                g = C.final_group(s.get(gcol), t["category"], s["Short description"],
                                  s.get("Description"), L, groups, signals)["group"]
                S["route"][1] += 1
                S["route"][0] += g == hr
        bits = [f"{k} {v[0]}/{v[1]}" for k, v in S.items() if v[1]]
        if bits:
            print(f"    {date:<12} " + "   ".join(bits))
