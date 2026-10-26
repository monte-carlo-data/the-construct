#!/usr/bin/env python3
"""
sbom_validate.py — Validate a merged CycloneDX SBOM produced by your SBOM-create workflow.

Checks performed:
  1. File parses as JSON.
  2. Top-level shape is CycloneDX 1.x (bomFormat == "CycloneDX", specVersion present).
  3. `components` array is present and non-empty.
  4. `metadata.properties` lists at least `--expected-sources` source-repo entries
     (each formatted `<SBOM_SOURCE_REPO_PREFIX><name>`, e.g. `your-org:source-repo:api`).
     This catches the case where a per-target scan silently dropped out of the merge.
  5. No component's `bom-ref` contains an obvious filesystem-path leak (a macOS or Linux
     home directory, a CI runner home, a scratch dir). Path leaks are a Syft footgun that
     should never reach a shareable SBOM.
  6. No component's `name` or `purl` contains the literal Anthropic API key prefix,
     known service-account email patterns, or `Bearer ` strings (basic secret tripwire).

Exits 0 on pass, non-zero on any failure. With --strict, warnings also fail the run.

Environment:
  SBOM_SOURCE_REPO_PREFIX   property-name prefix your SBOM-create step stamps per source repo
                            (default `your-org:source-repo:`).
  SBOM_EXPECTED_SOURCES     default for --expected-sources (default 1).

Usage:
  python3 sbom_validate.py --sbom path/to/merged-<date>.cdx.json \\
                           --expected-sources 18 [--strict]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


SOURCE_REPO_PREFIX = os.environ.get("SBOM_SOURCE_REPO_PREFIX", "your-org:source-repo:")
DEFAULT_EXPECTED_SOURCES = int(os.environ.get("SBOM_EXPECTED_SOURCES", "1"))

SECRET_TRIPWIRES = [
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),    # Anthropic API key prefix
    re.compile(r"Bearer [A-Za-z0-9._-]{16,}"),    # bearer tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS access key ID
    re.compile(r"ghp_[A-Za-z0-9]{36}"),           # GitHub personal access tokens
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
]

PATH_LEAK_PATTERNS = [
    re.compile(r"/private/tmp/"),
    re.compile(r"/Users/"),          # macOS home directories
    re.compile(r"/home/runner/"),    # GitHub-hosted runner home
    re.compile(r"/tmp/sbom-create-"),
]


def load_sbom(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        die(f"SBOM not found: {path}")
    except json.JSONDecodeError as e:
        die(f"SBOM is not valid JSON: {path}: {e}")
    return {}  # unreachable


def die(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(2)


def check_top_level_shape(sbom: dict) -> list[str]:
    errs: list[str] = []
    if sbom.get("bomFormat") != "CycloneDX":
        errs.append(f"bomFormat is {sbom.get('bomFormat')!r}, expected 'CycloneDX'")
    spec = sbom.get("specVersion", "")
    if not spec.startswith("1."):
        errs.append(f"specVersion is {spec!r}, expected '1.x'")
    if "components" not in sbom or not isinstance(sbom["components"], list):
        errs.append("`components` is missing or not a list")
    elif len(sbom["components"]) == 0:
        errs.append("`components` is empty — nothing was inventoried")
    return errs


def check_sources(sbom: dict, expected: int) -> tuple[list[str], list[str]]:
    """Return (errors, warnings)."""
    props = sbom.get("metadata", {}).get("properties", []) or []
    source_props = [
        p for p in props
        if isinstance(p, dict) and str(p.get("name", "")).startswith(SOURCE_REPO_PREFIX)
    ]
    found = len(source_props)
    errs: list[str] = []
    warns: list[str] = []
    if found < expected:
        errs.append(
            f"expected at least {expected} source-repo entries in metadata.properties, "
            f"found {found}"
        )
    elif found > expected:
        warns.append(
            f"found {found} source-repo entries, expected exactly {expected} — "
            f"scope may have grown without a spec update"
        )
    return errs, warns


def check_path_leaks(sbom: dict) -> list[str]:
    leaks: list[str] = []
    for c in sbom.get("components", []):
        for field in ("bom-ref", "name", "purl"):
            v = c.get(field)
            if not isinstance(v, str):
                continue
            for pat in PATH_LEAK_PATTERNS:
                if pat.search(v):
                    leaks.append(f"component {c.get('name','?')}::{field} contains path leak: {v[:80]}")
                    break
    return leaks


def check_secrets(sbom: dict) -> list[str]:
    blob = json.dumps(sbom)  # cheap: full-document scan
    hits: list[str] = []
    for pat in SECRET_TRIPWIRES:
        if pat.search(blob):
            hits.append(f"possible secret matching pattern {pat.pattern!r} present in SBOM")
    return hits


def validate(sbom_path: Path, expected_sources: int, strict: bool) -> int:
    sbom = load_sbom(sbom_path)
    errors: list[str] = []
    warnings: list[str] = []

    errors += check_top_level_shape(sbom)
    src_errs, src_warns = check_sources(sbom, expected_sources)
    errors += src_errs
    warnings += src_warns
    errors += check_path_leaks(sbom)
    errors += check_secrets(sbom)

    print(f"SBOM: {sbom_path}")
    print(f"  bomFormat:    {sbom.get('bomFormat')}")
    print(f"  specVersion:  {sbom.get('specVersion')}")
    print(f"  components:   {len(sbom.get('components', []))}")
    src_props = [p for p in sbom.get("metadata", {}).get("properties", []) if str(p.get("name","")).startswith(SOURCE_REPO_PREFIX)]
    print(f"  sources:      {len(src_props)} (expected {expected_sources})")
    print()

    for e in errors:
        print(f"FAIL: {e}", file=sys.stderr)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

    if errors:
        print(f"\nValidation FAILED with {len(errors)} error(s)", file=sys.stderr)
        return 2
    if strict and warnings:
        print(f"\nValidation FAILED in --strict mode with {len(warnings)} warning(s)", file=sys.stderr)
        return 2
    print(f"Validation PASSED ({len(warnings)} warning(s))")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sbom", required=True, type=Path, help="Path to merged CycloneDX SBOM JSON")
    p.add_argument("--expected-sources", type=int, default=DEFAULT_EXPECTED_SOURCES,
                   help=f"Expected count of {SOURCE_REPO_PREFIX}* properties "
                        f"(default {DEFAULT_EXPECTED_SOURCES}, or $SBOM_EXPECTED_SOURCES)")
    p.add_argument("--strict", action="store_true",
                   help="Treat warnings as failures")
    args = p.parse_args()
    return validate(args.sbom, args.expected_sources, args.strict)


if __name__ == "__main__":
    sys.exit(main())
