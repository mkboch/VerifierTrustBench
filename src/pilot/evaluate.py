from __future__ import annotations
import argparse
import collections
import csv
import json
import math
from pathlib import Path

from common import ROOT, load_json, read_jsonl

def correct(verdict: str, truth: str) -> bool:
    return verdict == truth

def pct(a, b):
    return 100.0 * a / b if b else float("nan")

def fmt(x):
    if isinstance(x, float) and math.isnan(x):
        return "NA"

    if isinstance(x, float):
        return f"{x:.1f}%"

    return str(x)

def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--run-dir",
        required=True,
    )

    args = ap.parse_args()

    rd = Path(args.run_dir)

    models = load_json(
        ROOT / "configs/models.json"
    )

    ledger = load_json(
        ROOT / "data/ledger.json"
    )

    src = read_jsonl(
        rd / "source_judgments.jsonl"
    )

    pair = read_jsonl(
        rd / "pair_trials.jsonl"
    )

    ctl = read_jsonl(
        rd / "controlled_exposure.jsonl"
    )

    blind = read_jsonl(
        rd / "blind.jsonl"
    )

    nat = read_jsonl(
        rd / "natural_crosscheck.jsonl"
    )

    md = []

    md.append(
        "# VerifierTrustBench Results\n"
    )

    md.append(
        "This report distinguishes **independent correctness** "
        "from simple agreement. Controlled defect/repaired pairs "
        "provide ground truth.\n"
    )

    # ==========================================================
    # 1. Baseline independent verification
    # ==========================================================

    md.append(
        "## 1. Independent targeted verification\n"
    )

    rows = []

    for m in models:
        rr = [
            x
            for x in src
            if x.get("model") == m
            and not x.get("_error")
        ]

        if not rr:
            continue

        n = len(rr)

        ok = sum(
            correct(
                x["result"].get("verdict"),
                x["truth"],
            )
            for x in rr
        )

        unr = sum(
            x["result"].get("verdict")
            == "UNRESOLVED"
            for x in rr
        )

        false_cases = [
            x
            for x in rr
            if x["truth"] == "NO_ISSUE"
        ]

        fp = sum(
            x["result"].get("verdict")
            == "ISSUE_PRESENT"
            for x in false_cases
        )

        true_cases = [
            x
            for x in rr
            if x["truth"] == "ISSUE_PRESENT"
        ]

        tp = sum(
            x["result"].get("verdict")
            == "ISSUE_PRESENT"
            for x in true_cases
        )

        rows.append(
            (
                m,
                n,
                pct(ok, n),
                pct(tp, len(true_cases)),
                pct(fp, len(false_cases)),
                pct(unr, n),
            )
        )

    md.append(
        "| Model | N | Accuracy | True-defect confirm | "
        "False-confirm on repaired | Unresolved |"
    )

    md.append(
        "|---|---:|---:|---:|---:|---:|"
    )

    for r in rows:
        md.append(
            f"| {r[0]} | {r[1]} | {fmt(r[2])} | "
            f"{fmt(r[3])} | {fmt(r[4])} | {fmt(r[5])} |"
        )

    md.append("")

    # ==========================================================
    # 2. Controlled prior influence
    # ==========================================================

    md.append(
        "## 2. Controlled prior-verdict influence\n"
    )

    srcidx = {
        (
            x.get("model"),
            x.get("case_id"),
            x.get("state"),
        ): x
        for x in src
        if not x.get("_error")
    }

    groups = collections.defaultdict(list)

    for x in ctl:
        if x.get("_error"):
            continue

        groups[
            (
                x["target_model"],
                x["condition"],
            )
        ].append(x)

    md.append(
        "| Target | Condition | Accuracy | "
        "Harmful flips vs neutral | "
        "Beneficial recoveries vs neutral |"
    )

    md.append(
        "|---|---|---:|---:|---:|"
    )

    for (m, cond), rr in sorted(groups.items()):
        ok = sum(
            correct(
                x["result"].get("verdict"),
                x["truth"],
            )
            for x in rr
        )

        harm = 0
        benef = 0
        den = 0

        for x in rr:
            b = srcidx.get(
                (
                    m,
                    x["case_id"],
                    x["state"],
                )
            )

            if not b:
                continue

            bv = b["result"].get(
                "verdict"
            )

            tv = x["result"].get(
                "verdict"
            )

            den += 1

            if (
                correct(bv, x["truth"])
                and
                not correct(tv, x["truth"])
            ):
                harm += 1

            if (
                not correct(bv, x["truth"])
                and
                correct(tv, x["truth"])
            ):
                benef += 1

        md.append(
            f"| {m} | {cond} | "
            f"{fmt(pct(ok, len(rr)))} | "
            f"{fmt(pct(harm, den))} | "
            f"{fmt(pct(benef, den))} |"
        )

    md.append("")

    # ==========================================================
    # 3. Actual verifier -> verifier influence
    # ==========================================================

    md.append(
        "## 3. Actual verifier-to-verifier influence\n"
    )

    groups = collections.defaultdict(list)

    for x in pair:
        if x.get("_error"):
            continue

        groups[
            (
                x["pair_type"],
                x["condition"],
            )
        ].append(x)

    md.append(
        "| Pair type | Exposure | N | Target accuracy | "
        "Source wrong cases | Target follows wrong source |"
    )

    md.append(
        "|---|---|---:|---:|---:|---:|"
    )

    for (pt, cond), rr in sorted(groups.items()):
        ok = sum(
            correct(
                x["result"].get("verdict"),
                x["truth"],
            )
            for x in rr
        )

        sw = [
            x
            for x in rr
            if x.get("source_verdict")
            != x["truth"]
        ]

        follow = sum(
            x["result"].get("verdict")
            == x.get("source_verdict")
            for x in sw
        )

        md.append(
            f"| {pt} | {cond} | {len(rr)} | "
            f"{fmt(pct(ok, len(rr)))} | "
            f"{len(sw)} | "
            f"{fmt(pct(follow, len(sw)))} |"
        )

    md.append("")

    # ==========================================================
    # 4. Independent correlated-error analysis
    # ==========================================================

    md.append(
        "## 4. Independent co-error by model pairing\n"
    )

    source_by_model = collections.defaultdict(dict)

    for x in src:
        if x.get("_error"):
            continue

        source_by_model[
            x["model"]
        ][
            (
                x["case_id"],
                x["state"],
            )
        ] = x

    present = [
        m
        for m in models
        if source_by_model[m]
    ]

    md.append(
        "| Model A | Model B | Relation | Shared cases | "
        "A wrong | B wrong | Both wrong | P(B wrong | A wrong) |"
    )

    md.append(
        "|---|---|---|---:|---:|---:|---:|---:|"
    )

    for i, a in enumerate(present):
        for b in present[i + 1:]:
            keys = sorted(
                set(source_by_model[a])
                &
                set(source_by_model[b])
            )

            if not keys:
                continue

            aw = 0
            bw = 0
            both = 0

            for k in keys:
                xa = source_by_model[a][k]
                xb = source_by_model[b][k]

                aerr = not correct(
                    xa["result"].get("verdict"),
                    xa["truth"],
                )

                berr = not correct(
                    xb["result"].get("verdict"),
                    xb["truth"],
                )

                aw += int(aerr)
                bw += int(berr)
                both += int(aerr and berr)

            relation = (
                "same_family"
                if models[a]["family"]
                == models[b]["family"]
                else "cross_family"
            )

            conditional = (
                fmt(pct(both, aw))
                if aw
                else "0.0%"
            )

            md.append(
                f"| {a} | {b} | {relation} | "
                f"{len(keys)} | {aw} | {bw} | "
                f"{both} | {conditional} |"
            )

    md.append("")

    # ==========================================================
    # 5. Evidence sensitivity
    # ==========================================================

    md.append(
        "## 5. Evidence sensitivity\n"
    )

    md.append(
        "A verifier passes a paired evidence test when it says "
        "ISSUE_PRESENT on the defective version and NO_ISSUE on "
        "the repaired version.\n"
    )

    md.append(
        "| Model | Complete pairs | "
        "Correct evidence-sensitive switches | Rate |"
    )

    md.append(
        "|---|---:|---:|---:|"
    )

    for m in present:
        d = source_by_model[m]
        passed = 0
        total = 0

        for c in ledger["cases"]:
            a = d.get(
                (
                    c["case_id"],
                    "defective",
                )
            )

            b = d.get(
                (
                    c["case_id"],
                    "repaired",
                )
            )

            if not a or not b:
                continue

            total += 1

            if (
                a["result"].get("verdict")
                == "ISSUE_PRESENT"
                and
                b["result"].get("verdict")
                == "NO_ISSUE"
            ):
                passed += 1

        md.append(
            f"| {m} | {total} | {passed} | "
            f"{fmt(pct(passed, total))} |"
        )

    md.append("")

    # ==========================================================
    # 6. Blind full-paper discovery
    # ==========================================================

    md.append(
        "## 6. Full-paper blind discovery on controlled defects\n"
    )

    md.append(
        "Detection below is a conservative string-based pilot audit "
        "of whether the blind finding output mentions the injected "
        "evidence terms. It is not the final semantic scorer.\n"
    )

    case_map = {
        c["case_id"]: c
        for c in ledger["cases"]
    }

    md.append(
        "| Model | Controlled defect papers | Detected | "
        "Pilot recall | Clean-paper findings |"
    )

    md.append(
        "|---|---:|---:|---:|---:|"
    )

    for m in models:
        rr = [
            x
            for x in blind
            if x.get("model") == m
            and x.get("state") == "defective"
            and not x.get("_error")
        ]

        det = 0

        for x in rr:
            c = case_map[
                x["case_id"]
            ]

            text = json.dumps(
                x.get(
                    "result",
                    {},
                ),
                ensure_ascii=False,
            ).lower()

            terms = [
                str(t).lower()
                for t in c["expected_terms"]
            ]

            if all(
                t in text
                for t in terms
            ):
                det += 1

        clean = [
            x
            for x in blind
            if x.get("model") == m
            and x.get("paper_id") == "clean"
            and not x.get("_error")
        ]

        nf = sum(
            len(
                x.get(
                    "result",
                    {},
                ).get(
                    "findings",
                    [],
                )
            )
            for x in clean
        )

        if rr or clean:
            md.append(
                f"| {m} | {len(rr)} | {det} | "
                f"{fmt(pct(det, len(rr)))} | {nf} |"
            )

    md.append("")

    # ==========================================================
    # 7. Natural cross-checks
    # ==========================================================

    valid_nat = [
        x
        for x in nat
        if not x.get("_error")
    ]

    md.append(
        "## 7. Exploratory natural cross-check\n"
    )

    md.append(
        f"Natural clean-paper cross-check trials recorded: "
        f"**{len(valid_nat)}**. These are intentionally not assigned "
        f"gold correctness unless deterministic or executable evidence "
        f"settles them. They remain unresolved rather than being "
        f"mislabeled by another model.\n"
    )

    # machine-readable summary
    with (
        rd / "baseline_summary.csv"
    ).open(
        "w",
        newline="",
    ) as f:

        w = csv.writer(f)

        w.writerow(
            [
                "model",
                "n",
                "accuracy_pct",
                "true_confirm_pct",
                "false_confirm_pct",
                "unresolved_pct",
            ]
        )

        w.writerows(rows)

    (
        rd / "REPORT.md"
    ).write_text(
        "\n".join(md)
        + "\n"
    )

    print(
        "\n".join(md)
    )

if __name__ == "__main__":
    main()
