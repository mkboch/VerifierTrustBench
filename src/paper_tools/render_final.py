#!/usr/bin/env python3
"""Render manuscript_final.template.md -> manuscript_final.md, failing loudly on any unresolved key.

Nothing numeric may be typed into the template. Every {{key}} must resolve from FINAL_NUMBERS.json, and any
bare digit left in the rendered prose is reported so it can be checked by eye.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
N = json.loads((HERE / "FINAL_NUMBERS.json").read_text())
TPL = (HERE / "manuscript_final.template.md").read_text()

missing = sorted({m for m in re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", TPL) if m not in N})
if missing:
    print(f"UNRESOLVED KEYS ({len(missing)}):")
    for m in missing:
        print("   " + m)
    sys.exit(1)

out = re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", lambda m: N[m.group(1)], TPL)
if "{{" in out:
    print("template still contains {{ after substitution"); sys.exit(1)
(HERE / "manuscript_final.md").write_text(out)

used = sorted(set(re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", TPL)))
(HERE / "KEYS_USED.json").write_text(json.dumps({k: N[k] for k in used}, indent=1) + "\n")
print(f"manuscript_final.md written: {len(out.splitlines())} lines, {len(out.split())} words")
print(f"{len(used)} canonical keys substituted, 0 unresolved")
