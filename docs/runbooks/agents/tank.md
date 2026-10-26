# Tank — Vulnerability Investigation & Disposition Runbook

**Character**: Tank from *The Matrix*  
**Domain**: CISSP Domain 6 — Security Assessment & Testing  
**Skill**: [`/tank`](../../../.claude/commands/tank.md)  
**Status**: Live

---

## What it does

Tank investigates a single Aikido or Wiz finding (or a Linear vulnerability ticket), reads the actual source code or cloud context, and makes a disposition decision: **false positive** (suppress + close) or **real vulnerability** (summarize fix path and hand off).

Named after Tank from The Matrix: born free, no implants. "I'm the operator. I load the guns."

---

## How to invoke

```text
/tank SEC-1234                          # Linear ticket ID  (single-finding mode)
/tank https://app.aikido.dev/...        # Aikido finding URL
/tank https://app.wiz.io/issues#...     # Wiz issue URL
/tank "yaml.load finding in the api repo"   # freeform description
/tank sweep                             # weekly auto-triage pass (sweep mode)
```

---

## Weekly sweep

`/tank sweep` is a **first-pass over the new-findings backlog**, not a deep single-target
investigation. Tank consumes the open Aikido/Wiz vuln tickets that discovery already created
(your intel feed / vuln-ticketing workflow) — it does **not** discover findings or create tickets — and
adds the real-vs-false-positive call. It collects everything new since the last sweep (bounded by the
most recent `.tank/sweeps/sweep-*.md`), triages each at triage altitude using the same FP-vs-real
logic as single-finding mode, and writes a ranked worklist to `.tank/sweeps/sweep-<date>.md`
in three buckets: **SUPPRESS CANDIDATES**, **FIX CANDIDATES** (ranked by severity × exploitability),
and **NEEDS DEEP TRIAGE** (hand to `/tank <target>`). A fourth top-of-list bucket, **ACTIVE
EXPLOITATION**, appears when the Panther sensor shows live exploitation against a fix candidate. The
human approves the suppress batch in one shot; Tank then executes the approved suppressions via the
normal false-positive path. Run weekly (e.g. Monday, after your intel and vuln-ticketing jobs have
populated the week's tickets). Suppression is always human-gated — the worklist is a proposal until
approved.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Aikido API | Fetch finding metadata, suppress false positives | `AIKIDO_CLIENT_ID` + `AIKIDO_CLIENT_SECRET` — injected env vars in a headless run; `<your-aikido-item>` in your credential vault for local dev (see [knowledge/config.md](../../../knowledge/config.md)) |
| Wiz MCP | Fetch Wiz issue details, container findings | MCP server auth |
| Socket (`.github/scripts/socket_threat_feed.py`) | Malware / typosquat verdicts for repos in a Socket-covered org | `SOCKET_API_TOKEN` |
| GitHub API / `gh` | Read source code for SAST/SCA findings | `gh` CLI auth |
| AWS CLI | Check EC2 instance state (cloud_instance findings) | AWS profile |
| Docker | Pull and scan container images (wizcli) | Local Docker daemon |
| `wizcli` | First-party container image scan | Wiz auth |
| Linear MCP | Read ticket, post analysis comment, close/update ticket | MCP server auth |
| [Panther sub-agent](../../../.claude/agents/panther.md) | Exploitation / probing telemetry for network-reachable findings (read-only) | Sensor's own credentials |
| [Bedrock sub-agent](../../../.claude/agents/bedrock.md) | Sensitive-data blast radius behind a data-bearing asset (read-only) | Sensor's own credentials |

---

## Disposition paths

### False positive

1. Suppress in Aikido. Default to **per-issue** (`PUT /api/public/v1/issues/{id}/ignore`)
   because a `group_id` often spans multiple unrelated resources. Use the group endpoint
   (`PUT /api/public/v1/issues/groups/{group_id}/ignore`) only when every finding in
   the group should be ignored. Always inspect the group's membership first.
2. Comment on Linear ticket with analysis
3. Close Linear ticket (state: Done)
4. Check for duplicate open tickets with same finding

### EOL finding — not yet EOL
1. Snooze in Aikido until `eol_date - 60 days`
2. Comment with actual EOL date and snooze rationale
3. Leave ticket open

### Real vulnerability
1. If Panther shows **active exploitation**, set priority Urgent and recommend a `/john-wick` handoff first
2. Verify a PR target exists in committed IaC (no target → lean to risk-acceptance via `/keymaker declined-blocker` or close + suppress with rationale)
3. Look up system owner in [`knowledge/System_Ownership.md`](../../../knowledge/System_Ownership.md)
4. Comment with attack vector, blast radius, fix path, recommended owner, and the **engineering agent that performs the fix** (`/roland` for a dependency bump, `/apoc` for a SAST/secret fix, `/hamann` for IaC, `/bane` for CI/CD, `/mouse` for a regression test — see [Engineering SDLC agents](../../engineering-sdlc-agents.md))
5. Update ticket priority if severity differs from Aikido's rating
6. Route: engineering/platform team → assign; non-engineering business owner or unknown → leave unassigned, GRC must act

### Exception requested
1. Collect: assigned engineer, committed remediation date, reason
2. Apply your workspace's `Exception` label
3. Set state to `Exception Requested`
4. Comment with exception details; do not suppress in Aikido

---

## Key technical details

**Aikido credentials**: read from `$AIKIDO_CLIENT_ID` / `$AIKIDO_CLIENT_SECRET` in the environment (injected
from your secrets manager when containerized). Local dev populates them from your credential vault:
```bash
AIKIDO_CLIENT_ID=$(op item get "<your-aikido-item>" --vault "$YOUR_CREDENTIAL_VAULT" --fields username)
AIKIDO_CLIENT_SECRET=$(op item get "<your-aikido-item>" --vault "$YOUR_CREDENTIAL_VAULT" --fields credential --reveal)
```

**Container image findings**: Tank uses a 3-step verification process:
1. Cross-check Wiz + Aikido finding lists
2. Run `wizcli scan container-image` for first-party confirmation
3. Code reachability analysis — just because a package is present doesn't mean the CVE is exploitable

**SAST findings**: Tank finds the true author by walking git history beyond `git blame` — migration commits are pass-throughs and must not be attributed.

**Known false-positive classes** (documented in the skill): stale `.claude/worktrees/` duplicates (diff against canonical HEAD), the taint-unaware `AIK_html_insecure-document-method` rule (suppress per-issue, never by group), and not-yet-EOL runtimes (snooze, don't suppress).

**Malware / typosquat findings**: for repos in an org where Socket is installed, Socket is the source of truth — a `listed: true` result is real (hand to John Wick), an `INCOMPLETE` result blocks suppression. Elsewhere Aikido stays the malware source.

**Sensor corroboration**: Panther (is it being exploited?) and Bedrock (what sensitive data sits behind it?) are triage inputs, never the sole basis for a call.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Real vuln confirmed, no known owner | GRC (accept risk or find owner) |
| Confirmed exploitable vuln in production / active exploitation in Panther | John Wick |
| Malicious or typosquatted package confirmed by Socket | John Wick |
| Real vuln explicitly accepted / won't-fix | `/keymaker declined-blocker` (risk register) |
| Fix is engineering work | pointer only (not a `suggested_next`): `/roland`, `/apoc`, `/hamann`, `/bane`, `/mouse` |

---

## Service account requirements

- **Aikido API key**: `<your-aikido-item>` in your credential vault (or injected env vars in a headless runtime)
- **Socket token**: `SOCKET_API_TOKEN` with `packages:list`; only needed for Socket-covered orgs
- **GitHub `gh` auth**: service account token with `repo` read scope (personal auth works for interactive runs)
- **AWS CLI**: dedicated read-only role for EC2 describe calls; terminate-instances only on explicit human confirmation
- **wizcli**: authenticated via Wiz MCP; ensure the service account has container scan permissions
