"""Release guards, run in CI on every push. These duplicate scripts/audit_public_release.py
deliberately: the audit is the gate a human runs before publishing, and these are the gate that
stops a prohibited file being merged in the first place."""
from __future__ import annotations
import pathlib
import json
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
    """The paper itself, and the source papers, must stay out of the repository.

    Matching any filename containing "manuscript" would now be wrong: the release ships a
    manuscript RESULTS INDEX and a manuscript TARGETS file, which are metadata about
    reported values, not manuscript text. Match the document formats and the paper
    sources instead.
    """
    doc_suffixes = {".tex", ".bib", ".docx", ".pdf"}
    # Two tracked files are named after the manuscript but contain no manuscript text:
    # an index of reported values to their frozen records, and the comparison targets.
    # They are listed explicitly so the guard stays strict for everything else.
    metadata_about_the_manuscript = {
        "docs/data/manuscript_results_index.json",
        "reproducibility/manuscript_targets.json",
    }
    bad = []
    for f in FILES:
        rel = f.relative_to(ROOT).as_posix()
        if rel in metadata_about_the_manuscript:
            continue
        if f.suffix.lower() in doc_suffixes or "manuscript" in f.name.lower():
            bad.append(rel)
    assert bad == [], f"manuscript material is tracked: {bad}"


def test_no_raw_generation_records_are_tracked():
    bad = [f.relative_to(ROOT).as_posix() for f in FILES if f.suffix == ".jsonl"]
    assert bad == [], f"raw record files are tracked: {bad}"


def test_the_only_tracked_data_files_are_the_documented_ones():
    """Every JSON the release ships is on this list, by path.

    The release now publishes outcome data on purpose. The guard that matters is that
    nothing ships which has not been reviewed and documented, so a new data file cannot
    appear without this list and the data dictionary being updated too.
    """
    allowed = {
        # released outcome data -- documented in docs/data/DATA_DICTIONARY.md
        "docs/data/fair_scoring_cells.json",
        "docs/data/fair_scoring_support.json",
        "docs/data/public_sufficient_statistics.json",
        "docs/data/research_results.json",
        "docs/data/scorer_audit_items.json",
        "docs/data/manuscript_results_index.json",
        # fabricated demo input, declares itself synthetic
        "docs/data/synthetic_demo_cells.json",
        # comparison targets, read only by the reconciliation
        "reproducibility/manuscript_targets.json",
        # method configuration, not outcomes
        "configs/models.json", "prompts/questions.json",
    }
    jsons = {f.relative_to(ROOT).as_posix() for f in FILES if f.suffix == ".json"}
    assert jsons <= allowed, f"undocumented JSON data: {sorted(jsons - allowed)}"


def test_every_released_data_file_is_in_the_data_dictionary():
    """A data file nobody documented is a data file nobody reviewed."""
    dd = (ROOT / "docs/data/DATA_DICTIONARY.md")
    assert dd.exists(), "docs/data/DATA_DICTIONARY.md is missing"
    text = dd.read_text()
    missing = [f.name for f in (ROOT / "docs/data").glob("*.json")
               if f.name not in text]
    assert missing == [], f"released data files are undocumented: {missing}"


# Frozen PRIVATE records that must never be copied into the public tree verbatim. The
# release ships DERIVED, de-identified files built from these by tools/; the originals
# carry manuscript text, model output and reviewer-level judgements. Named individually so
# that copying one in by accident fails loudly.
FORBIDDEN_RESULT_NAMES = {
    "STATISTICAL_RECHECK.csv", "FAIR_LADDER_METRICS.json", "SCORER_SENSITIVITY.json",
    "RT_AUDIT_RESULTS.json", "ANTHROPIC_ACCOUNTING.json", "MISS_ANATOMY.json",
    "BLIND_SCORER_AUDIT_ITEMS.json", "RELATION_TARGETED_AUDIT_SAMPLE.json",
    "FINAL_NUMBERS.json", "FINAL_PROVENANCE_MAP.json", "NATURAL_ERROR_LEDGER.json",
}


def test_no_private_frozen_record_is_tracked():
    bad = [f.relative_to(ROOT).as_posix() for f in FILES
           if f.name in FORBIDDEN_RESULT_NAMES]
    assert bad == [], f"private frozen records are tracked verbatim: {bad}"


def test_no_study_value_is_hard_coded_in_page_or_analysis_code():
    """The release publishes the study's results as DATA. That makes it more important,
    not less, that no analysis path can produce them without computing them.

    A value typed into the page scripts or into an estimator would make the site look
    reproducible while being a lookup table. Tests may assert these values -- that is what
    a test is for -- and reproducibility/manuscript_targets.json declares them openly as
    comparison targets, which is why those are excluded.

    The strings are assembled from fragments so this file does not itself trip the scan.
    """
    values = ["12" + ".752", "12" + ".8 pp", "+0" + ".460", "-0" + ".733",
              "\u2212" + "0.733", "29" + ".87", "13" + ".14", "394/" + "909",
              "95/" + "909", "15" + ".44", "70" + ".7", "79" + ".1"]
    # Where a hard-coded result would actually be a lie about reproduction.
    guarded = ("docs/assets/", "src/analysis/", "reproducibility/estimators.py",
               "reproducibility/bootstrap.py", "reproducibility/contrasts.py",
               "reproducibility/data.py")
    bad = []
    for f in scannable():
        rel = f.relative_to(ROOT).as_posix()
        if not rel.startswith(guarded):
            continue
        t = read(f)
        for v in values:
            if v in t:
                bad.append(f"{rel}: {v!r}")
    assert bad == [], (
        f"a study result value is hard-coded where it must be computed: {bad}")


def test_the_targets_file_is_never_read_by_an_analysis_module():
    """manuscript_targets.json is for comparison only. If an estimator read it, the
    reconciliation would be checking the targets against themselves."""
    for name in ("estimators.py", "bootstrap.py", "contrasts.py", "data.py"):
        f = ROOT / "reproducibility" / name
        if f.exists():
            assert "manuscript_targets" not in read(f), (
                f"reproducibility/{name} reads the manuscript targets file")


def test_the_shipped_fixture_is_marked_synthetic():
    f = ROOT / "docs/data/synthetic_demo_cells.json"
    if not f.exists():
        return
    doc = json.loads(f.read_text())
    assert doc.get("synthetic") is True
    assert "warning" in doc


def test_no_manuscript_identifier_reaches_the_published_data():
    for f in (ROOT / "docs/data").glob("*.json"):
        assert not re.search(r"\b\d{4}\.\d{4,5}\b", f.read_text()), \
            f"{f.name} contains something shaped like an arXiv identifier"


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
