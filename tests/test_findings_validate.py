#!/usr/bin/env python3
"""Tests for the findings ledger validator (.github/scripts/findings_validate.py).

The validator parses the roster, domain vocabulary and matrix-target allow-set FROM the
contract docs (`findings/SCHEMA.md`, `findings/HANDOFF_PROTOCOL.md`) rather than hardcoding
them, so the first tests prove those parsers read this repo's docs correctly. The rest
exercise `validate_finding` against the shipped example finding(s) and against synthetic
findings that must be rejected — in particular an off-matrix `suggested_next`, the
Zero-Trust poisoning signal.

Run:  python3 -m pytest tests/test_findings_validate.py
Requires PyYAML (the validator's only non-stdlib import).
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import findings_validate as fv  # via tests/conftest.py sys.path

REPO_ROOT = Path(__file__).resolve().parents[1]
FINDINGS_DIR = REPO_ROOT / "findings"
EXAMPLES = sorted((FINDINGS_DIR / "examples").glob("*.md"))

SCHEMA_TEXT = (FINDINGS_DIR / "SCHEMA.md").read_text()
PROTOCOL_TEXT = (FINDINGS_DIR / "HANDOFF_PROTOCOL.md").read_text()


@pytest.fixture(scope="module")
def roster() -> set[str]:
    return fv.parse_roster(SCHEMA_TEXT)


@pytest.fixture(scope="module")
def domains() -> set[str]:
    return fv.parse_domains(SCHEMA_TEXT)


@pytest.fixture(scope="module")
def allow_set() -> set[str]:
    return fv.parse_allow_set(PROTOCOL_TEXT)


# ---------------------------------------------------------------------------
# Doc parsers — the roster / allow-set / matrix come from the docs, never code
# ---------------------------------------------------------------------------

class TestDocParsers:
    def test_roster_parses_from_schema(self, roster):
        # Route targets, emit-only agents and the sensor tier are all `agent` values.
        for slug in ("john-wick", "trinity", "security-steve", "tank", "panther", "aws"):
            assert slug in roster
        # The engineering SDLC line-up is deliberately NOT on the roster.
        for slug in ("dozer", "apoc", "twins"):
            assert slug not in roster

    def test_domains_parse_from_schema(self, domains):
        assert len(domains) == 8
        assert "5 — Identity & Access Management" in domains
        assert "7 — Security Operations" in domains

    def test_allow_set_parses_from_protocol(self, allow_set, roster):
        assert len(allow_set) == 12
        assert allow_set <= roster
        # Emit-only agents and sensors are never route targets.
        for slug in ("tank", "cypher", "tracer", "on-call", "panther", "wing"):
            assert slug not in allow_set

    def test_allow_set_equals_matrix_union(self, allow_set):
        # Zero-Trust Rule 2: the documented block is derived from the matrix rows.
        assert fv.parse_matrix_union(PROTOCOL_TEXT) == allow_set

    def test_contract_self_check_is_clean(self):
        assert fv.check_contract(SCHEMA_TEXT, PROTOCOL_TEXT) == []


# ---------------------------------------------------------------------------
# The shipped example finding(s) validate clean
# ---------------------------------------------------------------------------

class TestExamples:
    def test_examples_dir_has_a_reference_finding(self):
        assert EXAMPLES, "findings/examples/ should ship at least one reference finding"

    @pytest.mark.parametrize("path", EXAMPLES, ids=[p.name for p in EXAMPLES])
    def test_example_validates(self, path, roster, domains, allow_set):
        data, raw = fv.load_frontmatter(path)
        assert isinstance(data, dict), f"{path.name}: {raw}"
        if data.get("id") in fv.INTENTIONAL_OFF_MATRIX:
            pytest.skip("intentionally poisoned fixture — covered by TestIntentionalFixture")
        errs = fv.validate_finding(path, data, roster, domains, allow_set, seen_ids={})
        assert errs == [], errs


# ---------------------------------------------------------------------------
# Synthetic findings — each invariant has a rejection test
# ---------------------------------------------------------------------------

def _good() -> dict:
    return {
        "schema_version": 1,
        "id": "2026-07-01-trinity-example-mfa-gap-abc123",
        "agent": "trinity",
        "timestamp": "2026-07-01T12:00:00Z",
        "severity": "high",
        "domain": "5 — Identity & Access Management",
        "subject": "okta-user:jdoe@example.com",
        "owner": "unknown",
        "status": "open",
        "evidence": [{"system": "okta", "url": "https://your-org.okta.com/admin/user/EXAMPLE"}],
        "suggested_next": ["morpheus"],
    }


def _validate(data: dict, roster, domains, allow_set, stem: str | None = None) -> list[str]:
    path = Path(f"findings/{stem or data['id']}.md")
    return fv.validate_finding(path, data, roster, domains, allow_set, seen_ids={})


class TestValidateFinding:
    def test_good_finding_is_clean(self, roster, domains, allow_set):
        assert _validate(_good(), roster, domains, allow_set) == []

    def test_off_matrix_suggested_next_is_rejected(self, roster, domains, allow_set):
        # `tank` is a real roster agent but no matrix row routes to it: a poisoning signal.
        data = _good() | {"suggested_next": ["tank"]}
        errs = _validate(data, roster, domains, allow_set)
        assert any("OFF-MATRIX" in e and "'tank'" in e for e in errs), errs

    def test_off_roster_suggested_next_is_rejected(self, roster, domains, allow_set):
        data = _good() | {"suggested_next": ["ghost-agent"]}
        errs = _validate(data, roster, domains, allow_set)
        assert any("OFF-MATRIX" in e and "'ghost-agent'" in e for e in errs), errs

    def test_engineering_agent_cannot_emit(self, roster, domains, allow_set):
        # The engineering SDLC line-up is not on the roster, so `agent: dozer` fails.
        data = _good() | {"agent": "dozer"}
        errs = _validate(data, roster, domains, allow_set)
        assert any("not in SCHEMA roster" in e for e in errs), errs

    def test_missing_required_field(self, roster, domains, allow_set):
        data = _good()
        del data["owner"]
        errs = _validate(data, roster, domains, allow_set)
        assert any("missing required field" in e and "owner" in e for e in errs), errs

    def test_bad_enums(self, roster, domains, allow_set):
        data = _good() | {"severity": "urgent", "status": "wontfix", "domain": "9 — Nope"}
        errs = _validate(data, roster, domains, allow_set)
        assert any("severity" in e for e in errs)
        assert any("status" in e for e in errs)
        assert any("domain" in e for e in errs)

    def test_unquoted_timestamp_is_rejected(self, roster, domains, allow_set, tmp_path):
        # An unquoted ISO-8601 timestamp parses to a datetime: not JSON-serializable.
        path = tmp_path / "2026-07-01-trinity-ts-abc123.md"
        path.write_text(
            "---\nschema_version: 1\nid: 2026-07-01-trinity-ts-abc123\nagent: trinity\n"
            "timestamp: 2026-07-01T12:00:00Z\nseverity: low\n"
            "domain: 5 — Identity & Access Management\nsubject: x\nowner: unknown\n"
            "status: open\nevidence: []\nsuggested_next: []\n---\n\n## What\n"
        )
        data, _ = fv.load_frontmatter(path)
        errs = fv.validate_finding(path, data, roster, domains, allow_set, seen_ids={})
        assert any("not JSON-serializable" in e for e in errs), errs
        assert any("timestamp is not a string" in e for e in errs), errs

    def test_id_must_match_filename_stem(self, roster, domains, allow_set):
        errs = _validate(_good(), roster, domains, allow_set, stem="some-other-name")
        assert any("!= filename stem" in e for e in errs), errs

    def test_duplicate_id_is_rejected(self, roster, domains, allow_set):
        seen: dict = {}
        data = _good()
        path = Path(f"findings/{data['id']}.md")
        assert fv.validate_finding(path, data, roster, domains, allow_set, seen) == []
        errs = fv.validate_finding(Path(f"findings/dup/{data['id']}.md"), copy.deepcopy(data),
                                   roster, domains, allow_set, seen)
        assert any("duplicate id" in e for e in errs), errs

    def test_unsupported_schema_version(self, roster, domains, allow_set):
        errs = _validate(_good() | {"schema_version": 2}, roster, domains, allow_set)
        assert any("schema_version" in e for e in errs), errs

    def test_non_finding_file_is_skipped(self, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("# just a doc, no frontmatter\n")
        data, reason = fv.load_frontmatter(path)
        assert data is None and reason == "no frontmatter"


# ---------------------------------------------------------------------------
# Self-check B — an intentionally poisoned fixture must STAY off-matrix
# ---------------------------------------------------------------------------

class TestIntentionalFixture:
    def _seed(self, tmp_path: Path, monkeypatch, suggested_next: str) -> str:
        fid = "2026-07-02-cypher-poisoned-example-c0ffee"
        (tmp_path / "examples").mkdir()
        (tmp_path / "examples" / f"{fid}.md").write_text(
            f"---\nschema_version: 1\nid: {fid}\nagent: cypher\n"
            f'timestamp: "2026-07-02T00:00:00Z"\nseverity: high\n'
            f"domain: 8 — Software Development Security\nsubject: your-org/example-repo\n"
            f"owner: unknown\nstatus: open\nevidence: []\nsuggested_next: {suggested_next}\n---\n"
        )
        monkeypatch.setattr(fv, "FINDINGS_DIR", tmp_path)
        monkeypatch.setattr(fv, "INTENTIONAL_OFF_MATRIX", {fid})
        return fid

    def test_default_has_no_configured_fixture(self):
        # Shipped empty: self-check B is a no-op until you seed a poisoned fixture.
        assert fv.INTENTIONAL_OFF_MATRIX == set()
        assert fv.check_intentional_fixture(set(), set()) == []

    def test_still_off_matrix_passes(self, tmp_path, monkeypatch, roster, allow_set):
        self._seed(tmp_path, monkeypatch, "[tank]")
        assert fv.check_intentional_fixture(roster, allow_set) == []

    def test_fixture_drifting_on_matrix_is_flagged(self, tmp_path, monkeypatch, roster, allow_set):
        self._seed(tmp_path, monkeypatch, "[morpheus]")
        errs = fv.check_intentional_fixture(roster, allow_set)
        assert any("fully ON-matrix" in e for e in errs), errs

    def test_missing_fixture_is_flagged(self, tmp_path, monkeypatch, roster, allow_set):
        monkeypatch.setattr(fv, "FINDINGS_DIR", tmp_path)
        monkeypatch.setattr(fv, "INTENTIONAL_OFF_MATRIX", {"2026-07-02-cypher-gone-000000"})
        errs = fv.check_intentional_fixture(roster, allow_set)
        assert any("not found under examples/" in e for e in errs), errs


# ---------------------------------------------------------------------------
# Driver — the real ledger runs clean
# ---------------------------------------------------------------------------

def test_run_over_this_repo_passes(capsys):
    assert fv.run(strict=False) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
