---
schema_version: 1
id: 2026-06-26-on-call-aspmx2-false-positive-b7e3d1
agent: on-call
timestamp: "2026-06-26T22:52:00Z"
severity: low
domain: 7 — Security Operations
subject: uptime-check:SMTP aspmx2.googlemail.com SSL/TLS
owner: platform-team
status: resolved
evidence:
  - system: url
    url: https://your-org.pagerduty.com/incidents/PEXAMPLE
    note: The P1 page this verdict triaged; the full manual triage is on the linked ticket (SEC-1234)
  - system: url
    url: https://www.google.com/appsstatus/dashboard/
    note: Google Workspace status green throughout the page window
suggested_next: []
---

## What

On-Call triaged a P1 page (2026-06-26 22:49:25 UTC) for an SMTP-over-SSL/TLS check against
`aspmx2.googlemail.com` — a **backup** Google Workspace MX. The deterministic core
(`oncall_triage.py`) classified it **false positive, high confidence, auto-ackable**, with this
cited evidence: 4 of 5 probes healthy (New York recovered at 1.66s, Los Angeles 0.35s, Dallas
0.11s, London 0.10s); the only failing node (Vienna) had been CRITICAL ~215h, past the 24h stale
threshold, **and** sits on a hosting/VPN range with poor IP reputation that the target tarpits;
target is a backup MX; Google status green; end-to-end mail delivery passing through 22:45.

## Why it matters

This is the class of page that motivated the On-Call agent. With a low sensitivity threshold and a
permanently-red probe node, a single transient blip from one more node crossed the threshold and
paged P1 — a monitoring artifact, not a mail incident. Mechanically reaching "false positive" with
the evidence already written down means this class of page is acked and closed without waking
on-call, while a *real* multi-node outage (3+ non-structural probes failing, or provider/service
health actually down) still escalates to John Wick.

## Recommended action

- **On-Call → (no agent handoff).** `suggested_next: []`, `status: resolved`: low blast radius
  (backup target, healthy majority, only structural failures), so On-Call auto-acks the PagerDuty
  incident and posts a close-out note linking this finding. No human page needed.
- **Human team (platform):** the durable fixes live on the parent ticket (SEC-1234): remove the
  permanently-red probe location, correct the check to STARTTLS on port 25, downgrade it from P1,
  and replace the per-node TLS probe with an end-to-end mail-flow monitor whose heartbeat feeds the
  service-health signal.

> Note: this is a **reference example** — the canonical On-Call false-positive verdict. The
> PagerDuty URL and the ticket are illustrative; it lives in `examples/` so the live ledger scan
> ignores it. Reproduce the verdict directly with
> `python3 .github/scripts/oncall_triage.py --alert <replayed-alert.json> --now 2026-06-26T22:52:00Z`.
