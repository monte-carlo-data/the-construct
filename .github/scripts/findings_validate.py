#!/usr/bin/env python3
"""
Findings ledger validator.

Enforces the `findings/` contract — the invariants a reviewer would otherwise verify
by hand every time the roster or the sensor tier changes — as a repeatable check. Runs
with no network, no token: it reads only `findings/*.md` and the two contract docs.

What it checks, per live finding (`findings/*.md`, excluding the doc files and the
`examples/` fixtures):
  1. Frontmatter parses as YAML **and round-trips to JSON** (no YAML-only constructs —
     SCHEMA "1:1 JSON-serializable"; the classic trap is an unquoted ISO-8601 `timestamp`
     that becomes a Python datetime).
  2. Every REQUIRED field is present.
  3. Every enum is in vocab: `severity`, `status`, `domain`, `agent`, and every
     `suggested_next` slug.
  4. `agent` is in the SCHEMA roster; every `suggested_next` slug is in the
     **matrix-target allow-set** (a slug on the roster but not a route target is
     OFF-MATRIX — the Zero-Trust poisoning signal).
  5. `id` equals the filename stem and is unique across the ledger.
  6. `schema_version` is the supported major version.

And two **contract self-checks** (independent of any finding), so the docs can't drift:
  A. The documented allow-set block in HANDOFF_PROTOCOL equals the union of the matrix
     rows' `suggested_next` columns (Zero-Trust Rule 2, "derived, not hand-maintained").
  B. Any intentionally poisoned fixture listed in INTENTIONAL_OFF_MATRIX (an
     `examples/` finding that deliberately routes off-matrix) is STILL off-matrix —
     so the negative test keeps testing something. Empty by default; add the id of
     your own poisoned fixture when you seed one.

The roster and allow-set are parsed **from the docs**, never hardcoded, so this stays
correct as the roster evolves (e.g. the sensor tier, future emit-only agents).

Run:
    python .github/scripts/findings_validate.py           # validate the ledger
    python .github/scripts/findings_validate.py --strict  # also fail on warnings
Exit 0 = clean, 1 = at least one error. Fail-soft print style (every problem is
listed, never just the first); unit tests live in tests/test_findings_validate.py.

Dependencies: Python 3.11+ and PyYAML (`pip install pyyaml`) — the only non-stdlib
import, needed to parse finding frontmatter.
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml to run the findings validator")

REPO_ROOT = Path(__file__).resolve().parents[2]
FINDINGS_DIR = REPO_ROOT / "findings"
SCHEMA_MD = FINDINGS_DIR / "SCHEMA.md"
PROTOCOL_MD = FINDINGS_DIR / "HANDOFF_PROTOCOL.md"

# Doc files are not findings (same exclusion the orchestrator uses). The examples/
# dir holds reference/negative fixtures; they are excluded from the live sweep and
# exercised by tests/test_findings_validate.py through validate_finding() directly.
DOC_FILES = {"README.md", "SCHEMA.md", "HANDOFF_PROTOCOL.md"}

REQUIRED_FIELDS = {
    "schema_version", "id", "agent", "timestamp", "severity", "domain",
    "subject", "owner", "status", "evidence", "suggested_next",
}
SEVERITY_VOCAB = {"critical", "high", "medium", "low", "informational"}
STATUS_VOCAB = {"open", "handed-off", "escalated", "resolved"}
SUPPORTED_SCHEMA_VERSIONS = {1}

# Fixtures under examples/ that are DELIBERATELY off-matrix — they exist to prove the
# poisoning detection has something to catch. Keyed by finding id. The validator
# asserts they STAY off-matrix (self-check B) rather than flagging them. Empty until
# you seed a poisoned fixture of your own (e.g. a finding whose `suggested_next`
# names an emit-only agent such as `tank`); then add its id here.
INTENTIONAL_OFF_MATRIX: set[str] = set()


# ---------------------------------------------------------------------------
# Parse the contract docs (roster + allow-set) — never hardcode them.
# ---------------------------------------------------------------------------

def parse_roster(schema_text: str) -> set[str]:
    """The `agent` vocabulary = the first-column code-spans of the roster table."""
    section = schema_text.split("## Agent roster")[1].split("\n---\n")[0]
    return set(re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", section, re.M))


def parse_domains(schema_text: str) -> set[str]:
    """The `domain` vocabulary = the backticked `N — Name` values in the domain table."""
    section = schema_text.split("## Domain vocabulary")[1].split("\n---\n")[0]
    return set(m.strip() for m in re.findall(r"`(\d+ — [^`]+)`", section))


def parse_allow_set(protocol_text: str) -> set[str]:
    """The matrix-target allow-set = the fenced 12-slug block under 'The matrix-target allow-set'."""
    block = protocol_text.split("The matrix-target allow-set")[1].split("```text")[1].split("```")[0]
    return {s for s in re.findall(r"[a-z0-9-]+", block) if not s.isdigit() and s != "slugs"}


def parse_matrix_union(protocol_text: str) -> set[str]:
    """Independent derivation: the union of every matrix row's `suggested_next` column."""
    matrix = protocol_text.split("## The handoff matrix")[1].split("## `suggested_next` population logic")[0]
    slugs = set()
    for cell in re.findall(r"`\[([^\]]*)\]`", matrix):
        slugs.update(re.findall(r"[a-z0-9-]+", cell))
    return slugs


# ---------------------------------------------------------------------------
# Finding loading
# ---------------------------------------------------------------------------

def load_frontmatter(path: Path):
    """Return (data, raw_frontmatter) or (None, reason) if it isn't a finding."""
    text = path.read_text()
    if not text.startswith("---"):
        return None, "no frontmatter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, "malformed frontmatter fences"
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        return None, "frontmatter is not a mapping"
    return data, parts[1]


def validate_finding(path: Path, data: dict, roster: set, domains: set,
                     allow_set: set, seen_ids: dict) -> list[str]:
    """Return a list of error strings for one finding (empty = valid)."""
    errs = []

    # 1. JSON round-trip (catches unquoted-datetime and other YAML-only constructs).
    try:
        json.dumps(data)
    except (TypeError, ValueError) as e:
        errs.append(f"frontmatter not JSON-serializable ({e}); check for an unquoted timestamp")

    # 2. Required fields.
    missing = REQUIRED_FIELDS - set(data)
    if missing:
        errs.append(f"missing required field(s): {sorted(missing)}")

    # 3 + 4 + 6. Enums / roster / allow-set / version.
    if "schema_version" in data and data["schema_version"] not in SUPPORTED_SCHEMA_VERSIONS:
        errs.append(f"schema_version {data['schema_version']!r} not supported {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    if "severity" in data and data["severity"] not in SEVERITY_VOCAB:
        errs.append(f"severity {data['severity']!r} not in vocab")
    if "status" in data and data["status"] not in STATUS_VOCAB:
        errs.append(f"status {data['status']!r} not in vocab")
    if "domain" in data and str(data["domain"]).strip() not in domains:
        errs.append(f"domain {data['domain']!r} not in CISSP domain vocab")
    if "agent" in data and data["agent"] not in roster:
        errs.append(f"agent {data['agent']!r} not in SCHEMA roster")
    sn = data.get("suggested_next")
    if sn is not None:
        if not isinstance(sn, list):
            errs.append(f"suggested_next must be a list, got {type(sn).__name__}")
        else:
            for slug in sn:
                if slug not in allow_set:
                    errs.append(f"suggested_next {slug!r} is OFF-MATRIX (not a route target) — poisoning signal")

    # 5. id == filename stem, and unique.
    fid = data.get("id")
    if fid:
        if fid != path.stem:
            errs.append(f"id {fid!r} != filename stem {path.stem!r}")
        if fid in seen_ids:
            errs.append(f"duplicate id {fid!r} (also in {seen_ids[fid].name})")
        else:
            seen_ids[fid] = path

    # timestamp must be a quoted string (SCHEMA rule) — safe_load turns an unquoted one
    # into a datetime, which the JSON round-trip above already flags; make it explicit.
    if "timestamp" in data and not isinstance(data["timestamp"], str):
        errs.append("timestamp is not a string — quote it (unquoted ISO-8601 parses to a datetime)")

    return errs


# ---------------------------------------------------------------------------
# Contract self-checks (docs can't drift)
# ---------------------------------------------------------------------------

def check_contract(schema_text: str, protocol_text: str) -> list[str]:
    errs = []
    allow_set = parse_allow_set(protocol_text)
    union = parse_matrix_union(protocol_text)
    # A. documented allow-set == union of matrix rows (Zero-Trust Rule 2).
    if allow_set != union:
        only_block = allow_set - union
        only_matrix = union - allow_set
        errs.append(
            "allow-set block != union of matrix rows "
            f"(block-only={sorted(only_block)}, matrix-only={sorted(only_matrix)}) — "
            "regenerate the allow-set block per HANDOFF_PROTOCOL 'derived, not hand-maintained'"
        )
    # Every allow-set slug must be a real roster slug.
    roster = parse_roster(schema_text)
    off_roster = allow_set - roster
    if off_roster:
        errs.append(f"allow-set contains non-roster slug(s): {sorted(off_roster)}")
    return errs


def check_intentional_fixture(roster: set, allow_set: set) -> list[str]:
    """Self-check B: the known poisoned fixture must STILL be off-matrix."""
    errs = []
    for fid in INTENTIONAL_OFF_MATRIX:
        matches = list(FINDINGS_DIR.glob(f"examples/{fid}.md"))
        if not matches:
            errs.append(f"intentional-poisoned fixture {fid!r} not found under examples/ — "
                        "update INTENTIONAL_OFF_MATRIX if it was renamed/removed")
            continue
        data, _ = load_frontmatter(matches[0])
        if not isinstance(data, dict):
            errs.append(f"poisoned fixture {fid!r} did not parse")
            continue
        sn = data.get("suggested_next") or []
        if all(s in allow_set for s in sn):
            errs.append(f"poisoned fixture {fid!r} is now fully ON-matrix ({sn}) — "
                        "the negative test no longer tests poisoning detection")
    return errs


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def run(strict: bool = False) -> int:
    schema_text = SCHEMA_MD.read_text()
    protocol_text = PROTOCOL_MD.read_text()
    roster = parse_roster(schema_text)
    domains = parse_domains(schema_text)
    allow_set = parse_allow_set(protocol_text)

    print(f"roster={len(roster)} slugs · allow-set={len(allow_set)} route targets · "
          f"domains={len(domains)}")

    errors = 0

    # Contract self-checks first — if the docs are inconsistent, everything downstream is suspect.
    for e in check_contract(schema_text, protocol_text):
        print(f"CONTRACT  {e}"); errors += 1
    for e in check_intentional_fixture(roster, allow_set):
        print(f"FIXTURE   {e}"); errors += 1

    # Live findings.
    seen_ids: dict = {}
    live = sorted(p for p in FINDINGS_DIR.glob("*.md") if p.name not in DOC_FILES)
    for path in live:
        data, reason = load_frontmatter(path)
        if data is None:
            print(f"SKIP      {path.name} ({reason})")
            if strict:
                errors += 1
            continue
        errs = validate_finding(path, data, roster, domains, allow_set, seen_ids)
        if errs:
            for e in errs:
                print(f"INVALID   {path.name}: {e}")
            errors += len(errs)
        else:
            print(f"OK        {path.name}")

    print()
    if errors:
        print(f"FAILED — {errors} error(s) across {len(live)} live finding(s)")
        return 1
    print(f"PASSED — {len(live)} live finding(s) valid; contract + poisoned-fixture self-checks OK")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Validate the findings/ ledger against the SCHEMA + handoff matrix.")
    ap.add_argument("--strict", action="store_true",
                    help="also fail on non-finding files that slipped into findings/ (SKIP → error)")
    args = ap.parse_args()
    sys.exit(run(strict=args.strict))


if __name__ == "__main__":
    main()
