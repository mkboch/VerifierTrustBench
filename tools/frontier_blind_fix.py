#!/usr/bin/env python3
"""The corrected frontier loader.

THE BUG

`fairlib.Fair._load_frontier` keyed every blind finding-list record by MANUSCRIPT:

    blind_by_paper[r["paper"]] = r

and then scored that single response against each of the manuscript's relations. That is
right for E1 and wrong for E0, because the two runners differ:

  * the E0 frontier runner issued one blind request PER RELATION, each against that
    relation's own perturbed manuscript -- 60 requests, 60 distinct case ids;
  * the E1 frontier runner issued one blind request PER MANUSCRIPT -- 21 requests, because
    the manuscript as published is the same document whichever relation is under test.

Keying by manuscript in E0 therefore discarded three of every four responses, kept the
last, and asked it about relations it had never been shown a defect for. A response that
correctly found the defect in its own perturbed copy was scored against three other
relations, where it counts as a miss.

The open-weight loader in the same file already makes this distinction -- its comment
reads "E0 per relation, E1 per paper". Only the frontier path lost it.

THE FIX

Index blind records both ways and choose by state: per case in E0, per manuscript in E1.
Nothing else changes. Duplicate trial keys resolve to the latest record, which is the
semantics `analyze_frontier.py` uses, and parsing and scoring remain the frozen routines.

EFFECT: GPT-5.2 blind E0 goes from 2/60 to 18/60, which reconciles exactly with the
canonical `FRONTIER_ITEMLEVEL.csv`. No other system, rung or state changes.
"""
from __future__ import annotations


def latest_by_key(jl, path):
    """Resolve duplicate trial keys the way analyze_frontier.py does: last record wins.

    A later record for the same key is a recovery of a client-side failure and supersedes
    the earlier attempt.
    """
    latest = {}
    for r in jl(path):
        latest[r["key"]] = r
    return latest


def install(fairlib):
    """Return a Fair subclass with the frontier blind-state bug corrected.

    The frozen module is never mutated: the correction is a subclass, so the private
    research tree stays byte-for-byte as it was and the deviation is explicit.
    """
    F = fairlib
    C = F.C

    class FixedFair(F.Fair):
        def _load_frontier(self, path, state):
            rows = list(latest_by_key(F.jl, path).values())
            blind_by_case, blind_by_paper = {}, {}
            for r in rows:
                if r["rung"] != "BLIND_FINDING_LIST":
                    continue
                if r.get("status") != "OK" or r.get("content") is None:
                    continue
                blind_by_case[r["case_id"]] = r
                blind_by_paper[r["paper"]] = r

            for r in rows:
                rung, cid = r["rung"], r["case_id"]
                if r.get("status") != "OK" or r.get("content") is None:
                    self.cell(F.FRONTIER, rung, cid)[f"{state.lower()}_status"] = \
                        r.get("status", "MISSING")
                    continue
                if rung == "RELATION_LOCALIZED_BINARY_VERDICT":
                    parsed, st = self._parse(r["content"], C.validate_targeted)
                    self._score_binary(F.FRONTIER, cid, state, parsed, st)
                elif rung != "BLIND_FINDING_LIST":
                    parsed, st = self._parse(r["content"], C.validate_blind)
                    self._score_findinglist(F.FRONTIER, rung, cid, state,
                                            (parsed or {}).get("findings"), st)

            # The correction. E0: each relation's own blind response.
            #                 E1: the manuscript-level response, reused across relations.
            per_case = (state == "E0")
            for cid in self.subset:
                r = (blind_by_case.get(cid) if per_case
                     else blind_by_paper.get(self.cases[cid]["paper"]))
                if r is None:
                    self.cell(F.FRONTIER, "BLIND_FINDING_LIST",
                              cid)[f"{state.lower()}_status"] = "MISSING"
                    continue
                parsed, st = self._parse(r["content"], C.validate_blind)
                self._score_findinglist(F.FRONTIER, "BLIND_FINDING_LIST", cid, state,
                                        (parsed or {}).get("findings"), st)

    return FixedFair
