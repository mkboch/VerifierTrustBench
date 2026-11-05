#!/usr/bin/env python3
"""Fail the release if anything prohibited is tracked in this repository.

Run from the repository root, immediately before publication and in CI:

    python scripts/audit_public_release.py          # audits git-tracked files
    python scripts/audit_public_release.py --all    # audits every file on disk

Exits non-zero on the first category that trips. It is intentionally blunt: a false positive is
cheap, a leaked artifact is not.
"""
from __future__ import annotations
import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- what must never be here

SECRET_PATTERNS = [
    (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    (r"github_pat_[A-Za-z0-9_]{22,}", "GitHub fine-grained token"),
    (r"gho_[A-Za-z0-9]{36}", "GitHub OAuth token"),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"\bhf_[A-Za-z0-9]{30,}", "Hugging Face token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS access key id"),
    (r"-----BEGIN (OPENSSH|RSA|DSA|EC|PGP) PRIVATE KEY-----", "private key"),
    (r"(?i)\bauthorization\s*:\s*bearer\s+[A-Za-z0-9._~+/-]{16,}", "bearer token"),
    (r"(?i)\b(password|passwd|secret_key|api_key)\s*[=:]\s*['\"][^'\"\s]{8,}['\"]", "hard-coded credential"),
]

# Assembled from fragments so that this file does not itself ship the personal paths and
# hostnames it exists to catch. That also lets the scan cover this file like any other.
_U = "manik" + "m"
_HOST = "ax" + "is"

PRIVACY_PATTERNS = [
    (rf"/home/{_U}", "personal home path"),
    (rf"/scratch/{_U}", "personal scratch path"),
    (rf"\b{_HOST}[12]\b", "internal hostname"),
    (r"[A-Za-z0-9._%+-]+@(?:rpi\.edu|gmail\.com|outlook\.com|hotmail\.com)", "email address"),
    (r"(?i)\braw" + r"_submissions\b", "human-study submission directory"),
    (r"(?i)\bhuman" + r"_summary\b", "human-study per-judgment table"),
    (r"(?i)\breviewer" + r"_matrix\b", "human-study reviewer assignment"),
    (r"(?i)\bparticipant[_ ]?(name|id)\b", "participant identifier"),
]

# file extensions that cannot be part of a code-only release
FORBIDDEN_SUFFIXES = {
    ".png": "image / possible paper figure", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".pdf": "PDF / possible manuscript", ".svg": "vector figure",
    ".tex": "LaTeX manuscript source", ".bib": "bibliography", ".docx": "document",
    ".pptx": "slides", ".xlsx": "spreadsheet", ".zip": "archive", ".tar": "archive",
    ".gz": "archive", ".jsonl": "raw generation records", ".ckpt": "checkpoint",
    ".safetensors": "model weights", ".bin": "binary / weights", ".pt": "checkpoint",
    ".pem": "key material", ".key": "key material", ".env": "environment secrets",
}

FORBIDDEN_NAMES = {
    "FINAL_NUMBERS.json", "NUMBERS.json", "manuscript_v1.md", "manuscript_final.md",
    "manuscript_final.template.md", "ledger.json", "analysis.json", "profile.json",
    "DATASET_MANIFEST.json", "CONTROL_MANIFEST.json", "human" + "_summary.csv",
    "gold" + "_reference.json", "reviewer" + "_matrix.json", ".env", "id_rsa", "id_ed25519",
}

FORBIDDEN_DIR_PARTS = {
    "runs", "results", "raw" + "_submissions", "__pycache__", ".venv", "venv", "node_modules",
    "hf_cache", "checkpoints", "papers_cache", "overleaf", "baseline", "phase" + "6_human_study",
}

# This is a CODE release. It ships research software and the instructions to run it; it
# does not ship the study's experimental results.
#
# The only data file allowed under docs/data/ is a fixture that is explicitly marked
# synthetic, and the marking is checked below rather than taken on trust. configs/ and
# prompts/ hold method configuration, not outcomes.
ALLOWED_DATA = {
    "docs/data/synthetic_demo_cells.json",
}

# Named result artifacts that must never reappear in a code release. Listed by name so
# that restoring one by accident fails loudly instead of quietly shipping outcomes.
FORBIDDEN_RESULT_FILES = {
    "public_sufficient_statistics.json": "published aggregate study statistics",
    "fair_scoring_cells.json": "per-relation experimental outcomes",
    "fair_scoring_support.json": "audited result aggregates and scorer-audit rates",
    "STATISTICAL_RECHECK.csv": "result table",
    "FAIR_LADDER_METRICS.json": "frozen result metrics",
    "SCORER_SENSITIVITY.json": "frozen result metrics",
    "RT_AUDIT_RESULTS.json": "human scorer-audit outcomes",
    "ANTHROPIC_ACCOUNTING.json": "frozen result accounting",
    "MISS_ANATOMY.json": "frozen result analysis",
}
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024

BINARY_HINT = b"\x00"


def tracked_files(all_files: bool) -> list[pathlib.Path]:
    if all_files:
        # Local build caches are never tracked (see .gitignore) and are not part of a release.
        # A cache directory that somehow IS tracked still gets caught, because the default
        # mode below asks git rather than the filesystem.
        transient = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
        return sorted(p for p in ROOT.rglob("*")
                      if p.is_file() and not (transient & set(p.relative_to(ROOT).parts)))
    try:
        res = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             capture_output=True, text=True, check=True)
        names = [n for n in res.stdout.split("\0") if n]
    except (subprocess.CalledProcessError, FileNotFoundError):
        names = []
    if names:
        return sorted(ROOT / n for n in names)
    # Nothing is tracked yet (first release, or git unavailable). Audit the working tree
    # instead: auditing more than asked is safe, auditing nothing is not.
    print("note: no tracked files; auditing the working tree instead")
    return tracked_files(True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="audit every file on disk, not just tracked files")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    files = tracked_files(a.all)
    if not files:
        print("FAIL: no files to audit (is this a git repository with a commit?)")
        return 2

    failures: list[str] = []
    total = 0
    self_path = pathlib.Path(__file__).resolve()

    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        size = f.stat().st_size
        total += size

        if size > MAX_FILE_BYTES:
            failures.append(f"[size] {rel} is {size} bytes (> {MAX_FILE_BYTES})")

        parts = set(pathlib.PurePosixPath(rel).parts[:-1])
        bad_dir = parts & FORBIDDEN_DIR_PARTS
        if bad_dir:
            failures.append(f"[path] {rel} sits under a forbidden directory: {sorted(bad_dir)}")

        if f.name in FORBIDDEN_NAMES:
            failures.append(f"[name] {rel} is a forbidden artifact name")

        suffix = f.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            failures.append(f"[type] {rel} is a {FORBIDDEN_SUFFIXES[suffix]}")

        if suffix == ".json" and rel not in ALLOWED_DATA and not rel.startswith(("configs/", "prompts/", ".github/")):
            failures.append(f"[data] {rel} is a JSON data file outside the allowed set")

        if f.name in FORBIDDEN_RESULT_FILES:
            failures.append(f"[results] {rel} is {FORBIDDEN_RESULT_FILES[f.name]}; "
                            "this is a code release and must not ship experimental outcomes")

        try:
            raw = f.read_bytes()
        except OSError as e:
            failures.append(f"[read] {rel}: {e}")
            continue
        if BINARY_HINT in raw[:8192]:
            failures.append(f"[binary] {rel} looks binary")
            continue

        text = raw.decode("utf-8", errors="replace")
        # Only the credential regexes are necessarily self-matching (a prefix like the
        # fine-grained-token one appears literally); the privacy patterns above are
        # assembled from fragments, so this file is scanned for them like any other.
        secret_pats = [] if f.resolve() == self_path else SECRET_PATTERNS
        for pat, what in secret_pats:
            if re.search(pat, text):
                failures.append(f"[secret] {rel}: {what}")
        for pat, what in PRIVACY_PATTERNS:
            m = re.search(pat, text)
            if m:
                failures.append(f"[privacy] {rel}: {what} ({m.group(0)[:48]!r})")

    # Every data file the site serves must say, in the file itself, that it is synthetic.
    # A reader who downloads it directly must not have to infer that from the filename.
    for rel in sorted(ALLOWED_DATA):
        f = ROOT / rel
        if not f.exists():
            continue
        try:
            doc = json.loads(f.read_text())
        except (OSError, ValueError) as e:
            failures.append(f"[fixture] {rel} is not readable JSON: {e}")
            continue
        if doc.get("synthetic") is not True:
            failures.append(f"[fixture] {rel} is not marked \"synthetic\": true")
        if "warning" not in doc:
            failures.append(f"[fixture] {rel} carries no warning that it is not evidence")
        for row in doc.get("cells", []):
            for v in row:
                if isinstance(v, str) and len(v) > 24:
                    failures.append(f"[fixture] {rel} contains a long string, which is what "
                                    f"leaked free text would look like: {v[:40]!r}")
                    break
            else:
                continue
            break

    if total > MAX_TOTAL_BYTES:
        failures.append(f"[size] repository is {total} bytes (> {MAX_TOTAL_BYTES})")

    if not a.quiet:
        print(f"audited {len(files)} files, {total/1024:.0f} KB total")

    if failures:
        print(f"\nPUBLIC RELEASE AUDIT: FAIL ({len(failures)} finding(s))\n")
        for x in failures:
            print("  " + x)
        return 1

    print("PUBLIC RELEASE AUDIT: PASS")
    print("  no secrets, no personal paths, no participant data, no figures,")
    print("  no manuscripts, no model weights, no oversized files.")
    print("  no experimental results: the only data file is a fixture that declares")
    print("  itself synthetic and carries a warning against being read as evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
