"""Tests for .github/scripts/sbom_validate.py (merged CycloneDX SBOM structural checks)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import sbom_validate as mod  # noqa: E402


def _doc(*, sources: int = 1, components: list[dict] | None = None, **top) -> dict:
    """A minimal merged CycloneDX document with `sources` source-repo properties."""
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "timestamp": "2026-01-01T00:00:00Z",
            "properties": [
                {"name": f"{mod.SOURCE_REPO_PREFIX}example-repo-{i}", "value": "abc123"}
                for i in range(sources)
            ],
        },
        "components": components if components is not None else [
            {"type": "library", "bom-ref": "pkg:npm/example-lib@1.0.0",
             "name": "example-lib", "version": "1.0.0", "purl": "pkg:npm/example-lib@1.0.0"},
        ],
    }
    doc.update(top)
    return doc


def _write(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "sbom.cdx.json"
    p.write_text(json.dumps(doc))
    return p


# --- pure checks ------------------------------------------------------------

def test_shape_ok_on_minimal_document():
    assert mod.check_top_level_shape(_doc()) == []


def test_shape_rejects_wrong_format_version_and_empty_components():
    errs = mod.check_top_level_shape({"bomFormat": "SPDX", "specVersion": "2.3", "components": []})
    assert any("bomFormat" in e for e in errs)
    assert any("specVersion" in e for e in errs)
    assert any("empty" in e for e in errs)
    assert any("missing" in e for e in mod.check_top_level_shape({"bomFormat": "CycloneDX", "specVersion": "1.5"}))


def test_sources_too_few_is_error_too_many_is_warning():
    assert mod.check_sources(_doc(sources=1), 2) == (
        ["expected at least 2 source-repo entries in metadata.properties, found 1"], [])
    errs, warns = mod.check_sources(_doc(sources=3), 2)
    assert errs == [] and len(warns) == 1 and "found 3" in warns[0]
    assert mod.check_sources(_doc(sources=2), 2) == ([], [])


def test_sources_only_count_the_configured_prefix():
    doc = _doc(sources=0)
    doc["metadata"]["properties"].append({"name": "other-org:source-repo:x", "value": "1"})
    assert mod.check_sources(doc, 1)[0]  # the foreign prefix does not count


def test_path_leaks_detected_in_ref_name_or_purl():
    leaked = _doc(components=[
        {"name": "ok", "bom-ref": "pkg:pypi/ok@1", "purl": "pkg:pypi/ok@1"},
        {"name": "bad", "bom-ref": "/home/runner/work/x/node_modules/bad", "purl": "pkg:npm/bad@1"},
        {"name": "/private/tmp/leak", "bom-ref": "r", "purl": "p"},
    ])
    leaks = mod.check_path_leaks(leaked)
    assert len(leaks) == 2
    assert all("path leak" in leak for leak in leaks)
    assert mod.check_path_leaks(_doc()) == []


def test_secret_tripwires_scan_the_whole_document():
    doc = _doc()
    doc["metadata"]["properties"].append({"name": "note", "value": "AKIA" + "A" * 16})
    hits = mod.check_secrets(doc)
    assert len(hits) == 1 and "AKIA" in hits[0]
    assert mod.check_secrets(_doc()) == []


# --- end to end -------------------------------------------------------------

def test_validate_passes_minimal_document(tmp_path, capsys):
    assert mod.validate(_write(tmp_path, _doc()), 1, strict=False) == 0
    assert "Validation PASSED" in capsys.readouterr().out


def test_validate_fails_on_missing_sources(tmp_path, capsys):
    assert mod.validate(_write(tmp_path, _doc(sources=0)), 1, strict=False) == 2
    assert "FAIL: expected at least 1 source-repo" in capsys.readouterr().err


def test_validate_strict_turns_warning_into_failure(tmp_path):
    p = _write(tmp_path, _doc(sources=2))
    assert mod.validate(p, 1, strict=False) == 0
    assert mod.validate(p, 1, strict=True) == 2


def test_validate_missing_or_invalid_file_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        mod.validate(tmp_path / "nope.json", 1, strict=False)
    assert exc.value.code == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(SystemExit) as exc:
        mod.validate(bad, 1, strict=False)
    assert exc.value.code == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
