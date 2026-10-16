#!/usr/bin/env python3
"""Print a compact relation-inventory view of a normalised candidate: headings, labels/refs, tables, number-dense sentences."""
import re, sys
p = sys.argv[1]
t = open(p).read().split("\n")
labels = {}
for i, l in enumerate(t, 1):
    for m in re.finditer(r"\\label\{([^}]+)\}", l):
        labels[m.group(1)] = i
print("LINES", len(t), "LABELS", labels)
refs = {}
for i, l in enumerate(t, 1):
    for m in re.finditer(r"\\(?:ref|eqref|autoref|cref|Cref)\{([^}]+)\}", l):
        refs.setdefault(m.group(1), []).append(i)
print("REFS", {k: v for k, v in refs.items()})
print("UNDEFINED REFS", [k for k in refs if k not in labels])
intable = False
for i, l in enumerate(t, 1):
    if re.match(r"\\(sub)*section", l):
        print(f"{i:4d} # {l[:120]}")
    if "\\begin{tabular" in l:
        intable = True
    if intable and re.search(r"\d", l):
        print(f"{i:4d} T {l[:200]}")
    if "\\end{tabular" in l:
        intable = False
    if not intable and not l.startswith("\\"):
        for s in re.split(r"(?<=[.;])\s+", l):
            if len(re.findall(r"\d+\.?\d*", s)) >= 3 and len(s) < 400:
                print(f"{i:4d} S {s[:300]}")
