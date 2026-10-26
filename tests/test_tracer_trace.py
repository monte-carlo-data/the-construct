#!/usr/bin/env python3
"""Tests for the Tracer requirements-to-test traceability extractor
(.github/scripts/tracer_trace.py).

Tracer's whole value is a DETERMINISTIC, auditable matrix: the same spec + same
verification surface yields the same requirement→test mapping every run, with no
model call. These tests exercise the pure functions behind that — spec parsing
(FR/SC/AISVS), the explicit-vs-inferred matcher, and the no-false-green summary —
with a synthetic in-memory file map, so they need no Anthropic API and no disk
(other than the shipped AISVS chapter registry).

Run:  python3 tests/test_tracer_trace.py      (standalone, prints every check)
      python3 -m pytest tests/                 (pytest: a failed check raises)
Exits 0 if all pass, 1 otherwise. Stdlib only.

Requirement traceability (the citation convention Tracer looks for — a spec-local
FR id next to the spec's ticket id. Swap `SEC-1234` for your own spec's ticket id
if you write a spec for Tracer and want this file to show as `covered`):
  - SEC-1234 FR-001: test_parse_spec        — FR/SC/AISVS parsing + level + dedup
  - SEC-1234 FR-002: test_explicit_match    — scan surface, covered/inferred/unmapped
  - SEC-1234 FR-003: test_explicit_match, test_no_false_substring_match, test_inferred_match
  - SEC-1234 FR-004: test_summary_no_false_green — coverage counts explicit only
  - SEC-1234 FR-005: test_spec_scope_guard  — spec-local id needs spec scope
  - SEC-1234 FR-006: test_determinism       — model-free, identical on repeat
  - SEC-1234 FR-007: test_aisvs_registry    — AISVS labels from config, no crash empty
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "tracer_trace.py"

spec = importlib.util.spec_from_file_location("tracer_trace", SCRIPT)
tracer = importlib.util.module_from_spec(spec)
# Register before exec so dataclass introspection (which resolves the module via
# sys.modules under `from __future__ import annotations`) can find it.
sys.modules["tracer_trace"] = tracer
spec.loader.exec_module(tracer)

parse_spec = tracer.parse_spec
build_matrix = tracer.build_matrix
match_requirement = tracer.match_requirement
summarize = tracer.summarize

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)
        if "pytest" in sys.modules:  # under pytest a failed check must fail the test, not just print
            raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


SAMPLE_SPEC = """# Feature Specification: Widget Gate

## Functional requirements

- **FR-001** — The gate MUST reject an unsigned widget manifest before deploy.
- **FR-002**: The system SHOULD emit a structured audit record for each rejection.
- **FR-003 — Threshold config.** Thresholds MUST live in `widget-gate.yaml`, never the code.
- **FR-001** — duplicate cross-reference that must NOT create a second row.

This design maps to AISVS C3 (model & provider security) and AISVS Chapter 6.

## Success criteria

- **SC-1** — A deliberately-unsigned manifest is rejected and audited in CI.
- **SC-2** — Re-running the gate on the same manifest is idempotent.
"""


def test_parse_spec() -> None:
    print("parse_spec:")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}

    check("parses three distinct FRs", sum(1 for r in reqs if r.kind == "functional") == 3,
          f"{[r.id for r in reqs if r.kind=='functional']}")
    check("FR id is canonical", "FR-001" in by_id and "FR-002" in by_id and "FR-003" in by_id)
    check("FR-001 not duplicated", [r.id for r in reqs].count("FR-001") == 1)

    check("FR-001 level MUST", by_id["FR-001"].level == "MUST", by_id["FR-001"].level)
    check("FR-002 level SHOULD", by_id["FR-002"].level == "SHOULD", by_id["FR-002"].level)

    check("parses two SCs", sum(1 for r in reqs if r.kind == "success-criterion") == 2)
    check("SC has empty level", by_id["SC-1"].level == "")

    aisvs = {r.id for r in reqs if r.kind == "aisvs"}
    check("AISVS C3 + Chapter 6 normalized", aisvs == {"AISVS-C3", "AISVS-C6"}, str(aisvs))

    # Keywords drop boilerplate stopwords ("system", "must", "the").
    kw = by_id["FR-001"].keywords
    check("keywords exclude boilerplate", "must" not in kw and "system" not in kw and "the" not in kw, str(kw))
    check("keywords keep distinctive nouns", "widget" in kw or "manifest" in kw, str(kw))


def test_explicit_match() -> None:
    print("\nmatch_requirement — explicit citation is authoritative:")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}

    files = {
        "tests/test_widget_gate.py": "def test_fr001_rejects_unsigned(): ...  # covers FR-001",
        "tests/test_other.py": "def test_unrelated(): assert True",
    }
    row = match_requirement(by_id["FR-001"], files)
    check("explicit FR-001 -> covered", row.status == "covered", row.status)
    check("explicit ref names the file", row.explicit_refs == ["tests/test_widget_gate.py"], str(row.explicit_refs))

    # Compact form (FR001) in a test name also counts as explicit.
    row2 = match_requirement(by_id["FR-001"], {"tests/t.py": "def test_FR001(): pass"})
    check("compact FR001 token -> covered", row2.status == "covered", row2.status)


def test_no_false_substring_match() -> None:
    print("\nmatch_requirement — id boundary (no FR-001 inside FR-0011):")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}
    files = {"tests/t.py": "# this references FR-0011, a different requirement"}
    row = match_requirement(by_id["FR-001"], files)
    check("FR-001 does NOT match FR-0011", row.status == "unmapped", row.status)

    # Trailing-letter boundary: FR-001 must not match FR-001a (sub-label), and the
    # compact form FR001 must not match FR001foo.
    row2 = match_requirement(by_id["FR-001"], {"tests/t.py": "# covers FR-001a only"})
    check("FR-001 does NOT match FR-001a", row2.status == "unmapped", row2.status)
    row3 = match_requirement(by_id["FR-001"], {"tests/t.py": "def test_FR001foo(): ..."})
    check("compact FR001 does NOT match FR001foo", row3.status == "unmapped", row3.status)


def test_overlong_id_not_dropped() -> None:
    # Regression: a digit-capped id regex + \b silently DROPPED 5+ digit ids. A
    # traceability tool must never silently lose a requirement.
    print("\nparse_spec — over-length ids are parsed, not silently dropped:")
    reqs = parse_spec("- **FR-12345** — The system MUST handle a five-digit id.\n")
    ids = [r.id for r in reqs]
    check("FR-12345 parsed (not dropped)", "FR-12345" in ids, str(ids))


def test_short_stem_no_scope_collapse() -> None:
    # Regression: a tiny stem (ai/v2) as a scope token would substring-match nearly
    # every file and defeat the cross-spec guard.
    print("\nspec_scope_tokens — short stem is not a scope token:")
    scope = tracer.spec_scope_tokens("specs/ai.md")
    check("2-char stem excluded from scope", "ai" not in scope, str(scope))
    # With no distinctive scope token, a bare FR-001 must NOT auto-cover.
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}
    row = match_requirement(by_id["FR-001"], {"tests/t.py": "# ai FR-001 here"}, scope)
    check("no distinctive scope => not covered", row.status != "covered", row.status)
    # A long stem (no ticket id) IS distinctive enough to be a scope token.
    scope2 = tracer.spec_scope_tokens("specs/widget-gate-design.md")
    check("long stem kept as scope", "widget-gate-design" in scope2, str(scope2))


def test_inferred_match() -> None:
    print("\nmatch_requirement — keyword heuristic is 'inferred', never 'covered':")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}

    # No id token, but two distinctive keywords co-occur -> inferred.
    files = {"tests/test_x.py": "def test_rejects_unsigned_widget_manifest(): ..."}
    row = match_requirement(by_id["FR-001"], files)
    check("keyword co-occurrence -> inferred", row.status == "inferred", row.status)
    check("inferred ref recorded", row.inferred_refs == ["tests/test_x.py"], str(row.inferred_refs))

    # One keyword only -> not enough -> unmapped.
    row2 = match_requirement(by_id["FR-001"], {"tests/y.py": "def test_widget_color(): ..."})
    check("single keyword -> unmapped", row2.status == "unmapped", row2.status)


def test_aisvs_match() -> None:
    print("\nmatch_requirement — AISVS chapter reference round-trips:")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}
    files = {"tests/test_models.py": "# verifies AISVS Chapter 3 provider controls"}
    row = match_requirement(by_id["AISVS-C3"], files)
    check("AISVS C3 matched via 'AISVS Chapter 3'", row.status == "covered", row.status)
    # AISVS rows have no keywords, so they never infer.
    row2 = match_requirement(by_id["AISVS-C6"], {"tests/t.py": "model provider security stuff"})
    check("AISVS never inferred (no keywords)", row2.status == "unmapped", row2.status)


def test_spec_scope_guard() -> None:
    print("\nmatch_requirement — spec-local id needs spec scope (no cross-spec collision):")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}
    # These fixtures are in-memory file maps, so the placeholder ticket ids never
    # collide with a real spec when Tracer traces this repo itself.
    scope = tracer.spec_scope_tokens("specs/sec-1234-widget-gate.md")

    # A file citing FR-001 AND the spec's ticket id => in scope => covered.
    in_scope = {"tests/test_widget.py": "# SEC-1234 FR-001: rejects unsigned"}
    row = match_requirement(by_id["FR-001"], in_scope, scope)
    check("FR-001 + spec ticket id -> covered", row.status == "covered", row.status)

    # A DIFFERENT spec's test mentions FR-001 (its own) but not THIS spec's scope.
    other = {"tests/test_other.py": "# GRC-100 FR-001: unrelated requirement"}
    row2 = match_requirement(by_id["FR-001"], other, scope)
    check("FR-001 from another spec -> not covered", row2.status != "covered", row2.status)

    # AISVS is a GLOBAL id — matched even without spec scope.
    row3 = match_requirement(by_id["AISVS-C3"], {"tests/t.py": "AISVS Chapter 3 checks"}, scope)
    check("AISVS matched unscoped (global id)", row3.status == "covered", row3.status)

    # scope tokens include the ticket id (case-insensitive) and the stem.
    check("scope tokens include ticket id",
          any(s.lower() == "sec-1234" for s in scope), str(scope))


def test_summary_no_false_green() -> None:
    print("\nsummarize — coverage counts EXPLICIT only (no false-green):")
    reqs = parse_spec(SAMPLE_SPEC)
    by_id = {r.id: r for r in reqs}
    files = {
        # FR-001 explicit, FR-002 inferred (2 keywords), FR-003 nothing.
        "tests/test_a.py": "test_fr001(): ...",
        "tests/test_b.py": "def test_structured_audit_record_rejection(): ...",
    }
    rows = build_matrix([by_id["FR-001"], by_id["FR-002"], by_id["FR-003"]], files)
    s = summarize(rows)
    check("covered counts only explicit", s["covered"] == 1, str(s))
    check("inferred is separate from covered", s["inferred"] == 1, str(s))
    check("unmapped counted", s["unmapped"] == 1, str(s))
    check("coverage_pct excludes inferred", s["coverage_pct"] == round(100 / 3, 1), str(s["coverage_pct"]))


def test_aisvs_registry() -> None:
    print("\nAISVS registry — labels load from config + enrich parsed chapters:")
    labels = tracer.load_aisvs_labels()
    check("registry loads non-empty", len(labels) >= 10, str(len(labels)))
    check("C3 has a title", labels.get("AISVS-C3", "") != "", labels.get("AISVS-C3", ""))

    reqs = parse_spec(SAMPLE_SPEC)
    tracer.enrich_aisvs(reqs, labels)
    c3 = next(r for r in reqs if r.id == "AISVS-C3")
    check("C3 text enriched with title", labels["AISVS-C3"] in c3.text, c3.text)

    # Empty labels => no crash, generic text preserved.
    reqs2 = parse_spec(SAMPLE_SPEC)
    tracer.enrich_aisvs(reqs2, {})
    c3b = next(r for r in reqs2 if r.id == "AISVS-C3")
    check("empty registry is a no-op", "chapter 3" in c3b.text.lower(), c3b.text)


def test_determinism() -> None:
    print("\ndeterminism — same inputs => identical matrix:")
    reqs = parse_spec(SAMPLE_SPEC)
    files = {"tests/test_a.py": "test_fr001(): ...", "tests/test_b.py": "widget manifest unsigned reject"}
    a = tracer.to_dict("spec.md", build_matrix(reqs, files), summarize(build_matrix(reqs, files)))
    b = tracer.to_dict("spec.md", build_matrix(reqs, files), summarize(build_matrix(reqs, files)))
    check("two runs identical", a == b)


def main() -> int:
    print("Tracer traceability extractor tests\n")
    test_parse_spec()
    test_explicit_match()
    test_no_false_substring_match()
    test_overlong_id_not_dropped()
    test_short_stem_no_scope_collapse()
    test_inferred_match()
    test_aisvs_match()
    test_spec_scope_guard()
    test_summary_no_false_green()
    test_aisvs_registry()
    test_determinism()

    print()
    if _failures:
        print(f"{len(_failures)} test(s) FAILED: {', '.join(_failures)}")
        return 1
    print("All Tracer traceability tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
