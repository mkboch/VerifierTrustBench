from __future__ import annotations
import os, shutil, subprocess
from pathlib import Path
from common import ROOT, save_json

RAW = ROOT / "papers/raw"
PREP = ROOT / "papers/prepared"
RAW.mkdir(parents=True, exist_ok=True)
PREP.mkdir(parents=True, exist_ok=True)

def strip_comments(tex: str) -> str:
    out = []

    for line in tex.splitlines():
        cut = None

        for i, ch in enumerate(line):
            if ch == "%":
                bs = 0
                j = i - 1
                while j >= 0 and line[j] == "\\":
                    bs += 1
                    j -= 1

                if bs % 2 == 0:
                    cut = i
                    break

        out.append(line if cut is None else line[:cut])

    return "\n".join(out)

def insert_before_end(tex: str, block: str) -> str:
    marker = "\\end{document}"

    if marker in tex:
        return tex.replace(marker, "\n" + block + "\n" + marker, 1)

    return tex + "\n" + block + "\n"

def obtain_paper() -> Path:
    override = os.environ.get("PAPER_SOURCE")

    if override:
        src = Path(override).expanduser().resolve()

        if not src.exists():
            raise FileNotFoundError(f"PAPER_SOURCE does not exist: {src}")

        out = PREP / "elvae_clean.tex"
        out.write_text(strip_comments(src.read_text(errors="ignore")))
        print(f"[prepare] using PAPER_SOURCE={src}")
        return out

    archive = RAW / "2608.10398.tar"
    srcdir = RAW / "2608.10398_src"

    if not srcdir.exists():
        if not archive.exists():
            url = "https://export.arxiv.org/e-print/2608.10398"
            print(f"[prepare] downloading {url}")

            subprocess.run(
                [
                    "curl",
                    "-L",
                    "--fail",
                    "--retry",
                    "3",
                    "-A",
                    "Mozilla/5.0",
                    "-o",
                    str(archive),
                    url,
                ],
                check=True,
            )

        srcdir.mkdir(exist_ok=True)

        try:
            subprocess.run(
                ["tar", "-xf", str(archive), "-C", str(srcdir)],
                check=True,
            )
        except subprocess.CalledProcessError:
            shutil.rmtree(srcdir, ignore_errors=True)
            srcdir.mkdir()

            subprocess.run(
                ["tar", "-xzf", str(archive), "-C", str(srcdir)],
                check=True,
            )

    texfiles = sorted(srcdir.rglob("*.tex"))

    if not texfiles:
        raise RuntimeError("No .tex files found in arXiv source")

    chunks = []

    for p in texfiles:
        try:
            txt = p.read_text(errors="ignore")
        except Exception:
            continue

        chunks.append(
            f"\n\n% ===== FILE: {p.relative_to(srcdir)} =====\n\n{txt}"
        )

    full = strip_comments("\n".join(chunks))

    out = PREP / "elvae_clean.tex"
    out.write_text(full)

    return out

def make_cases(clean: str) -> list[dict]:
    cases = []

    defective = insert_before_end(
        clean,
        r'''
\paragraph{Scale-matched transition analysis.}
For the same scale-matched transition ratio, the primary analysis yields 2.22.
The corresponding summary reports the same ratio as 1.69.
'''
    )

    repaired = insert_before_end(
        clean,
        r'''
\paragraph{Scale-matched transition analysis.}
For the same scale-matched transition ratio, the primary analysis yields 1.69.
The corresponding summary reports the same ratio as 1.69.
'''
    )

    cases.append(
        {
            "case_id": "number_consistency",
            "category": "cross_section_number_consistency",
            "neutral_question":
                "Inspect the scale-matched transition analysis paragraph. "
                "Do all reported values for the same transition ratio agree?",
            "allegation":
                "The scale-matched transition analysis is internally inconsistent "
                "because it reports 2.22 and 1.69 for the same transition ratio.",
            "expected_terms": ["2.22", "1.69"],
            "defective_text": defective,
            "repaired_text": repaired,
        }
    )

    defective = insert_before_end(
        clean,
        r'''
\paragraph{Relative improvement analysis.}
The score increased from 0.62 to 0.81, corresponding to a 47\% relative improvement.
'''
    )

    repaired = insert_before_end(
        clean,
        r'''
\paragraph{Relative improvement analysis.}
The score increased from 0.62 to 0.81, corresponding to a 30.6\% relative improvement.
'''
    )

    cases.append(
        {
            "case_id": "arithmetic_relative_change",
            "category": "arithmetic",
            "neutral_question":
                "Inspect the relative-improvement paragraph. Recompute the "
                "relative percentage change from the reported before and after values.",
            "allegation":
                "The paper incorrectly calls an increase from 0.62 to 0.81 "
                "a 47% relative improvement.",
            "expected_terms": ["0.62", "0.81", "47"],
            "defective_text": defective,
            "repaired_text": repaired,
        }
    )

    defective = insert_before_end(
        clean,
        r'''
\paragraph{Replication stability.}
Thirteen of twenty independent runs met the prespecified stability criterion (80\%).
'''
    )

    repaired = insert_before_end(
        clean,
        r'''
\paragraph{Replication stability.}
Thirteen of twenty independent runs met the prespecified stability criterion (65\%).
'''
    )

    cases.append(
        {
            "case_id": "proportion_mismatch",
            "category": "proportion",
            "neutral_question":
                "Inspect the replication-stability paragraph. Recompute the "
                "percentage implied by the reported count.",
            "allegation":
                "The paper incorrectly reports 13 of 20 runs as 80%.",
            "expected_terms": ["13", "20", "80"],
            "defective_text": defective,
            "repaired_text": repaired,
        }
    )

    defective = insert_before_end(
        clean,
        r'''
\paragraph{Supplementary breakdown.}
Additional breakdowns are summarized in \autoref{tab:supplementary-breakdown}.
'''
    )

    repaired = insert_before_end(
        clean,
        r'''
\paragraph{Supplementary breakdown.}
Additional breakdowns are summarized in \autoref{tab:supplementary-breakdown}.

\begin{table}[h]
\centering
\caption{Supplementary breakdown}
\label{tab:supplementary-breakdown}
\begin{tabular}{cc}
Setting & Value\\
A & 1\\
\end{tabular}
\end{table}
'''
    )

    cases.append(
        {
            "case_id": "dangling_reference",
            "category": "cross_reference",
            "neutral_question":
                "Inspect the supplementary-breakdown cross-reference. "
                "Is the referenced target actually defined in the manuscript?",
            "allegation":
                "The manuscript references tab:supplementary-breakdown "
                "but never defines that label.",
            "expected_terms": ["tab:supplementary-breakdown"],
            "defective_text": defective,
            "repaired_text": repaired,
        }
    )

    return cases

def main():
    clean_path = obtain_paper()
    clean = clean_path.read_text(errors="ignore")

    cases = make_cases(clean)
    ledger = []

    for c in cases:
        cid = c["case_id"]

        dp = PREP / f"elvae_{cid}_defective.tex"
        rp = PREP / f"elvae_{cid}_repaired.tex"

        dp.write_text(c.pop("defective_text"))
        rp.write_text(c.pop("repaired_text"))

        c["defective_path"] = str(dp.relative_to(ROOT))
        c["repaired_path"] = str(rp.relative_to(ROOT))

        ledger.append(c)

    save_json(
        ROOT / "data/ledger.json",
        {
            "base_paper": str(clean_path.relative_to(ROOT)),
            "cases": ledger,
        },
    )

    print(f"[prepare] wrote {len(ledger)} controlled defect/repaired pairs")

if __name__ == "__main__":
    main()
