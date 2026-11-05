#!/usr/bin/env python3
"""Phase 3: generic manuscript-navigation environment for agentic blind verification.

The environment is CONTENT-NEUTRAL and DEFECT-FAMILY-NEUTRAL. It exposes exactly two tools over the
line-indexed manuscript and nothing else.

  SEARCH(query)            lexical search; returns matching line IDs with bounded surrounding context
  READ(start_line, end)    read a bounded contiguous line interval

DELIBERATELY NOT EXPOSED (would leak the answer or bias the search):
  * the deterministic gold checker
  * the defect family or any family-specific linter (in particular NO cross-reference linter)
  * the target relation, the mutation location, the E0/E1/E2 label
  * any case metadata, gold explanation, blind token list or evidence line list

The manuscript text handed to the agent is byte-identical to the text used in the DIRECT blind condition, so the
two conditions differ only in whether the model may inspect iteratively.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# ---- frozen interaction budget (calibrated on OLD development papers only; see BUDGET_CALIBRATION.md)
MAX_TOOL_CALLS = 8
MAX_READ_LINES = 80
MAX_SEARCH_HITS = 20
SEARCH_CONTEXT = 1          # lines of context either side of a hit
MAX_TOOL_OUTPUT_CHARS = 6000

TOOL_SPEC = """You may inspect the manuscript with two tools before answering.

SEARCH(query)
  Lexical, case-insensitive search over the manuscript. Returns up to {hits} matching lines with {ctx} line(s) of
  surrounding context. Use it to locate terms, numbers, symbols or phrases.

READ(start_line, end_line)
  Return the manuscript lines in the inclusive interval [start_line, end_line]. At most {lines} lines per call.

Budget: at most {calls} tool calls in total. Emit exactly one tool call per turn, on its own line, in one of these
forms:
  SEARCH("your query")
  READ(1234, 1300)
When you have finished inspecting, emit DONE on its own line and you will then be asked for your final answer.
""".format(hits=MAX_SEARCH_HITS, ctx=SEARCH_CONTEXT, lines=MAX_READ_LINES, calls=MAX_TOOL_CALLS)

LINE_RE = re.compile(r"^\[L(\d{5})\]\s?(.*)$")


@dataclass
class ManuscriptEnv:
    """Line-indexed manuscript with a bounded tool interface. Pure function of the numbered text."""
    numbered_text: str
    lines: dict = field(default_factory=dict)
    calls: int = 0
    log: list = field(default_factory=list)

    def __post_init__(self):
        for ln in self.numbered_text.splitlines():
            m = LINE_RE.match(ln)
            if m:
                self.lines[int(m.group(1))] = m.group(2)

    # ---------------- tools
    def search(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return "SEARCH error: empty query."
        try:
            rx = re.compile(re.escape(q), re.I)
        except re.error as e:
            return f"SEARCH error: {e}"
        hits = [n for n in sorted(self.lines) if rx.search(self.lines[n])]
        total = len(hits)
        hits = hits[:MAX_SEARCH_HITS]
        if not hits:
            return f'SEARCH("{q}"): no matching lines.'
        shown, out = set(), [f'SEARCH("{q}"): {total} matching line(s); showing {len(hits)}.']
        for n in hits:
            for k in range(n - SEARCH_CONTEXT, n + SEARCH_CONTEXT + 1):
                if k in self.lines and k not in shown:
                    shown.add(k)
                    out.append(f"[L{k:05d}] {self.lines[k]}")
        return _cap("\n".join(out))

    def read(self, start: int, end: int) -> str:
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            return "READ error: line numbers must be integers."
        if end < start:
            start, end = end, start
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
        got = [f"[L{n:05d}] {self.lines[n]}" for n in range(start, end + 1) if n in self.lines]
        if not got:
            return f"READ({start}, {end}): no manuscript lines in that interval."
        return _cap(f"READ({start}, {end}):\n" + "\n".join(got))

    # ---------------- dispatch
    def step(self, raw: str) -> tuple[str, bool]:
        """Parse one agent turn. Returns (tool_output, done)."""
        text = (raw or "").strip()
        if re.search(r"^\s*DONE\s*$", text, re.M):
            self.log.append({"call": self.calls + 1, "action": "DONE"})
            return "", True
        m = re.search(r'SEARCH\(\s*"([^"]*)"\s*\)', text) or re.search(r"SEARCH\(\s*'([^']*)'\s*\)", text)
        if m:
            self.calls += 1
            out = self.search(m.group(1))
            self.log.append({"call": self.calls, "action": "SEARCH", "query": m.group(1),
                             "out_chars": len(out)})
            return out, False
        m = re.search(r"READ\(\s*(\d+)\s*,\s*(\d+)\s*\)", text)
        if m:
            self.calls += 1
            out = self.read(m.group(1), m.group(2))
            self.log.append({"call": self.calls, "action": "READ", "start": int(m.group(1)),
                             "end": int(m.group(2)), "out_chars": len(out)})
            return out, False
        self.log.append({"call": self.calls + 1, "action": "UNPARSED", "raw": text[:200]})
        return ('No tool call recognised. Emit exactly one of:\n  SEARCH("query")\n  READ(start, end)\n'
                "or DONE to finish inspecting."), False

    @property
    def exhausted(self) -> bool:
        return self.calls >= MAX_TOOL_CALLS


def _cap(s: str) -> str:
    return s if len(s) <= MAX_TOOL_OUTPUT_CHARS else s[:MAX_TOOL_OUTPUT_CHARS] + "\n... [output truncated]"


BUDGET = {"max_tool_calls": MAX_TOOL_CALLS, "max_read_lines": MAX_READ_LINES,
          "max_search_hits": MAX_SEARCH_HITS, "search_context_lines": SEARCH_CONTEXT,
          "max_tool_output_chars": MAX_TOOL_OUTPUT_CHARS}
