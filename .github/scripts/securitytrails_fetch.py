#!/usr/bin/env python3
"""
SecurityTrails deterministic fetcher for Switch perimeter mode.

Why this exists: Switch's `perimeter` mode needs CT-log + DNS/DNSSEC data from SecurityTrails. Doing
that via the agent's `WebFetch` tool gives the agent open internet egress while it also holds Slack/Linear
write tools — a prompt-injection → exfiltration channel that a *prose* rule can't enforce. This script is
the **enforced boundary**: it only ever talks to the SecurityTrails API host, so the agent no longer needs
WebFetch at all. The agent invokes this, reads JSON back, and treats it as untrusted data.

Hard guarantees:
  - Network egress is restricted to exactly ONE host: api.securitytrails.com (HOST constant). The URL is
    built here from a validated domain arg — it is never taken from the agent/model or from fetched data.
  - The API key is read at call time from the environment (sourced from your credential vault by the
    caller) and is NEVER printed, logged, or echoed back in output.
  - Output is plain JSON on stdout for the agent to diff against its baseline. Nothing executable.

Usage:
  SECURITYTRAILS_API_KEY=<key> python3 .github/scripts/securitytrails_fetch.py <domain> [--what subdomains|dns|whois]

  <domain> must be a bare hostname (e.g. example.com). It is validated against a strict regex; anything
  else is rejected. The caller (Switch) passes one monitored domain at a time.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

# The ONLY host this script will ever contact. Not overridable by arg, env, or input.
HOST = "api.securitytrails.com"
BASE = f"https://{HOST}/v1"

# Strict hostname validation — labels of letters/digits/hyphens, dot-separated, 1–253 chars total.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)

# Endpoints we allow, keyed by --what. Each is a fixed path template; the domain is the only variable,
# and it's URL-encoded. No caller-supplied path or query reaches the request.
_ENDPOINTS = {
    "subdomains": "/domain/{d}/subdomains",   # CT/passive surface for the domain
    "dns": "/domain/{d}",                      # current DNS records
    "whois": "/domain/{d}/whois",
}


def _validate_domain(domain: str) -> str:
    if not _DOMAIN_RE.match(domain):
        sys.stderr.write(f"ERROR: invalid domain '{domain}' — must be a bare hostname.\n")
        sys.exit(2)
    return domain.lower()


def fetch(domain: str, what: str, api_key: str) -> dict:
    path = _ENDPOINTS[what].format(d=urllib.parse.quote(domain, safe=""))
    url = f"{BASE}{path}"
    # Defense in depth: confirm the assembled URL still points at the one allowed host.
    if urllib.parse.urlparse(url).hostname != HOST:
        sys.stderr.write("ERROR: refusing to fetch — assembled URL is not the SecurityTrails host.\n")
        sys.exit(2)
    req = urllib.request.Request(url, headers={"APIKEY": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — host is the hardcoded constant
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        # Never include the key or full headers in the error.
        sys.stderr.write(f"ERROR: SecurityTrails request failed ({type(e).__name__}): {e}\n")
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic SecurityTrails fetch (one host only).")
    ap.add_argument("domain", help="bare hostname, e.g. example.com")
    ap.add_argument("--what", choices=list(_ENDPOINTS), default="dns")
    args = ap.parse_args()

    api_key = os.environ.get("SECURITYTRAILS_API_KEY", "")
    if not api_key:
        sys.stderr.write("ERROR: SECURITYTRAILS_API_KEY not set (source it from your credential vault before calling).\n")
        return 2

    domain = _validate_domain(args.domain)
    data = fetch(domain, args.what, api_key)
    # Plain JSON to stdout — untrusted data for the agent to diff, nothing executable.
    json.dump({"domain": domain, "what": args.what, "host": HOST, "data": data}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
