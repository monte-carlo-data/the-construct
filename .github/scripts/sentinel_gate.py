#!/usr/bin/env python3
"""Sentinel — Secure Build gate.

Turns your SBOM tooling from documentation into an enforced release gate.
Given a CycloneDX SBOM for a repo, run three fail-closed checks and emit a
verdict the reusable workflow posts as a PR comment:

  1. SBOM present     — the file exists, parses as CycloneDX, has >=1 component.
  2. SBOM complete    — delegate to the existing sbom_validate.py
                        (--expected-sources 1); honor its exit code.
  3. Vuln threshold   — run Grype over the SBOM, count CRITICAL CVE matches,
                        FAIL when the count exceeds --critical-threshold.

This is the executable behind the `/sentinel` skill (.claude/commands/sentinel.md)
and the reusable workflow (.github/workflows/sentinel-gate-reusable.yml). It is
the SBOM counterpart to an image-centric vuln-scan workflow, and it reuses the
SAME Syft->Grype pipeline your SBOM-create (Syft) and SBOM-scanning (Grype over
CycloneDX) tooling already run — no new scanner.

Fail-closed by design: a missing/unparseable SBOM or an unavailable Grype binary
is a check FAILURE (ERROR), never a silent PASS. The gate only exits non-zero in
--mode block; in --mode warn it reports FAILs but always exits 0 (the
merge-but-dormant rollout — flip to block once the signal is trusted).

Stdlib only (like sbom_validate.py) — no pip install needed beyond Syft + Grype
on PATH, which the workflow installs.

Usage:
    python sentinel_gate.py --sbom sbom.cdx.json --mode warn \
        --critical-threshold 0 [--repo owner/name] [--run-url URL] [--out verdict.md]

Exit codes:
    0  gate passed, OR mode==warn (always 0 in warn mode)
    1  mode==block AND >=1 check FAILED/ERRORED
    2  bad invocation (e.g. --sbom missing on disk handled as a FAIL, not a crash)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# The completeness check reuses the repo's existing validator rather than
# re-implementing SBOM validation. Same dir as this script.
VALIDATOR = Path(__file__).resolve().parent / "sbom_validate.py"

COMMENT_MARKER = "<!-- sentinel-secure-build-gate -->"  # stable marker for idempotent PR comment

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"
_ICON = {PASS: "✅", FAIL: "⚠️", ERROR: "🛑"}


# ---------------------------------------------------------------------------
# Check 1 — SBOM present
# ---------------------------------------------------------------------------

def check_present(sbom: Path) -> tuple[str, str, dict]:
    """(status, detail, parsed-or-empty). Fail-closed: no file / no components = FAIL."""
    if not sbom.is_file():
        return FAIL, f"No SBOM at `{sbom}` — build cannot be proven clean.", {}
    try:
        doc = json.loads(sbom.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return ERROR, f"SBOM could not be read/parsed: {type(e).__name__}: {e}", {}
    if doc.get("bomFormat") != "CycloneDX":
        return FAIL, f"Not a CycloneDX SBOM (bomFormat={doc.get('bomFormat')!r}).", doc
    components = doc.get("components") or []
    if not components:
        return FAIL, "SBOM has zero components — nothing was inventoried.", doc
    return PASS, f"CycloneDX {doc.get('specVersion', '?')} · {len(components)} components.", doc


# ---------------------------------------------------------------------------
# Check 2 — SBOM complete (delegate to sbom_validate.py)
# ---------------------------------------------------------------------------

def check_complete(sbom: Path) -> tuple[str, str]:
    """Shell out to the existing validator (single-source scope). Honor its exit code."""
    if not VALIDATOR.is_file():
        return ERROR, f"validator not found at `{VALIDATOR}`."
    try:
        proc = subprocess.run(
            [sys.executable, str(VALIDATOR), "--sbom", str(sbom), "--expected-sources", "1"],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired:
        return ERROR, "sbom_validate.py timed out."
    if proc.returncode == 0:
        return PASS, "structural validation passed (path-leak / secret / shape checks)."
    # Validator prints each failure; surface a trimmed tail so the PR comment is useful.
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    detail = " ".join(tail[-4:]) if tail else f"validator exited {proc.returncode}."
    return FAIL, detail[:500]


# ---------------------------------------------------------------------------
# Check 3 — CRITICAL known-vuln threshold (Grype over the SBOM)
# ---------------------------------------------------------------------------

def _grype_available() -> bool:
    return shutil.which("grype") is not None


def check_vulns(sbom: Path, threshold: int) -> tuple[str, str, list[dict]]:
    """Run Grype over the CycloneDX SBOM; FAIL if CRITICAL count > threshold.

    Mirrors the normalization in your SBOM-scanning tooling.
    Fail-closed: Grype missing/erroring is ERROR, never a silent PASS.
    """
    if not _grype_available():
        return ERROR, "Grype binary not on PATH — cannot evaluate the vuln threshold.", []
    try:
        # NOTE: do NOT pass -q here. -q silences Grype's diagnostic log lines —
        # including the DB-load / schema-migration errors the ERROR branch below
        # reports via proc.stderr. With -q, a real failure surfaces as
        # "Grype exited 1:" with nothing after the colon. JSON still goes to
        # stdout (-o json), so keeping stderr un-silenced costs us nothing.
        proc = subprocess.run(
            ["grype", f"sbom:{sbom}", "-o", "json"],
            capture_output=True, text=True, timeout=300, check=False,
        )
    except subprocess.TimeoutExpired:
        return ERROR, "Grype timed out scanning the SBOM.", []
    if proc.returncode != 0:
        return ERROR, f"Grype exited {proc.returncode}: {proc.stderr.strip()[:300]}", []

    try:
        out = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as e:
        return ERROR, f"Could not parse Grype JSON: {e}", []

    sev_count: dict[str, int] = {}
    criticals: list[dict] = []
    for m in out.get("matches", []):
        vuln = m.get("vulnerability", {})
        artifact = m.get("artifact", {})
        sev = (vuln.get("severity") or "Unknown").title()
        sev_count[sev] = sev_count.get(sev, 0) + 1
        if sev == "Critical":
            fixed = (vuln.get("fix") or {}).get("versions") or []
            criticals.append({
                "cve": vuln.get("id"),
                "package": artifact.get("name"),
                "version": artifact.get("version"),
                "fixed_in": ", ".join(fixed) if fixed else "—",
                "url": vuln.get("dataSource"),
            })

    n_crit = sev_count.get("Critical", 0)
    # Context line: Critical/High/Medium counts (only CRITICAL gates in v1).
    ctx = " · ".join(
        f"{sev_count.get(s, 0)} {s}" for s in ("Critical", "High", "Medium") if sev_count.get(s)
    ) or "no CVE matches"
    if n_crit > threshold:
        return FAIL, f"{n_crit} CRITICAL CVE(s) > threshold {threshold} ({ctx}).", criticals
    return PASS, f"{n_crit} CRITICAL ≤ threshold {threshold} ({ctx}).", criticals


# ---------------------------------------------------------------------------
# Verdict rendering
# ---------------------------------------------------------------------------

def render_verdict(results: list[tuple[str, str, str]], criticals: list[dict],
                   mode: str, threshold: int, repo: str | None, run_url: str | None) -> str:
    """results: list of (check_name, status, detail). Returns the PR-comment markdown."""
    any_fail = any(status in (FAIL, ERROR) for _n, status, _d in results)
    if not any_fail:
        headline = "✅ **PASS** — secure-build gate is green."
    elif mode == "block":
        headline = "🛑 **BLOCKED** — secure-build gate failed (this build is blocked)."
    else:
        headline = "⚠️ **FAIL (warn mode)** — gate failed but is not blocking yet."

    lines = [
        COMMENT_MARKER,
        "## 🛡️ Sentinel — Secure Build Gate",
        "",
        headline,
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for name, status, detail in results:
        lines.append(f"| {name} | {_ICON[status]} {status} | {detail} |")
    lines.append("")

    if criticals:
        lines += ["### CRITICAL findings", "",
                  "| CVE | Package | Version | Fixed in |", "|---|---|---|---|"]
        for c in criticals:
            cve = f"[{c['cve']}]({c['url']})" if c.get("url") else (c.get("cve") or "—")
            lines.append(f"| {cve} | {c.get('package') or '—'} | {c.get('version') or '—'} | {c.get('fixed_in')} |")
        lines.append("")

    meta = []
    if repo:
        meta.append(f"repo `{repo}`")
    meta.append(f"mode `{mode}`")
    meta.append(f"CRITICAL threshold `{threshold}`")
    if run_url:
        meta.append(f"[CI run]({run_url})")
    lines.append("_" + " · ".join(meta) + " · Sentinel_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sbom", required=True, type=Path, help="Path to the repo's CycloneDX SBOM JSON")
    p.add_argument("--mode", choices=["warn", "block"], default="warn",
                   help="warn = report FAILs but exit 0; block = exit non-zero on any FAIL")
    p.add_argument("--critical-threshold", type=int, default=0,
                   help="Max allowed CRITICAL CVEs before the vuln check fails (default 0)")
    p.add_argument("--repo", default=None, help="owner/name, for the verdict footer")
    p.add_argument("--run-url", default=None, help="CI run URL, for the verdict footer")
    p.add_argument("--out", type=Path, default=None, help="Also write the verdict markdown here")
    args = p.parse_args()

    # Check 1 — present (and parse once for downstream context).
    s_present, d_present, _doc = check_present(args.sbom)
    results = [("SBOM present", s_present, d_present)]

    # Only run the deeper checks if the SBOM is at least readable; otherwise they
    # would crash or be meaningless. A missing SBOM already FAILs the gate.
    criticals: list[dict] = []
    if s_present == PASS:
        s_complete, d_complete = check_complete(args.sbom)
        results.append(("SBOM complete", s_complete, d_complete))
        s_vuln, d_vuln, criticals = check_vulns(args.sbom, args.critical_threshold)
        results.append((f"CRITICAL ≤ {args.critical_threshold}", s_vuln, d_vuln))
    else:
        results.append(("SBOM complete", ERROR, "skipped — no usable SBOM."))
        results.append((f"CRITICAL ≤ {args.critical_threshold}", ERROR, "skipped — no usable SBOM."))

    verdict = render_verdict(results, criticals, args.mode, args.critical_threshold,
                             args.repo, args.run_url)
    print(verdict)
    if args.out:
        args.out.write_text(verdict + "\n", encoding="utf-8")

    failed = any(status in (FAIL, ERROR) for _n, status, _d in results)
    if failed and args.mode == "block":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
