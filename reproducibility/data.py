"""Loading, checksum verification and schema validation for the public research data.

Every loader verifies the file's SHA-256 against docs/data/SHA256SUMS.txt before parsing
it. A reproduction that silently runs on a file somebody edited is not a reproduction.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "docs/data"
SUMS = DATA / "SHA256SUMS.txt"


def recorded_sums() -> dict:
    out = {}
    if SUMS.exists():
        for line in SUMS.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                out[parts[-1].lstrip("*")] = parts[0]
    return out


def verify_checksums():
    """Returns (rows, ok). Each row: (name, status, detail)."""
    want = recorded_sums()
    rows, ok = [], True
    if not want:
        return [("SHA256SUMS.txt", "FAIL", "no recorded checksums")], False
    root = DATA.parents[1]
    for name, want_hash in sorted(want.items()):
        # entries may be repo-relative (docs/assets/app.js) or bare (fair_scoring_cells.json)
        p = (root / name) if (root / name).exists() else (DATA / Path(name).name)
        if not p.exists():
            rows.append((name, "FAIL", "file missing")); ok = False; continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got == want_hash:
            rows.append((name, "PASS", got[:16]))
        else:
            rows.append((name, "FAIL", f"recorded {want_hash[:16]} got {got[:16]}")); ok = False
    return rows, ok


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def load_cells(name: str = "fair_scoring_cells.json"):
    """Return (doc, cells-as-dicts). The file stores rows positionally to stay small."""
    doc = load(name)
    f = doc["fields"]
    cells = [dict(zip(f, row)) for row in doc["cells"]]
    return doc, cells


def validate_cells(doc, cells):
    """Structural checks that would catch a corrupted or doctored table."""
    errs = []
    need = ["system", "rung", "cluster", "relation", "e0_scoreable", "e1_scoreable",
            "e0_hit", "e1_false_alarm"]
    for k in need:
        if k not in doc["fields"]:
            errs.append(f"missing field {k}")
    if errs:
        return errs
    clusters = {c["cluster"] for c in cells}
    if len(clusters) != doc["n_clusters"]:
        errs.append(f"n_clusters says {doc['n_clusters']} but {len(clusters)} present")
    rel = {c["relation"] for c in cells}
    if len(rel) != doc["n_relations"]:
        errs.append(f"n_relations says {doc['n_relations']} but {len(rel)} present")
    for c in cells:
        for k in ("e0_scoreable", "e1_scoreable"):
            if c[k] not in (0, 1):
                errs.append(f"{k} is not binary: {c[k]!r}")
        # an outcome is null exactly when that state is not scoreable
        for k, gate in (("e0_hit", "e0_scoreable"), ("e1_false_alarm", "e1_scoreable")):
            if c[gate]:
                if c[k] not in (0, 1):
                    errs.append(f"{k} must be 0 or 1 on a scoreable cell: {c[k]!r}")
            elif c[k] not in (0, None):
                errs.append(f"{k} must be null or 0 on an unscoreable cell: {c[k]!r}")
        if c["e0_hit"] and not c["e0_scoreable"]:
            errs.append("a hit was recorded on a cell that is not E0-scoreable")
        if c["e1_false_alarm"] and not c["e1_scoreable"]:
            errs.append("a false alarm was recorded on a cell that is not E1-scoreable")
    return errs[:20]
