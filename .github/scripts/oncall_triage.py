#!/usr/bin/env python3
"""On-call triage extractor — the deterministic core behind the /on-call agent.

The motivating shape: an uptime-monitor SMTP/TLS check pages P1 against a *backup* MX
host from datacenter/VPN probe IPs. Inbound mail is never impacted: 4 of 5 probes are
green, the one failing node self-recovers in ~2 min, and a node on a VPN-range probe IP
has been falsely CRITICAL for days — so with Sensitivity=2 a single transient blip crosses
the page threshold. A human reconstructs all of that by hand, every time.

This module reconstructs it MECHANICALLY. Given the alert + check config + per-location
probe status (the shape an uptime-monitor MCP returns) it classifies the page as
`false_positive` / `incident` / `inconclusive` with *cited evidence* — same spec + same
inputs → same verdict every run, no model call, no sampling. That is deliberate: an
on-call classifier that auto-acks pages must be auditable and reproducible, not a
temperature knob. The /on-call skill is the judgment layer on top — it reads the verdict,
emits a finding, and (gated) acts on PagerDuty.

The verdict maps to a finding (`findings/` SCHEMA, domain 7 — Security Operations):
  - false_positive  → suggested_next [],          status resolved   (low blast radius → auto-ackable)
  - incident        → suggested_next [john-wick],  status escalated  (HANDOFF row 1 — never auto-run)
  - inconclusive    → suggested_next [],           status escalated  (human decides)

Run:  python3 .github/scripts/oncall_triage.py --alert <alert.json>
      python3 .github/scripts/oncall_triage.py --alert <alert.json> --json-out verdict.json
Stdlib only. Exit 0 on a produced verdict, 2 on bad input.

Configuration (optional):
  ONCALL_TARPITTED_PROBE_OWNERS — comma-separated, case-insensitive substrings matched
  against a probe's `ip_owner` / `ip` to mark it as a tarpitted/VPN range (default:
  "vpn,proxy"). Add the hosting/VPN ASNs your monitoring provider's probes sit on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# --- Tunables -----------------------------------------------------------------
# A probe that has been CRITICAL longer than this is "stale" — its failure is structural
# (a tarpitted IP range, a decommissioned node), not signal about the monitored service.
# One day is already well past any real outage that would not have been resolved or
# escalated by other means.
STALE_CRITICAL_HOURS = 24.0

# Probe IP ranges/owners that monitoring providers' upstreams routinely tarpit or
# rate-limit (hosting / VPN / anti-abuse-flagged ASNs). A timeout from one of these against
# a shared third-party endpoint says more about the probe than the service. Matched as a
# case-insensitive substring against a probe's `ip_owner` / `ip` fields. Not exhaustive;
# extend via ONCALL_TARPITTED_PROBE_OWNERS, and the skill layer can note an unknown owner
# for a human to add.
TARPITTED_PROBE_OWNERS = tuple(
    tok.strip().lower()
    for tok in os.environ.get("ONCALL_TARPITTED_PROBE_OWNERS", "vpn,proxy").split(",")
    if tok.strip()
)

# Failing-probe states that count as "this node is red".
FAILING_STATES = ("critical", "down", "timeout", "error")
HEALTHY_STATES = ("ok", "up", "healthy", "passing")


# --- Inputs (the shape an uptime-monitor MCP / a PagerDuty payload provide) ---------------
@dataclass
class ProbeStatus:
    location: str
    state: str                      # critical | ok | down | timeout | ...
    response_time_s: float | None = None
    ip: str | None = None
    ip_owner: str | None = None     # ASN / hosting-provider name, e.g. "ExampleVPN / AS64496"
    critical_since: str | None = None  # ISO-8601 UTC; how long this node has been red

    def is_failing(self) -> bool:
        return self.state.strip().lower() in FAILING_STATES

    def is_healthy(self) -> bool:
        return self.state.strip().lower() in HEALTHY_STATES

    def is_tarpitted_range(self) -> bool:
        hay = f"{self.ip_owner or ''} {self.ip or ''}".lower()
        return any(tok in hay for tok in TARPITTED_PROBE_OWNERS)

    def stale_critical_hours(self, now: datetime) -> float | None:
        """Hours this probe has been continuously CRITICAL, or None if unknown/not failing."""
        if not self.is_failing() or not self.critical_since:
            return None
        try:
            since = _parse_iso(self.critical_since)
        except ValueError:
            return None
        return max(0.0, (now - since).total_seconds() / 3600.0)


@dataclass
class Alert:
    check_name: str
    check_type: str                 # SMTP | HTTP | ...
    target: str                     # the monitored host, e.g. mx2.example.com
    fired_at: str                   # ISO-8601 UTC
    probes: list[ProbeStatus]
    sensitivity: int = 1            # # of locations that must fail concurrently to page
    is_backup_target: bool = False  # e.g. a backup MX alias, not the primary
    provider_status_healthy: bool | None = None  # provider's own status page, if known
    service_health_ok: bool | None = None        # end-to-end check (e.g. mailbox delivery)


# --- Output -------------------------------------------------------------------
@dataclass
class Verdict:
    classification: str             # false_positive | incident | inconclusive
    confidence: str                 # high | medium | low
    severity: str                   # critical | high | medium | low | informational
    suggested_next: list[str]
    finding_status: str             # resolved | escalated | open
    auto_actionable: bool           # may the skill auto-ack without human approval?
    reasons: list[str] = field(default_factory=list)   # cited evidence, human-readable

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string to an aware UTC datetime. Accepts a trailing 'Z'."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def triage(alert: Alert, now: datetime | None = None) -> Verdict:
    """Classify a page as false_positive / incident / inconclusive with cited evidence.

    The logic mirrors the manual triage an on-call engineer does, made mechanical:
      1. Partition probes into healthy / failing, and within failing distinguish
         *stale-CRITICAL* and *tarpitted-range* nodes whose failure is structural.
      2. The "real" failing signal is failing probes that are NEITHER stale NOR on a
         tarpitted range — those are the only ones that say something about the service.
      3. If a majority of probes are healthy AND no corroborating signal (provider status,
         end-to-end service health) is bad, it's a false positive — and low-blast-radius
         (backup target, recovered/transient) ones are auto-ackable.
      4. If the real failing signal alone meets/exceeds the page sensitivity, or provider
         status / end-to-end health is bad, it's an incident → escalate to john-wick.
      5. Otherwise inconclusive → escalate to a human.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    total = len(alert.probes)
    if total == 0:
        return Verdict(
            classification="inconclusive", confidence="low", severity="medium",
            suggested_next=[], finding_status="escalated", auto_actionable=False,
            reasons=["No per-location probe data available; cannot assess consensus."],
        )

    healthy = [p for p in alert.probes if p.is_healthy()]
    failing = [p for p in alert.probes if p.is_failing()]

    stale = [p for p in failing if (h := p.stale_critical_hours(now)) is not None and h >= STALE_CRITICAL_HOURS]
    tarpitted = [p for p in failing if p.is_tarpitted_range()]
    # "Real" failing signal: failing, and not explained away as stale or tarpitted.
    structural = {p.location for p in stale} | {p.location for p in tarpitted}
    real_failing = [p for p in failing if p.location not in structural]

    if healthy:
        reasons.append(
            f"{len(healthy)}/{total} probes healthy ("
            + ", ".join(f"{p.location} {p.state}" for p in healthy) + ")."
        )
    for p in stale:
        hrs = p.stale_critical_hours(now)
        reasons.append(
            f"{p.location} has been CRITICAL ~{hrs:.0f}h (>= {STALE_CRITICAL_HOURS:.0f}h "
            "stale threshold) — structural, not fresh signal."
        )
    for p in tarpitted:
        reasons.append(
            f"{p.location} is on a tarpitted/VPN probe range ({p.ip_owner or p.ip}) — "
            "timeouts there reflect probe-IP reputation, not service health."
        )
    if alert.is_backup_target:
        reasons.append(f"Target {alert.target} is a backup/secondary endpoint, not the primary.")
    if alert.provider_status_healthy is True:
        reasons.append("Provider status page is green for the monitored service.")
    if alert.service_health_ok is True:
        reasons.append("End-to-end service health check (e.g. mailbox delivery) is passing.")

    # --- Strong incident signals override everything: corroborated real failure. ---
    if alert.provider_status_healthy is False:
        reasons.append("Provider status page reports a real outage.")
        return _incident(alert, reasons, confidence="high")
    if alert.service_health_ok is False:
        reasons.append("End-to-end service health check is FAILING — user-visible impact.")
        return _incident(alert, reasons, confidence="high")

    # --- Consensus among non-structural probes. ---
    real_fail_n = len(real_failing)
    if real_fail_n >= max(alert.sensitivity, 2) and real_fail_n > len(healthy):
        reasons.append(
            f"{real_fail_n} non-structural probe(s) failing concurrently "
            f"(>= sensitivity {alert.sensitivity} and a majority) — outage-shaped."
        )
        return _incident(alert, reasons, confidence="high" if real_fail_n >= 3 else "medium")

    # --- Majority healthy with no corroboration → false positive. ---
    if len(healthy) > real_fail_n:
        # Low blast radius (auto-ackable) when there's no real failing signal at all and the
        # surviving "failures" are all structural — or a single recovered/transient blip on a
        # backup target. Consequential-looking ones stay non-auto (human eyeballs them).
        only_structural = real_fail_n == 0
        single_transient = real_fail_n == 1 and (alert.is_backup_target or len(healthy) >= total - 1)
        auto = only_structural or single_transient
        conf = "high" if only_structural else "medium"
        if only_structural:
            reasons.append("All failing probes are structural (stale and/or tarpitted); no fresh failure.")
        else:
            reasons.append(
                f"{real_fail_n} transient failure against a healthy majority on a "
                f"{'backup ' if alert.is_backup_target else ''}target — below an outage shape."
            )
        sev = "low" if alert.is_backup_target else "medium"
        return Verdict(
            classification="false_positive", confidence=conf, severity=sev,
            suggested_next=[], finding_status="resolved", auto_actionable=auto,
            reasons=reasons,
        )

    # --- Neither clearly healthy nor clearly an outage. ---
    reasons.append(
        f"Mixed signal: {real_fail_n} non-structural failure(s) vs {len(healthy)} healthy "
        "with no corroborating provider/service signal — cannot auto-classify."
    )
    return Verdict(
        classification="inconclusive", confidence="low", severity="medium",
        suggested_next=[], finding_status="escalated", auto_actionable=False,
        reasons=reasons,
    )


def _incident(alert: Alert, reasons: list[str], confidence: str) -> Verdict:
    """Build an incident verdict. Always routes to john-wick and is NEVER auto-actionable —
    HANDOFF row 1: a confirmed incident is drop-everything human-confirmed response."""
    return Verdict(
        classification="incident", confidence=confidence,
        severity="critical" if confidence == "high" else "high",
        suggested_next=["john-wick"], finding_status="escalated",
        auto_actionable=False, reasons=reasons,
    )


# --- Loading ------------------------------------------------------------------
def alert_from_dict(d: dict) -> Alert:
    probes = [ProbeStatus(**{k: p.get(k) for k in ProbeStatus.__dataclass_fields__ if k in p})
              for p in d.get("probes", [])]
    fields = {k: d[k] for k in Alert.__dataclass_fields__ if k in d and k != "probes"}
    return Alert(probes=probes, **fields)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="On-call page triage extractor.")
    ap.add_argument("--alert", required=True, help="Path to the alert JSON (alert + check + probes).")
    ap.add_argument("--json-out", help="Write the verdict JSON here instead of stdout.")
    ap.add_argument("--now", help="Override 'now' (ISO-8601 UTC) for deterministic stale calc.")
    args = ap.parse_args(argv)

    try:
        raw = json.loads(open(args.alert, encoding="utf-8").read())
        alert = alert_from_dict(raw)
    except (OSError, ValueError, TypeError) as e:
        print(f"error: could not load alert: {e}", file=sys.stderr)
        return 2

    now = _parse_iso(args.now) if args.now else None
    verdict = triage(alert, now=now)
    payload = {"alert": {"check_name": alert.check_name, "target": alert.target}, "verdict": verdict.to_dict()}
    out = json.dumps(payload, indent=2) + "\n"
    if args.json_out:
        open(args.json_out, "w", encoding="utf-8").write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
