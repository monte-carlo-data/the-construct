"""Tests for .github/scripts/domain_surface_discover.py (crt.sh host discovery, key-free)."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import domain_surface_discover as mod  # noqa: E402

INVENTORY = """# Domain Inventory

## External domain surface

| Domain | Purpose | Zone | Scorecard id | Notes |
| --- | --- | --- | --- | --- |
| `example.com` | product | dns-repo | ✅ | |
| `example.org` | marketing | root | ✅ | |
| `example-parked.com`, `example-parked.net` | parked | dns-repo | — | redirects |
| not a domain | — | — | — | |

### Probe hosts (self-run TLS / header checks)

| Host | Purpose | Apex | Scanner finding |
|---|---|---|---|
| `example.com` | apex | example.com | — |
| `ingest.example.com` | ingest | example.com | TLS |

## Something else

| Domain | x |
| --- | --- |
| `ignored.example` | y |
"""


def _rows(*names: str) -> list[dict]:
    return [{"name_value": "\n".join(names)}]


# --- inventory parsing ------------------------------------------------------

def test_parse_apexes_reads_first_table_only_and_splits_comma_cells():
    assert mod.parse_apexes(INVENTORY) == [
        "example.com", "example.org", "example-parked.com", "example-parked.net",
    ]


def test_parse_apexes_empty_when_heading_missing():
    assert mod.parse_apexes("# nothing here\n| a | b |\n") == []


def test_validate_apex_rejects_garbage():
    for bad in ("", "localhost", "-x.com", "a b.com", "evil.com/../", "x" * 70 + ".com"):
        with pytest.raises(mod.DiscoverError):
            mod.validate_apex(bad)
    assert mod.validate_apex(" Example.COM. ") == "example.com"


# --- crt.sh egress boundary -------------------------------------------------

def test_build_url_is_pinned_to_crt_sh_and_encodes_query():
    url = mod.build_url("example.com")
    assert url.startswith("https://crt.sh/?")
    assert "q=%25.example.com" in url and "output=json" in url


def test_build_url_rejects_invalid_apex():
    with pytest.raises(mod.DiscoverError):
        mod.build_url("crt.sh/../../evil")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_ct_parses_json_and_sends_user_agent():
    seen = {}

    def opener(req, timeout):
        seen["url"] = req.full_url
        seen["ua"] = req.get_header("User-agent")
        return _Resp(json.dumps(_rows("a.example.com")).encode())

    rows = mod.fetch_ct("example.com", opener=opener, sleep=lambda s: None)
    assert rows == _rows("a.example.com")
    assert seen["url"].startswith("https://crt.sh/")
    assert "domain-surface-discover" in seen["ua"]


def test_fetch_ct_retries_once_on_5xx_then_raises():
    calls = []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

    with pytest.raises(mod.DiscoverError, match="unavailable"):
        mod.fetch_ct("example.com", opener=opener, sleep=lambda s: None)
    assert len(calls) == mod.CT_RETRIES


def test_fetch_ct_does_not_retry_4xx():
    calls = []

    def opener(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)

    with pytest.raises(mod.DiscoverError, match="HTTP 400"):
        mod.fetch_ct("example.com", opener=opener, sleep=lambda s: None)
    assert len(calls) == 1


def test_fetch_ct_rejects_non_list_payload():
    def opener(req, timeout):
        return _Resp(b'{"oops": 1}')

    with pytest.raises(mod.DiscoverError, match="non-list"):
        mod.fetch_ct("example.com", opener=opener, sleep=lambda s: None)


# --- name extraction --------------------------------------------------------

def test_names_from_ct_dedupes_lowercases_and_drops_wildcards_and_foreign_names():
    rows = [
        {"name_value": "API.Example.com\n*.example.com\nexample.com"},
        {"name_value": "api.example.com\nadmin@example.com\nnotexample.com\nx.other.org"},
        {"name_value": "bad_name.example.com\n-lead.example.com"},
    ]
    assert mod.names_from_ct(rows, "example.com") == ["api.example.com", "example.com"]


def test_names_from_ct_tolerates_missing_field():
    assert mod.names_from_ct([{}, {"name_value": None}], "example.com") == []


# --- liveness ---------------------------------------------------------------

def test_liveness_classifies_three_states():
    status = mod.liveness(
        ["live.example.com", "parked.example.com", "gone.example.com"],
        resolve_fn=lambda h: h != "gone.example.com",
        connect_fn=lambda h: h == "live.example.com",
        workers=2,
    )
    assert status == {
        "live.example.com": "live",
        "parked.example.com": "resolves",
        "gone.example.com": "no DNS record",
    }


# --- discover + render ------------------------------------------------------

def _fake_fetch(apex):
    if apex == "example.org":
        raise mod.DiscoverError("crt.sh unavailable for example.org: boom")
    return _rows(
        "example.com", "ingest.example.com", "api.example.com",
        "old.example.com", "*.example.com",
    )


def _fake_live(hosts):
    return {h: ("no DNS record" if h.startswith("old.") else "live") for h in hosts}


def test_discover_excludes_probed_hosts_and_records_per_apex_errors():
    result = mod.discover(
        ["example.com", "example.org"],
        mod.parse_probe_hosts(INVENTORY),
        fetch=_fake_fetch, live_fn=_fake_live,
    )
    assert result["errors"] == {"example.org": "crt.sh unavailable for example.org: boom"}
    assert [(h["host"], h["status"]) for h in result["hosts"]] == [
        ("api.example.com", "live"),
        ("old.example.com", "no DNS record"),
    ]
    assert all(h["apex"] == "example.com" and h["probed"] is False for h in result["hosts"])


def test_discover_include_probed_flags_existing_rows():
    result = mod.discover(["example.com"], mod.parse_probe_hosts(INVENTORY),
                          fetch=_fake_fetch, live_fn=_fake_live, include_probed=True)
    probed = {h["host"] for h in result["hosts"] if h["probed"]}
    assert probed == {"example.com", "ingest.example.com"}


def test_render_lists_candidate_rows_and_errors():
    result = mod.discover(["example.com", "example.org"], mod.parse_probe_hosts(INVENTORY),
                          fetch=_fake_fetch, live_fn=_fake_live)
    text = mod.render(result)
    assert "ERROR example.org" in text
    assert "| `api.example.com` | TODO | example.com | discovered " in text
    assert "| Host | Class | Apex | Note |" in text
    assert "old.example.com" not in text.split("Candidate rows")[1]
    assert "live and not in probe table: 1" in text


def test_render_without_candidates_has_no_table():
    text = mod.render({"apexes": ["x.com"], "errors": {}, "hosts": []})
    assert "Candidate rows" not in text and "CT names: 0" in text


# --- CLI --------------------------------------------------------------------

def test_main_defaults_apexes_from_inventory_and_prints_json(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text(INVENTORY, encoding="utf-8")
    seen = []

    def fetch(apex):
        seen.append(apex)
        return _rows(f"new.{apex}")

    out = io.StringIO()
    rc = mod.main(["--json", "--inventory", str(inv)], fetch=fetch, live_fn=_fake_live, out=out)
    assert rc == 0
    assert seen == ["example.com", "example.org", "example-parked.com", "example-parked.net"]
    data = json.loads(out.getvalue())
    assert {h["host"] for h in data["hosts"]} == {f"new.{a}" for a in seen}


def test_main_explicit_apexes_override_inventory(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text(INVENTORY, encoding="utf-8")
    seen = []
    out = io.StringIO()
    rc = mod.main(["example.net", "--inventory", str(inv)],
                  fetch=lambda a: seen.append(a) or [], live_fn=_fake_live, out=out)
    assert rc == 0 and seen == ["example.net"]


def test_main_bad_apex_exits_2(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text(INVENTORY, encoding="utf-8")
    rc = mod.main(["not valid", "--inventory", str(inv)], fetch=lambda a: [], live_fn=_fake_live,
                  out=io.StringIO())
    assert rc == 2


def test_main_missing_inventory_exits_2(tmp_path):
    rc = mod.main(["--inventory", str(tmp_path / "nope.md")], fetch=lambda a: [],
                  live_fn=_fake_live, out=io.StringIO())
    assert rc == 2


def test_main_all_apexes_failing_exits_1(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text(INVENTORY, encoding="utf-8")

    def fetch(apex):
        raise mod.DiscoverError("down")

    rc = mod.main(["--inventory", str(inv)], fetch=fetch, live_fn=_fake_live, out=io.StringIO())
    assert rc == 1


def test_main_partial_failure_exits_0(tmp_path):
    inv = tmp_path / "inv.md"
    inv.write_text(INVENTORY, encoding="utf-8")
    rc = mod.main(["--inventory", str(inv)], fetch=_fake_fetch, live_fn=_fake_live, out=io.StringIO())
    assert rc == 0


def test_template_inventory_parses_apexes_and_probe_hosts():
    """Guard the shipped template: both tables must parse (the scripts' only inputs)."""
    markdown = (REPO_ROOT / "knowledge" / "Domain_Inventory.md").read_text(encoding="utf-8")
    apexes = mod.parse_apexes(markdown)
    assert "example.com" in apexes and "example.org" in apexes
    assert "example-parked.net" in apexes  # comma-separated cell
    hosts = mod.parse_probe_hosts(markdown)
    assert "www.example.com" in hosts and len(hosts) >= 3


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
