#!/usr/bin/env python
"""Fail if any statistic was typed into the manuscript template instead of substituted.

Strips every {{key}} placeholder and reports the numeric tokens that remain in the prose.
Only structural numbers are allowed: figure/table numbers, the values of k, criterion
numbers, temperature, and model parameter counts.
"""
import json, re, sys, pathlib
HERE = pathlib.Path(__file__).resolve().parent
ALLOWED = {"0", "1", "2", "3", "4", "5", "6", "10", "11", "30", "70", "1,2,3,5"}
prose = re.sub(r"\{\{\w+\}\}", " ", (HERE / "manuscript_final.template.md").read_text())
typed = sorted(set(re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?", prose)))
bad = [t for t in typed if t not in ALLOWED]
for t in typed:
    ctx = next((l.strip() for l in prose.split("\n")
                if re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\d])", l)), "")
    print(f"{'BAD ' if t in bad else '  ok'} {t!r:10} {ctx[:100]}")
print(f"\n{len(typed)} numeric tokens in prose, {len(bad)} not structural")
sys.exit(1 if bad else 0)
