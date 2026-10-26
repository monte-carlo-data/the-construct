#!/usr/bin/env python3
"""Discover public hosts under your apex domains and diff them against the probe table.

The weekly domain-surface monitor only probes the hosts listed under `### Probe hosts` in
your domain inventory (a markdown file; see DOMAIN_INVENTORY_PATH below and the template at
knowledge/Domain_Inventory.md). A customer's scanner (SecurityScorecard, BitSight) finds
hosts the same way everyone else does — from certificate-transparency logs — so this script
asks the same source, key-free, and prints the hosts that are live today but absent from the
probe table. A human reviews the list and adds rows; nothing here edits the inventory.

Egress boundary: the ONLY remote host contacted for discovery is crt.sh (constant below).
Apex strings are validated before they reach the URL. Liveness is a DNS lookup plus one TCP
connect to :443 per candidate — no HTTP request, no TLS handshake.

Inventory format (two markdown tables):
    ## External domain surface      first column = apex domain (comma-separated cells allowed)
    ### Probe hosts                 first column = hostname already probed weekly

Environment:
    DOMAIN_INVENTORY_PATH   path to the inventory markdown (default knowledge/Domain_Inventory.md
                            relative to the repo root; --inventory overrides).

Usage:
    python3 .github/scripts/domain_surface_discover.py                  # apexes from inventory
    python3 .github/scripts/domain_surface_discover.py example.com example.org
    python3 .github/scripts/domain_surface_discover.py --json           # machine-readable
    python3 .github/scripts/domain_surface_discover.py --all            # include hosts already probed

Exit codes: 0 ok (candidates or none) · 1 a crt.sh fetch failed for every apex · 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

# The script lives in .github/scripts/ and imports its siblings by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from domain_surface_probe import parse_probe_hosts  # noqa: E402  (sibling module)

CT_HOST = "crt.sh"
CT_TIMEOUT_SECONDS = 90
CT_RETRIES = 3  # crt.sh answers 502/503 under load; later attempts usually succeed
CT_RETRY_SLEEP_SECONDS = 10
CONNECT_TIMEOUT_SECONDS = 4
WORKERS = 16
USER_AGENT = "domain-surface-discover (the-construct)"

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = Path(os.environ.get("DOMAIN_INVENTORY_PATH", "") or
                      REPO_ROOT / "knowledge" / "Domain_Inventory.md")
APEX_HEADING = "## External domain surface"

_APEX_RE = re.compile(r"^(?=.{4,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


class DiscoverError(Exception):
    pass


# ---------------------------------------------------------------------------
# Inventory parsing
# ---------------------------------------------------------------------------

def parse_apexes(markdown: str) -> list[str]:
    """Apex domains = first-column cells of the first table under `## External domain surface`.

    Stops at the next heading of any level, so the `### Probe hosts` table is not read.
    Cells may list several apexes separated by commas (the parked-domain row); each is taken.
    """
    apexes: list[str] = []
    inside = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith(APEX_HEADING):
            inside = True
            continue
        if inside and stripped.startswith("#"):
            break
        if not inside or not stripped.startswith("|"):
            continue
        first = stripped.strip("|").split("|")[0]
        for raw in first.split(","):
            apex = raw.strip().strip("`").strip().lower()
            if not apex or apex == "domain" or set(apex) <= set("-: "):
                continue
            if _APEX_RE.match(apex) and apex not in apexes:
                apexes.append(apex)
    return apexes


def validate_apex(apex: str) -> str:
    apex = (apex or "").strip().lower().rstrip(".")
    if not _APEX_RE.match(apex) or apex.count(".") < 1:
        raise DiscoverError(f"not a valid apex domain: {apex!r}")
    return apex


# ---------------------------------------------------------------------------
# crt.sh (host-pinned)
# ---------------------------------------------------------------------------

def build_url(apex: str) -> str:
    apex = validate_apex(apex)
    query = urllib.parse.urlencode({"q": f"%.{apex}", "output": "json"})
    return f"https://{CT_HOST}/?{query}"


def fetch_ct(apex: str, *, opener=urllib.request.urlopen, sleep=time.sleep) -> list[dict]:
    """Return crt.sh's JSON rows for `%.<apex>`; retries once on a 5xx or a timeout."""
    url = build_url(apex)
    if urllib.parse.urlparse(url).hostname != CT_HOST:  # belt and braces
        raise DiscoverError("refusing to contact a host other than crt.sh")
    last: Exception | None = None
    for attempt in range(CT_RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener(req, timeout=CT_TIMEOUT_SECONDS) as resp:
                body = resp.read()
            data = json.loads(body.decode("utf-8") or "[]")
            if not isinstance(data, list):
                raise DiscoverError(f"crt.sh returned a non-list payload for {apex}")
            return data
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code < 500:
                raise DiscoverError(f"crt.sh HTTP {exc.code} for {apex}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last = exc
        if attempt + 1 < CT_RETRIES:
            sleep(CT_RETRY_SLEEP_SECONDS)
    raise DiscoverError(f"crt.sh unavailable for {apex}: {last}")


def names_from_ct(rows: Iterable[dict], apex: str) -> list[str]:
    """Distinct lowercase hostnames under `apex` from crt.sh rows.

    `name_value` carries one name per line and may include wildcards and the apex itself.
    Wildcard entries are dropped (a `*.x` cert says nothing about which hosts exist); names
    outside the apex, invalid names, and e-mail-style SAN entries are ignored.
    """
    apex = validate_apex(apex)
    suffix = "." + apex
    seen: set[str] = set()
    for row in rows:
        for raw in str(row.get("name_value", "")).splitlines():
            name = raw.strip().lower().rstrip(".")
            if not name or name.startswith("*") or "@" in name:
                continue
            if name != apex and not name.endswith(suffix):
                continue
            if _HOST_RE.match(name):
                seen.add(name)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Liveness (DNS + TCP:443)
# ---------------------------------------------------------------------------

def resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, UnicodeError, OSError):
        return False


def accepts_443(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=CONNECT_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def liveness(hosts: list[str], *, resolve_fn: Callable[[str], bool] = resolves,
             connect_fn: Callable[[str], bool] = accepts_443, workers: int = WORKERS) -> dict[str, str]:
    """Map host -> 'live' | 'resolves' | 'no DNS record'."""
    def check(host: str) -> tuple[str, str]:
        if not resolve_fn(host):
            return host, "no DNS record"
        return host, "live" if connect_fn(host) else "resolves"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return dict(pool.map(check, hosts))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def discover(apexes: list[str], probe_hosts: list[str], *, fetch=fetch_ct, live_fn=liveness,
             include_probed: bool = False) -> dict:
    """Run discovery; returns {apexes, errors, hosts:[{host, apex, status, probed}]}."""
    errors: dict[str, str] = {}
    found: dict[str, str] = {}  # host -> apex
    for apex in apexes:
        try:
            for name in names_from_ct(fetch(apex), apex):
                found.setdefault(name, apex)
        except DiscoverError as exc:
            errors[apex] = str(exc)
    probed = set(h.lower() for h in probe_hosts)
    candidates = sorted(h for h in found if include_probed or h not in probed)
    status = live_fn(candidates) if candidates else {}
    hosts = [
        {"host": h, "apex": found[h], "status": status.get(h, "no DNS record"), "probed": h in probed}
        for h in candidates
    ]
    return {"apexes": apexes, "errors": errors, "hosts": hosts}


def render(result: dict) -> str:
    live = [h for h in result["hosts"] if h["status"] == "live" and not h["probed"]]
    stale = [h for h in result["hosts"] if h["status"] == "resolves" and not h["probed"]]
    gone = [h for h in result["hosts"] if h["status"] == "no DNS record"]
    lines = [f"Apexes: {', '.join(result['apexes'])}"]
    for apex, err in sorted(result["errors"].items()):
        lines.append(f"ERROR {apex}: {err}")
    lines.append(
        f"CT names: {len(result['hosts'])} · live and not in probe table: {len(live)} · "
        f"resolves but no :443: {len(stale)} · no DNS record: {len(gone)}"
    )
    if live:
        lines.append("")
        lines.append("Candidate rows for `### Probe hosts` (fill in the class column, then add):")
        lines.append("")
        lines.append("| Host | Class | Apex | Note |")
        lines.append("| --- | --- | --- | --- |")
        today = time.strftime("%Y-%m-%d")
        for h in live:
            lines.append(f"| `{h['host']}` | TODO | {h['apex']} | discovered {today} (crt.sh) |")
    if stale:
        lines.append("")
        lines.append("Resolve but refuse :443 (not probe-able as HTTPS; listed for awareness):")
        lines.extend(f"- {h['host']}" for h in stale)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None, *, inventory_path: Path = INVENTORY_PATH,
         fetch=fetch_ct, live_fn=liveness, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("apexes", nargs="*", help="apex domains (default: the External domain surface table)")
    parser.add_argument("--json", action="store_true", help="print the raw result as JSON")
    parser.add_argument("--all", action="store_true", help="include hosts already in the probe table")
    parser.add_argument("--inventory", type=Path, default=inventory_path)
    args = parser.parse_args(argv)

    try:
        markdown = args.inventory.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"cannot read inventory: {exc}", file=sys.stderr)
        return 2
    try:
        apexes = [validate_apex(a) for a in args.apexes] or parse_apexes(markdown)
    except DiscoverError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not apexes:
        print("no apex domains found", file=sys.stderr)
        return 2

    result = discover(apexes, parse_probe_hosts(markdown), fetch=fetch, live_fn=live_fn,
                      include_probed=args.all)
    print(json.dumps(result, indent=2) if args.json else render(result), file=out)
    return 1 if result["errors"] and len(result["errors"]) == len(apexes) else 0


if __name__ == "__main__":
    sys.exit(main())
