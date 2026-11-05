"""The estimators, written once so that every caller uses the same definitions.

Two things here are easy to get wrong and are therefore spelled out.

THE LOG-LINEAR CORRECTION is applied UNCONDITIONALLY, to every cell, not only to cells at
a boundary. Hautus (1995): add 0.5 to each count and 1.0 to each total. Applying it only
when a rate hits 0 or 1 is a different, biased estimator.

POOLED AND SYSTEM-BALANCED ARE DIFFERENT ESTIMANDS. Pooled counts every cell once, so
systems contributing more cells weigh more. System-balanced takes each system's own
difference and averages those unweighted. They can disagree in sign and in significance,
and the manuscript reports cases where they do. Nothing in this module silently picks one.
"""
from __future__ import annotations
import math

Z_975 = 1.959963984540054


def phi_inv(p: float) -> float:
    """Inverse normal CDF: Acklam's rational approximation, refined by one Halley step.

    The same routine as the frozen analysis, so d' agrees to the last digit rather than
    to plotting precision.
    """
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= ph:
        q = p - 0.5
        r = q * q
        x = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
            (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    e = 0.5 * math.erfc(-x / math.sqrt(2)) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def rates(hits: int, n0: int, fas: int, n1: int):
    """Sensitivity, false-alarm rate, specificity, balanced accuracy, log-linear d'."""
    if n0 <= 0 or n1 <= 0:
        return None
    sens = hits / n0
    far = fas / n1
    h = (hits + 0.5) / (n0 + 1.0)          # Hautus, applied unconditionally
    f = (fas + 0.5) / (n1 + 1.0)
    return {
        "n_e0": n0, "n_e1": n1, "hits": hits, "false_alarms": fas,
        "sensitivity": sens, "false_alarm_rate": far, "specificity": 1 - far,
        "balanced_accuracy": (sens + (1 - far)) / 2,
        "dprime": phi_inv(h) - phi_inv(f),
    }


def aggregate(cells):
    """Sum a list of cell dicts into the four counts the estimators need."""
    n0 = sum(c["e0_scoreable"] for c in cells)
    n1 = sum(c["e1_scoreable"] for c in cells)
    hits = sum(c["e0_hit"] for c in cells if c["e0_scoreable"])
    fas = sum(c["e1_false_alarm"] for c in cells if c["e1_scoreable"])
    return hits, n0, fas, n1


def wilson(k: int, n: int, z: float = Z_975):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)
