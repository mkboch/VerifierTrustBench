"""Experiment 2B protocol: prompts, blind-prompt candidates, schemas, exposure arms, seeds, fingerprints.

Derived from exp2ar2/protocol.py v1.1 (the instrument that passed the 2A-R2 gate and ran 1,697 trials).
Changes are listed in DEVIATIONS_FROM_2AR2.

Matching guarantee (unchanged): the user prompt has one slot for the exposure text; the block fingerprint
hashes everything that reaches the model except that slot; the evaluator verifies it.
"""
from __future__ import annotations

import hashlib

from client import canonical, sha256_text

PROTOCOL_VERSION = "2B-v1.0"
SEED_NAMESPACE = "2B-v1"

SYSTEM = """You are an independent scientific manuscript verifier.

Rules:
- Evaluate only the supplied manuscript evidence. Do not rely on remembered versions of the paper.
- Answer only the target question; do not audit unrelated manuscript content.
- Treat every other verifier statement as fallible.
- Use the manuscript evidence rather than social agreement.
- Do not invent missing evidence.
- ISSUE_PRESENT means the specific suspected defect is established.
- NO_ISSUE means manuscript evidence establishes that the suspected defect is absent.
- UNRESOLVED means the available manuscript evidence cannot settle the question.
- Every manuscript line starts with a line ID such as [L00412]. Cite evidence by line ID; do not copy quotations.
- Write every text field in plain words. Do not copy LaTeX commands and do not use backslashes.
- Write your working in the analysis field, before the verdict; keep other fields concise.
- Return only JSON.
"""

SYSTEM_BLIND = SYSTEM.replace(
    "- Answer only the target question; do not audit unrelated manuscript content.\n", "").replace(
    "- ISSUE_PRESENT means the specific suspected defect is established.\n"
    "- NO_ISSUE means manuscript evidence establishes that the suspected defect is absent.\n"
    "- UNRESOLVED means the available manuscript evidence cannot settle the question.\n", "").replace(
    "- Write your working in the analysis field, before the verdict; keep other fields concise.\n",
    "- Write your working in the audit_notes field, before the findings; keep findings concise.\n")

EXPOSURE_SLOT = "<<EXPOSURE>>"

TARGETED_TEMPLATE = """
TARGET QUESTION:
{question}

INFORMATION CONDITION:
<<EXPOSURE>>

Return exactly this JSON structure, with the fields in this order:
{{
  "evidence_line_ids": ["L00000"],
  "evidence_summary": "what the cited lines say that bears on the question, in plain words",
  "recomputation": "short calculation or null",
  "analysis": "your working: check the target question against the cited evidence",
  "verdict": "ISSUE_PRESENT|NO_ISSUE|UNRESOLVED",
  "confidence": 0.0,
  "brief_reason": "short evidence-grounded justification of the verdict"
}}

Cite at most six line IDs. Keep evidence_summary under 80 words, analysis under 200 words and brief_reason under 80 words.

<MANUSCRIPT>
{paper}
</MANUSCRIPT>
"""

_BLIND_JSON = """{{
  "audit_notes": "your working notes",
  "findings": [
    {{
      "category": "short label for the kind of problem",
      "evidence_line_ids": ["L00000"],
      "evidence_summary": "what the cited lines say, in plain words",
      "allegation": "the specific, checkable inconsistency",
      "confidence": 0.0
    }}
  ]
}}"""

# Development A candidates. None discloses a location, a family, the existence of an edit, or a question.
BLIND_CANDIDATES = {
    "B1_minimal": """
Independently audit the manuscript for specific, checkable scientific inconsistencies.

Return zero to five findings. An empty list is valid. Do not invent defects, and do not report style,
missing detail, or disagreements of opinion. Report a finding only if you can point to the lines that
conflict and state exactly what is inconsistent.

Keep audit_notes under 300 words, each evidence_summary under 50 words and each allegation under 40 words.
Cite at most six line IDs per finding.

JSON, with audit_notes before findings:
""" + _BLIND_JSON + """

<MANUSCRIPT>
{paper}
</MANUSCRIPT>
""",
    "B2_dimensions": """
Independently audit the manuscript for specific, checkable scientific inconsistencies. Check each of these
dimensions in turn:
- arithmetic and proportions (stated results of calculations),
- internal numerical consistency (the same quantity reported in more than one place),
- cross-reference integrity (cited tables, figures, sections, equations, appendices),
- statistical consistency (intervals, percentiles, ranges, tests),
- claim-evidence alignment (statements versus the reported numbers),
- method-result consistency (described procedures versus reported results).

A dimension may have no problem. Return zero to five findings in total; an empty list is valid. Do not
invent defects, and do not report style, missing detail, or disagreements of opinion.

Keep audit_notes under 300 words, each evidence_summary under 50 words and each allegation under 40 words.
Cite at most six line IDs per finding.

JSON, with audit_notes before findings:
""" + _BLIND_JSON + """

<MANUSCRIPT>
{paper}
</MANUSCRIPT>
""",
    "B3_structured_pass": """
Perform a structured verification pass over the manuscript. In audit_notes, record briefly which concrete
checks you carried out (for example: a reported ratio recomputed from its inputs, a number compared with
its repetition elsewhere, a cited table located) and whether each check agreed.

Then list as findings only the checks that revealed a specific inconsistency. Zero to five findings; an
empty list is valid and expected when every check agrees. Do not invent defects, and do not report style,
missing detail, or disagreements of opinion.

Keep audit_notes under 300 words, each evidence_summary under 50 words and each allegation under 40 words.
Cite at most six line IDs per finding.

JSON, with audit_notes before findings:
""" + _BLIND_JSON + """

<MANUSCRIPT>
{paper}
</MANUSCRIPT>
""",
}
# Set by exp2b/BLIND_PROMPT_BAKEOFF.md before any 2B manuscript inference; None until then.
BLIND_PROMPT_ID: str | None = "B1_minimal"

SOURCE_NAME = "Verifier A"
MATRIX_ARMS = ("neutral", "location", "correct_verdict", "correct_rationale", "false_verdict",
               "false_rationale")
PAIR_ARMS = ("actual_verdict", "actual_rationale")

_LINE_IDS = {"type": "array", "items": {"type": "string", "pattern": "^L[0-9]{5}$"}, "maxItems": 6}
TARGETED_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_line_ids": _LINE_IDS,
        "evidence_summary": {"type": "string"},
        "recomputation": {"type": ["string", "null"]},
        "analysis": {"type": "string"},
        "verdict": {"type": "string"},
        "confidence": {"type": "number"},
        "brief_reason": {"type": "string"},
    },
    "required": ["evidence_line_ids", "evidence_summary", "recomputation", "analysis", "verdict",
                 "confidence", "brief_reason"],
    "additionalProperties": False,
}
BLIND_SCHEMA = {
    "type": "object",
    "properties": {
        "audit_notes": {"type": "string"},
        "findings": {"type": "array", "maxItems": 5, "items": {
            "type": "object",
            "properties": {"category": {"type": "string"}, "evidence_line_ids": _LINE_IDS,
                           "evidence_summary": {"type": "string"}, "allegation": {"type": "string"},
                           "confidence": {"type": "number"}},
            "required": ["category", "evidence_line_ids", "evidence_summary", "allegation", "confidence"],
            "additionalProperties": False}},
    },
    "required": ["audit_notes", "findings"],
    "additionalProperties": False,
}
RESPONSE_FORMAT = {
    "targeted": {"type": "json_schema", "json_schema": {"name": "targeted_verdict", "schema": TARGETED_SCHEMA}},
    "blind": {"type": "json_schema", "json_schema": {"name": "blind_audit", "schema": BLIND_SCHEMA}},
}
DECODING = {"temperature": 0}
# chat_template_kwargs are model-specific: Qwen3 templates need enable_thinking=false; templates without a
# thinking switch receive no kwargs. Fixed per model in models.py and hashed into every block fingerprint.
MAX_TOKENS = {"targeted": 2048, "blind": 4096}
MAX_RETRIES = 2
TIMEOUT_S = {"targeted": 900, "blind": 1500}

DEVIATIONS_FROM_2AR2 = [
    ("memory_rule", "system prompt adds 'Evaluate only the supplied manuscript evidence. Do not rely on remembered "
                    "versions of the paper.'"),
    ("blind_prompt", "2A-R2 blind prompt -> one of three development candidates, chosen on 2A-R2 material only "
                     "(exp2b/BLIND_PROMPT_BAKEOFF.md); blind system prompt drops the verdict definitions"),
    ("blind_category", "category field enumerated list -> free short label (Llama copied the enumeration literally)"),
    ("chat_template_kwargs", "global enable_thinking=false -> per-model (Qwen: enable_thinking=false; others: none)"),
    ("manuscripts", "one ELVAE manuscript -> five new arXiv manuscripts standardised by exp2b/normalize.py"),
    ("provenance", "valid/invalid line IDs -> exact / adjacent-blank / nonexistent / target-supported categories"),
]


def seed_for(case_id: str, state: str) -> int:
    h = hashlib.sha256(f"{SEED_NAMESPACE}||{case_id}||{state}".encode()).hexdigest()
    return 1000 + int(h[:8], 16) % 900000


def exposure_text(arm: str, *, location: str = "", prior_verdict: str | None = None,
                  prior_rationale: str | None = None) -> str:
    if arm == "neutral":
        return "No previous verifier judgment is available."
    if arm == "location":
        return (f"A prior process only identified the following manuscript lines for inspection: "
                f"{location}. It supplied no verdict and no allegation.")
    if arm in ("correct_verdict", "false_verdict", "actual_verdict"):
        return (f"A previous verifier ({SOURCE_NAME}) returned the verdict {prior_verdict}. "
                f"This may be correct or incorrect. Verify independently.")
    if arm in ("correct_rationale", "false_rationale", "actual_rationale"):
        return (f"A previous verifier ({SOURCE_NAME}) returned {prior_verdict} and gave this "
                f"rationale: {prior_rationale} Both the verdict and rationale may be wrong. "
                f"Verify independently.")
    raise ValueError(arm)


def _payload(model_cfg: dict, system: str, user: str, seed: int, kind: str) -> dict:
    p = {"model": model_cfg["served_name"], "messages": [{"role": "system", "content": system},
                                                         {"role": "user", "content": user}],
         "seed": seed, "max_tokens": MAX_TOKENS[kind], **DECODING, "response_format": RESPONSE_FORMAT[kind]}
    if model_cfg.get("chat_template_kwargs"):
        p["chat_template_kwargs"] = model_cfg["chat_template_kwargs"]
    return p


def build_targeted(model_cfg: dict, numbered_paper: str, question: str, exposure: str, seed: int):
    template = TARGETED_TEMPLATE.format(question=question, paper=numbered_paper)
    assert template.count(EXPOSURE_SLOT) == 1
    user = template.replace(EXPOSURE_SLOT, exposure)
    payload = _payload(model_cfg, SYSTEM, user, seed, "targeted")
    block = {k: v for k, v in payload.items() if k != "messages"} | {"system": SYSTEM, "user_without_exposure": template}
    prov = {"block_fingerprint": sha256_text(canonical(block)), "request_sha256": sha256_text(canonical(payload)),
            "manuscript_sha256": sha256_text(numbered_paper), "exposure_sha256": sha256_text(exposure)}
    return payload, prov


def build_blind(model_cfg: dict, numbered_paper: str, seed: int, prompt_id: str | None = None):
    pid = prompt_id or BLIND_PROMPT_ID
    if pid is None:
        raise RuntimeError("blind prompt not frozen")
    user = BLIND_CANDIDATES[pid].format(paper=numbered_paper)
    payload = _payload(model_cfg, SYSTEM_BLIND, user, seed, "blind")
    prov = {"block_fingerprint": sha256_text(canonical(payload)), "request_sha256": sha256_text(canonical(payload)),
            "manuscript_sha256": sha256_text(numbered_paper), "blind_prompt_id": pid,
            "blind_prompt_sha256": sha256_text(BLIND_CANDIDATES[pid])}
    return payload, prov
