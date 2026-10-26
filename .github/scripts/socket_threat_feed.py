#!/usr/bin/env python3
"""
socket_threat_feed.py — Socket malware / typosquat client for the Matrix roster.

Socket is the roster's source for malware and supply-chain signals (known malware,
typosquats) for repos in ONE GitHub org — the org Socket is installed on, named by
SOCKET_GITHUB_ORG. Every other org stays on Aikido for malware as well as CVEs.

Every call goes to the org PURL endpoint (`POST /orgs/{org}/purl?alerts=true`), which
returns each package version's alerts. Not the org threat-feed endpoint: that needs the
separate Threat Feed add-on on top of Enterprise and answers `403 threat_feed_not_entitled`
for orgs without it.

Subcommands:
  sbom    Build a merged CycloneDX SBOM of every repo in SOCKET_GITHUB_ORG (gh + syft).
  scan    Check every SOCKET_GITHUB_ORG component in that SBOM against Socket. Components
          from any other org are ignored. Used by /cypher.
  lookup  Check specific packages (PURLs) for one SOCKET_GITHUB_ORG repo (--repo).
          Used by /tank, /dozer, /john-wick for one-off questions.

A version is flagged when Socket raises one of THREAT_ALERTS on it: `malware` (Socket's
confirmed verdict), `gptMalware` (AI-detected) or `didYouMean` (possible typosquat).

Output is JSON on stdout. Exit codes:
  0  every package got a finished verdict (flags, if any, are in the JSON)
  3  INCOMPLETE — missing token, HTTP error, plan gate (401/402/403), timeout, bad JSON,
     an SBOM with no SOCKET_GITHUB_ORG components, or (scan) packages Socket could not
     resolve or had not finished analysing. The JSON carries "status": "INCOMPLETE" and a
     reason; scan still lists the flags it did find. Never read as "no threats".
  4  OUT_OF_SCOPE — lookup --repo is not in SOCKET_GITHUB_ORG. Socket was not called;
     use Aikido for this repo.
  1  usage error (argparse errors exit 2)

Environment:
  SOCKET_API_TOKEN    required — an org token with `packages:list` (source it from your
                      credential vault; never commit it). Each request costs 100 quota
                      units and carries up to BATCH_SIZE PURLs.
  SOCKET_ORG          your Socket org slug (default placeholder `your-socket-org`; also
                      settable with --org).
  SOCKET_GITHUB_ORG   the ONE GitHub org Socket covers (default placeholder
                      `your-sandbox-org`). Deliberately not a flag: callers must not widen
                      the scope per invocation.
  SOCKET_API_BASE     API base URL (default https://api.socket.dev/v0); tests point it at
                      a local fake.

Alert props can carry package-author text, which is attacker-controlled: only the alert
type is ever output.

Usage:
  python3 socket_threat_feed.py sbom --out /tmp/your-sandbox-org.cdx.json
  python3 socket_threat_feed.py scan --sbom /tmp/your-sandbox-org.cdx.json
  python3 socket_threat_feed.py lookup --repo your-sandbox-org/example-repo \\
      --purl pkg:npm/example-lib@1.0.0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = os.environ.get("SOCKET_API_BASE", "https://api.socket.dev/v0")
DEFAULT_ORG = os.environ.get("SOCKET_ORG", "your-socket-org")
# The only GitHub org Socket is used for. Deliberately not a flag.
SCOPE_GITHUB_ORG = os.environ.get("SOCKET_GITHUB_ORG", "your-sandbox-org").lower()
# Cloudflare rejects the default Python urllib agent (403 error 1010).
USER_AGENT = "socket-threat-feed/1.0 (the-construct)"
# Socket allows 1024 PURLs per request, but one version it is still analysing turns the
# whole request into a POLL_TIMEOUT_SEC wait that reports every PURL in it as pending.
# Small batches keep the rest of the SBOM out of that, and pending versions get one retry
# in smaller batches still. Quota is not the constraint: 100 units per request.
BATCH_SIZE = 50
RETRY_BATCH_SIZE = 5
# Socket waits up to this long for versions it has not finished analysing; kept inside TIMEOUT.
POLL_TIMEOUT_SEC = 30
TIMEOUT = 120
MAX_429_RETRIES = 3
# Package types Socket analyses. Syft also emits types Socket has no registry for
# (github actions, deb, apk...); scan counts those as skipped instead of sending them.
SOCKET_ECOSYSTEMS = {"npm", "pypi", "gem", "golang", "maven", "cargo", "nuget", "composer"}

# Socket alert type -> (threat_type, confirmed). Only these flag a version.
THREAT_ALERTS = {
    "malware": ("malware", True),
    "gptMalware": ("malware", False),
    "didYouMean": ("typosquat", False),
}
# Alerts Socket synthesizes about the lookup itself rather than the package.
NOT_FOUND, PENDING = "notFound", "pendingScan"

EXIT_OK, EXIT_USAGE, EXIT_INCOMPLETE, EXIT_OUT_OF_SCOPE = 0, 1, 3, 4


class FeedError(Exception):
    """Any failure that makes the read incomplete."""


class OutOfScope(Exception):
    """The repo is outside SCOPE_GITHUB_ORG; the caller should use Aikido instead."""


def in_scope(repo: str) -> bool:
    """True for `<SOCKET_GITHUB_ORG>/<name>` (owner match is case-insensitive)."""
    owner, sep, name = repo.partition("/")
    return bool(sep and name) and owner.lower() == SCOPE_GITHUB_ORG


# --------------------------------------------------------------------------- PURLs

def parse_purl(purl: str) -> tuple[str, str, str] | None:
    """Return (type, normalized name incl. namespace, version) or None if unparseable."""
    if not isinstance(purl, str) or not purl.startswith("pkg:"):
        return None
    body = purl[4:].split("#", 1)[0].split("?", 1)[0]
    if "/" not in body:
        return None
    ptype, rest = body.split("/", 1)
    # A leading "@" is an npm scope, not a version separator.
    at = rest.rfind("@")
    name, version = (rest[:at], rest[at + 1:]) if at > 0 else (rest, "")
    ptype = ptype.lower()
    name = urllib.parse.unquote(name).strip("/")
    version = urllib.parse.unquote(version)
    if not name:
        return None
    if ptype == "pypi":
        name = re.sub(r"[-_.]+", "-", name.lower())
    elif ptype in {"npm", "github", "golang", "cargo", "gem", "nuget", "composer"}:
        name = name.lower()
    return ptype, name, version


def _record_key(rec: dict) -> tuple[str, str, str] | None:
    """The normalized (type, name, version) of one streamed artifact record."""
    ns = rec.get("namespace")
    name = f"{ns}/{rec.get('name')}" if ns else rec.get("name")
    return parse_purl(f"pkg:{rec.get('type')}/{name}@{rec.get('version')}")


def to_purl(key: tuple[str, str, str]) -> str:
    """Rebuild a PURL from a normalized key; a leading npm-scope "@" is percent-encoded."""
    ptype, name, version = key
    if name.startswith("@"):
        name = "%40" + name[1:]
    return f"pkg:{ptype}/{name}@{urllib.parse.quote(version, safe='')}"


def package_url(ptype: str, name: str, version: str) -> str:
    """Socket's page for one package version."""
    return f"https://socket.dev/{ptype}/package/{name}/overview/{urllib.parse.quote(version)}"


def sbom_index(sbom_path: Path) -> tuple[dict, str]:
    """Map (type, name) -> {version -> set(repos)} for in-scope components of a merged SBOM.

    Only components whose bom-ref starts `<SOCKET_GITHUB_ORG>/<repo>::` (as written by
    `sbom`) count. Production-SBOM refs (`<repo>::`) carry no org and are skipped.
    """
    try:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FeedError(f"cannot read SBOM {sbom_path}: {e}") from e
    index: dict[tuple[str, str], dict[str, set[str]]] = {}
    for comp in sbom.get("components") or []:
        ref = str(comp.get("bom-ref", ""))
        repo = ref.split("::", 1)[0] if "::" in ref else ""
        if not in_scope(repo):
            continue
        parsed = parse_purl(comp.get("purl", ""))
        if not parsed:
            continue
        ptype, name, version = parsed
        index.setdefault((ptype, name), {}).setdefault(version, set()).add(repo)
    if not index:
        raise FeedError(f"SBOM {sbom_path} has no {SCOPE_GITHUB_ORG} components with a PURL "
                        f"(Socket is scoped to {SCOPE_GITHUB_ORG}; build the SBOM with `sbom`)")
    sbom_date = (sbom.get("metadata") or {}).get("timestamp", "unknown")
    return index, sbom_date


def merge_repo_sboms(per_repo: dict[str, dict], timestamp: str) -> dict:
    """Merge per-repo Syft CycloneDX docs, namespacing bom-refs as `<org>/<repo>::<ref>`."""
    components = []
    for repo, doc in sorted(per_repo.items()):
        for comp in doc.get("components") or []:
            if comp.get("type") == "file":
                continue
            ref = comp.get("bom-ref") or f"{comp.get('name', '?')}@{comp.get('version', '?')}"
            components.append(comp | {"bom-ref": f"{SCOPE_GITHUB_ORG}/{repo}::{ref}"})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {"timestamp": timestamp,
                     "properties": [{"name": "socket:github_org", "value": SCOPE_GITHUB_ORG}]},
        "components": components,
    }


def _run(cmd: list[str], what: str) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise FeedError(f"{what}: {e}") from e
    if p.returncode != 0:
        raise FeedError(f"{what}: exit {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout


def build_sbom(out: Path) -> dict:
    """Clone every non-archived repo in SCOPE_GITHUB_ORG, run Syft, write the merged SBOM.

    Any repo that fails to clone or scan makes the whole build INCOMPLETE: a partial SBOM
    would turn a miss into "not shipped".
    """
    listing = json.loads(_run(["gh", "repo", "list", SCOPE_GITHUB_ORG, "--no-archived",
                               "--limit", "500", "--json", "name"], "gh repo list"))
    repos = sorted(r["name"] for r in listing)
    if not repos:
        raise FeedError(f"no repos visible in {SCOPE_GITHUB_ORG}")
    per_repo: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="socket-sbom-") as td:
        for repo in repos:
            dest = Path(td) / repo
            _run(["gh", "repo", "clone", f"{SCOPE_GITHUB_ORG}/{repo}", str(dest), "--",
                  "--depth", "1", "--quiet"], f"clone {repo}")
            if not dest.exists():  # empty repo: nothing to scan
                per_repo[repo] = {}
                continue
            try:
                per_repo[repo] = json.loads(_run(["syft", f"dir:{dest}", "-q", "-o", "cyclonedx-json"],
                                                 f"syft {repo}"))
            except json.JSONDecodeError as e:
                raise FeedError(f"syft {repo}: unparseable output: {e}") from e
    merged = merge_repo_sboms(per_repo, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(merged) + "\n", encoding="utf-8")
    return {"status": "OK", "github_org": SCOPE_GITHUB_ORG, "sbom": str(out),
            "repos": repos, "components": len(merged["components"])}


# --------------------------------------------------------------------------- HTTP

def _post_purls(org: str, token: str, purls: list[str]) -> list[dict]:
    """One batched PURL request; returns the NDJSON records. Raises FeedError on any failure."""
    params = {"alerts": "true", "compact": "true", "purlErrors": "true", "summary": "true",
              "poll": "true", "timeoutSec": str(POLL_TIMEOUT_SEC)}
    req = urllib.request.Request(
        f"{API_BASE}/orgs/{org}/purl?{urllib.parse.urlencode(params)}",
        data=json.dumps({"components": [{"purl": p} for p in purls]}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT,
                 "Content-Type": "application/json", "Accept": "application/x-ndjson"})
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_429_RETRIES:
                try:
                    wait = int(e.headers.get("Retry-After", ""))
                except ValueError:  # absent, or an HTTP-date
                    wait = 2 ** (attempt + 2)
                time.sleep(min(wait, 60))
                continue
            hint = (" (bad token, missing packages:list, or a plan gate)"
                    if e.code in (401, 402, 403) else "")
            raise FeedError(f"HTTP {e.code} from Socket PURL lookup{hint}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise FeedError(f"Socket unreachable: {e}") from e
    else:
        raise FeedError("Socket rate limit (429) persisted after retries")
    records = []
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise FeedError(f"unparseable Socket response: {e}") from e
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _read_batch(org: str, token: str, batch: dict, verdicts: dict, unverified: dict) -> None:
    """One request for `batch` ({key: purl}); fills `verdicts` and `unverified` in place."""
    by_purl = {p: k for k, p in batch.items()}
    for rec in _post_purls(org, token, list(batch.values())):
        if rec.get("_type") == "purlError":
            value = rec.get("value")
            err = value if isinstance(value, dict) else {"inputPurl": value}
            key = by_purl.get(str(err.get("inputPurl", "")))
            if not key:
                continue
            message = str(err.get("error", "unresolved PURL"))
            if err.get("retryable") is not True and "package not found" in message.lower():
                # Socket's text is "does not exist or Socket hasn't scanned it yet", but a public
                # version it hasn't seen comes back pendingScan, so in practice this is a version
                # that isn't on the public registry (internal packages, yanked releases). Counted
                # as a verdict so internal packages don't leave every scan INCOMPLETE.
                verdicts.setdefault(key, {"found": False, "threats": set()})
            else:
                unverified[key] = f"Socket error: {message[:120]}"
            continue
        if rec.get("_type"):  # the closing summary
            continue
        key = _record_key(rec)
        if key not in batch:
            continue
        alerts = [a for a in rec.get("alerts") or [] if isinstance(a, dict)]
        if any(a.get("type") == PENDING for a in alerts):
            unverified.setdefault(key, "Socket has not finished analysing this version")
            continue
        v = verdicts.setdefault(key, {"found": False, "threats": set()})
        if not any(a.get("type") == NOT_FOUND for a in alerts):
            v["found"] = True
        v["threats"].update(a["type"] for a in alerts if a.get("type") in THREAT_ALERTS)
    for key in batch:
        if key not in verdicts and key not in unverified:
            unverified[key] = "Socket returned no verdict"
    for key in batch:  # a pending artifact taints the whole version
        if key in unverified:
            verdicts.pop(key, None)


def fetch_verdicts(org: str, token: str, keys: list[tuple[str, str, str]]) -> dict:
    """Ask Socket about every (type, name, version): BATCH_SIZE per request, then one retry of
    whatever is left in RETRY_BATCH_SIZE requests.

    Returns {"verdicts": {key: {"found", "threats"}}, "unverified": {key: reason}}. A key is
    unverified when Socket could not resolve it, had not finished analysing it, or returned
    nothing for it: never a clean verdict. Records for other artifacts of the same version
    (a PyPI sdist and wheel) are merged.
    """
    verdicts: dict[tuple, dict] = {}
    unverified: dict[tuple, str] = {}
    pending = list(keys)
    for size in (BATCH_SIZE, RETRY_BATCH_SIZE):
        unverified = {}
        for i in range(0, len(pending), size):
            _read_batch(org, token, {k: to_purl(k) for k in pending[i:i + size]}, verdicts, unverified)
        pending = list(unverified)
        if not pending:
            break
    return {"verdicts": verdicts, "unverified": unverified}


def _threats(alert_types: set[str]) -> list[dict]:
    return [{"alert": t, "threat_type": THREAT_ALERTS[t][0], "confirmed": THREAT_ALERTS[t][1]}
            for t in sorted(alert_types)]


# --------------------------------------------------------------------------- commands

def _token() -> str:
    token = os.environ.get("SOCKET_API_TOKEN", "")
    if not token:
        raise FeedError("SOCKET_API_TOKEN not set")
    return token


def cmd_scan(args: argparse.Namespace) -> tuple[dict, int]:
    index, sbom_date = sbom_index(Path(args.sbom))
    keys, skipped = [], {}
    for (ptype, name), versions in sorted(index.items()):
        for version in sorted(versions):
            if ptype not in SOCKET_ECOSYSTEMS or not version:
                label = ptype if version else f"{ptype} (no version)"
                skipped[label] = skipped.get(label, 0) + 1
            else:
                keys.append((ptype, name, version))
    if not keys:
        raise FeedError(f"SBOM {args.sbom} has no versioned {SCOPE_GITHUB_ORG} packages Socket can check")
    result = fetch_verdicts(args.org, _token(), keys)

    matches = []
    for key, v in sorted(result["verdicts"].items()):
        if not v["threats"]:
            continue
        threats = _threats(v["threats"])
        # Both route to john-wick (handoff matrix row 1); AI-detected / typosquat-only
        # flags drop to high so John Wick confirms before containment.
        confirmed = any(t["confirmed"] for t in threats)
        matches.append({
            "purl": to_purl(key),
            "repos": sorted(index[key[:2]][key[2]]),
            "threats": threats,
            "severity": "critical" if confirmed else "high",
            "confirmed": confirmed,
            "socket_url": package_url(*key),
            "suggested_next": ["john-wick"],
        })
    unverified = [{"purl": to_purl(k), "reason": r}
                  for k, r in sorted(result["unverified"].items())]
    out = {
        "status": "INCOMPLETE" if unverified else "OK",
        "github_org": SCOPE_GITHUB_ORG,
        "sbom_date": sbom_date,
        "checked": len(keys),
        # Not on the public registry: internal packages and yanked releases. Not malware, but an
        # internal name here is worth a dependency-confusion look (/dozer).
        "not_in_registry": [to_purl(k) for k, v in sorted(result["verdicts"].items()) if not v["found"]],
        "skipped_by_ecosystem": dict(sorted(skipped.items())),
        "matches": matches,
        "unverified": unverified,
    }
    if unverified:
        out["reason"] = f"{len(unverified)} of {len(keys)} packages have no finished Socket verdict"
    return out, EXIT_INCOMPLETE if unverified else EXIT_OK


def cmd_lookup(args: argparse.Namespace) -> tuple[dict, int]:
    if not in_scope(args.repo):
        raise OutOfScope(f"{args.repo!r} is not in {SCOPE_GITHUB_ORG}; Socket is scoped to that "
                         "org only. Use Aikido for this repo.")
    keys: dict[tuple, str] = {}
    for purl in args.purl:
        parsed = parse_purl(purl)
        if not parsed or not parsed[2]:
            raise FeedError(f"not a versioned PURL: {purl!r}")
        keys.setdefault(parsed, purl)
    result = fetch_verdicts(args.org, _token(), list(keys))
    if result["unverified"]:
        key, reason = next(iter(result["unverified"].items()))
        raise FeedError(f"{reason}: {keys[key]}")
    out = []
    for key, purl in keys.items():
        v = result["verdicts"][key]
        out.append({
            "purl": purl,
            "listed": bool(v["threats"]),
            "found": v["found"],
            "threats": _threats(v["threats"]),
            "socket_url": package_url(*key),
        })
    return {"status": "OK", "github_org": SCOPE_GITHUB_ORG, "repo": args.repo, "results": out}, EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--org", default=DEFAULT_ORG, help="Socket org slug (default: $SOCKET_ORG)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sb = sub.add_parser("sbom", help=f"build a merged SBOM of every {SCOPE_GITHUB_ORG} repo")
    sb.add_argument("--out", required=True)
    sc = sub.add_parser("scan", help="check every in-scope SBOM component against Socket")
    sc.add_argument("--sbom", required=True, help=f"merged {SCOPE_GITHUB_ORG} SBOM (from `sbom`)")
    lk = sub.add_parser("lookup", help="check specific PURLs against Socket")
    lk.add_argument("--repo", required=True, help=f"owner/name; must be in {SCOPE_GITHUB_ORG}")
    lk.add_argument("--purl", action="append", required=True)
    args = ap.parse_args(argv)

    commands = {"sbom": lambda a: (build_sbom(Path(a.out)), EXIT_OK),
                "scan": cmd_scan, "lookup": cmd_lookup}
    try:
        result, code = commands[args.cmd](args)
    except OutOfScope as e:
        print(json.dumps({"status": "OUT_OF_SCOPE", "reason": str(e)}, indent=2))
        return EXIT_OUT_OF_SCOPE
    except FeedError as e:
        print(json.dumps({"status": "INCOMPLETE", "reason": str(e)}, indent=2))
        return EXIT_INCOMPLETE
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
