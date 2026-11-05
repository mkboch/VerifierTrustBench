"""Deterministic manuscript standardisation for Experiment 2B.

flatten(main, files)   resolve \\input/\\include from the source archive
normalize(text)        document body only; comments, identity metadata and bibliography removed;
                       prose paragraphs joined onto single lines; table/math rows kept one per line
number(text)           '[L00001] ...' prefix on every non-empty line (identical rule to 2A-R2)

Scientific content is never altered: only comments, author/affiliation/contact/acknowledgement metadata,
the reference list and whitespace layout change. The same function is applied to every variant.
"""
from __future__ import annotations

import posixpath
import re

META_CMDS = ["author", "affiliation", "affil", "address", "email", "thanks", "institute", "orcid", "corref",
             "cortext", "ead", "date", "authorrunning", "titlerunning", "icmlauthor", "icmlaffiliation",
             "icmlcorrespondingauthor", "correspondingauthor", "authornote", "IEEEauthorblockN",
             "IEEEauthorblockA", "fntext", "footnotetext", "index"]
DROP_ENVS = ["thebibliography", "acknowledgments", "acknowledgements", "acks", "comment"]
LINE_ENVS = ["tabular", "tabular*", "tabularx", "longtable", "array", "align", "align*", "equation", "equation*",
             "eqnarray", "eqnarray*", "gather", "gather*", "multline", "multline*", "split", "cases", "matrix",
             "pmatrix", "bmatrix", "verbatim", "lstlisting", "algorithmic", "algorithm", "displaymath"]
STRUCT = re.compile(r"^\\(begin|end|section|subsection|subsubsection|paragraph|item|caption|label|centering|"
                    r"toprule|midrule|bottomrule|hline|includegraphics|maketitle|title|appendix|tableofcontents|"
                    r"resizebox|small|footnotesize|scriptsize|addlinespace|cmidrule|multicolumn|\[|\])")


def flatten(main: str, files: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    base = posixpath.dirname(main)

    def load(name: str, depth: int) -> str:
        return re.sub(r"\\(?:input|include)\{([^}]+)\}", lambda m: sub(m, depth), strip_comments(files[name]))

    def sub(m, depth):
        target = m.group(1).strip()
        cands = [posixpath.normpath(posixpath.join(base, target)), posixpath.normpath(target)]
        cands += [c + ".tex" for c in cands]
        for c in cands:
            if c in files and depth < 8:
                return load(c, depth + 1)
        missing.append(target)
        return ""
    return load(main, 0), missing


def strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        m = re.search(r"(?<!\\)%", line)
        if m:
            if not line[:m.start()].strip():
                continue  # whole-line comment: drop the line, not just its content
            line = line[:m.start()]
        out.append(line.rstrip())
    return "\n".join(out)


def _drop_command(text: str, cmd: str) -> str:
    pat = re.compile(r"\\" + re.escape(cmd) + r"\*?\s*(\[[^\]]*\])?\s*\{")
    while True:
        m = pat.search(text)
        if not m:
            return text
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "{" and text[i - 1] != "\\":
                depth += 1
            elif text[i] == "}" and text[i - 1] != "\\":
                depth -= 1
            i += 1
        text = text[:m.start()] + text[i:]


def normalize(text: str) -> str:
    text = strip_comments(text)
    text = re.sub(r"\\iffalse.*?\\fi\b", "", text, flags=re.S)
    m1, m2 = re.search(r"\\begin\{document\}", text), re.search(r"\\end\{document\}", text)
    if m1:
        text = text[m1.end():m2.start() if m2 else len(text)]
    for env in DROP_ENVS:
        text = re.sub(r"\\begin\{" + re.escape(env) + r"\}.*?\\end\{" + re.escape(env) + r"\}", "", text, flags=re.S)
    for cmd in META_CMDS:
        text = _drop_command(text, cmd)
    text = re.sub(r"\\(bibliography|bibliographystyle)\{[^}]*\}", "", text)
    nonsci = (r"(Acknowledg[e]?ments?|Funding[^}]*|Author contributions?[^}]*|Data availability[^}]*|"
              r"Code availability[^}]*|Data and code availability[^}]*|Competing interests?|Conflicts? of interest[^}]*|"
              r"Declaration[^}]*|Disclosure[^}]*|Ethics[^}]*|CRediT[^}]*)")
    text = re.sub(r"\\(?:sub)*section\*?\{" + nonsci + r"\.?\}.*?(?=\\(?:sub)*section|\\appendix|$)",
                  "", text, flags=re.S | re.I)
    text = re.sub(r"\\paragraph\*?\{" + nonsci + r"\.?\}.*?(?=\n\s*\n|\\(?:sub)*section|\\paragraph|$)",
                  "", text, flags=re.S | re.I)
    lines = [l.strip() for l in text.split("\n")]
    out: list[str] = []
    depth = 0
    buf: list[str] = []

    def flush():
        if buf:
            out.append(" ".join(buf))
            buf.clear()
    for line in lines:
        opens = sum(len(re.findall(r"\\begin\{" + re.escape(e) + r"\}", line)) for e in LINE_ENVS)
        closes = sum(len(re.findall(r"\\end\{" + re.escape(e) + r"\}", line)) for e in LINE_ENVS)
        if not line:
            flush()
            if out and out[-1] != "":
                out.append("")
            continue
        if depth > 0 or opens or STRUCT.match(line):
            flush()
            out.append(line)
        else:
            buf.append(line)
        depth = max(0, depth + opens - closes)
    flush()
    while out and out[-1] == "":
        out.pop()
    while out and out[0] == "":
        out.pop(0)
    return "\n".join(out) + "\n"


def number(text: str) -> tuple[str, set[int]]:
    out, valid = [], set()
    for i, line in enumerate(text.split("\n"), start=1):
        if line.strip():
            out.append(f"[L{i:05d}] {line}")
            valid.add(i)
    return "\n".join(out), valid
