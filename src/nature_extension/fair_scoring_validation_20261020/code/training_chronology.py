#!/usr/bin/env python3
"""Section 10: training chronology from documentary records only.

Checkpoint dates come from the Hugging Face model API for the EXACT repository that was
served, not from a vendor blog post or from memory. Manuscript posting dates come from the
arXiv API v1 <published> timestamp. No inference is run.

A checkpoint published BEFORE a manuscript first appeared cannot contain that manuscript.
That is the only contamination argument this file makes. It does not claim the converse,
and where the ordering runs the other way the case is recorded as NOT RULED OUT.
"""
from __future__ import annotations
import json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
TV = ROOT / "nature_extension/final_topvenue_validation_20261018"
sys.path.insert(0, str(ROOT / "exp2bbroad"))
import models_broad as MB  # noqa: E402

LEDGER = json.loads((ROOT / "exp3heldout/ledger.json").read_text())
PAPERS = LEDGER["papers"]
SYSTEMS = ["qwen38_27", "qwen36_27", "gemma4_12", "granite42_30", "qwen3_8"]
UPSTREAM = {"cyankiwi/Qwen3.8-27B-AWQ-INT4": "Qwen/Qwen3.8-27B",
            "QuantTrio/Qwen3.6-27B-AWQ": "Qwen/Qwen3.6-27B"}


def hf(repo):
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}", timeout=60) as f:
        d = json.load(f)
    return {"repo": repo, "created_utc": d.get("createdAt"),
            "last_modified_utc": d.get("lastModified"), "head_sha": d.get("sha")}


def cutoff(repo):
    """Look for a documented training cutoff in the model card. Absence is reported as
    unknown, never as a date inferred from the release."""
    try:
        with urllib.request.urlopen(f"https://huggingface.co/{repo}/raw/main/README.md",
                                    timeout=60) as f:
            t = f.read().decode("utf-8", "replace")
    except Exception:
        return {"documented_training_cutoff": "unknown", "basis": "model card not retrievable"}
    hits = [l.strip() for l in t.split("\n")
            if re.search(r"cut[- ]?off date|training cut[- ]?off|data.*cut[- ]?off", l, re.I)]
    if hits:
        return {"documented_training_cutoff": hits[0][:300], "basis": "model card"}
    return {"documented_training_cutoff": "unknown",
            "basis": f"model card retrieved ({len(t)} chars) and contains no training-cutoff "
                     f"statement"}


# ---- manuscripts
ids = ",".join(PAPERS)
with urllib.request.urlopen(
        f"http://export.arxiv.org/api/query?id_list={ids}&max_results=100", timeout=90) as f:
    xml = f.read().decode()
posted = {}
for e in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
    aid = re.search(r"<id>http://arxiv\.org/abs/([0-9.]+)v\d+</id>", e).group(1)
    posted[aid] = re.search(r"<published>(.*?)</published>", e).group(1)
missing = [p for p in PAPERS if p not in posted]
first, last = min(posted.values()), max(posted.values())

# ---- checkpoints
rows = {}
for s in SYSTEMS:
    served = MB.MODELS[s]["root"]
    rec = {"served_repository": served, "served_revision_pinned":
           MB.MODELS[s].get("revision"), "served": hf(served)}
    rec.update(cutoff(served))
    up = UPSTREAM.get(served)
    if up:
        rec["upstream_base_repository"] = up
        rec["upstream"] = hf(up)
        rec.update({"upstream_" + k: v for k, v in cutoff(up).items()})
    ref = (rec.get("upstream") or rec["served"])["created_utc"]
    rec["chronology_reference_date"] = ref
    rec["reference_basis"] = ("upstream base checkpoint publication"
                              if up else "served checkpoint publication")
    after = [p for p, d in posted.items() if d > ref]
    rec["manuscripts_posted_after_this_checkpoint"] = len(after)
    rec["manuscripts_posted_before_this_checkpoint"] = len(posted) - len(after)
    if len(after) == len(posted):
        rec["memorization_status"] = "TEMPORALLY_RULED_OUT"
        rec["statement"] = (f"Every one of the {len(posted)} held-out manuscripts was first "
                            f"posted after this checkpoint was published, so direct "
                            f"memorization of them by this frozen checkpoint is temporally "
                            f"ruled out under the documented chronology.")
    elif not after:
        rec["memorization_status"] = "NOT_RULED_OUT"
        rec["statement"] = ("This checkpoint was published after every held-out manuscript "
                            "had appeared. Direct memorization is not ruled out by "
                            "chronology, and no training cutoff is documented, so it cannot "
                            "be ruled out on any other documentary basis either.")
    else:
        rec["memorization_status"] = "PARTIALLY_RULED_OUT"
        rec["statement"] = (f"{len(after)} of {len(posted)} manuscripts postdate this "
                            f"checkpoint and are temporally ruled out; the remaining "
                            f"{len(posted) - len(after)} are not.")
    rows[s] = rec

# ---- frontier
fman = json.loads((TV / "frontier/FRONTIER_LADDER_MANIFEST.json").read_text())
snap = fman["models"]["openai"]["snapshot_id"]
m = re.search(r"(\d{4}-\d{2}-\d{2})$", snap)
snap_date = m.group(1) + "T00:00:00Z" if m else None
gpt = {"model_id": fman["models"]["openai"]["model_id"], "snapshot_id": snap,
       "snapshot_date": snap_date,
       "snapshot_recorded_from": fman["models"]["openai"]["recorded_from"],
       "snapshot_confirmed_at_runtime": True,
       "runtime_confirmation": "the E1 runner aborts unless the API's resolved model field "
                               "equals this snapshot; it returned gpt-5.2-2025-12-11",
       "documented_training_cutoff": "unknown — the provider publishes no training cutoff for "
                                     "this snapshot",
       }
if snap_date:
    after = [p for p, d in posted.items() if d > snap_date]
    gpt["manuscripts_posted_after_snapshot"] = len(after)
    gpt["memorization_status"] = ("TEMPORALLY_RULED_OUT" if len(after) == len(posted)
                                  else "NOT_RULED_OUT")
    gpt["statement"] = (
        f"The snapshot is dated {m.group(1)}. All {len(posted)} held-out manuscripts were "
        f"first posted between {first[:10]} and {last[:10]}, every one of them after that "
        f"date. Direct memorization of these manuscripts in this frozen checkpoint's training "
        f"data is therefore temporally ruled out under the documented chronology."
        if len(after) == len(posted) else
        f"{len(posted) - len(after)} manuscripts predate the snapshot; memorization is not "
        f"ruled out for those.")

payload = {
    "label": "TRAINING_CHRONOLOGY_FINAL",
    "sources": {"checkpoints": "Hugging Face model API, the exact served repository",
                "manuscripts": "arXiv API, v1 <published> timestamp",
                "frontier_snapshot": "provider models endpoint, recorded at selection time and "
                                     "re-confirmed by the live API during the E1 run"},
    "no_inference_run": True,
    "manuscripts": {"n": len(PAPERS), "n_resolved": len(posted), "unresolved": missing,
                    "first_posted_utc": first, "last_posted_utc": last,
                    "posted_utc": dict(sorted(posted.items()))},
    "open_weight": rows,
    "frontier_gpt_5_2": gpt,
    "caveat": "A release date bounds only what could have been in a checkpoint published on "
              "that date. It says nothing about continued or pre-release training, and no "
              "training cutoff is documented for any system here. Where the ordering does not "
              "rule memorization out, this file says so rather than arguing from silence.",
}
(OUT / "data/TRAINING_CHRONOLOGY.json").write_text(json.dumps(payload, indent=1) + "\n")

print(f"manuscripts: {len(posted)}/{len(PAPERS)} resolved, {first[:10]} .. {last[:10]}")
for s, r in rows.items():
    print(f"{s:14s} ref={r['chronology_reference_date'][:10]}  "
          f"after={r['manuscripts_posted_after_this_checkpoint']:2d}/{len(posted)}  "
          f"{r['memorization_status']}")
print(f"{'gpt-5.2':14s} ref={gpt['snapshot_date'][:10]}  "
      f"after={gpt['manuscripts_posted_after_snapshot']:2d}/{len(posted)}  "
      f"{gpt['memorization_status']}")
