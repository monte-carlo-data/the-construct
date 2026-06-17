# Trinity — Identity & Access Security Agent Runbook

**Character**: Trinity from *The Matrix*  
**Domain**: CISSP Domain 5 — Identity & Access Management  
**Skill**: [`/trinity`](../../../.claude/commands/trinity.md)  
**Status**: Live

---

## What it does

Trinity audits who has access to what across Okta, GitHub org, and AWS IAM. She surfaces privilege creep, MFA gaps, overprivileged accounts, stale access, and cross-system access accumulation. Read-only — she surfaces findings, humans act.

---

## How to invoke

```text
/trinity              # full audit: Okta + GitHub + AWS IAM
/trinity okta         # Okta only
/trinity github       # GitHub org only
/trinity iam          # AWS IAM only
/trinity --stale-days=60   # override 90-day stale threshold
/trinity SEC-1504     # load scope from Linear ticket
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Okta MCP | Users, MFA, groups, OAuth apps | Device Authorization Grant (browser login on first use) |
| GitHub CLI (`gh`) | Org members, collaborators, repos, tokens | `read:org`, `repo` scopes |
| Wiz MCP | AWS IAM identities, entitlements, excessive access | MCP server auth |
| AWS CLI | IAM fallback if Wiz unavailable | Profile with `SecurityAuditAccess` |
| Linear MCP | Attach findings to ticket | MCP server auth |

---

## Prerequisites

1. **Okta MCP**: run `.setup/mcp-okta.sh` — requires browser auth on first use
   - Required scopes: `okta.users.read okta.groups.read okta.logs.read okta.apps.read`
2. **GitHub CLI**: `gh auth login` with `read:org` and `repo` scopes
3. **Wiz MCP**: active in session (preferred IAM source)
4. **AWS CLI** (optional fallback): profile with `SecurityAuditAccess` managed policy

---

## What Trinity audits

### Okta
- Stale active users (no login > threshold)
- MFA enrollment gaps (no factor enrolled — Critical)
- Phishing-susceptible MFA only (TOTP/SMS/push with no FIDO2/passkey — High)
- Phishing-resistant MFA coverage percentage (org-wide metric)
- Privileged group membership
- Unreviewed OAuth app grants

### GitHub Org
- Outside collaborators with elevated access
- Stale org members
- Elevated OAuth tokens and PATs
- Public repos with no owner/security policy
- Missing CODEOWNERS files

### AWS IAM (via Wiz preferred)
- Stale IAM users with console access
- Old access keys (>90 days)
- Wildcard IAM policies (Action `*` or Resource `*`)
- Cross-account trust relationships

### Cross-system
- Privilege creep: accounts with elevated access in 2+ systems
- Stale accounts with broad access across systems

---

## Output

Trinity produces a structured Markdown findings report with severity ratings (Critical/High/Medium/Low) and recommended actions. Can be attached to a Linear ticket or posted (Executive Summary only) to Slack.

Findings about individuals go to **terminal + Linear only** — never auto-posted to Slack.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active breach or compromised credential | John Wick |
| Shadow SaaS OAuth app with customer data | Oracle |
| Compliance implications (SOC 2, ISO 27001) | Keymaker |
| Employee offboarding gaps | Platform team + `runbooks/okta-offboarding-access-removal.md` |

---

## Service account requirements

- **Okta service account**: dedicated API service account with read-only scopes; must not be tied to a personal Okta identity. Currently uses Device Auth (personal browser). Needs migration to service account API token.
- **GitHub token**: org-level token with `read:org` + `repo`; currently uses personal `gh` auth. Needs dedicated service account PAT.
- **AWS**: `SecurityAuditAccess` IAM role; currently personal. Needs dedicated read-only role assumption.

---

## Cleanup

Trinity writes temp files to `/tmp/trinity-*.csv` and `/tmp/trinity-*.json`. These are deleted at session end automatically. If the session is interrupted, run:
```bash
rm -f /tmp/trinity-*.csv /tmp/trinity-*.json
```
