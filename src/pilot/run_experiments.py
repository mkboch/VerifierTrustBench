from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

from common import ROOT, load_json, read_jsonl, append_jsonl
from verifier import blind_verify, targeted_verify

def stable_seed(*parts: str) -> int:
    h = hashlib.sha256("||".join(parts).encode()).hexdigest()
    return 1000 + (int(h[:8], 16) % 900000)

def existing_keys(path: Path) -> set[str]:
    return {
        str(x.get("_key"))
        for x in read_jsonl(path)
        if x.get("_key")
    }

def record(path: Path, key: str, fn):
    keys = existing_keys(path)

    if key in keys:
        print(f"[skip] {key}")
        return

    print(f"[run]  {key}")

    try:
        obj = fn()
        obj["_key"] = key
        append_jsonl(path, obj)

    except Exception as e:
        append_jsonl(
            path,
            {
                "_key": key,
                "_error": repr(e),
            },
        )

        print(f"[error] {key}: {e}", file=sys.stderr)

def read_paper(relpath: str) -> str:
    return (ROOT / relpath).read_text(errors="ignore")

def source_index(run_dir: Path):
    idx = {}

    for x in read_jsonl(run_dir / "source_judgments.jsonl"):
        if x.get("_error"):
            continue

        idx[
            (
                x.get("model"),
                x.get("case_id"),
                x.get("state"),
            )
        ] = x

    return idx

def blind_index(run_dir: Path):
    idx = {}

    for x in read_jsonl(run_dir / "blind.jsonl"):
        if x.get("_error"):
            continue

        idx[
            (
                x.get("model"),
                x.get("paper_id"),
            )
        ] = x

    return idx

def pair_type(source: str, target: str, models: dict) -> str:
    if source == target:
        return "same_exact_model"

    if models[source]["family"] == models[target]["family"]:
        return "same_family"

    return "cross_family"

def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--phase",
        choices=["qwen27", "small"],
        required=True,
    )

    ap.add_argument(
        "--run-dir",
        required=True,
    )

    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    models = load_json(ROOT / "configs/models.json")
    ledger = load_json(ROOT / "data/ledger.json")

    current = [
        m
        for m, cfg in models.items()
        if cfg["phase"] == args.phase
    ]

    # ----------------------------------------------------------
    # 1. Blind whole-paper verification
    # ----------------------------------------------------------

    for model in current:
        ep = models[model]["endpoint"]

        base_rel = ledger["base_paper"]

        record(
            run_dir / "blind.jsonl",
            f"blind::{model}::clean",
            lambda m=model, e=ep, p=base_rel: {
                "model": m,
                "paper_id": "clean",
                "state": "clean",
                "result": blind_verify(
                    e,
                    read_paper(p),
                    seed=stable_seed("blind", m, "clean"),
                ),
            },
        )

        for case in ledger["cases"]:
            rel = case["defective_path"]
            pid = f'{case["case_id"]}_defective'

            record(
                run_dir / "blind.jsonl",
                f"blind::{model}::{pid}",
                lambda m=model, e=ep, p=rel, pid=pid,
                       cid=case["case_id"]: {
                    "model": m,
                    "paper_id": pid,
                    "case_id": cid,
                    "state": "defective",
                    "result": blind_verify(
                        e,
                        read_paper(p),
                        seed=stable_seed("blind", m, pid),
                    ),
                },
            )

    # ----------------------------------------------------------
    # 2. Independent targeted verification
    # ----------------------------------------------------------

    for model in current:
        ep = models[model]["endpoint"]

        for case in ledger["cases"]:
            settings = [
                (
                    "defective",
                    case["defective_path"],
                    "ISSUE_PRESENT",
                ),
                (
                    "repaired",
                    case["repaired_path"],
                    "NO_ISSUE",
                ),
            ]

            for state, rel, truth in settings:
                key = (
                    f"source::{model}::"
                    f"{case['case_id']}::{state}"
                )

                record(
                    run_dir / "source_judgments.jsonl",
                    key,
                    lambda m=model, e=ep, c=case,
                           s=state, p=rel, t=truth: {
                        "model": m,
                        "case_id": c["case_id"],
                        "state": s,
                        "truth": t,
                        "neutral_question": c["neutral_question"],
                        "allegation": c["allegation"],
                        "result": targeted_verify(
                            e,
                            read_paper(p),
                            c["neutral_question"],
                            condition="neutral",
                            seed=stable_seed(
                                "source",
                                m,
                                c["case_id"],
                                s,
                            ),
                        ),
                    },
                )

    src = source_index(run_dir)

    # ----------------------------------------------------------
    # 3. Real verifier -> verifier exposure
    # ----------------------------------------------------------

    if args.phase == "qwen27":
        pairs = [
            ("qwen38_27", "qwen38_27"),
            ("qwen36_27", "qwen36_27"),
            ("qwen38_27", "qwen36_27"),
            ("qwen36_27", "qwen38_27"),
        ]

    else:
        pairs = [
            ("qwen3_8", "qwen3_8"),
            ("llama31_8", "llama31_8"),
            ("mistral7", "mistral7"),
            ("phi4mini", "phi4mini"),

            ("qwen38_27", "qwen3_8"),

            ("qwen38_27", "llama31_8"),
            ("qwen38_27", "mistral7"),
            ("qwen38_27", "phi4mini"),

            ("llama31_8", "mistral7"),
            ("mistral7", "phi4mini"),
            ("phi4mini", "llama31_8"),
        ]

    for source, target in pairs:
        if target not in current:
            continue

        ep = models[target]["endpoint"]

        for case in ledger["cases"]:
            settings = [
                (
                    "defective",
                    case["defective_path"],
                    "ISSUE_PRESENT",
                ),
                (
                    "repaired",
                    case["repaired_path"],
                    "NO_ISSUE",
                ),
            ]

            for state, rel, truth in settings:
                srec = src.get(
                    (
                        source,
                        case["case_id"],
                        state,
                    )
                )

                if not srec or srec.get("_error"):
                    continue

                sres = srec["result"]
                sver = sres.get(
                    "verdict",
                    "UNRESOLVED",
                )
                sreason = sres.get(
                    "brief_reason",
                    "",
                )

                for cond in (
                    "actual_verdict",
                    "actual_rationale",
                ):
                    key = (
                        f"pair::{source}->{target}::"
                        f"{case['case_id']}::{state}::{cond}"
                    )

                    record(
                        run_dir / "pair_trials.jsonl",
                        key,
                        lambda so=source, ta=target,
                               e=ep, c=case, s=state,
                               p=rel, t=truth,
                               sv=sver, sr=sreason,
                               co=cond: {
                            "source_model": so,
                            "target_model": ta,
                            "pair_type": pair_type(
                                so,
                                ta,
                                models,
                            ),
                            "case_id": c["case_id"],
                            "state": s,
                            "truth": t,
                            "condition": co,
                            "source_verdict": sv,
                            "source_reason": sr,
                            "result": targeted_verify(
                                e,
                                read_paper(p),
                                c["neutral_question"],
                                condition=co,
                                source_verdict=sv,
                                source_reason=sr,
                                source_name=so,
                                seed=stable_seed(
                                    "pair",
                                    so,
                                    ta,
                                    c["case_id"],
                                    s,
                                    co,
                                ),
                            ),
                        },
                    )

    # ----------------------------------------------------------
    # 4. Controlled correct/wrong prior-verdict exposure
    # ----------------------------------------------------------

    for target in current:
        ep = models[target]["endpoint"]

        for case in ledger["cases"]:
            settings = [
                (
                    "defective",
                    case["defective_path"],
                    "ISSUE_PRESENT",
                ),
                (
                    "repaired",
                    case["repaired_path"],
                    "NO_ISSUE",
                ),
            ]

            for state, rel, truth in settings:
                wrong = (
                    "NO_ISSUE"
                    if truth == "ISSUE_PRESENT"
                    else "ISSUE_PRESENT"
                )

                controlled = [
                    (
                        "forced_correct",
                        truth,
                    ),
                    (
                        "forced_wrong",
                        wrong,
                    ),
                ]

                for cond, prior in controlled:
                    key = (
                        f"controlled::{target}::"
                        f"{case['case_id']}::{state}::{cond}"
                    )

                    record(
                        run_dir / "controlled_exposure.jsonl",
                        key,
                        lambda ta=target, e=ep, c=case,
                               s=state, p=rel, t=truth,
                               co=cond, pr=prior: {
                            "target_model": ta,
                            "case_id": c["case_id"],
                            "state": s,
                            "truth": t,
                            "condition": co,
                            "source_verdict": pr,
                            "result": targeted_verify(
                                e,
                                read_paper(p),
                                c["neutral_question"],
                                condition=co,
                                source_verdict=pr,
                                source_name="controlled-prior",
                                seed=stable_seed(
                                    "controlled",
                                    ta,
                                    c["case_id"],
                                    s,
                                    co,
                                ),
                            ),
                        },
                    )

    # ----------------------------------------------------------
    # 5. Cross-check real blind findings on the clean paper
    # ----------------------------------------------------------

    bidx = blind_index(run_dir)

    if args.phase == "qwen27":
        natural_pairs = [
            ("qwen38_27", "qwen36_27"),
            ("qwen36_27", "qwen38_27"),
        ]
    else:
        natural_pairs = [
            ("qwen3_8", "llama31_8"),
            ("llama31_8", "mistral7"),
            ("mistral7", "phi4mini"),
        ]

    clean_text = read_paper(
        ledger["base_paper"]
    )

    for source, target in natural_pairs:
        if target not in current:
            continue

        brec = bidx.get(
            (
                source,
                "clean",
            )
        )

        if not brec:
            continue

        findings = (
            brec
            .get("result", {})
            .get("findings", [])
        )[:4]

        ep = models[target]["endpoint"]

        for i, f in enumerate(findings):
            location = str(
                f.get(
                    "location",
                    "the cited location",
                )
            )

            category = str(
                f.get(
                    "category",
                    "scientific consistency",
                )
            )

            allegation = str(
                f.get(
                    "allegation",
                    "",
                )
            )

            reason = "; ".join(
                str(x)
                for x in f.get(
                    "evidence_quotes",
                    [],
                )[:2]
            )

            neutral = (
                f"Inspect {location}. "
                f"Is there a checkable {category} defect there? "
                f"Do not assume that a defect exists."
            )

            key = (
                f"natural::{source}->{target}::"
                f"{i}::location_only"
            )

            record(
                run_dir / "natural_crosscheck.jsonl",
                key,
                lambda so=source, ta=target,
                       e=ep, q=neutral, ii=i: {
                    "source_model": so,
                    "target_model": ta,
                    "finding_index": ii,
                    "condition": "location_only",
                    "result": targeted_verify(
                        e,
                        clean_text,
                        q,
                        condition="neutral",
                        seed=stable_seed(
                            "natural",
                            so,
                            ta,
                            str(ii),
                            "neutral",
                        ),
                    ),
                },
            )

            key = (
                f"natural::{source}->{target}::"
                f"{i}::allegation_plus_evidence"
            )

            record(
                run_dir / "natural_crosscheck.jsonl",
                key,
                lambda so=source, ta=target,
                       e=ep, q=neutral,
                       a=allegation, r=reason,
                       ii=i: {
                    "source_model": so,
                    "target_model": ta,
                    "finding_index": ii,
                    "condition":
                        "allegation_plus_evidence",
                    "source_allegation": a,
                    "source_reason": r,
                    "result": targeted_verify(
                        e,
                        clean_text,
                        q,
                        condition="actual_rationale",
                        source_verdict="ISSUE_PRESENT",
                        source_reason=(
                            a
                            + " Evidence cited by source: "
                            + r
                        ),
                        source_name=so,
                        seed=stable_seed(
                            "natural",
                            so,
                            ta,
                            str(ii),
                            "rationale",
                        ),
                    ),
                },
            )

    print(
        f"[phase complete] "
        f"{args.phase} -> {run_dir}"
    )

if __name__ == "__main__":
    main()
