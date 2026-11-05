#!/usr/bin/env python3
"""G: training-data contamination chronology.

Factual question: were the held-out manuscripts first posted AFTER the frozen checkpoint was
released? Where the documented chronology supports it, direct memorisation of those manuscripts
in that checkpoint's training data is temporally impossible. Where it does not, or where the
release date is undocumented in the frozen artifacts, that is stated as unavailable rather than
guessed.

Model release dates and training cutoffs are NOT recorded in the frozen artifacts. This script
therefore reports what the artifacts DO pin down (exact repository, revision hash where recorded,
and the manuscript posting dates) and marks every undocumented field explicitly.
"""
from __future__ import annotations
import csv, json, sys, datetime, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2bbroad")); sys.path.insert(0, str(ROOT / "exp2b"))
import models_broad as MB  # noqa: E402

LED = json.loads((ROOT / "exp3heldout/ledger.json").read_text())
papers = sorted(LED["domains"])

meta = {}
for line in (ROOT / "exp3heldout/pool/meta.jsonl").read_text().splitlines():
    if line.strip():
        r = json.loads(line)
        meta[r["id"]] = r


def parse_date(s):
    for f in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


rows = []
for p in papers:
    m = meta.get(p, {})
    d = parse_date(m.get("v1_date", "")) if m.get("v1_date") else None
    rows.append({"arxiv_id": p, "domain": LED["domains"][p], "v1_date_raw": m.get("v1_date", "UNAVAILABLE"),
                 "v1_date_iso": d.isoformat() if d else "UNAVAILABLE",
                 "listing_month": m.get("listing_month", "UNAVAILABLE")})

dates = [datetime.date.fromisoformat(r["v1_date_iso"]) for r in rows if r["v1_date_iso"] != "UNAVAILABLE"]
earliest, latest = min(dates), max(dates)
print(f"held-out manuscripts: {len(rows)}")
print(f"first-posted range: {earliest.isoformat()} to {latest.isoformat()}")
print(f"all dates recovered: {len(dates)}/{len(rows)}")

MODELS = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8",
          "mistral_small32", "olmo31_32", "llama33_70awq", "gptoss_20", "glm4_32",
          "exaone45_33", "seedoss_36"]
mrows = []
for m in MODELS:
    c = MB.MODELS[m]
    mrows.append({
        "system": m, "repository": c.get("root", "UNAVAILABLE"),
        "revision_pinned_in_artifacts": c.get("revision") or "NOT_RECORDED",
        "params_b": c.get("params_b"), "quantization": c.get("quantization", "none"),
        "role": "primary" if m in ("qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8") else "broad_replication",
        "release_date_documented_in_artifacts": "UNAVAILABLE",
        "training_cutoff_documented_in_artifacts": "UNAVAILABLE",
    })

print(f"\n{'system':18}{'repository':46}{'revision':14}{'release/cutoff'}")
for r in mrows:
    print(f"{r['system']:18}{r['repository']:46}{str(r['revision_pinned_in_artifacts'])[:12]:14}"
          f"{'UNAVAILABLE in frozen artifacts'}")

out = {
    "question": ("Were the held-out manuscripts first posted after the frozen model checkpoints "
                 "were released? If so, direct memorisation of those manuscripts in those "
                 "checkpoints' training data is temporally impossible."),
    "manuscripts": {"n": len(rows), "earliest_v1": earliest.isoformat(),
                    "latest_v1": latest.isoformat(), "rows": rows},
    "models": mrows,
    "what_the_artifacts_pin_down": [
        "the exact Hugging Face repository for every system",
        "a pinned revision hash for 8 of the 12 systems",
        "the arXiv v1 posting date for all 21 held-out manuscripts",
    ],
    "what_the_artifacts_do_NOT_pin_down": [
        "model release dates",
        "training-data cutoffs",
        "whether any provider performed undocumented continued training",
    ],
    "conclusion_status": "CANNOT_BE_CONCLUDED_FROM_FROZEN_ARTIFACTS_ALONE",
    "required_to_complete": (
        "Release dates and documented cutoffs must be taken from each model card / release record "
        "and cited in the manuscript. Only then can the temporal-impossibility statement be made, "
        "and only for the systems whose documented release predates "
        f"{earliest.isoformat()} (the earliest held-out manuscript)."),
    "caveats": [
        "A pinned revision fixes the weights we served, not the data they were trained on.",
        "For any system whose provider may have performed continued training on undisclosed data, "
        "the temporal argument cannot be made and uncertainty must be stated.",
        "Temporal impossibility of MEMORISING THESE MANUSCRIPTS does not exclude contamination by "
        "closely related earlier work, nor does it address the defect perturbations, which were "
        "generated by this project and have never been published.",
        "The defect perturbations (E0/E2) are novel by construction: they were created by the "
        "frozen miner from manuscripts posted after the corpus window opened, so no checkpoint "
        "can have seen the perturbed text regardless of its cutoff.",
    ],
}
json.dump(out, (OUT / "data/CONTAMINATION_CHRONOLOGY.json").open("w"), indent=1)
with (OUT / "data/MANUSCRIPT_DATES.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
with (OUT / "data/MODEL_CHECKPOINTS.csv").open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(mrows[0])); w.writeheader(); w.writerows(mrows)
print(f"\nSTATUS: {out['conclusion_status']}")
print("wrote data/CONTAMINATION_CHRONOLOGY.json, MANUSCRIPT_DATES.csv, MODEL_CHECKPOINTS.csv")
