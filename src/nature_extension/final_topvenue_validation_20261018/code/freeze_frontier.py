#!/usr/bin/env python3
"""2C: freeze the frontier-ladder design before any paid request.

Writes FRONTIER_LADDER_MANIFEST.json. Model IDs are left as a REQUIRED-AT-RUNTIME slot: the brief
forbids inferring availability from documentation, and no credential is configured here, so the
immutable snapshot identifier must be captured from the provider's models endpoint at run time and
written into the manifest before the first scientific request.
"""
from __future__ import annotations
import hashlib, json, sys, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parents[1]
RR = ROOT / "nature_extension/reviewer_response_20261016"
sys.path.insert(0, str(RR / "code"))
for p in ("exp3heldout", "exp2b", "exp2br"):
    sys.path.insert(0, str(ROOT / p))
import design_heldout as D, protocol as P, protocol_br as PBR, ladder_protocol as LP  # noqa: E402
from client import canonical, sha256_text  # noqa: E402

LAD = json.loads((RR / "ladder/LADDER_DESIGN_MANIFEST.json").read_text())
TK = json.loads((OUT / "data/FRONTIER_TOKEN_COUNTS.json").read_text())
COST = json.loads((OUT / "data/FRONTIER_COST_PREFLIGHT.json").read_text())
plan = D.Plan(); cases = {c["case_id"]: c for c in plan.cases}


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


man = {
 "label": "FRONTIER_LOCALIZATION_LADDER_EXTERNAL_VALIDATION",
 "status": "POST_HOC_EXTERNAL_VALIDATION MOTIVATED BY INTERNAL REVIEW",
 "not_preregistered": True,
 "preregistration_note": ("Post hoc external validation, designed after internal review showed the "
                          "blind-versus-localized difference was largely a response-format effect. "
                          "It must never be described as preregistered."),
 "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
 "scientific_question": ("Does the response-format effect measured on open-weight systems persist "
                         "in contemporary proprietary frontier systems from two independent "
                         "providers? The question is whether the measurement instrument changes "
                         "apparent verification performance, not whether frontier systems score "
                         "higher."),
 "inherits_from": {"ladder_manifest": sha_file(RR / "ladder/LADDER_DESIGN_MANIFEST.json"),
                   "case_ids": LAD["case_ids"], "n_relations": len(LAD["case_ids"])},
 "arms": {
   "RUNG_1_BLIND_FINDING_LIST": {"information": "none",
     "output": "ranked finding list, maxItems 5", "scoring": "strict discovery (TRUE_DETECTION)"},
   "RUNG_2_CATEGORY_TARGETED_FINDING_LIST": {"information": "broad defect category",
     "output": "ranked finding list, maxItems 5", "scoring": "strict discovery (TRUE_DETECTION)"},
   "RUNG_3_RELATION_TARGETED_FINDING_LIST": {"information": "the specific relation, state not revealed",
     "output": "ranked finding list, maxItems 5", "scoring": "strict discovery (TRUE_DETECTION)"},
   "RUNG_4_RELATION_LOCALIZED_BINARY_VERDICT": {"information": "the specific relation",
     "output": "binary verdict with evidence line ids", "scoring": "verdict equals deterministic gold"},
 },
 "prompts": {
   "source": "reconstructed verbatim from the frozen generators, not re-authored",
   "rungs_1_3": "exp2br.protocol_br.build_blind_br plus the frozen ladder insertion "
                "(code/ladder_protocol.py), identical to the completed open-weight ladder",
   "rung_4": "exp2b.protocol.build_targeted with the neutral exposure, identical to the frozen "
             "relation-localized condition",
   "system_blind_sha256": sha256_text(P.SYSTEM_BLIND),
   "system_targeted_sha256": sha256_text(P.SYSTEM),
   "blind_user_template_sha256": sha256_text(P.BLIND_CANDIDATES[P.BLIND_PROMPT_ID]),
   "blind_schema_sha256": sha256_text(canonical(PBR.BLIND_SCHEMA_BR)),
   "category_text": LP.CATEGORY_TEXT,
   "provider_wrapper_allowance": ("Only the transport may differ: provider-specific JSON-mode or "
                                  "tool-schema syntax expressing the SAME schema. The scientific "
                                  "content of system prompt, user prompt and schema is unchanged."),
 },
 "api_parameters": {
   "temperature": 0,
   "max_output_tokens": {"finding_list_rungs": 4096, "verdict_rung": 2048},
   "reasoning_effort": "REQUIRED_AT_RUNTIME — choose the lowest setting that is a normal "
                       "configuration for the chosen model, per the cost preflight; record it here "
                       "before the first request",
   "top_p": "provider default, not tuned",
   "seed": "provider seed where supported; per-case seed from exp2b.protocol.seed_for",
   "batch_api": "USE IF AVAILABLE — halves cost and changes nothing scientific",
   "prompt_caching": "NOT APPLICABLE as the prompts stand: the ladder insertion precedes the "
                     "manuscript, so the cacheable prefix diverges before the manuscript. Moving "
                     "the insertion after the manuscript would enable caching but would deviate "
                     "from the completed ladder and break comparability. Not done.",
 },
 "models": {
   "openai": {"model_id": "REQUIRED_AT_RUNTIME", "snapshot_id": "REQUIRED_AT_RUNTIME",
              "selection_rule": "strongest current reasoning-class model whose full four-rung "
                                "60-relation run fits under the cap; do not pick a flagship for "
                                "prestige if it prevents full coverage"},
   "anthropic": {"model_id": "REQUIRED_AT_RUNTIME", "snapshot_id": "REQUIRED_AT_RUNTIME",
                 "selection_rule": "Claude Opus 5.5 if the complete run fits safely under the cap, "
                                   "otherwise the strongest current Sonnet 5.x available. The cost "
                                   "preflight indicates Opus-class pricing does NOT fit: see "
                                   "data/FRONTIER_COST_PREFLIGHT.json"},
   "immutable_ids_required": True,
   "moving_aliases_forbidden": True,
 },
 "scoring": {
   "rungs_1_3": "exp2b.scoring.label_defective == TRUE_DETECTION, the frozen strict scorer",
   "rung_4": "parsed verdict equals the deterministic gold for the E0 state",
   "parser": "exp2b.client.validate_blind / validate_targeted, unchanged",
   "gold": "the frozen deterministic checker labels; no model judges gold",
 },
 "exclusion_rules": ["technically invalid generations (truncation, parse failure) are counted as "
                     "failures and excluded from paired contrasts, exactly as in the frozen runs",
                     "no case is excluded on the basis of its outcome"],
 "retry_policy": {"max_retries": 2, "payload_identical_between_attempts": True,
                  "max_tokens_never_escalated": True},
 "cost_controls": {
   "hard_cap_per_provider_usd": 14.00,
   "buffer_usd": 1.00,
   "stopping_rule": "abort the run and write a partial-results record if cumulative measured spend "
                    "reaches the cap; never continue past it",
   "subset_rule": ("If the full 60-relation ladder does not fit, the largest affordable count is "
                   "selected BEFORE any inference by stratified sampling across defect family and "
                   "domain with seed 20261016, frozen into this manifest, and used identically for "
                   "both providers. Outcomes must not influence the subset."),
   "measured_token_counts": {"input_tokens_per_model_full_60": TK["total_input_tokens_per_model"],
                             "requests_per_model_full_60": TK["n_requests_per_model"]},
 },
 "primary_contrasts": [
   "category-targeted finding list minus blind finding list (category information, format held)",
   "relation-targeted finding list minus category-targeted finding list (exact-relation increment)",
   "relation-targeted finding list minus blind finding list (total information, format held)",
   "relation-localized verdict minus relation-targeted finding list (RESPONSE FORMAT, information held)",
 ],
 "analysis": {"uncertainty": "manuscript-cluster bootstrap, 10,000 draws, seed 20261016",
              "secondary": "exact paired McNemar",
              "reporting": "per model separately; pooled only as descriptive secondary",
              "heterogeneity": "must not be hidden"},
 "prespecified_interpretation": {
   "FRONTIER_FORMAT_EFFECT_REPLICATED": "both providers show a substantial positive response-format effect",
   "FRONTIER_FORMAT_EFFECT_HETEROGENEOUS": "one does, one does not",
   "FRONTIER_FORMAT_EFFECT_NOT_REPLICATED": "neither does",
   "substantial_defined_now": ("a point estimate of at least +10 pp on the response-format contrast "
                               "with a manuscript-cluster 95% interval excluding zero. Fixed before "
                               "any frontier data exist and not to be redefined afterwards."),
 },
 "source_code_sha256": {
   "ladder_protocol.py": sha_file(RR / "code/ladder_protocol.py"),
   "exp2b/protocol.py": sha_file(ROOT / "exp2b/protocol.py"),
   "exp2br/protocol_br.py": sha_file(ROOT / "exp2br/protocol_br.py"),
   "exp2b/scoring.py": sha_file(ROOT / "exp2b/scoring.py"),
   "exp2b/client.py": sha_file(ROOT / "exp2b/client.py"),
 },
 "execution_status": "NOT_RUN — no API credential is configured on this machine",
}
text = json.dumps(man, indent=1) + "\n"
(OUT / "frontier/FRONTIER_LADDER_MANIFEST.json").write_text(text)
print(f"froze FRONTIER_LADDER_MANIFEST.json  sha256 {hashlib.sha256(text.encode()).hexdigest()[:16]}")
print(f"relations: {len(LAD['case_ids'])}  rungs: 4  requests per model: {TK['n_requests_per_model']}")
print(f"execution status: {man['execution_status']}")
