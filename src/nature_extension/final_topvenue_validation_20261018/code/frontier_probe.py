#!/usr/bin/env python3
"""2A: read-only probe of what each provider actually offers this account.

Costs nothing: lists models and, where the provider exposes it, batch support. Writes the
immutable snapshot identifiers into the frozen manifest. NEVER prints, logs or stores a key.

    python frontier_probe.py --provider openai
    python frontier_probe.py --provider anthropic
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
MANP = OUT / "frontier/FRONTIER_LADDER_MANIFEST.json"


def probe_openai():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return {"error": "OPENAI_API_KEY not set"}
    from openai import OpenAI
    c = OpenAI()
    models = sorted(m.id for m in c.models.list().data)
    return {"n_models": len(models), "models": models,
            "batch_api": "available on this account" if any("batch" in m for m in models)
                         else "not determinable from the models list; see /v1/batches"}


def probe_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"error": "ANTHROPIC_API_KEY not set"}
    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic SDK not installed: pip install anthropic"}
    c = anthropic.Anthropic()
    page = c.models.list(limit=100)
    return {"n_models": len(page.data),
            "models": [{"id": m.id, "display_name": getattr(m, "display_name", ""),
                        "created_at": str(getattr(m, "created_at", ""))} for m in page.data]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=["openai", "anthropic"])
    ap.add_argument("--write-manifest", action="store_true",
                    help="record the chosen model id into the frozen manifest")
    ap.add_argument("--chosen-model", default=None)
    a = ap.parse_args()

    info = probe_openai() if a.provider == "openai" else probe_anthropic()
    if "error" in info:
        print(f"{a.provider}: {info['error']}")
        return 1
    print(f"{a.provider}: {info['n_models']} models visible to this account")
    for m in info["models"]:
        print("  ", m if isinstance(m, str) else f"{m['id']:44} {m.get('display_name','')}")

    p = OUT / f"data/FRONTIER_PROBE_{a.provider}.json"
    p.write_text(json.dumps(info, indent=1) + "\n")
    print(f"\nwrote {p.name} (no credential is stored in it)")

    if a.write_manifest:
        if not a.chosen_model:
            print("--write-manifest requires --chosen-model"); return 2
        man = json.loads(MANP.read_text())
        man["models"][a.provider]["model_id"] = a.chosen_model
        man["models"][a.provider]["snapshot_id"] = a.chosen_model
        man["models"][a.provider]["recorded_from"] = "provider models endpoint, not documentation"
        MANP.write_text(json.dumps(man, indent=1) + "\n")
        print(f"recorded {a.chosen_model} into the manifest for {a.provider}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
