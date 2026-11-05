"""Experiment 2B-R blind protocol: the frozen 2B blind request with a bounded output schema.

Everything is imported from the frozen Experiment 2B protocol (exp2b/protocol.py) except the JSON schema, which adds
fixed string-length limits. Scientific prompt (B1_minimal), system prompt, decoding, seeds, max_tokens and per-model
chat-template kwargs are unchanged.

Bounds are derived from the frozen B1 prompt's own length instructions ("Keep audit_notes under 300 words, each
evidence_summary under 50 words and each allegation under 40 words") at 8 characters per word, a deliberately generous
conversion (typical English prose is about 6 characters per word including the space); category is a "short label"
bounded at 80 characters. They were fixed before any 2B-R blind inference and are not tuned on any result.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "exp2b"))

import protocol as P  # noqa: E402  (frozen 2B protocol)
from client import canonical, sha256_text  # noqa: E402

PROTOCOL_VERSION = "2B-R-v1.0"
PROMPT_ID = "B1_minimal"
CHARS_PER_WORD = 8
BOUNDS = {"audit_notes": 300 * CHARS_PER_WORD, "evidence_summary": 50 * CHARS_PER_WORD,
          "allegation": 40 * CHARS_PER_WORD, "category": 80}

BLIND_SCHEMA_BR = copy.deepcopy(P.BLIND_SCHEMA)
BLIND_SCHEMA_BR["properties"]["audit_notes"]["maxLength"] = BOUNDS["audit_notes"]
_item = BLIND_SCHEMA_BR["properties"]["findings"]["items"]["properties"]
_item["evidence_summary"]["maxLength"] = BOUNDS["evidence_summary"]
_item["allegation"]["maxLength"] = BOUNDS["allegation"]
_item["category"]["maxLength"] = BOUNDS["category"]
RESPONSE_FORMAT_BLIND_BR = {"type": "json_schema", "json_schema": {"name": "blind_audit", "schema": BLIND_SCHEMA_BR}}

# The only difference from the 2B blind schema, computed rather than asserted.
SCHEMA_DIFF = {"added_maxLength": {"audit_notes": BOUNDS["audit_notes"], "findings[].evidence_summary": BOUNDS["evidence_summary"],
                                   "findings[].allegation": BOUNDS["allegation"], "findings[].category": BOUNDS["category"]},
               "unchanged": "findings maxItems 5; evidence_line_ids maxItems 6 with pattern ^L[0-9]{5}$; required fields; "
                            "additionalProperties false; field order"}


def build_blind_br(model_cfg: dict, numbered_paper: str, seed: int):
    """Identical to exp2b.protocol.build_blind(prompt_id='B1_minimal') except response_format."""
    payload, prov = P.build_blind(model_cfg, numbered_paper, seed, prompt_id=PROMPT_ID)
    payload = dict(payload)
    payload["response_format"] = RESPONSE_FORMAT_BLIND_BR
    prov = dict(prov)
    prov.update({"request_sha256": sha256_text(canonical(payload)), "block_fingerprint": sha256_text(canonical(payload)),
                 "blind_schema_sha256": sha256_text(canonical(BLIND_SCHEMA_BR)), "protocol_version": PROTOCOL_VERSION})
    return payload, prov


def _self_check():
    import json
    old = copy.deepcopy(P.BLIND_SCHEMA)
    new = copy.deepcopy(BLIND_SCHEMA_BR)
    new["properties"]["audit_notes"].pop("maxLength")
    for k in ("evidence_summary", "allegation", "category"):
        new["properties"]["findings"]["items"]["properties"][k].pop("maxLength")
    assert json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True), "schema differs beyond maxLength"


_self_check()
