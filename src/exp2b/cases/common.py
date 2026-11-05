"""Shared helpers for 2B case checkers (deterministic, text-only)."""
import re

WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20, "fifty": 50, "all six": 6}


def num(s: str) -> str:
    """Regex for a decimal literal not embedded in a longer number."""
    return r"(?<![\d.])" + re.escape(s) + r"(?![\d])"


def f(pat: str, text: str, group: int = 1) -> str:
    m = re.search(pat, text)
    if not m:
        raise ValueError(f"pattern not found: {pat!r}")
    return m.group(group)


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def labels(L: dict) -> set:
    return {m.group(1) for t in L.values() for m in re.finditer(r"\\label\{([^}]+)\}", t)}


def ref_at(L: dict, line: int, pat: str) -> str:
    return f(pat, L[line])


def cells(line: str) -> list:
    return [c.strip().rstrip("\\").strip() for c in line.split("&")]


def first_number(s: str) -> float:
    return float(f(r"(-?[\d]+(?:\.\d+)?)", s.replace(",", "")))
