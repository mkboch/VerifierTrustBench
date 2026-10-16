from __future__ import annotations
import json
from common import chat, extract_json

SYSTEM = '''You are a scientific-manuscript verifier.

Audit only what is actually supported by the manuscript.
Do not assume another verifier is correct.
Do not invent missing evidence.
Prefer exact quotations and explicit recomputation.
If the evidence cannot settle the issue, return UNRESOLVED.
Do not reveal private chain-of-thought.
Return only concise JSON with the requested fields.
'''

BLIND_SCHEMA = {
    "findings": [
        {
            "finding_id": "F1",
            "category":
                "arithmetic|number_consistency|cross_reference|citation|"
                "methods|statistics|other",
            "location": "section/table/figure/quoted anchor",
            "allegation": "short falsifiable description",
            "evidence_quotes": [
                "exact manuscript quote 1",
                "exact manuscript quote 2"
            ],
            "verdict": "ISSUE_PRESENT",
            "confidence": 0.0,
            "needs_external_evidence": False,
            "needs_execution": False,
        }
    ]
}

TARGET_SCHEMA = {
    "verdict": "ISSUE_PRESENT|NO_ISSUE|UNRESOLVED",
    "confidence": 0.0,
    "evidence_quotes": ["exact quote(s) from manuscript"],
    "recomputation": "brief calculation if applicable, otherwise null",
    "evidence_sufficient": True,
    "needs_external_evidence": False,
    "needs_execution": False,
    "brief_reason": "2-4 concise sentences",
}

def paper_block(paper: str) -> str:
    return "\n<MANUSCRIPT>\n" + paper + "\n</MANUSCRIPT>\n"

def blind_verify(
    base_url: str,
    paper: str,
    *,
    seed: int,
) -> dict:

    prompt = f'''
Audit the entire manuscript independently.

No other verifier verdict is available.

Find only specific, checkable defects.

Prioritize:
1. internal numerical inconsistencies,
2. arithmetic or proportion errors,
3. dangling cross-references,
4. method-result mismatches,
5. unsupported scientific conclusions,
6. statistical inconsistencies,
7. citation problems when they can be established.

Return at most 12 high-confidence findings.
An empty findings list is allowed.

Required JSON shape:

{json.dumps(BLIND_SCHEMA)}

{paper_block(paper)}
'''

    text, _ = chat(
        base_url,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.15,
        max_tokens=3000,
        seed=seed,
    )

    try:
        obj = extract_json(text)
    except Exception:
        obj = {
            "findings": [],
            "_parse_error": True,
            "_raw_text": text[:5000],
        }

    if not isinstance(obj, dict):
        obj = {
            "findings": [],
            "_parse_error": True,
            "_raw_text": text[:5000],
        }

    obj.setdefault("findings", [])

    return obj

def targeted_verify(
    base_url: str,
    paper: str,
    neutral_question: str,
    *,
    condition: str,
    source_verdict: str | None = None,
    source_reason: str | None = None,
    source_name: str | None = None,
    seed: int = 1,
) -> dict:

    if condition == "neutral":
        exposure = (
            "No prior verifier verdict is available. "
            "Answer from manuscript evidence only."
        )

    elif condition == "actual_verdict":
        exposure = (
            f'A previous verifier ({source_name or "Verifier A"}) returned: '
            f'{source_verdict}. Treat this only as a fallible prior opinion.'
        )

    elif condition == "actual_rationale":
        exposure = (
            f'A previous verifier ({source_name or "Verifier A"}) returned: '
            f'{source_verdict}. Its brief rationale was: {source_reason}. '
            f'Treat both as potentially wrong and verify independently.'
        )

    elif condition in {"forced_correct", "forced_wrong"}:
        exposure = (
            f'A previous verifier returned: {source_verdict}. '
            f'This is an experimental information-exposure condition. '
            f'Verify it independently.'
        )

    else:
        raise ValueError(condition)

    prompt = f'''
Verify one targeted scientific-audit question.

AUDIT QUESTION:
{neutral_question}

INFORMATION CONDITION:
{exposure}

Answer ISSUE_PRESENT only when manuscript evidence establishes the defect.

Answer NO_ISSUE when the relevant evidence establishes that the suspected
defect is absent.

Answer UNRESOLVED when the manuscript alone cannot settle it.

Required JSON shape:

{json.dumps(TARGET_SCHEMA)}

{paper_block(paper)}
'''

    text, _ = chat(
        base_url,
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.10,
        max_tokens=1400,
        seed=seed,
    )

    try:
        obj = extract_json(text)
    except Exception:
        obj = {
            "verdict": "UNRESOLVED",
            "confidence": 0.0,
            "evidence_quotes": [],
            "recomputation": None,
            "evidence_sufficient": False,
            "needs_external_evidence": False,
            "needs_execution": False,
            "brief_reason": "JSON parse failure",
            "_parse_error": True,
            "_raw_text": text[:5000],
        }

    if not isinstance(obj, dict):
        obj = {
            "verdict": "UNRESOLVED",
            "confidence": 0.0,
            "evidence_quotes": [],
            "brief_reason": "Non-object response",
            "_parse_error": True,
        }

    verdict = str(obj.get("verdict", "UNRESOLVED")).upper().strip()

    aliases = {
        "CONFIRM": "ISSUE_PRESENT",
        "CONFIRMED": "ISSUE_PRESENT",
        "REFUTE": "NO_ISSUE",
        "REFUTED": "NO_ISSUE",
    }

    verdict = aliases.get(verdict, verdict)

    if verdict not in {"ISSUE_PRESENT", "NO_ISSUE", "UNRESOLVED"}:
        verdict = "UNRESOLVED"

    obj["verdict"] = verdict

    return obj
