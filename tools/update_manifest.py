#!/usr/bin/env python3
"""Regenerate docs/data/SHA256SUMS.txt over every file the playground serves.

The playground fetches this file and prints the relevant line inside each result card, so
a visitor can check that the bytes their browser computed from are the bytes the release
claims. Run it after changing anything under docs/ and commit the result.

    python tools/update_manifest.py            # rewrite
    python tools/update_manifest.py --check    # verify, exit non-zero on drift (used in CI)
"""
from __future__ import annotations
import argparse, hashlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/data/SHA256SUMS.txt"
# Deterministic order; the manifest never lists itself.
PATTERNS = ["docs/data/*.json", "docs/*.html", "docs/assets/*.js", "docs/assets/*.css"]


def manifest() -> str:
    lines = []
    for pat in PATTERNS:
        for f in sorted(ROOT.glob(pat)):
            rel = f.relative_to(ROOT).as_posix()
            lines.append(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {rel}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = manifest()
    if a.check:
        have = OUT.read_text() if OUT.exists() else ""
        if have != text:
            print("SHA256SUMS.txt is out of date. Run: python tools/update_manifest.py")
            for line in text.split("\n"):
                if line and line not in have:
                    print("  missing or changed:", line)
            return 1
        print(f"SHA256SUMS.txt is current ({len(text.strip().splitlines())} files)")
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.strip().splitlines())} files)")
    for line in text.strip().split("\n"):
        print("  " + line)
    return 0


raise SystemExit(main())
