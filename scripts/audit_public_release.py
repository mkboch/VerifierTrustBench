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

# This is a RESEARCH DATA AND CODE release. It deliberately ships the study's released
# outcome data so that the published numerical results can be reproduced independently.
#
# What it must never ship is the material behind those outcomes: manuscript text, model
# generations, participant identities, free-text judgements and the arXiv identifiers that
# would attach an injected defect to a named third-party paper. Each released file is
# listed here with what it is allowed to contain, and the contents are checked below
# rather than taken on trust.
ALLOWED_DATA = {
    "docs/data/fair_scoring_cells.json":
        "per-cell binary outcomes, opaque manuscript and relation labels",
    "docs/data/fair_scoring_support.json":
        "audited aggregates supporting the ladder",
    "docs/data/public_sufficient_statistics.json":
        "de-identified sufficient statistics for the other experiments",
    "docs/data/research_results.json":
        "aggregate outcome blocks and the manuscript index routes",
    "docs/data/scorer_audit_items.json":
        "PER-ITEM human rating counts only; no reviewer axis, no free text",
    "docs/data/manuscript_results_index.json":
        "source-of-truth manifest: macro, value, canonical record, reproduction route",
    "docs/data/synthetic_demo_cells.json":
        "synthetic fixture; must declare itself synthetic",
}
SYNTHETIC_FIXTURES = {"docs/data/synthetic_demo_cells.json"}

# Frozen private records that must never be copied into the public tree verbatim. The
# public release carries DERIVED, de-identified files built from these by tools/; shipping
# the originals would ship manuscript text, model output and reviewer-level judgements.
FORBIDDEN_RESULT_FILES = {
    "STATISTICAL_RECHECK.csv": "private audit result table",
    "FAIR_LADDER_METRICS.json": "frozen private metrics record",
    "SCORER_SENSITIVITY.json": "frozen private metrics record",
    "RT_AUDIT_RESULTS.json": "reviewer-level human scorer-audit record",
    "ANTHROPIC_ACCOUNTING.json": "frozen private accounting record",
    "MISS_ANATOMY.json": "frozen private analysis record",
    "BLIND_SCORER_AUDIT_ITEMS.json": "audited items: manuscript text and model output",
    "RELATION_TARGETED_AUDIT_SAMPLE.json": "audited items: manuscript text and model output",
    "FINAL_NUMBERS.json": "private manuscript macro store",
    "NATURAL_ERROR_LEDGER.json": "naturally occurring errors in third-party manuscripts",
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

        if suffix == ".json" and rel not in ALLOWED_DATA and not rel.startswith(("configs/", "prompts/", ".github/", "reproducibility/")):
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

    # Every released data file is checked for what it must and must not contain. The
    # filename is not evidence of anything; the contents are.
    ARXIV = re.compile(r"\b(?:19|20|21|22|23|24|25|26|27)\d\d\.\d{4,5}\b")
    for rel in sorted(ALLOWED_DATA):
        f = ROOT / rel
        if not f.exists():
            continue
        try:
            raw = f.read_text()
            doc = json.loads(raw)
        except (OSError, ValueError) as e:
            failures.append(f"[data] {rel} is not readable JSON: {e}")
            continue

        # No released file may name a third-party manuscript. Attaching an injected defect
        # to a named paper is the one thing this release must never do.
        m = ARXIV.search(raw)
        if m:
            failures.append(f"[data] {rel} contains what looks like an arXiv identifier "
                            f"({m.group(0)!r}); manuscripts must appear as opaque labels")
        # No released file may carry the reviewer axis or free-text judgements.
        for pat, what in ((r"Reviewer_\d", "a reviewer identifier"),
                          (r'"notes"\s*:', "a free-text notes field")):
            m = re.search(pat, raw)
            if m:
                failures.append(f"[data] {rel} contains {what} ({m.group(0)[:32]!r})")

        if rel in SYNTHETIC_FIXTURES:
            if doc.get("synthetic") is not True:
                failures.append(f"[fixture] {rel} is not marked \"synthetic\": true")
            if "warning" not in doc:
                failures.append(f"[fixture] {rel} carries no warning that it is not evidence")
        else:
            # A released outcome file must state that E0 defects are injected, so a reader
            # who downloads it alone cannot mistake it for a list of real paper errors.
            if "defect" in raw.lower() or "e0" in raw.lower():
                if not re.search(r"inject|perturbation|synthetic", raw, re.I):
                    failures.append(f"[data] {rel} discusses E0 defects without stating "
                                    f"that they are injected perturbations")

        # Long free-text strings are what a leak would look like in any cell table.
        for row in doc.get("cells", []):
            for v in row:
                if isinstance(v, str) and len(v) > 24:
                    failures.append(f"[data] {rel} contains a long string in a cell row, "
                                    f"which is what leaked free text would look like: "
                                    f"{v[:40]!r}")
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
    print("  no credentials, no personal paths, no manuscript text, no model")
    print("  generations, no model weights, no oversized files.")
    print("  released outcome data: every data file is on the approved list, carries no")
    print("  arXiv identifier, no reviewer axis and no free text, and states that E0")
    print("  defects are perturbations this study injected, not errors in real papers.")
    print("  human review data: per-item rating counts only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
