"""Experiment 2B inference client (copied from exp2ar2/client.py v1.1 unchanged except this line and provenance helpers at the end).

Standalone on purpose: it does not import `src/common.py`, which the pilot and
Experiment 2A depend on and which a previous session modified in place.

Contract
--------
One call to `request()` is exactly one HTTP request. There are no hidden retries; the
caller (`call_with_retries`) performs every retry itself and records each attempt.

A trial ends in exactly one status:

    OK              parseable JSON satisfying the task schema
    HTTP_FAILED     connection error, timeout, non-200, or a body that is not a completion
    TRUNCATED       finish_reason == "length"
    EMPTY_CONTENT   final message.content empty or whitespace
    PARSE_FAILED    content is not strict JSON after stripping an enclosing markdown fence
    INVALID_SCHEMA  strict JSON that does not satisfy the task schema

None of these is ever converted into a verdict. `UNRESOLVED` exists only when a model
itself emitted a parseable object whose verdict field is "UNRESOLVED".

Reasoning text (`message.reasoning` / `message.reasoning_content`) is measured and
recorded but never substituted for final content: a verdict read out of hidden reasoning
is not the verdict the model returned.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable

VERDICTS = ("ISSUE_PRESENT", "NO_ISSUE", "UNRESOLVED")

FAILURE_STATUSES = ("HTTP_FAILED", "TRUNCATED", "EMPTY_CONTENT", "PARSE_FAILED",
                    "INVALID_SCHEMA")

# A single enclosing fence is harmless formatting. Nothing else is removed.
_FENCE = re.compile(r"^```[ \t]*(?:json|JSON)?[ \t]*\r?\n(.*?)\r?\n?```$", re.S)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request(base_url: str, payload: dict, timeout: int) -> dict:
    """Exactly one HTTP request. Returns a raw attempt record; never raises."""
    t0 = time.time()
    rec: dict = {"http_status": None, "latency_s": None, "error": None, "body": None}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rec["http_status"] = r.status
            raw = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        rec["http_status"] = e.code
        raw = e.read().decode("utf-8", errors="replace")
        rec["error"] = f"HTTPError {e.code}"
    except Exception as e:  # refused, reset, timeout
        rec["error"] = repr(e)
        raw = None
    rec["latency_s"] = round(time.time() - t0, 3)
    if raw is not None:
        try:
            rec["body"] = json.loads(raw)
        except json.JSONDecodeError:
            rec["body"] = {"_unparseable_http_body": raw[:4000]}
    return rec


def diagnostics(body: dict) -> dict:
    ch = body["choices"][0]
    msg = ch.get("message") or {}
    content = msg.get("content")
    reasoning = msg.get("reasoning")
    reasoning_content = msg.get("reasoning_content")
    return {
        "message_keys": sorted(msg.keys()),
        "finish_reason": ch.get("finish_reason"),
        "usage": body.get("usage"),
        "content_length": len(content or ""),
        "reasoning_length": len(reasoning or ""),
        "reasoning_content_length": len(reasoning_content or ""),
        "system_fingerprint": body.get("system_fingerprint"),
    }


def strict_json(content: str) -> tuple[object, bool]:
    """Parse strictly. Returns (obj, fence_stripped). Raises ValueError on failure.

    Permitted: surrounding whitespace, one enclosing ```json fence.
    Not permitted: prose around the object, brace scanning, repairing escapes,
    completing truncated structures.
    """
    text = content.strip()
    fence = False
    m = _FENCE.match(text)
    if m:
        text, fence = m.group(1).strip(), True
    return json.loads(text), fence


def classify(attempt: dict, validator: Callable[[object], tuple[dict | None, str | None, list]]) -> dict:
    """Turn one raw HTTP attempt into a status, a parsed object, and diagnostics."""
    out: dict = {"status": None, "failure_detail": None, "parsed": None,
                 "content": None, "fence_stripped": False, "schema_warnings": [],
                 "diagnostics": None, "http_status": attempt["http_status"],
                 "latency_s": attempt["latency_s"]}
    body = attempt.get("body")
    if attempt["http_status"] != 200 or not isinstance(body, dict) or not body.get("choices"):
        out["status"] = "HTTP_FAILED"
        detail = attempt.get("error") or ""
        if isinstance(body, dict):
            detail += " " + json.dumps(body)[:800]
        out["failure_detail"] = detail.strip()[:1200]
        return out

    diag = diagnostics(body)
    out["diagnostics"] = diag
    content = body["choices"][0].get("message", {}).get("content")
    out["content"] = content

    # Length before emptiness: a budget spent entirely on hidden reasoning is a truncation
    # whose visible symptom is empty content, and the cause is what needs reporting.
    if diag["finish_reason"] == "length":
        out["status"] = "TRUNCATED"
        out["failure_detail"] = (f"finish_reason=length; content_length={diag['content_length']}; "
                                 f"reasoning_length={diag['reasoning_length']}")
        return out
    if not (content or "").strip():
        out["status"] = "EMPTY_CONTENT"
        out["failure_detail"] = (f"finish_reason={diag['finish_reason']}; "
                                 f"reasoning_length={diag['reasoning_length']}; "
                                 f"reasoning_content_length={diag['reasoning_content_length']}")
        return out
    try:
        obj, fence = strict_json(content)
    except Exception as e:
        out["status"] = "PARSE_FAILED"
        out["failure_detail"] = repr(e)[:400]
        return out
    out["fence_stripped"] = fence
    parsed, err, warnings = validator(obj)
    out["schema_warnings"] = warnings
    if err:
        out["status"] = "INVALID_SCHEMA"
        out["failure_detail"] = err[:400]
        return out
    out["status"] = "OK"
    out["parsed"] = parsed
    return out


def call_with_retries(base_url: str, payload: dict, validator, *, max_retries: int,
                      timeout: int, backoff_s: float = 2.0) -> dict:
    """First attempt plus up to `max_retries` retries, every retry an identical payload.

    The payload is never altered between attempts - in particular `max_tokens` is not
    escalated after a truncation, because a matched causal block must decode every arm
    under the same budget.
    """
    attempts = []
    final = None
    for i in range(max_retries + 1):
        raw = request(base_url, payload, timeout)
        c = classify(raw, validator)
        c["attempt"] = i + 1
        attempts.append({k: c[k] for k in ("attempt", "status", "failure_detail", "http_status",
                                            "latency_s", "diagnostics", "fence_stripped")}
                        | {"content_excerpt": (c["content"] or "")[:1500] if c["status"] != "OK" else None})
        final = c
        if c["status"] == "OK":
            break
        if i < max_retries:
            time.sleep(backoff_s * (i + 1))
    final["attempts"] = attempts
    final["n_attempts"] = len(attempts)
    return final


# --------------------------------------------------------------------------- validators

LINE_ID = re.compile(r"^\s*\[?L(\d{5})\]?\s*$")


def parse_line_ids(raw) -> tuple[list[int], list]:
    """Returns (line numbers, malformed entries). Accepted spellings: 'L00412' or '[L00412]'."""
    ids, bad = [], []
    for x in raw:
        m = LINE_ID.match(x) if isinstance(x, str) else None
        if m:
            ids.append(int(m.group(1)))
        else:
            bad.append(x)
    return ids, bad


def check_line_refs(ids: list[int], malformed: list, valid_ids: set[int]) -> dict:
    """Whether every cited line exists in the manuscript that was sent."""
    missing = sorted({i for i in ids if i not in valid_ids})
    return {"n_ids": len(ids), "n_malformed": len(malformed), "nonexistent": missing,
            "valid": not malformed and not missing}


def validate_targeted(obj) -> tuple[dict | None, str | None, list]:
    """Required: verdict from the fixed vocabulary, non-empty brief_reason, evidence_line_ids list.

    Verdict normalization is limited to surrounding whitespace and letter case; any other
    spelling is INVALID_SCHEMA, never mapped. Line IDs that are malformed or absent from the
    manuscript do not fail the trial; they are recorded and reported as invalid line
    references (the runner checks them against the manuscript it sent).
    """
    warnings: list[str] = []
    if not isinstance(obj, dict):
        return None, "top-level JSON is not an object", warnings
    v_raw = obj.get("verdict")
    if not isinstance(v_raw, str):
        return None, f"verdict missing or not a string: {v_raw!r}", warnings
    v = v_raw.strip().upper()
    if v not in VERDICTS:
        return None, f"verdict outside vocabulary: {v_raw!r}", warnings
    if v != v_raw:
        warnings.append(f"verdict_case_or_space_normalized:{v_raw!r}")
    reason = obj.get("brief_reason")
    if not isinstance(reason, str) or not reason.strip():
        return None, "brief_reason missing or empty", warnings
    raw_ids = obj.get("evidence_line_ids")
    if not isinstance(raw_ids, list):
        return None, f"evidence_line_ids missing or not a list: {type(raw_ids).__name__}", warnings
    ids, malformed = parse_line_ids(raw_ids)
    if malformed:
        warnings.append(f"malformed_line_ids:{len(malformed)}")
    conf = obj.get("confidence")
    if conf is not None and not (isinstance(conf, (int, float)) and not isinstance(conf, bool)
                                 and 0.0 <= conf <= 1.0):
        warnings.append(f"confidence_invalid:{conf!r}")
        conf = None
    summary = obj.get("evidence_summary")
    if not isinstance(summary, str):
        warnings.append("evidence_summary_missing")
        summary = None
    analysis = obj.get("analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        warnings.append("analysis_missing_or_empty")
        analysis = None
    extra = sorted(set(obj) - {"verdict", "confidence", "evidence_line_ids", "evidence_summary",
                               "recomputation", "brief_reason", "analysis"})
    if extra:
        warnings.append("extra_keys:" + ",".join(extra))
    keys = list(obj)
    if "analysis" in keys and keys.index("verdict") < keys.index("analysis"):
        warnings.append("verdict_emitted_before_analysis")
    if any("\\" in (x or "") for x in (reason, summary, analysis)):
        warnings.append("backslash_in_prose")
    return {"verdict": v, "verdict_raw": v_raw, "confidence": conf, "evidence_line_ids": ids,
            "evidence_line_ids_malformed": malformed, "evidence_summary": summary,
            "recomputation": obj.get("recomputation"), "analysis": analysis,
            "brief_reason": reason}, None, warnings


def validate_blind(obj) -> tuple[dict | None, str | None, list]:
    """Required: a `findings` list of objects, each with an allegation and an evidence_line_ids list."""
    warnings: list[str] = []
    if not isinstance(obj, dict):
        return None, "top-level JSON is not an object", warnings
    f = obj.get("findings")
    if not isinstance(f, list):
        return None, "findings missing or not a list", warnings
    clean = []
    for i, item in enumerate(f):
        if not isinstance(item, dict):
            return None, f"finding {i} is not an object", warnings
        if not isinstance(item.get("allegation"), str) or not item["allegation"].strip():
            return None, f"finding {i} has no allegation", warnings
        raw_ids = item.get("evidence_line_ids")
        if not isinstance(raw_ids, list):
            return None, f"finding {i} evidence_line_ids missing or not a list", warnings
        ids, malformed = parse_line_ids(raw_ids)
        if malformed:
            warnings.append(f"finding_{i}_malformed_line_ids:{len(malformed)}")
        if not isinstance(item.get("evidence_summary"), str):
            warnings.append(f"finding_{i}_evidence_summary_missing")
        clean.append({"category": item.get("category"), "evidence_line_ids": ids,
                      "evidence_line_ids_malformed": malformed,
                      "evidence_summary": item.get("evidence_summary") if isinstance(item.get("evidence_summary"), str) else "",
                      "allegation": item["allegation"], "confidence": item.get("confidence")})
    if len(clean) > 5:
        warnings.append(f"more_than_5_findings:{len(clean)}")
    notes = obj.get("audit_notes")
    if not isinstance(notes, str):
        warnings.append("audit_notes_missing")
        notes = None
    return {"findings": clean, "audit_notes": notes}, None, warnings
