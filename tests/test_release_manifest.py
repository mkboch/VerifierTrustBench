"""The published hash manifest must describe the files actually being served.

The playground prints a line from docs/data/SHA256SUMS.txt inside each derivation, as the
provenance of the numbers above it. A stale manifest would make that display a lie, so a
stale manifest fails the build.
"""
from __future__ import annotations
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/data/SHA256SUMS.txt"


def _entries():
    out = {}
    for line in MANIFEST.read_text().split("\n"):
        if line.strip():
            digest, rel = line.split()
            out[rel] = digest
    return out


def test_every_served_file_is_listed_and_correct():
    entries = _entries()
    served = sorted(
        p.relative_to(ROOT).as_posix()
        for pat in ("docs/data/*.json", "docs/*.html", "docs/assets/*")
        for p in ROOT.glob(pat)
    )
    assert set(served) == set(entries), (
        f"manifest and served files disagree: "
        f"missing={sorted(set(served) - set(entries))} "
        f"extra={sorted(set(entries) - set(served))}"
    )
    for rel, digest in entries.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        assert actual == digest, f"{rel}: manifest says {digest}, file is {actual}"


def test_the_manifest_generator_agrees():
    r = subprocess.run([sys.executable, str(ROOT / "tools/update_manifest.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
