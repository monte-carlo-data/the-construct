# Agent Smith — Security Chaos Engineering Agent Runbook

**Character**: Agent Smith from *The Matrix* — the agent that breaks things on purpose  
**Domain**: CISSP Domain 7 — Security Operations (resiliency / continuous verification)  
**Skill**: [`/smith`](../../../.claude/commands/smith.md)  
**Status**: Wired — no live target enrolled yet (enroll one via the opt-in registry, with owner sign-off)

---

## What it does

Smith deliberately induces controlled, reversible failures in **opt-in** security infrastructure
(e.g. a proxy, a private-network mesh — never your secrets manager in v1) and verifies that the
system-health probes (your infrastructure liveness probes), the alerting, and the failover behave
the way you *think* they do. He finds single points of failure and monitoring blind spots **on your
schedule**, before a real incident does.

> "Never send a human to do a machine's job."

**The pattern is Netflix ChAP, not Chaos Monkey.** Netflix moved past random termination —
hypothesis-driven experiments judged by automated canary analysis, with an auto-abort circuit
breaker. Smith's automated canary analysis *is* the liveness probes: both the pass/fail oracle and
the abort signal. **A PASS requires detection + alerting (+ failover) to all fire; a silent recovery
is a FAIL** — that blind spot is the most valuable thing Smith can find.

---

## How to invoke

```text
/smith                      # status — enrolled targets, last verdicts, kill-switch state
/smith status               # same as above
/smith list                 # full registry (targets, env, hypothesis, owner sign-off, last result)
/smith dry-run <target>     # run every preflight gate + print the experiment card; NO inject, NO Slack
/smith run <target>         # live experiment: baseline → announce → inject → verify → restore → record
/smith abort                # engage the global kill switch (disables all experiments)
/smith SEC-1234             # load target/scope focus from a Linear ticket
```

---

## Experiment lifecycle

`preflight gates → healthy baseline (control) → before-announce → human approval (non-trivial only)
→ inject → verify vs. probes → always-restore + confirm recovery → after-announce + append-only run
record → emit finding on FAIL`

Verdict logic: **PASS** = every claimed signal fired within SLA · **FAIL** = service recovered but a
claimed signal (detection / alert / failover) did NOT fire · **ABORTED** = watchdog or kill switch
stopped the run before a clean verdict.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| System-health liveness probes | Read probe results as the pass/fail oracle + abort signal | read-only (`snapshot_source` per target) |
| Alert source (system-health / your SIEM / Slack) | Confirm the alert actually fired | read-only (`alert_source` per target) |
| Inject / restore actions | Execute the registry's **named** reversible action | least privilege that action needs |
| Slack | Before/after announce to `#security-team` | `mcp__slack__slack_send_message_draft` |
| Linear MCP | Load ticket scope; attach findings | MCP server auth |

---

## State layout

```text
review-resilience/smith/
  README.md        — enrollment checklist, probe-oracle wiring, owner sign-off process
  registry.yaml    — opt-in targets (THE allow-list); hypothesis + named inject/restore + SLAs
  blackout.yaml    — hard blackout windows (unconditional veto)
  KILL_SWITCH      — (absent normally) presence disables ALL experiments
  .inflight        — (transient) concurrency lock while an experiment runs
  runs/            — append-only JSON run records = the audit trail (commit these)
```

---

## Critical rules (v1 guardrails)

- **Opt-in only** — nothing eligible unless in `registry.yaml`, `enabled: true`, `owner_signoff: true`
- **Secrets-management systems (your secrets manager) are hard-denied** regardless of registry contents
- **Staging before prod** — a `prod` target is refused until its `staging_twin` has a recorded PASS
- **Restore always runs** and must confirm recovery; an unrecoverable restore escalates LOUDLY
  (Slack + a `critical` finding)
- **Fixed named actions only** — inject/restore are never built from probe output or external strings
- **Global kill switch** (checked twice) + **per-experiment auto-abort** circuit breaker
- **One experiment at a time** (concurrency lock); business-hours-only by default; blackout always wins
- **No secrets, no internal endpoints** in any output, Slack message, or run record
- **The probes are the oracle** — if the mapped probe is an unimplemented stub, Smith refuses (never
  invents detection)

---

## Routing

Slice of the canonical [findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md) (rows 11,
13, 20, 20b). Smith is **emit-only** — findings carry `agent: smith` and route *out*; nothing routes
*to* smith.

| Situation | Route to | Matrix row |
|---|---|---|
| Restore could not confirm recovery — something is degraded *now* | John Wick | 20b |
| Confirmed single point of failure / failover didn't hold (architecture gap) | Niobe | 20 |
| Alerting / detection didn't fire — monitor/architecture of the control needs work | Niobe | 20 |
| Network-path failover gap (TLS/SG/VPC/DNS redundancy) | Niobe + Switch | 20, 11 |
| An availability control we attest to doesn't actually work | Keymaker (+ Seraph for $-figure) | 13 |
| Engineering accepts / won't-fix the gap | `/keymaker declined-blocker` (source `smith`) | 13 |

---

## Service account requirements

- **System-health snapshot + alert source**: read-only access to wherever the liveness probe
  results and alert state are published — confirm the concrete path/API before the first live run
- **Inject/restore credentials**: the least-privilege credential each named action needs (e.g. a
  cloud role scoped to restart only the redundant staging probe); sourced from your secrets manager
- **Slack / Linear MCP**: shared agent service accounts (post to `#security-team`; Linear read/write)

---

## Cleanup

Run records under `review-resilience/smith/runs/` are the **audit trail** — commit them, do not delete.
The `.inflight` lock is removed automatically at the end of every experiment (including on abort/error).
