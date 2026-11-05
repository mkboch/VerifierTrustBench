#!/usr/bin/env python3
"""Tests for verifier_profile. Run: python test_profile.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import profile_core as P

FAIL = []
def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   [{detail}]"))
    if not cond: FAIL.append(name)

print("information path")
check("blind store -> BLIND_DISCOVERY", P.information_path({"experiment": "blind"}) == P.BLIND_DISCOVERY)
check("broad_blind key -> BLIND_DISCOVERY",
      P.information_path({"experiment": "broad_family", "key": "broad_blind::m::c::E0"}) == P.BLIND_DISCOVERY)
check("evidence -> RELATION_LOCALIZED", P.information_path({"experiment": "evidence"}) == P.RELATION_LOCALIZED)
check("matrix neutral -> RELATION_LOCALIZED",
      P.information_path({"experiment": "matrix", "arm": "neutral"}) == P.RELATION_LOCALIZED)
check("matrix rationale -> UPSTREAM_AGENT_SUPPLIED",
      P.information_path({"experiment": "matrix", "arm": "correct_rationale"}) == P.UPSTREAM_AGENT_SUPPLIED)

print("exact McNemar")
check("symmetric -> 1.0", P.exact_mcnemar(5, 5) == 1)
check("empty -> 1.0", P.exact_mcnemar(0, 0) == 1)
check("known value 332 vs 33", f"{P.exact_mcnemar(332, 33):.3E}" == "2.751E-63", f"{P.exact_mcnemar(332,33):.3E}")
check("never exceeds 1", all(P.exact_mcnemar(a, b) <= 1 for a, b in [(1,1),(2,1),(3,3),(0,4)]))

print("responsiveness")
r = P.responsiveness({"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "ISSUE_PRESENT"})
check("perfect trajectory", r["trajectory"] and r["pattern"] == "111")
check("no failure flags on perfect", not (r["MISS_DEFECT"] or r["FALSE_ALARM_ON_REPAIR"] or r["MISS_REVERSAL"]))
r = P.responsiveness({"E0": "ISSUE_PRESENT", "E1": "NO_ISSUE", "E2": "NO_ISSUE"})
check("MISS_REVERSAL detected", r["MISS_REVERSAL"] and not r["trajectory"] and r["pattern"] == "110")
r = P.responsiveness({"E0": "NO_ISSUE", "E1": "ISSUE_PRESENT", "E2": "ISSUE_PRESENT"})
check("MISS_DEFECT + FALSE_ALARM", r["MISS_DEFECT"] and r["FALSE_ALARM_ON_REPAIR"])
r = P.responsiveness({"E0": "ISSUE_PRESENT", "E1": None, "E2": "ISSUE_PRESENT"})
check("incomplete not a trajectory", (not r["trajectory"]) and r["pattern"] == "incomplete")

print("false-alarm rate")
fa = P.false_alarm_rate(90, 100)
check("1 - clearance", fa["x"] == 10 and fa["n"] == 100 and abs(fa["rate"] - 0.10) < 1e-9)

print("provenance detail")
d = P.provenance_detail([10, 11, 99], [], {10, 11, 12}, [10])
check("GROUNDED when a target cited", d["status"] == "GROUNDED", d["status"])
check("citation precision 1/3", abs(d["citation_precision"] - 1/3) < 1e-9)
check("nonexistent counted", d["n_nonexistent"] == 1)
check("span computed", d["citation_span"] == 90)
d = P.provenance_detail([], [], {1, 2}, [1])
check("empty -> NO_CITATION", d["status"] == "NO_CITATION" and d["citation_precision"] is None)
d = P.provenance_detail([2], [], {1, 2}, [1])
check("unrelated valid -> UNGROUNDED_VALID_LINES", d["status"] == "UNGROUNDED_VALID_LINES", d["status"])

print("verdict x provenance cells")
check("correct+grounded", P.verdict_provenance_cell(True, "GROUNDED") == "CORRECT_RELATION_SUPPORTED")
check("correct+ungrounded", P.verdict_provenance_cell(True, "UNGROUNDED_VALID_LINES") == "CORRECT_UNSUPPORTED")
check("incorrect+adjacent supported",
      P.verdict_provenance_cell(False, "GROUNDED_VIA_ADJACENT") == "INCORRECT_RELATION_SUPPORTED")
check("incorrect+nocitation", P.verdict_provenance_cell(False, "NO_CITATION") == "INCORRECT_UNSUPPORTED")

print("paired contrast")
t = P.paired([True]*10 + [False]*10, [True]*5 + [False]*15)
check("discordance counted", t["first_only"] == 5 and t["second_only"] == 0, str(t))
check("exact_p present", "exact_p" in t)

print()
print(("ALL TESTS PASSED" if not FAIL else f"{len(FAIL)} FAILURES: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
