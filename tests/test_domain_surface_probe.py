#!/usr/bin/env python3
"""Tests for the self-run domain-surface probe (.github/scripts/domain_surface_probe.py).

The probe's value is reproducing a vendor-risk scanner's TLS / header findings from a CI
runner with no vendor account. `evaluate` is pure and `observe` takes injected network
callables, so every check here runs without a socket. Stdlib + unittest only.

Run:  python3 tests/test_domain_surface_probe.py      (or: python3 -m pytest tests/test_domain_surface_probe.py)

Coverage map:
  - probe hosts parsed from the inventory  → TestInventory
  - each finding class a scanner reports   → TestEvaluate.test_*
  - unreachable host isolated              → TestProbeHosts.test_unreachable_*
  - stable keys, severity filter           → TestProbeHosts.test_keys_* / test_min_severity
"""

from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "domain_surface_probe.py"

spec = importlib.util.spec_from_file_location("domain_surface_probe", SCRIPT)
dsp = importlib.util.module_from_spec(spec)
sys.modules["domain_surface_probe"] = dsp
spec.loader.exec_module(dsp)

OK12 = {"ok": True, "version": "TLSv1.2", "cipher": "ECDHE-RSA-AES128-GCM-SHA256"}
REFUSED = {"ok": False, "reason": "ssl", "detail": "tlsv1 alert protocol version"}
UNREACH = {"ok": False, "reason": "unreachable", "detail": "timed out"}
HTML_OK = {"status": 200, "headers": {"content-type": "text/html; charset=utf-8",
                                      "content-security-policy": "default-src 'self'; script-src 'self' 'nonce-x'; object-src 'none'",
                                      "strict-transport-security": "max-age=31536000"}, "location": ""}
REDIRECT_OK = {"status": 301, "headers": {"location": "https://h.example.com/"}, "location": "https://h.example.com/"}
CERT_OK = {"ok": True, "days_left": 200, "not_after": "Jan  1 00:00:00 2027 GMT"}


def clean_obs(host="h.example.com"):
    """A fully hardened host: nothing should be flagged. Deep-copied so tests can mutate freely."""
    return copy.deepcopy({"host": host,
                          "tls": {"TLSv1": REFUSED, "TLSv1.1": REFUSED, "TLSv1.2": OK12},
                          "cipher": {"weak_only": REFUSED, "weak_first": OK12, "strong_first": OK12},
                          "cert": CERT_OK, "http": REDIRECT_OK, "https": HTML_OK})


def types_of(findings):
    return [f["type"] for f in findings]


class TestInventory(unittest.TestCase):
    MD = """## External domain surface

| Domain | Scorecard id |
| --- | --- |
| `example.com` | ✅ |

### Probe hosts (self-run TLS / header checks)

intro text

| Host | Class |
| --- | --- |
| `ingest.example.com` | ingest |
| `Ingest.EXAMPLE.com` | duplicate, case-insensitive |
| `not a host` | bad |
| `www.example.org` | marketing |

## WordPress

| Host | Class |
| `after.example` | ignored |
"""

    def test_parses_hosts_under_probe_heading_only(self):
        self.assertEqual(dsp.parse_probe_hosts(self.MD), ["ingest.example.com", "www.example.org"])

    def test_no_heading_yields_nothing(self):
        self.assertEqual(dsp.parse_probe_hosts("# x\n| Host |\n| `a.example` |\n"), [])


class TestEvaluate(unittest.TestCase):
    def test_clean_host_has_no_findings(self):
        self.assertEqual(dsp.evaluate(clean_obs()), [])

    def test_deprecated_protocols_are_high(self):
        obs = clean_obs()
        obs["tls"]["TLSv1"] = {"ok": True, "version": "TLSv1", "cipher": "AES128-SHA"}
        obs["tls"]["TLSv1.1"] = {"ok": True, "version": "TLSv1.1", "cipher": "AES128-SHA"}
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["tls_weak_protocol"])
        self.assertEqual(f[0]["severity"], "high")
        self.assertEqual(f[0]["evidence"], "accepts TLSv1, TLSv1.1")

    def test_untestable_legacy_protocol_is_not_a_finding(self):
        obs = clean_obs()
        obs["tls"]["TLSv1"] = {"ok": False, "reason": "untestable", "detail": "no TLSv1 in this OpenSSL"}
        self.assertEqual(dsp.evaluate(obs), [])

    def test_weak_cipher_accepted(self):
        obs = clean_obs()
        obs["cipher"]["weak_only"] = {"ok": True, "version": "TLSv1.2", "cipher": "AES128-SHA"}
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["tls_weak_cipher"])
        self.assertIn("accepts AES128-SHA", f[0]["evidence"])

    def test_no_server_preference_flagged_as_weak_cipher(self):
        obs = clean_obs()
        obs["cipher"]["weak_only"] = {"ok": True, "cipher": "AES128-SHA"}
        obs["cipher"]["weak_first"] = {"ok": True, "cipher": "AES128-SHA"}
        obs["cipher"]["strong_first"] = {"ok": True, "cipher": "ECDHE-RSA-AES128-GCM-SHA256"}
        evid = [f["evidence"] for f in dsp.evaluate(obs) if f["type"] == "tls_weak_cipher"]
        self.assertEqual(len(evid), 2)
        self.assertTrue(any("no server cipher preference" in e for e in evid))

    def test_server_prefers_weak_cipher(self):
        obs = clean_obs()
        obs["cipher"]["weak_only"] = {"ok": True, "cipher": "AES256-SHA"}
        obs["cipher"]["weak_first"] = {"ok": True, "cipher": "AES256-SHA"}
        obs["cipher"]["strong_first"] = {"ok": True, "cipher": "AES256-SHA"}
        evid = [f["evidence"] for f in dsp.evaluate(obs) if f["type"] == "tls_weak_cipher"]
        self.assertTrue(any(e == "server prefers weak cipher AES256-SHA" for e in evid))

    def test_server_preference_honoured_is_clean(self):
        obs = clean_obs()
        obs["cipher"]["weak_only"] = dict(REFUSED)
        obs["cipher"]["weak_first"] = {"ok": True, "cipher": "ECDHE-RSA-AES128-GCM-SHA256"}
        obs["cipher"]["strong_first"] = {"ok": True, "cipher": "ECDHE-RSA-AES128-GCM-SHA256"}
        self.assertEqual(dsp.evaluate(obs), [])

    def test_untrusted_cert_is_high_and_expiring_is_medium(self):
        obs = clean_obs()
        obs["cert"] = {"ok": False, "reason": "ssl", "detail": "Hostname mismatch, certificate is not valid for 'h'"}
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["tlscert_untrusted"])
        self.assertEqual(f[0]["severity"], "high")
        obs["cert"] = {"ok": True, "days_left": 12, "not_after": "x"}
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["tlscert_expiring"])

    def test_unreachable_cert_check_is_not_a_finding(self):
        obs = clean_obs()
        obs["cert"] = dict(UNREACH)
        self.assertEqual(dsp.evaluate(obs), [])

    def test_missing_http_redirect_and_http_target(self):
        obs = clean_obs()
        obs["http"] = {"status": 200, "headers": {"content-type": "text/html"}, "location": ""}
        self.assertEqual(types_of(dsp.evaluate(obs)), ["http_no_https_redirect"])
        obs["http"] = {"status": 302, "headers": {}, "location": "http://h.example.com/x"}
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["http_no_https_redirect"])
        self.assertIn("redirects to http://", f[0]["evidence"])
        obs["http"] = {"error": "URLError: connection refused"}   # no :80 listener → fine
        self.assertEqual(dsp.evaluate(obs), [])

    def test_csp_missing_unsafe_and_hsts(self):
        obs = clean_obs()
        obs["https"] = {"status": 200, "headers": {"content-type": "text/html"}, "location": ""}
        self.assertEqual(types_of(dsp.evaluate(obs)), ["csp_no_policy", "hsts_missing"])
        # No default-src, so object-src really is missing — a scanner's "Missing object-src" finding.
        obs["https"]["headers"]["content-security-policy"] = "script-src 'self' 'unsafe-inline' https:"
        f = dsp.evaluate(obs)
        self.assertEqual(types_of(f), ["csp_unsafe_policy", "hsts_missing"])
        self.assertIn("'unsafe-inline'", f[0]["evidence"])
        self.assertIn("bare https:", f[0]["evidence"])
        self.assertIn("object-src is missing", f[0]["evidence"])
        # default-src covers object-src, so only the script-src issues remain.
        obs["https"]["headers"]["content-security-policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'"
        f = dsp.evaluate(obs)
        self.assertEqual(f[0]["evidence"], "script-src allows 'unsafe-inline'")

    def test_header_checks_follow_one_same_host_redirect(self):
        """Scanners grade the login page; an apex that answers 301 → /Auth/Login is graded there."""
        obs = clean_obs()
        obs["https"] = {"status": 301, "headers": {"content-type": "text/html"}, "location": "https://h.example.com:443/Auth/Login"}
        self.assertEqual(dsp.evaluate(obs), [])            # redirect alone: nothing to grade
        obs["https_final"] = {"status": 200, "headers": {"content-type": "text/html"}, "location": ""}
        self.assertEqual(types_of(dsp.evaluate(obs)), ["csp_no_policy", "hsts_missing"])

    def test_same_host_redirect_detection(self):
        f = dsp._same_host_https_redirect
        self.assertEqual(f("h.example", {"status": 301, "location": "/login"}), "https://h.example/login")
        self.assertEqual(f("h.example", {"status": 302, "location": "https://H.EXAMPLE/x"}), "https://H.EXAMPLE/x")
        self.assertEqual(f("h.example", {"status": 301, "location": "https://other.example/"}), "")   # cross-host
        self.assertEqual(f("h.example", {"status": 301, "location": "http://h.example/"}), "")      # downgrade
        self.assertEqual(f("h.example", {"status": 200, "location": ""}), "")
        self.assertEqual(f("h.example", {"error": "x"}), "")

    def test_csp_checks_only_apply_to_html(self):
        obs = clean_obs()
        obs["https"] = {"status": 200, "headers": {"content-type": "application/json"}, "location": ""}
        self.assertEqual(dsp.evaluate(obs), [])

    def test_csp_issue_rules(self):
        self.assertEqual(dsp.csp_issues("default-src 'self'; object-src 'none'"), [])
        self.assertEqual(dsp.csp_issues("script-src 'self' 'nonce-abc' 'unsafe-inline'; object-src 'none'"), [])
        self.assertIn("script-src directive is missing", dsp.csp_issues("img-src *"))
        self.assertIn("script-src allows bare *", dsp.csp_issues("script-src *; object-src 'none'"))

    def test_is_weak_cipher(self):
        self.assertTrue(dsp.is_weak_cipher("AES128-SHA"))
        self.assertTrue(dsp.is_weak_cipher("ECDHE-RSA-DES-CBC3-SHA"))
        self.assertFalse(dsp.is_weak_cipher("ECDHE-RSA-AES128-GCM-SHA256"))
        self.assertFalse(dsp.is_weak_cipher("TLS_CHACHA20_POLY1305_SHA256"))
        self.assertFalse(dsp.is_weak_cipher(""))


class TestObserve(unittest.TestCase):
    def test_observe_wires_injected_calls_and_skips_cipher_tests_without_tls12(self):
        calls = []

        def handshake(host, min_v, max_v, ciphers):
            calls.append((min_v, max_v, ciphers))
            return dict(REFUSED)

        obs = dsp.observe("h.example", handshake=handshake, http=lambda url: {"error": "x"},
                          cert=lambda host: dict(UNREACH), weak_suites=["AES128-SHA"], strong_suites=["ECDHE-RSA-AES128-GCM-SHA256"])
        self.assertEqual(set(obs["tls"]), {"TLSv1", "TLSv1.1", "TLSv1.2"})
        self.assertEqual(obs["cipher"], {})      # no TLS 1.2 → no cipher probes
        self.assertEqual(len(calls), 3)

    def test_observe_follows_one_same_host_redirect_only(self):
        fetched = []

        def http(url):
            fetched.append(url)
            if url == "https://h.example/":
                return {"status": 301, "headers": {}, "location": "/Auth/Login"}
            if url == "https://h.example/Auth/Login":
                return {"status": 302, "headers": {}, "location": "/Auth/Login?step=2"}   # would be hop 2
            return {"status": 200, "headers": {"content-type": "text/html"}, "location": ""}

        obs = dsp.observe("h.example", handshake=lambda *a: dict(OK12), http=http, cert=lambda host: dict(CERT_OK),
                          weak_suites=[], strong_suites=[])
        self.assertEqual(obs["https_final"]["status"], 302)
        self.assertEqual(fetched.count("https://h.example/Auth/Login"), 1)
        self.assertNotIn("https://h.example/Auth/Login?step=2", fetched)

    def test_observe_orders_cipher_lists(self):
        seen = []

        def handshake(host, min_v, max_v, ciphers):
            seen.append(ciphers)
            return dict(OK12)

        dsp.observe("h.example", handshake=handshake, http=lambda url: dict(HTML_OK), cert=lambda host: dict(CERT_OK),
                    weak_suites=["AES128-SHA"], strong_suites=["ECDHE-RSA-AES128-GCM-SHA256"])
        self.assertIn("AES128-SHA:@SECLEVEL=0", seen)
        self.assertIn("AES128-SHA:ECDHE-RSA-AES128-GCM-SHA256:@SECLEVEL=0", seen)
        self.assertIn("ECDHE-RSA-AES128-GCM-SHA256:AES128-SHA:@SECLEVEL=0", seen)


class TestProbeHosts(unittest.TestCase):
    def test_keys_are_stable_and_source_tagged(self):
        def observe_fn(host):
            obs = clean_obs(host)
            obs["tls"]["TLSv1.1"] = {"ok": True, "version": "TLSv1.1", "cipher": "AES128-SHA"}
            return obs

        f1, s1 = dsp.probe_hosts(["ingest.example.com"], observe_fn=observe_fn)
        f2, _ = dsp.probe_hosts(["ingest.example.com"], observe_fn=observe_fn)
        self.assertEqual(list(f1), ["probe|tls_weak_protocol|ingest.example.com|accepts TLSv1.1"])
        self.assertEqual(list(f1), list(f2))
        finding = next(iter(f1.values()))
        self.assertEqual(finding["source"], "probe")
        self.assertEqual(finding["domain"], "example.com")
        self.assertEqual(s1["ingest.example.com"], {"status": "ok", "tls": "TLSv1.1, TLSv1.2", "findings": 1})

    def test_min_severity_filters_low(self):
        def observe_fn(host):
            obs = clean_obs(host)
            del obs["https"]["headers"]["strict-transport-security"]
            return obs

        f, s = dsp.probe_hosts(["h.example.com"], "medium", observe_fn=observe_fn)
        self.assertEqual(f, {})
        self.assertEqual(s["h.example.com"]["findings"], 0)
        f, _ = dsp.probe_hosts(["h.example.com"], "low", observe_fn=observe_fn)
        self.assertEqual(types_of(f.values()), ["hsts_missing"])

    def test_unreachable_host_is_isolated(self):
        def observe_fn(host):
            if host == "down.example.com":
                return {"host": host, "tls": {"TLSv1": dict(UNREACH), "TLSv1.1": dict(UNREACH), "TLSv1.2": dict(UNREACH)},
                        "cipher": {}, "cert": dict(UNREACH), "http": {"error": "x"}, "https": {"error": "x"}}
            obs = clean_obs(host)
            obs["cert"] = {"ok": False, "reason": "ssl", "detail": "self-signed"}
            return obs

        f, s = dsp.probe_hosts(["down.example.com", "up.example.com"], observe_fn=observe_fn)
        self.assertEqual(s["down.example.com"]["status"], "unreachable")
        self.assertEqual(s["up.example.com"]["status"], "ok")
        self.assertEqual(types_of(f.values()), ["tlscert_untrusted"])

    def test_host_without_dns_record_is_reported_distinctly(self):
        nodns = {"ok": False, "reason": "dns", "detail": "nodename nor servname provided, or not known"}

        def observe_fn(host):
            return {"host": host, "tls": {"TLSv1": dict(nodns), "TLSv1.1": dict(nodns), "TLSv1.2": dict(nodns)},
                    "cipher": {}, "cert": dict(nodns), "http": {"error": "x"}, "https": {"error": "x"}}

        f, s = dsp.probe_hosts(["gone.example.com"], observe_fn=observe_fn)
        self.assertEqual(f, {})
        self.assertEqual(s["gone.example.com"]["status"], "no DNS record")

    def test_probe_exception_on_one_host_is_recorded(self):
        def observe_fn(host):
            if host == "boom.example":
                raise RuntimeError("bug")
            return clean_obs(host)

        f, s = dsp.probe_hosts(["boom.example", "ok.example"], observe_fn=observe_fn)
        self.assertEqual(s["boom.example"]["status"], "error: RuntimeError")
        self.assertEqual(s["ok.example"]["status"], "ok")
        self.assertEqual(f, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
