#!/usr/bin/env python3
"""Fetch a private GitHub file using an org-owned GitHub App - NO PAT, no user account.

Read-mostly agents need to pull Git source-of-truth files (e.g. the approved-inventory lists)
from inside a container. A PAT ties that to a user (or a service USER, which still needs a
mailbox, a GitHub invite, and a rotation calendar). An org-owned GitHub App avoids all three: the
container mints a short-lived installation token (1h, contents:read on exactly the installed repos)
and fetches with it.

Env (inject from your credential vault / secrets manager; never commit them):
    GH_APP_ID                  the App's id
    GH_APP_PRIVATE_KEY         the App's PEM (multiline value is fine in an env var)
    GH_APP_INSTALLATION_ID     optional - resolved per-repo via the API when unset

Requires PyJWT with the `crypto` extra (`pip install 'PyJWT[crypto]'`) for the RS256 App JWT.

Usage: github_app_fetch.py <raw.githubusercontent.com URL or owner/repo/path[,ref]>
Prints the file to stdout; exits non-zero with a clean stderr message on any failure (never the key).
"""
from __future__ import annotations

import os
import sys
import time
import urllib.request

# PyJWT[crypto] is imported lazily in _jwt() (RS256 needs the cryptography extra) so a missing dep
# surfaces as a clean message, and images that carry this module but never call it don't break.

API = "https://api.github.com"
_token_cache: dict[str, tuple[str, float]] = {}  # repo -> (token, expires_at)


def _fail(msg: str) -> "SystemExit":
    return SystemExit(f"github_app_fetch: {msg}")


def _jwt(app_id: str, pem: str) -> str:
    try:
        import jwt
    except ImportError:
        raise _fail("PyJWT[crypto] is not installed in this image")
    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, pem, algorithm="RS256")


def _api(method: str, url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    import json
    req = urllib.request.Request(url, method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode(errors="replace")
        raise _fail(f"GitHub API {method} {url} -> {e.code} ({detail})")


def _token_for(app_id: str, pem: str, inst: str, owner: str, repo: str) -> str:
    cached = _token_cache.get(repo)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    app_jwt = _jwt(app_id, pem)
    if not inst:
        st, d = _api("GET", f"{API}/repos/{owner}/{repo}/installation", app_jwt)
        if st != 200:
            raise _fail(f"App is not installed on {owner}/{repo} (or the JWT is wrong)")
        inst = str(d["id"])
    # Scope the token to THIS repo with contents:read even if the App holds more - the wire
    # credential is then narrower than the App, not just the install.
    st, d = _api("POST", f"{API}/app/installations/{inst}/access_tokens", app_jwt,
                 {"repositories": [repo], "permissions": {"contents": "read"}})
    if st != 201:
        raise _fail(f"access token mint for {repo} -> {st}")
    exp = time.time() + 3600
    if d.get("expires_at"):  # 1h by default; parse defensively without a date lib
        exp = time.time() + 3500
    _token_cache[repo] = (d["token"], exp)
    return d["token"]


def fetch(spec: str) -> str:
    app_id = os.environ.get("GH_APP_ID", "").strip()
    pem = os.environ.get("GH_APP_PRIVATE_KEY", "").strip()
    if not app_id or not pem:
        raise _fail("GH_APP_ID and GH_APP_PRIVATE_KEY are required")
    inst = os.environ.get("GH_APP_INSTALLATION_ID", "").strip()
    if spec.startswith("https://raw.githubusercontent.com/"):
        parts = spec[len("https://raw.githubusercontent.com/"):].split("/", 3)
        if len(parts) != 4:
            raise _fail(f"unparseable raw URL: {spec}")
        owner, repo, ref, path = parts
    else:
        # owner/repo/path form - the default ref is main
        parts = spec.split("/", 2)
        if len(parts) != 3 or not all(parts):
            raise _fail(f"expected owner/repo/path, got: {spec}")
        owner, repo, path = parts
        ref = "main"
    token = _token_for(app_id, pem, inst, owner, repo)
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    req = urllib.request.Request(raw, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        raise _fail(f"fetch {owner}/{repo}/{path} -> {e.code}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise _fail("usage: github_app_fetch.py <raw-url | owner/repo/path>")
    sys.stdout.write(fetch(sys.argv[1]))
