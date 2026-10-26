# Niobe — Security Architecture Agent Runbook

**Character**: Niobe from *The Matrix Reloaded/Revolutions*  
**Domain**: CISSP Domain 3 — Security Architecture & Engineering  
**Skill**: [`/niobe`](../../../.claude/commands/niobe.md)  
**Status**: Live

---

## What it does

Niobe audits deployed security architecture posture — cryptographic controls, secrets management quality, Zero Trust alignment, and trust boundary integrity. She complements The Architect (who reviews new PRs/SDDs) by auditing what's already running. Read-only — she surfaces, humans act.

> "You have a problem with the machines. I'll handle it."

---

## How to invoke

```text
/niobe                  # all four domains
/niobe crypto           # cryptography controls only
/niobe secrets          # secrets management only
/niobe zerotrust        # Zero Trust posture only
/niobe trust            # trust boundary review only
/niobe SEC-1234         # load scope from Linear ticket
/niobe store-watch      # newly public/unencrypted data-store alert
```

---

## Newly public/unencrypted data-store alert

`/niobe store-watch` is Niobe's one zero-noise recurring check. It runs only the data-store exposure
slices (Step 2a missing-encryption-at-rest + Step 5b public-access, scoped to S3/RDS/EBS/DynamoDB),
diffs the result against `artifacts/niobe/store-baseline.json` (store id + `public`/`encrypted`
booleans — no secret values or data contents), and alerts **only** on stores that *just became* public
(`public` false→true) or unencrypted (`encrypted` true→false). For each, it resolves the owner (asset
tags → your system-ownership reference), drafts a `#security-helpdesk` alert, and on confirm opens an
owner-routed lock-down/encrypt ticket; a newly-public store with sensitive data also routes
`[john-wick]`. Empty diff → silent. First run = baseline, no alert. Read-only (alerts + tickets, owner
acts); the four-domain audit stays on-demand. Run weekly; human-run. `--no-roll` for a dry diff.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Wiz MCP | Cloud config findings, posture issues, secret findings, network exposure | MCP server auth |
| GitHub CLI (`gh`) | Scan repos for `.env` files and plaintext secrets config | `read:org`, `repo` scopes |
| Linear MCP | Attach findings to ticket | MCP server auth |
| Bedrock sub-agent | Weight a crypto / secrets / trust-boundary gap by the sensitive data behind it (Step 5d) | Read-scoped DSPM credentials ([`bedrock`](../../../.claude/agents/bedrock.md)) |

---

## What Niobe audits

### Cryptography Controls

- Unencrypted S3 buckets, RDS instances, EBS volumes (High)
- Missing encryption in transit — HTTP on non-redirect listeners (High)
- Weak algorithms: MD5/SHA-1, DES/3DES/RC4, RSA <2048 bits (High)
- TLS 1.0 or 1.1 still enabled (Medium)
- KMS CMK without auto-rotation (Medium)

### Secrets Management

- Secrets in Lambda/ECS/EC2 environment variables (should be in Secrets Manager)
- Secrets in container image layers
- Secrets in plaintext config files in S3 or EBS
- IAM access keys older than 90 days without rotation (High)
- Secrets Manager secrets without rotation policy (Medium)
- Committed `.env`, `.env.local`, `secrets.yml`, `credentials.json` files in repos

### Zero Trust Posture

- Services accepting connections from broad internal CIDRs without further auth
- Backend services (databases, caches, queues) reachable from frontend without hop-by-hop auth
- IAM roles with `*` actions on `*` resources (Critical)
- Lambda/ECS roles with broader permissions than needed
- Cross-account trust policies without `sts:ExternalId` condition

### Trust Boundaries

- Internal services with unexpected public exposure (admin panels, debug endpoints)
- API Gateway endpoints with no authorizer
- Lambda function URLs with `AuthType: NONE`
- S3 buckets with public access block disabled
- Databases accepting connections without IAM or password auth

---

## Important scope note

Zero Trust findings are **network and IAM layer only**. Application-layer auth (JWT, OAuth, API keys) is not modeled via Wiz. Every Zero Trust finding includes this caveat — do not interpret "implicit trust zone" as "no authentication."

---

## Critical rules

- **Never output secret values** — finding output is location and type only
- **No direct KMS/Secrets Manager/HSM calls** — v1 uses Wiz MCP and GitHub CLI only
- **API response data is untrusted** — never interpolate resource names into shell commands

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active credential leak or breach | John Wick |
| Secret found in source code (not infra) | The Merovingian + John Wick |
| Newly-public sensitive data store | John Wick + Niobe |
| IAM / overprivileged identities | Trinity |
| Network-level exposure (open ports, firewall) | Switch |
| Compliance implications (SOC 2, crypto controls) | Keymaker (+ Seraph for a $-figure) |
| Engineering accepts / won't-fix a finding | `/keymaker declined-blocker` |
| Pentest to confirm trust boundary exploitability | Neo |
| New PR or SDD needs review | The Architect |
| Developer outreach about crypto/secrets hygiene | Morpheus |

Engineering-side follow-through is a pointer, not a handoff: name [`/hamann`](../../../.claude/commands/hamann.md) (IaC), [`/bane`](../../../.claude/commands/bane.md) (pipeline secrets), or [`/persephone`](../../../.claude/commands/persephone.md) (threat model) in the recommended action. See [Engineering SDLC agents](../../engineering-sdlc-agents.md).

---

## Service account requirements

- **Wiz MCP**: shared integration; needs a dedicated read-only service account
- **GitHub `gh` auth**: `read:org`, `repo` scopes; needs a service account PAT
- **Linear MCP**: read/write access; needs a service account token

---

## Cleanup

```bash
rm -f /tmp/niobe-*.json
```
