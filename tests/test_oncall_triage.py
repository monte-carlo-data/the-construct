#!/usr/bin/env python3
"""Tests for the on-call triage extractor (.github/scripts/oncall_triage.py).

The headline test is a REPLAY of the canonical false-positive page — the shape that motivated
the extractor: a P1 against a *backup* MX host from a tarpitted VPN probe range while 4 of 5
nodes were green. The extractor must independently reach "false positive" with cited evidence,
and (because it was a backup target with a single structural failure) mark it auto-ackable.
The mirror test is a genuine multi-node outage: the extractor must classify `incident`,
route to john-wick, and NEVER mark it auto-actionable.

The core is deterministic and model-free, so these are pure stdlib unit tests with
in-memory fixtures — no Anthropic API, no network. The one on-disk input is the shipped
replay fixture `.github/scripts/fixtures/oncall/replay_example.json`, loaded through the
same `alert_from_dict` path the CLI uses.

Run:  python3 tests/test_oncall_triage.py      (standalone, prints every check)
      python3 -m pytest tests/                 (pytest: a failed check raises)
Exits 0 if all pass, 1 otherwise. Stdlib only.

Acceptance criteria this file traces:
  - AC-1: test_replay_example_is_false_positive — replay → false positive + evidence + close-out
  - AC-2: test_genuine_multinode_failure_escalates — real outage escalates, not auto-resolved
  - AC-3: test_incident_never_auto_actionable — gated action: incidents never auto-ack
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "oncall_triage.py"
REPLAY_FIXTURE = REPO_ROOT / ".github" / "scripts" / "fixtures" / "oncall" / "replay_example.json"

spec = importlib.util.spec_from_file_location("oncall_triage", SCRIPT)
ot = importlib.util.module_from_spec(spec)
sys.modules["oncall_triage"] = ot  # register before exec (dataclass annotations resolve via sys.modules)
spec.loader.exec_module(ot)

Alert = ot.Alert
ProbeStatus = ot.ProbeStatus
triage = ot.triage
alert_from_dict = ot.alert_from_dict

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)
        if "pytest" in sys.modules:  # under pytest a failed check must fail the test, not just print
            raise AssertionError(f"{name}" + (f" — {detail}" if detail else ""))


# "Now" pinned a few minutes after the replay page so the stale calc is deterministic.
NOW = datetime(2026, 6, 26, 22, 52, 0, tzinfo=timezone.utc)


def _replay_alert() -> Alert:
    """The canonical false-positive page, as an in-memory Alert (mirrors replay_example.json).

    P1 at 22:49:25 UTC, SMTP/TLS check against the BACKUP MX mx2.example.com.
    US-East-1 recovered (1.66s) by ~22:50; the other three US/EU nodes fast & green;
    EU-Central-1 (a VPN-range probe) red for 8 days. Sensitivity was 2. Provider status
    green; mail delivered continuously through 22:45.
    """
    return Alert(
        check_name="SMTP mx2.example.com SSL/TLS",
        check_type="SMTP",
        target="mx2.example.com",
        fired_at="2026-06-26T22:49:25Z",
        sensitivity=2,
        is_backup_target=True,
        provider_status_healthy=True,   # provider status page green throughout
        service_health_ok=True,         # mail delivered continuously through 22:45
        probes=[
            ProbeStatus("US-East-1", "ok", 1.66, ip="203.0.113.10", ip_owner="ExampleColo"),
            ProbeStatus("US-West-1", "ok", 0.35),
            ProbeStatus("US-Central-1", "ok", 0.11),
            ProbeStatus("EU-West-1", "ok", 0.10),
            ProbeStatus("EU-Central-1", "critical", None, ip="203.0.113.50",
                        ip_owner="ExampleVPN / AS64496", critical_since="2026-06-18T00:00:00Z"),
        ],
    )


def test_replay_example_is_false_positive() -> None:
    """AC-1: the replay yields false_positive, with cited evidence, auto-ackable, no handoff."""
    v = triage(_replay_alert(), now=NOW)
    check("replay → false_positive", v.classification == "false_positive", v.classification)
    check("replay no agent handoff", v.suggested_next == [], str(v.suggested_next))
    check("replay status resolved (close-out)", v.finding_status == "resolved", v.finding_status)
    check("replay auto-ackable (low blast radius)", v.auto_actionable is True)
    check("replay low severity (backup target)", v.severity == "low", v.severity)
    # Cited evidence: must mention the healthy majority AND the EU-Central-1 structural failure.
    joined = " ".join(v.reasons).lower()
    check("replay cites healthy majority", "4/5 probes healthy" in joined, joined)
    check("replay cites stale VPN-range node", "eu-central-1" in joined and "stale" in joined, joined)


def test_replay_fixture_file_matches_in_memory_alert() -> None:
    """The shipped replay_example.json loads via alert_from_dict and reaches the same verdict."""
    raw = json.loads(REPLAY_FIXTURE.read_text(encoding="utf-8"))
    from_file = triage(alert_from_dict(raw), now=NOW)
    in_memory = triage(_replay_alert(), now=NOW)
    check("fixture file → false_positive", from_file.classification == "false_positive", from_file.classification)
    check("fixture file verdict == in-memory verdict", from_file.to_dict() == in_memory.to_dict())


def test_genuine_multinode_failure_escalates() -> None:
    """AC-2: 3 healthy nodes go CRITICAL at once on the primary MX → incident, not auto-resolve."""
    a = Alert(
        check_name="SMTP mx1.example.com SSL/TLS",
        check_type="SMTP",
        target="mx1.example.com",
        fired_at="2026-06-26T22:49:25Z",
        sensitivity=2,
        is_backup_target=False,
        provider_status_healthy=None,
        service_health_ok=None,
        probes=[
            ProbeStatus("US-East-1", "critical", None),
            ProbeStatus("US-West-1", "critical", None),
            ProbeStatus("US-Central-1", "critical", None),
            ProbeStatus("EU-West-1", "ok", 0.10),
            ProbeStatus("EU-Central-1", "critical", None, ip_owner="ExampleVPN / AS64496",
                        critical_since="2026-06-18T00:00:00Z"),  # still structural — excluded
        ],
    )
    v = triage(a, now=NOW)
    check("multinode → incident", v.classification == "incident", v.classification)
    check("multinode routes to john-wick", v.suggested_next == ["john-wick"], str(v.suggested_next))
    check("multinode escalated", v.finding_status == "escalated", v.finding_status)
    # 3 real failures (EU-Central-1 excluded as structural) is a real outage shape, high confidence.
    check("multinode high confidence", v.confidence == "high", v.confidence)


def test_incident_never_auto_actionable() -> None:
    """AC-3 (gated action): any incident verdict is never auto-ackable. Use a provider-down signal."""
    a = _replay_alert()
    a.provider_status_healthy = False   # provider now reports a real outage
    a.service_health_ok = None
    v = triage(a, now=NOW)
    check("provider-down → incident", v.classification == "incident", v.classification)
    check("incident NOT auto-actionable", v.auto_actionable is False)
    check("incident routes to john-wick", v.suggested_next == ["john-wick"], str(v.suggested_next))


def test_end_to_end_failure_overrides_green_probes() -> None:
    """A failing end-to-end service check beats green reachability probes — user impact wins."""
    a = _replay_alert()
    a.service_health_ok = False         # mailbox delivery actually failing
    a.provider_status_healthy = None
    v = triage(a, now=NOW)
    check("service-down → incident", v.classification == "incident", v.classification)
    check("service-down high confidence", v.confidence == "high", v.confidence)


def test_stale_threshold_boundary() -> None:
    """A fresh CRITICAL node is NOT excluded as structural; an 8-day one is."""
    fresh = ProbeStatus("X", "critical", critical_since="2026-06-26T22:00:00Z")  # ~52 min
    old = ProbeStatus("Y", "critical", critical_since="2026-06-18T00:00:00Z")    # ~8 days
    check("fresh not stale", fresh.stale_critical_hours(NOW) < ot.STALE_CRITICAL_HOURS)
    check("old is stale", old.stale_critical_hours(NOW) >= ot.STALE_CRITICAL_HOURS)


def test_tarpitted_range_detection() -> None:
    """VPN / proxy ranges are recognized regardless of which field carries the marker."""
    check("VPN owner tarpitted", ProbeStatus("V", "critical", ip_owner="ExampleVPN / AS64496").is_tarpitted_range())
    check("proxy owner tarpitted", ProbeStatus("V", "critical", ip_owner="example-proxy-net").is_tarpitted_range())
    check("clean owner not tarpitted", not ProbeStatus("V", "critical", ip_owner="ExampleColo").is_tarpitted_range())


def test_no_probe_data_is_inconclusive() -> None:
    a = _replay_alert()
    a.probes = []
    v = triage(a, now=NOW)
    check("no probes → inconclusive", v.classification == "inconclusive", v.classification)
    check("no probes escalated", v.finding_status == "escalated", v.finding_status)
    check("no probes not auto", v.auto_actionable is False)


def test_determinism() -> None:
    """Same input → identical verdict every run (model-free guarantee)."""
    a = _replay_alert()
    v1, v2 = triage(a, now=NOW), triage(_replay_alert(), now=NOW)
    check("deterministic verdict", v1.to_dict() == v2.to_dict())


def test_alert_from_dict_roundtrip() -> None:
    """The MCP/PagerDuty JSON shape loads into an Alert without losing probe fields."""
    raw = {
        "check_name": "c", "check_type": "SMTP", "target": "t", "fired_at": "2026-06-26T22:49:25Z",
        "sensitivity": 3, "is_backup_target": True,
        "probes": [{"location": "US-East-1", "state": "ok", "response_time_s": 0.1},
                   {"location": "EU-Central-1", "state": "critical", "ip_owner": "ExampleVPN"}],
    }
    a = alert_from_dict(raw)
    check("loaded probe count", len(a.probes) == 2, str(len(a.probes)))
    check("loaded sensitivity", a.sensitivity == 3, str(a.sensitivity))
    check("loaded tarpit marker", a.probes[1].is_tarpitted_range())


if __name__ == "__main__":
    print("oncall_triage tests")
    for fn in (
        test_replay_example_is_false_positive,
        test_replay_fixture_file_matches_in_memory_alert,
        test_genuine_multinode_failure_escalates,
        test_incident_never_auto_actionable,
        test_end_to_end_failure_overrides_green_probes,
        test_stale_threshold_boundary,
        test_tarpitted_range_detection,
        test_no_probe_data_is_inconclusive,
        test_determinism,
        test_alert_from_dict_roundtrip,
    ):
        fn()
    if _failures:
        print(f"\n{len(_failures)} FAILED: {', '.join(_failures)}")
        sys.exit(1)
    print("\nall passed")
    sys.exit(0)
