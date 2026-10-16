"""The verifier_profile package ships its own self-test as a standalone script (it predates this
repository's pytest layout and is kept byte-identical to the research version). Run it as a
subprocess and require a clean exit."""
from __future__ import annotations
import pathlib
import subprocess
import sys

SCRIPT = (pathlib.Path(__file__).resolve().parents[1]
          / "src/nature_extension/verifier_profile/test_profile.py")


def test_verifier_profile_self_test_passes():
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, f"verifier_profile self-test failed:\n{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout.replace("  FAIL  ", "") or " FAIL " not in r.stdout
