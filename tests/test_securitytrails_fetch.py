"""Tests for .github/scripts/securitytrails_fetch.py (host-pinned SecurityTrails fetcher). No network."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import securitytrails_fetch as mod  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_validate_domain_lowercases_bare_hostnames():
    assert mod._validate_domain("Example.COM") == "example.com"
    assert mod._validate_domain("api.example.com") == "api.example.com"


@pytest.mark.parametrize("bad", ["", "-x.com", "a b.com", "example.com/../", "https://example.com",
                                 "x" * 70 + ".com", "example.com?x=1", "user@example.com"])
def test_validate_domain_rejects_anything_but_a_hostname(bad, capsys):
    with pytest.raises(SystemExit) as exc:
        mod._validate_domain(bad)
    assert exc.value.code == 2
    assert "invalid domain" in capsys.readouterr().err


@pytest.mark.parametrize("what,path", [
    ("dns", "/v1/domain/example.com"),
    ("subdomains", "/v1/domain/example.com/subdomains"),
    ("whois", "/v1/domain/example.com/whois"),
])
def test_fetch_builds_pinned_url_and_sends_key_header(monkeypatch, what, path):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["key"] = req.get_header("Apikey")
        seen["timeout"] = timeout
        return _Resp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.fetch("example.com", what, "k-secret") == {"ok": True}
    assert seen["url"] == f"https://{mod.HOST}{path}"
    assert seen["key"] == "k-secret" and seen["timeout"] == 20


def test_fetch_url_encodes_the_domain_segment(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        return _Resp(b"{}")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    mod.fetch("sub.example.com", "dns", "k")
    assert seen["url"].startswith("https://api.securitytrails.com/v1/domain/")
    assert seen["url"].count("/") == 5  # scheme + host + v1 + domain + encoded name, no extra path


def test_fetch_failure_exits_1_without_echoing_the_key(monkeypatch, capsys):
    def fake_urlopen(req, timeout):
        raise OSError("boom")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit) as exc:
        mod.fetch("example.com", "dns", "k-secret")
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "request failed" in err and "k-secret" not in err


def test_main_requires_the_key_in_env(monkeypatch, capsys):
    monkeypatch.delenv("SECURITYTRAILS_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["securitytrails_fetch.py", "example.com"])
    assert mod.main() == 2
    assert "SECURITYTRAILS_API_KEY" in capsys.readouterr().err


def test_main_prints_json_envelope(monkeypatch, capsys):
    monkeypatch.setenv("SECURITYTRAILS_API_KEY", "k")
    monkeypatch.setattr(sys, "argv", ["securitytrails_fetch.py", "Example.com", "--what", "subdomains"])
    monkeypatch.setattr(mod, "fetch", lambda domain, what, key: {"subdomains": ["www"]})
    assert mod.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"domain": "example.com", "what": "subdomains", "host": mod.HOST,
                   "data": {"subdomains": ["www"]}}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
