"""Independent reproduction of VerifierTrustBench's published numerical results.

    python -m reproducibility.verify_all

Runs from the public release alone: no private path, no environment variable, no GPU and
no paid model API. What it cannot reproduce from public data it says so about, by name,
rather than passing quietly.
"""
__all__ = ["estimators", "bootstrap", "data", "contrasts", "verify_all"]
