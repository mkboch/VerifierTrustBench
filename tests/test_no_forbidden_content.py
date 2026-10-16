"""Release guards, run in CI on every push. These duplicate scripts/audit_public_release.py
deliberately: the audit is the gate a human runs before publishing, and these are the gate that
stops a prohibited file being merged in the first place."""
from __future__ import annotations
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts/audit_public_release.py"


def repo_files() -> list[pathlib.Path]:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                             capture_output=True, text=True, check=True).stdout
        names = [n for n in out.split("\0") if n]
        if names:
            return [ROOT / n for n in names]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return [p for p in ROOT.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and ".git" not in p.parts]


FILES = repo_files()
TEXT = [f for f in FILES if f.suffix in
        {".py", ".js", ".html", ".css", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ".sh"}]


#: files that necessarily contain the very strings they forbid, and so are not scanned
GUARDS = {AUDIT.resolve(), pathlib.Path(__file__).resolve()}


def scannable() -> list[pathlib.Path]:
    return [f for f in TEXT if f.resolve() not in GUARDS]


def read(f: pathlib.Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


def test_the_audit_script_passes():
    r = subprocess.run(["python3", str(AUDIT), "--quiet"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"audit failed:\n{r.stdout}\n{r.stderr}"


def test_no_generated_figures_are_tracked():
    bad = [f.relative_to(ROOT).as_posix() for f in FILES
           if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".eps"}]
    assert bad == [], f"image or PDF files are tracked: {bad}"


def test_no_manuscript_sources_are_tracked():
    bad = [f.relative_to(ROOT).as_posix() for f in FILES
           if f.suffix.lower() in {".tex", ".bib", ".docx"} or "manuscript" in f.name.lower()]
    assert bad == [], f"manuscript material is tracked: {bad}"


def test_no_raw_generation_records_are_tracked():
    bad = [f.relative_to(ROOT).as_posix() for f in FILES if f.suffix == ".jsonl"]
    assert bad == [], f"raw record files are tracked: {bad}"


def test_the_only_tracked_data_file_is_the_aggregate():
    allowed = {"docs/data/public_sufficient_statistics.json", "configs/models.json",
               "prompts/questions.json"}
    jsons = {f.relative_to(ROOT).as_posix() for f in FILES if f.suffix == ".json"}
    assert jsons <= allowed, f"unexpected JSON data: {sorted(jsons - allowed)}"


def test_no_personal_paths_or_hostnames():
    """Patterns are assembled at runtime so that this file does not itself contain a
    personal path -- the public repository must not ship one anywhere, tests included."""
    user = "manik" + "m"
    bad = []
    for f in scannable():
        t = read(f)
        for pat in (rf"/home/{user}", rf"/scratch/{user}", r"\bax" + r"is[12]\b"):
            if re.search(pat, t):
                bad.append(f"{f.relative_to(ROOT).as_posix()}: {pat}")
    assert bad == [], bad


def test_no_credentials():
    pats = [r"ghp_[A-Za-z0-9]{36}", r"github_pat_[A-Za-z0-9_]{22,}", r"gho_[A-Za-z0-9]{36}",
            r"\bsk-[A-Za-z0-9]{20,}", r"\bhf_[A-Za-z0-9]{30,}", r"\bAKIA[0-9A-Z]{16}\b",
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----"]
    bad = []
    for f in scannable():
        t = read(f)
        bad += [f"{f.relative_to(ROOT).as_posix()}: {p}" for p in pats if re.search(p, t)]
    assert bad == [], bad


def test_no_human_study_material():
    """Not a single trace of the human validation: no names, no slots, no per-judgment fields."""
    terms = ["raw" + "_submissions", "human" + "_summary", "reviewer" + "_matrix",
             "gold" + "_reference", "PARTICIPANT" + "_INSTRUCTIONS", "phase" + "6"]
    bad = []
    for f in scannable():
        t = read(f).lower()
        bad += [f"{f.relative_to(ROOT).as_posix()}: {term}" for term in terms if term.lower() in t]
    assert bad == [], bad


def test_no_email_addresses():
    rx = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    bad = []
    for f in scannable():
        for m in rx.finditer(read(f)):
            bad.append(f"{f.relative_to(ROOT).as_posix()}: {m.group(0)}")
    assert bad == [], bad


def test_repository_stays_small():
    total = sum(f.stat().st_size for f in FILES)
    assert total < 8 * 1024 * 1024, f"repository is {total/1024/1024:.1f} MB"


def test_no_file_is_unexpectedly_large():
    big = [(f.relative_to(ROOT).as_posix(), f.stat().st_size) for f in FILES
           if f.stat().st_size > 512 * 1024]
    assert big == [], f"oversized files: {big}"
