#!/usr/bin/env python3
"""3A: turn harvested corrections into an auditable ledger, and test the decisive question.

A documented erratum is only usable by this benchmark if the published error creates an
inconsistency a reader could detect FROM THE TEXT ALONE. "350 mg/mL should be 300 mg/mL" is a
real, documented error, but if nothing else in the paper contradicts 350, no verifier -- human or
machine -- can find it without the correction notice. Such a case measures clairvoyance, not
verification.

This script fetches each original article and asks, mechanically: does the corrected value appear
elsewhere in the article, so that the published value would contradict it? That is a necessary
condition for internal detectability. It is not sufficient, which is why every surviving case
still needs manual confirmation before use.
"""
from __future__ import annotations
import os
import csv, json, re, time, urllib.parse, urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL, EMAIL = "VerifierTrustBench-natural-error-curation", os.environ.get("NCBI_CONTACT_EMAIL", "")


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": f"{TOOL} ({EMAIL})"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def efetch(pmcid):
    q = urllib.parse.urlencode({"db": "pmc", "id": pmcid.replace("PMC", ""), "rettype": "xml",
                                "tool": TOOL, "email": EMAIL})
    return get(f"{EUTILS}/efetch.fcgi?{q}")


def body_text(xml):
    m = re.search(r"<body>(.*?)</body>", xml, re.S)
    t = m.group(1) if m else xml
    t = re.sub(r"<[^>]+>", " ", t)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#x000a0;", " "),
                 ("&#x02009;", " "), ("&#x02212;", "-")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t)


def occurrences(text, value):
    v = value.strip().rstrip(".,;").replace(",", "")
    if not v:
        return 0
    return len(re.findall(r"(?<![\d.])" + re.escape(v) + r"(?![\d])", text.replace(",", "")))


CAND = json.loads((OUT / "natural/CORRECTION_CANDIDATES_WIDE.json").read_text())["candidates"]
# de-duplicate on the documented value pair plus the linked article
seen, uniq = set(), []
for c in CAND:
    k = (c["published_value"].strip(), c["corrected_value"].strip(), c["related_article_doi"])
    if k in seen:
        continue
    seen.add(k); uniq.append(c)
print(f"{len(CAND)} harvested -> {len(uniq)} after de-duplication")

rows = []
for c in uniq:
    rel = c["related_article_doi"]
    row = {**{k: c[k] for k in ("correction_pmcid", "correction_url", "journal", "year",
                                "correction_title", "published_value", "corrected_value",
                                "matched_sentence")},
           "original_article_ref": rel, "fulltext_retrieved": 0,
           "published_value_occurrences": "", "corrected_value_occurrences": "",
           "route": "", "internally_detectable_necessary_condition": "",
           "admissible_pending_manual_check": 0, "exclusion_reason": ""}
    if not rel.startswith("PMC"):
        row["exclusion_reason"] = "original article not in PMC (DOI only); full text not retrievable here"
        rows.append(row); continue
    try:
        time.sleep(0.4)
        txt = body_text(efetch(rel))
    except Exception as e:
        row["exclusion_reason"] = f"fetch failed: {type(e).__name__}"
        rows.append(row); continue
    if len(txt) < 2000:
        row["exclusion_reason"] = "full text not available (abstract only or restricted)"
        rows.append(row); continue
    row["fulltext_retrieved"] = 1
    np_, nc = occurrences(txt, c["published_value"]), occurrences(txt, c["corrected_value"])
    row["published_value_occurrences"], row["corrected_value_occurrences"] = np_, nc
    if np_ > 0 and nc == 0:
        row["route"] = "A (as-published erroneous text still present)"
    elif nc > 0:
        row["route"] = "B (article amended; documented value would be reinstated)"
    else:
        row["route"] = "neither value located in the retrieved text"
    # necessary condition: the corrected value must appear somewhere else in the article, so that
    # the published value would contradict it
    det = nc >= 2 if row["route"].startswith("B") else np_ >= 2
    row["internally_detectable_necessary_condition"] = "yes" if det else "no"
    if row["route"].startswith("neither"):
        row["exclusion_reason"] = "value not locatable in the retrieved text"
    elif not det:
        row["exclusion_reason"] = ("the documented value appears only once; the published error "
                                   "would contradict nothing in the text, so no verifier could "
                                   "detect it without the correction notice")
    else:
        row["admissible_pending_manual_check"] = 1
    rows.append(row)
    print(f"  {c['correction_pmcid']:12} {c['published_value']:>9}->{c['corrected_value']:<9} "
          f"{row['route'][:22]:24} occ pub={np_} corr={nc}  "
          f"{'CANDIDATE' if row['admissible_pending_manual_check'] else 'excluded'}")

with (OUT / "natural/NATURAL_ERROR_CASE_LEDGER.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

import collections
print(f"\n{'':4}{'outcome':62}{'n':>4}")
print(f"  {'full text retrieved':62}{sum(r['fulltext_retrieved'] for r in rows):>4}")
print(f"  {'passes the internal-detectability necessary condition':62}"
      f"{sum(r['admissible_pending_manual_check'] for r in rows):>4}")
for reason, n in collections.Counter(r["exclusion_reason"] for r in rows if r["exclusion_reason"]).most_common():
    print(f"  excluded: {reason[:52]:52}{n:>4}")
json.dump({"n_harvested": len(CAND), "n_deduplicated": len(uniq),
           "n_fulltext": sum(r["fulltext_retrieved"] for r in rows),
           "n_passing_necessary_condition": sum(r["admissible_pending_manual_check"] for r in rows),
           "rows": rows}, (OUT / "natural/NATURAL_ERROR_LEDGER.json").open("w"), indent=1)
print("\nwrote natural/NATURAL_ERROR_CASE_LEDGER.csv and NATURAL_ERROR_LEDGER.json")
