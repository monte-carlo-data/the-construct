#!/usr/bin/env python3
"""Tests for the Sentinel secure-build gate engine (.github/scripts/sentinel_gate.py).

Exercises the gate's decision logic and exit-code contract WITHOUT requiring Syft or
Grype on PATH — the point is to prove the fail-closed behavior (missing SBOM, missing
Grype, zero components) and the warn-vs-block exit codes, which are the gate's whole job.

Run:  python3 tests/test_sentinel_gate.py      (or: python3 -m pytest tests/test_sentinel_gate.py)
Exits 0 if all pass, 1 otherwise. Stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / ".github" / "scripts" / "sentinel_gate.py"

_failures: list[str] = []


SOURCE_REPO_PREFIX = "your-org:source-repo:"  # pinned so the host's SBOM_SOURCE_REPO_PREFIX can't skew check 2


def run_gate(sbom: Path, mode: str, threshold: int = 0) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GATE), "--sbom", str(sbom),
         "--mode", mode, "--critical-threshold", str(threshold)],
        capture_output=True, text=True, check=False,
        env={**os.environ, "SBOM_SOURCE_REPO_PREFIX": SOURCE_REPO_PREFIX},
    )
    return proc.returncode, proc.stdout


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


def write_sbom(path: Path, *, components: int, bom_format: str = "CycloneDX") -> None:
    doc = {
        "bomFormat": bom_format,
        "specVersion": "1.6",
        # One source-repo property: the "SBOM complete" check runs sbom_validate.py with
        # --expected-sources 1, so a fixture without it FAILs check 2 whenever Grype is present.
        "metadata": {"properties": [{"name": f"{SOURCE_REPO_PREFIX}example-repo", "value": "abc123"}]},
        "components": [{"name": f"pkg{i}", "version": "1.0", "type": "library"}
                       for i in range(components)],
    }
    path.write_text(json.dumps(doc))


def main() -> int:
    print("Sentinel gate engine tests\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)

        # 1. Missing SBOM, block mode → fail-closed, exit 1.
        rc, out = run_gate(tmpd / "nope.cdx.json", "block")
        check("missing SBOM blocks (exit 1)", rc == 1, f"rc={rc}")
        check("missing SBOM verdict shows BLOCKED", "BLOCKED" in out)
        check("missing SBOM present-check FAILs", "SBOM present | ⚠️ FAIL" in out)

        # 2. Missing SBOM, warn mode → reports FAIL but exits 0.
        rc, out = run_gate(tmpd / "nope.cdx.json", "warn")
        check("missing SBOM in warn mode exits 0", rc == 0, f"rc={rc}")
        check("warn-mode verdict says not blocking", "warn mode" in out)

        # 3. Zero-component SBOM → present check FAILs (nothing inventoried).
        empty = tmpd / "empty.cdx.json"
        write_sbom(empty, components=0)
        rc, out = run_gate(empty, "block")
        check("zero-component SBOM blocks (exit 1)", rc == 1, f"rc={rc}")
        check("zero-component detail mentions zero components",
              "zero components" in out)

        # 4. Non-CycloneDX doc → present check FAILs.
        notcdx = tmpd / "notcdx.cdx.json"
        write_sbom(notcdx, components=3, bom_format="SPDX")
        rc, out = run_gate(notcdx, "warn")
        check("non-CycloneDX flagged", "Not a CycloneDX" in out)

        # 5. Valid multi-component SBOM, Grype absent on PATH → vuln check ERROR,
        #    block mode fails closed (exit 1). (Grype is not installed in this test env.)
        good = tmpd / "good.cdx.json"
        write_sbom(good, components=5)
        rc, out = run_gate(good, "block")
        check("present check PASSes on a real SBOM", "SBOM present | ✅ PASS" in out)
        check("complete check PASSes (sbom_validate.py honoured, one source repo)",
              "SBOM complete | ✅ PASS" in out)
        # With Grype absent the vuln check ERRORs → block fails closed.
        if "Grype binary not on PATH" in out:
            check("Grype-absent fails closed in block mode (exit 1)", rc == 1, f"rc={rc}")
            check("Grype-absent reported as ERROR (not a silent PASS)", "🛑 ERROR" in out)
            # Same SBOM in warn mode → exits 0 despite the ERROR.
            rc_warn, _ = run_gate(good, "warn")
            check("Grype-absent in warn mode exits 0", rc_warn == 0, f"rc={rc_warn}")
        else:
            # Grype IS installed here — the 5 fake packages have no real CVEs, so PASS.
            check("with Grype present, clean SBOM passes (exit 0)", rc == 0, f"rc={rc}")

        # 6. Grype must NOT be invoked with -q: -q silences the diagnostic log
        #    lines (DB-load / schema-migration errors) that the ERROR branch
        #    surfaces via proc.stderr. Without this the failure mode is an
        #    empty "Grype exited 1:" message. Source-level guard.
        gate_src = GATE.read_text(encoding="utf-8")
        check('Grype invocation does not pass -q (keeps stderr for ERROR branch)',
              '"-q"' not in gate_src.split("def check_vulns")[1].split("def ")[0])

    print()
    if _failures:
        print(f"{len(_failures)} test(s) FAILED: {', '.join(_failures)}")
        return 1
    print("All Sentinel gate tests passed.")
    return 0


def test_sentinel_gate() -> None:
    """pytest entry point: the whole suite runs as one case; per-check results are printed."""
    assert main() == 0, f"{len(_failures)} check(s) failed: {_failures}"


if __name__ == "__main__":
    sys.exit(main())
