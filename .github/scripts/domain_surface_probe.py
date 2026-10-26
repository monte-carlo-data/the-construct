#!/usr/bin/env python3
"""
Self-run domain-surface probe — the vendor-free default source for a weekly
domain-surface monitor.

Measures, for each customer-visible host in the *Probe hosts* table of your domain
inventory (see domain_surface_discover.py for the file and its format), what a customer's
vendor-risk scanner (SecurityScorecard, BitSight and the like) typically reports:

  tls_weak_protocol       TLS 1.0 / 1.1 handshake accepted                         high
  tls_weak_cipher         non-AEAD (CBC / 3DES / RC4) suite accepted, or the server  medium
                          follows client cipher order instead of its own preference
  tlscert_untrusted       certificate chain / hostname fails default verification  high
  tlscert_expiring        certificate expires within 30 days                       medium
  http_no_https_redirect  http://host/ answers 2xx (or redirects to http://)       medium
  csp_no_policy           HTML page served without Content-Security-Policy         medium
  csp_unsafe_policy       script-src allows 'unsafe-inline' / bare http: https:,   medium
                          or object-src / script-src missing
  hsts_missing            HTML page served without Strict-Transport-Security       low

Only the inventory's own hosts are probed (the list is parsed from the repo, never from input).
Each check is a single TLS handshake or GET — read-only, the same traffic a browser sends.
Stdlib only, no vendor account. An optional vendor feed can be a second source; findings
from both can share one key space and one ticket.

Network functions are injectable (`observe(host, handshake=..., http=..., cert=...)`) so
the evaluation is testable without a socket. `evaluate(obs)` is pure.

Usage (manual):  python3 .github/scripts/domain_surface_probe.py www.example.com [more hosts] [--json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings

PROBE_HEADING = "### Probe hosts"
TIMEOUT_SECONDS = 10
CERT_EXPIRY_WARN_DAYS = 30
USER_AGENT = "domain-surface-probe (the-construct)"

SEVERITY = {
    "tls_weak_protocol": "high",
    "tlscert_untrusted": "high",
    "tls_weak_cipher": "medium",
    "tlscert_expiring": "medium",
    "http_no_https_redirect": "medium",
    "csp_no_policy": "medium",
    "csp_unsafe_policy": "medium",
    "hsts_missing": "low",
}

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$"
)

# Legacy protocol handshakes need SECLEVEL=0 on OpenSSL 3. The TLSVersion members are
# deprecated in Python but still functional — we *want* to offer them, that is the test.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    LEGACY_VERSIONS = (("TLSv1", ssl.TLSVersion.TLSv1), ("TLSv1.1", ssl.TLSVersion.TLSv1_1))
TLS12 = ssl.TLSVersion.TLSv1_2
ANY_CIPHERS = "ALL:@SECLEVEL=0"

# Non-AEAD suites a vendor scanner calls "weak": CBC-mode and legacy stream/3DES. AEAD
# (GCM / CCM / CHACHA20) suites with ECDHE are the "strong" reference set. Suites the local
# OpenSSL doesn't know (e.g. RC4 without the legacy provider) are dropped at runtime.
WEAK_CANDIDATES = (
    "DES-CBC3-SHA", "ECDHE-RSA-DES-CBC3-SHA", "RC4-SHA", "RC4-MD5",
    "AES128-SHA", "AES256-SHA", "AES128-SHA256", "AES256-SHA256",
    "ECDHE-RSA-AES128-SHA", "ECDHE-RSA-AES256-SHA", "ECDHE-ECDSA-AES128-SHA", "ECDHE-ECDSA-AES256-SHA",
    "ECDHE-RSA-AES128-SHA256", "ECDHE-RSA-AES256-SHA384",
)
STRONG_CANDIDATES = (
    "ECDHE-RSA-AES128-GCM-SHA256", "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES256-GCM-SHA384", "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-CHACHA20-POLY1305", "ECDHE-ECDSA-CHACHA20-POLY1305",
)


def is_weak_cipher(name: str) -> bool:
    """A TLS 1.2 suite is 'weak' for this probe when it is not AEAD (no GCM / CCM / CHACHA20)."""
    n = (name or "").upper()
    return bool(n) and not any(tag in n for tag in ("GCM", "CCM", "CHACHA20"))


# ---------------------------------------------------------------------------
# Inventory parsing
# ---------------------------------------------------------------------------

def parse_probe_hosts(markdown: str) -> list[str]:
    """Hosts = first-column cells of the table under the `### Probe hosts` heading."""
    hosts: list[str] = []
    inside = False
    for line in markdown.splitlines():
        if line.strip().startswith(PROBE_HEADING):
            inside = True
            continue
        if inside and line.startswith("#"):
            break
        if not inside or not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells:
            continue
        host = cells[0].strip("`").strip().lower()
        if not host or host == "host" or set(host) <= set("-: "):
            continue
        if _HOST_RE.match(host) and host not in hosts:
            hosts.append(host)
    return hosts


# ---------------------------------------------------------------------------
# Network primitives (injectable)
# ---------------------------------------------------------------------------

def _available_ciphers(candidates) -> list[str]:
    out = []
    for name in candidates:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            ctx.set_ciphers(f"{name}:@SECLEVEL=0")
            out.append(name)
        except ssl.SSLError:
            continue
    return out


def tls_handshake(host: str, min_version, max_version, ciphers: str = ANY_CIPHERS,
                  timeout: float = TIMEOUT_SECONDS) -> dict:
    """One handshake. Returns {ok: True, version, cipher} or {ok: False, reason, detail}.

    reason ∈ {"ssl" (server refused the offered parameters), "unreachable" (no TCP / timeout),
    "untestable" (this OpenSSL cannot offer the parameters)}. Certificate is NOT verified here —
    that is cert_check's job; this call only asks "will you negotiate X".
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers(ciphers)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ctx.minimum_version = min_version
            ctx.maximum_version = max_version
    except (ssl.SSLError, ValueError) as e:
        return {"ok": False, "reason": "untestable", "detail": str(e)[:120]}
    try:
        with socket.create_connection((host, 443), timeout=timeout) as sock, \
                ctx.wrap_socket(sock, server_hostname=host) as tls:
            cipher = tls.cipher()
            return {"ok": True, "version": tls.version(), "cipher": cipher[0] if cipher else ""}
    except ssl.SSLError as e:
        return {"ok": False, "reason": "ssl", "detail": str(e)[:120]}
    except socket.gaierror as e:
        return {"ok": False, "reason": "dns", "detail": str(e)[:120]}
    except (OSError, TimeoutError) as e:
        return {"ok": False, "reason": "unreachable", "detail": str(e)[:120]}


def cert_check(host: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """Default-verifying handshake: chain + hostname. Returns {ok, days_left, not_after} or {ok: False, reason, detail}."""
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, 443), timeout=timeout) as sock, \
                ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert() or {}
            not_after = cert.get("notAfter", "")
            days_left = None
            if not_after:
                expires = _dt.datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=_dt.timezone.utc)
                days_left = (expires - _dt.datetime.now(tz=_dt.timezone.utc)).days
            return {"ok": True, "days_left": days_left, "not_after": not_after}
    except ssl.SSLCertVerificationError as e:
        return {"ok": False, "reason": "ssl", "detail": (e.verify_message or str(e))[:120]}
    except ssl.SSLError as e:
        return {"ok": False, "reason": "ssl", "detail": str(e)[:120]}
    except socket.gaierror as e:
        return {"ok": False, "reason": "dns", "detail": str(e)[:120]}
    except (OSError, TimeoutError) as e:
        return {"ok": False, "reason": "unreachable", "detail": str(e)[:120]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 — never follow
        return None


def http_get(url: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """GET without following redirects. Returns {status, headers (lower-cased), location} or {error}.

    TLS verification is disabled for the https fetch on purpose: certificate trust is a separate
    finding (cert_check); here we only want the headers the server sends.
    """
    opener = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=ssl._create_unverified_context())  # noqa: SLF001
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310 — host comes from the repo inventory
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return {"status": resp.status, "headers": headers, "location": headers.get("location", "")}
    except urllib.error.HTTPError as e:
        headers = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
        return {"status": e.code, "headers": headers, "location": headers.get("location", "")}
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        return {"error": f"{type(e).__name__}: {str(e)[:100]}"}


# ---------------------------------------------------------------------------
# Observe (I/O) and evaluate (pure)
# ---------------------------------------------------------------------------

def observe(host: str, *, handshake=tls_handshake, http=http_get, cert=cert_check,
            weak_suites: list[str] | None = None, strong_suites: list[str] | None = None) -> dict:
    """Collect raw observations for one host. Every network call goes through the injected
    callables; nothing here interprets the results."""
    weak = weak_suites if weak_suites is not None else _available_ciphers(WEAK_CANDIDATES)
    strong = strong_suites if strong_suites is not None else _available_ciphers(STRONG_CANDIDATES)
    obs: dict = {"host": host, "tls": {}, "cipher": {}}
    for name, version in LEGACY_VERSIONS:
        obs["tls"][name] = handshake(host, version, version, ANY_CIPHERS)
    obs["tls"]["TLSv1.2"] = handshake(host, TLS12, TLS12, ANY_CIPHERS)
    if obs["tls"]["TLSv1.2"].get("ok") and weak and strong:
        obs["cipher"]["weak_only"] = handshake(host, TLS12, TLS12, ":".join(weak) + ":@SECLEVEL=0")
        obs["cipher"]["weak_first"] = handshake(host, TLS12, TLS12, ":".join(weak + strong) + ":@SECLEVEL=0")
        obs["cipher"]["strong_first"] = handshake(host, TLS12, TLS12, ":".join(strong + weak) + ":@SECLEVEL=0")
    obs["cert"] = cert(host)
    obs["http"] = http(f"http://{host}/")
    obs["https"] = http(f"https://{host}/")
    # Header checks want the page a browser lands on. Follow ONE same-host https
    # redirect (e.g. / → /Auth/Login) — a vendor scanner reports the login page's
    # missing CSP, not the 301 that led there. Cross-host redirects are not
    # followed: that host is probed on its own row, or is not ours to grade.
    target = _same_host_https_redirect(host, obs["https"])
    if target:
        obs["https_final"] = http(target)
    return obs


def _same_host_https_redirect(host: str, resp: dict) -> str:
    status = resp.get("status")
    location = str(resp.get("location") or "")
    if status not in (301, 302, 303, 307, 308) or not location:
        return ""
    if location.startswith("/"):
        return f"https://{host}{location}"
    parsed = urllib.parse.urlsplit(location)
    if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower() == host.lower():
        return location
    return ""


def _parse_csp(value: str) -> dict[str, list[str]]:
    directives: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.strip().split()
        if tokens:
            directives[tokens[0].lower()] = [t.lower() for t in tokens[1:]]
    return directives


def csp_issues(value: str) -> list[str]:
    """The high-severity CSP checks vendor scanners run against script-src / object-src."""
    d = _parse_csp(value)
    issues: list[str] = []
    script = d.get("script-src", d.get("default-src"))
    if script is None:
        issues.append("script-src directive is missing")
    else:
        if "'unsafe-inline'" in script and not any(t.startswith("'nonce-") or t.startswith("'sha") for t in script):
            issues.append("script-src allows 'unsafe-inline'")
        for scheme in ("http:", "https:", "*"):
            if scheme in script:
                issues.append(f"script-src allows bare {scheme}")
    obj = d.get("object-src", d.get("default-src"))
    if obj is None:
        issues.append("object-src is missing (set 'none')")
    return issues


def _is_html(resp: dict) -> bool:
    return str(resp.get("headers", {}).get("content-type", "")).lower().startswith("text/html")


def evaluate(obs: dict) -> list[dict]:
    """Pure: observations → findings (type, severity, host, evidence). Order is deterministic."""
    host = obs["host"]
    out: list[dict] = []

    def add(ftype: str, evidence: str) -> None:
        out.append({"type": ftype, "severity": SEVERITY[ftype], "host": host, "evidence": evidence})

    tls = obs.get("tls", {})
    accepted = [name for name, _ in LEGACY_VERSIONS if tls.get(name, {}).get("ok")]
    if accepted:
        add("tls_weak_protocol", "accepts " + ", ".join(accepted))

    cipher = obs.get("cipher", {})
    weak_only = cipher.get("weak_only", {})
    if weak_only.get("ok") and is_weak_cipher(weak_only.get("cipher", "")):
        add("tls_weak_cipher", f"accepts {weak_only['cipher']}")
    wf, sf = cipher.get("weak_first", {}), cipher.get("strong_first", {})
    if wf.get("ok") and sf.get("ok"):
        if is_weak_cipher(wf.get("cipher", "")) and not is_weak_cipher(sf.get("cipher", "")):
            add("tls_weak_cipher", f"no server cipher preference (client order honoured: {wf['cipher']} vs {sf['cipher']})")
        elif is_weak_cipher(wf.get("cipher", "")) and is_weak_cipher(sf.get("cipher", "")):
            add("tls_weak_cipher", f"server prefers weak cipher {sf['cipher']}")

    cert = obs.get("cert", {})
    if cert and not cert.get("ok") and cert.get("reason") == "ssl":
        add("tlscert_untrusted", cert.get("detail") or "certificate verification failed")
    elif cert.get("ok") and cert.get("days_left") is not None and cert["days_left"] < CERT_EXPIRY_WARN_DAYS:
        add("tlscert_expiring", f"expires in {cert['days_left']}d ({cert.get('not_after', '')})")

    http = obs.get("http", {})
    if "status" in http:
        status, location = http["status"], str(http.get("location", ""))
        if status in (301, 302, 303, 307, 308):
            if location and not location.lower().startswith("https://"):
                add("http_no_https_redirect", f"HTTP {status} redirects to {location[:80]}")
        elif 200 <= status < 300:
            add("http_no_https_redirect", f"HTTP {status} served over plain http without redirect")

    https = obs.get("https_final") or obs.get("https", {})
    if "status" in https and 200 <= https["status"] < 300 and _is_html(https):
        headers = https.get("headers", {})
        csp = headers.get("content-security-policy")
        if csp is None:
            add("csp_no_policy", "no Content-Security-Policy header on HTML response")
        else:
            issues = csp_issues(csp)
            if issues:
                add("csp_unsafe_policy", "; ".join(issues))
        if "strict-transport-security" not in headers:
            add("hsts_missing", "no Strict-Transport-Security header on HTML response")
    return out


def _apex(host: str) -> str:
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def probe_hosts(hosts: list[str], min_severity: str = "medium", *, observe_fn=observe,
                severity_rank: dict | None = None):
    """Probe every host; return ({key: finding}, {host: status}). One unreachable host never
    aborts the run — it is recorded as such and the others proceed."""
    rank = severity_rank or {"positive": 0, "info": 1, "low": 2, "medium": 3, "high": 4}
    threshold = rank.get(min_severity, rank["medium"])
    findings: dict[str, dict] = {}
    host_status: dict[str, dict] = {}
    for host in hosts:
        try:
            obs = observe_fn(host)
        except Exception as e:  # noqa: BLE001 — a probe bug on one host must not kill the run
            host_status[host] = {"status": f"error: {type(e).__name__}", "findings": 0, "tls": "?"}
            continue
        tls = obs.get("tls", {})
        reachable = any(v.get("ok") for v in tls.values()) or "status" in obs.get("https", {})
        reasons = {v.get("reason") for v in tls.values() if not v.get("ok")}
        no_dns = bool(tls) and reasons == {"dns"}
        unreachable = bool(tls) and reasons <= {"unreachable", "dns"} and not any(v.get("ok") for v in tls.values())
        versions = [n for n, v in tls.items() if v.get("ok")]
        count = 0
        if reachable and not unreachable:
            for f in evaluate(obs):
                if rank.get(f["severity"], 0) < threshold:
                    continue
                key = f"probe|{f['type']}|{host}|{f['evidence']}"
                findings[key] = {**f, "key": key, "source": "probe", "domain": _apex(host),
                                 "first_seen": "", "last_seen": ""}
                count += 1
        host_status[host] = {
            "status": "no DNS record" if no_dns else ("unreachable" if unreachable or not reachable else "ok"),
            "tls": ", ".join(versions) or "—",
            "findings": count,
        }
    return findings, host_status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Self-run TLS / header probe of your public hosts (read-only).")
    ap.add_argument("hosts", nargs="+", help="bare hostnames to probe")
    ap.add_argument("--json", action="store_true", help="emit raw observations + findings as JSON")
    ap.add_argument("--min-severity", default="low", choices=["low", "medium", "high"])
    args = ap.parse_args(argv)
    for h in args.hosts:
        if not _HOST_RE.match(h):
            sys.stderr.write(f"ERROR: invalid host {h!r}\n")
            return 2
    if args.json:
        payload = []
        for h in args.hosts:
            obs = observe(h)
            payload.append({"host": h, "observations": obs, "findings": evaluate(obs)})
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0
    findings, status = probe_hosts(args.hosts, args.min_severity)
    for host, st in status.items():
        print(f"{host}: {st['status']} · TLS {st['tls']} · {st['findings']} finding(s)")
    for f in findings.values():
        print(f"  [{f['severity']}] {f['type']} — {f['evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
