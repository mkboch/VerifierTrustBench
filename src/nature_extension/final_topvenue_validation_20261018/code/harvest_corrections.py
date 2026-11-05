#!/usr/bin/env python3
"""3A: harvest publicly documented quantitative corrections from PubMed Central.

Uses NCBI E-utilities, the sanctioned programmatic interface. No scraping, no LLM judgment.
A candidate is kept only if the correction notice states BOTH the incorrect and the corrected
value in a machine-extractable form, so the gold is grounded in the public record rather than in
anyone's opinion.
"""
from __future__ import annotations
import os
import json, re, time, urllib.parse, urllib.request, sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "VerifierTrustBench-natural-error-curation"
EMAIL = os.environ.get("NCBI_CONTACT_EMAIL", "")  # NCBI asks identifying contact for programmatic use
SLEEP = 0.4                        # stay well inside the 3 req/s unauthenticated limit


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"{TOOL} ({EMAIL})"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def esearch(term: str, retmax: int = 200) -> list[str]:
    q = urllib.parse.urlencode({"db": "pmc", "term": term, "retmax": retmax,
                                "retmode": "json", "tool": TOOL, "email": EMAIL})
    d = json.loads(get(f"{EUTILS}/esearch.fcgi?{q}"))
    return d.get("esearchresult", {}).get("idlist", [])


def efetch(pmcid: str) -> str:
    q = urllib.parse.urlencode({"db": "pmc", "id": pmcid, "rettype": "xml",
                                "tool": TOOL, "email": EMAIL})
    return get(f"{EUTILS}/efetch.fcgi?{q}")


def strip_tags(x: str) -> str:
    x = re.sub(r"<[^>]+>", " ", x)
    x = (x.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&#x02019;", "'").replace("&#x0201c;", '"')
          .replace("&#x0201d;", '"').replace("&#x02018;", "'").replace("&#x000a0;", " "))
    return re.sub(r"\s+", " ", x).strip()


# A quantitative correction states a wrong value and its replacement. These patterns capture the
# common journal phrasings; each match is kept verbatim for manual audit.
PATTERNS = [
    re.compile(r'[""„"\'(]?\s*([-+]?\d[\d,]*\.?\d*\s*%?)\s*[""\')]?\s*'
               r'should (?:have been|read|be)\s*[""„"\'(]?\s*([-+]?\d[\d,]*\.?\d*\s*%?)', re.I),
    re.compile(r'incorrectly (?:reported|stated|given|listed) as\s*[""„"\'(]?\s*'
               r'([-+]?\d[\d,]*\.?\d*\s*%?)\s*[""\')]?[^.]{0,60}?'
               r'correct (?:value|figure|number)[^.]{0,20}?\s*(?:is|was)\s*[""„"\'(]?\s*'
               r'([-+]?\d[\d,]*\.?\d*\s*%?)', re.I),
    re.compile(r'reported as\s*[""„"\'(]?\s*([-+]?\d[\d,]*\.?\d*\s*%?)\s*[""\')]?'
               r'[^.]{0,40}?instead of\s*[""„"\'(]?\s*([-+]?\d[\d,]*\.?\d*\s*%?)', re.I),
]

QUERIES = [
    '"incorrectly reported as"[Body - All Words] AND correction[Publication Type]',
    '"incorrectly stated as"[Body - All Words] AND correction[Publication Type]',
    '"incorrectly listed as"[Body - All Words] AND correction[Publication Type]',
    '"incorrectly given as"[Body - All Words] AND correction[Publication Type]',
    '"the correct value is"[Body - All Words] AND correction[Publication Type]',
    '"the correct value should be"[Body - All Words]',
    '"instead of"[Body - All Words] AND "was reported as"[Body - All Words] AND correction[Publication Type]',
    '"should have read"[Body - All Words] AND correction[Publication Type]',
    'erratum[Publication Type] AND "incorrectly reported"[Body - All Words]',
    'erratum[Publication Type] AND "the correct value"[Body - All Words]',
]

seen, cands = set(), []
for term in QUERIES:
    try:
        ids = esearch(term, retmax=400)
    except Exception as e:
        print(f"  search failed ({type(e).__name__}) for: {term[:50]}"); continue
    print(f"{len(ids):4} hits  <- {term[:62]}")
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        time.sleep(SLEEP)
        try:
            xml = efetch(pid)
        except Exception:
            continue
        txt = strip_tags(xml)
        for rx in PATTERNS:
            m = rx.search(txt)
            if not m:
                continue
            wrong, right = m.group(1).strip(), m.group(2).strip()
            if wrong == right or len(wrong) > 18 or len(right) > 18:
                continue
            jt = re.search(r"<journal-title>([^<]+)</journal-title>", xml)
            ti = re.search(r"<article-title>(.*?)</article-title>", xml, re.S)
            yr = re.search(r"<pub-date[^>]*>.*?<year>(\d{4})</year>", xml, re.S)
            rel = re.search(r'related-article[^>]*xlink:href="([^"]+)"', xml)
            cands.append({
                "correction_pmcid": f"PMC{pid}",
                "correction_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pid}/",
                "journal": jt.group(1) if jt else "",
                "correction_title": strip_tags(ti.group(1))[:160] if ti else "",
                "year": yr.group(1) if yr else "",
                "related_article_doi": rel.group(1) if rel else "",
                "published_value": wrong, "corrected_value": right,
                "matched_sentence": strip_tags(m.group(0))[:300],
            })
            break
    print(f"     cumulative quantitative candidates: {len(cands)}")

(OUT / "natural").mkdir(exist_ok=True)
json.dump({"queries": QUERIES, "n_notices_examined": len(seen),
           "n_quantitative_candidates": len(cands), "candidates": cands},
          (OUT / "natural/CORRECTION_CANDIDATES_WIDE.json").open("w"), indent=1)
print(f"\nexamined {len(seen)} correction notices")
print(f"quantitative candidates with an extractable wrong->right value pair: {len(cands)}")
print(f"with a linked original article DOI: {sum(1 for c in cands if c['related_article_doi'])}")
print("\nsample:")
for c in cands[:12]:
    print(f"  {c['correction_pmcid']:12} {c['published_value']:>9} -> {c['corrected_value']:<9} "
          f"{c['journal'][:34]:36} doi={'yes' if c['related_article_doi'] else 'no'}")
print("\nwrote natural/CORRECTION_CANDIDATES.json")
