#!/usr/bin/env python3
"""github_app_fetch.py: the org-owned-App read path (.github/scripts/github_app_fetch.py). Fakes throughout - no network."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".github" / "scripts"))

import github_app_fetch as gaf  # noqa: E402


def test_missing_env_fails_cleanly(monkeypatch):
    monkeypatch.delenv("GH_APP_ID", raising=False)
    monkeypatch.delenv("GH_APP_PRIVATE_KEY", raising=False)
    try:
        gaf.fetch("your-org/example-repo/knowledge/x.md")
        assert False, "should have raised"
    except SystemExit as e:
        assert "GH_APP_ID" in str(e)


def test_url_and_shorthand_parse_identically(monkeypatch):
    monkeypatch.setenv("GH_APP_ID", "123")
    monkeypatch.setenv("GH_APP_PRIVATE_KEY", "pem")
    seen = {}

    class FakeResp:
        status = 200
        def read(self): return b'{"id": 42}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req):
        seen["url"] = req.full_url
        return FakeResp()

    # installation resolution path: _token_for is faked to a constant, urlopen faked for the fetch
    monkeypatch.setattr(gaf, "_token_for", lambda *a: "tok")
    monkeypatch.setattr(gaf.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(gaf, "fetch", gaf.fetch)  # no-op, clarity

    # patch the raw fetch's read to return text instead of the JSON above
    class FakeTextResp(FakeResp):
        def read(self): return b"hello"
    monkeypatch.setattr(gaf.urllib.request, "urlopen", lambda req: FakeTextResp())

    a = gaf.fetch("https://raw.githubusercontent.com/your-org/example-repo/main/knowledge/x.md")
    b = gaf.fetch("your-org/example-repo/knowledge/x.md")
    assert a == b == "hello"


def test_token_cache_reused_within_ttl(monkeypatch):
    monkeypatch.setattr(gaf, "_jwt", lambda *a: "jwt")
    calls = {"n": 0}

    def fake_api(method, url, token, body=None):
        calls["n"] += 1
        return 201, {"token": "tok", "expires_at": "soon"}

    monkeypatch.setattr(gaf, "_api", fake_api)
    monkeypatch.setenv("GH_APP_INSTALLATION_ID", "42")
    gaf._token_cache.clear()
    gaf._token_for("1", "pem", "42", "o", "repo")
    gaf._token_for("1", "pem", "42", "o", "repo")
    assert calls["n"] == 1, "second call within TTL must reuse the cached token"


def test_installation_resolved_per_repo_when_unset(monkeypatch):
    monkeypatch.setattr(gaf, "_jwt", lambda *a: "jwt")
    seen = []

    def fake_api(method, url, token, body=None):
        seen.append(url)
        if url.endswith("/installation"):
            return 200, {"id": 77}
        return 201, {"token": "tok"}

    monkeypatch.setattr(gaf, "_api", fake_api)
    gaf._token_cache.clear()
    gaf._token_for("1", "pem", "", "your-org", "example-repo")
    assert seen[0].endswith("/repos/your-org/example-repo/installation")
    assert "/app/installations/77/access_tokens" in seen[1]


def test_token_request_is_scoped_to_the_repo(monkeypatch):
    monkeypatch.setattr(gaf, "_jwt", lambda *a: "jwt")
    bodies = []

    def fake_api(method, url, token, body=None):
        bodies.append(body)
        return 201, {"token": "tok"}

    monkeypatch.setattr(gaf, "_api", fake_api)
    gaf._token_cache.clear()
    gaf._token_for("1", "pem", "42", "your-org", "example-repo")
    assert bodies[0] == {"repositories": ["example-repo"], "permissions": {"contents": "read"}}
