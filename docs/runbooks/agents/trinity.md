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
/trinity SEC-1234     # load scope from Linear ticket
/trinity diff         # weekly access diff — report only what changed
/trinity policy-drift # Okta SSO/MFA policy drift vs known-good baseline
```

---

## Weekly access diff

`/trinity diff [scope]` turns the full audit into a **change-only** signal. Trinity runs the normal
audit (read-only, scope-confirmed), builds a snapshot, compares it to the stored baseline at
`.trinity/baseline.json`, and reports only the **delta**: new privilege-creep, new
privileged grants, new MFA gaps, newly-stale accounts, and resolved items. If nothing changed, it
prints "No access changes since `<date>`" and **posts nothing** — silence = good news. A non-empty
delta drafts a short `#security-helpdesk` post (draft-then-send) and emits findings for the high-signal
changes with the usual routing.

**Privacy:** the baseline stores identities as **salted hashes** (salt in your credential vault as
`<your-trinity-item>`, or the `TRINITY_HMAC_SALT` env var when headless) — no emails, display names, or
secrets in git. Names are re-resolved at runtime from the live audit for the human-facing delta only,
never persisted. The baseline is committed each run, so git history is the access-change audit trail.
Run weekly; interactive or headless (headless needs a private-key-JWT Okta API Services app). A
`--no-roll` flag does a dry diff without advancing the baseline.

---

## Okta SSO/policy drift

Where `diff` watches *who has access*, `/trinity policy-drift` watches *whether the access policy itself
changed*. It reads Okta sign-on + MFA-enrollment policies (and their rules) plus MFA/sign-on **bypass /
excluded groups**, diffs them against a known-good baseline at
`.trinity/okta-policy-baseline.json`, and surfaces drift with **before→after**: MFA
enforcement removed/weakened (Critical), new bypass/exclusion group or network bypass (High), new/edited
sign-on policy (Medium). First run captures the known-good baseline; later runs report drift only. The
baseline advances **only on explicit confirmation that the change was intended** — unexplained drift
keeps re-alerting until a human blesses it. Read-only (never edits a policy). The baseline is policy
config + group names — **no per-user PII**, so plain JSON (no salt, unlike the access-diff baseline).
High/Critical drift emits findings (auth-tampering → `[john-wick]`); any drift that *weakens*
enforcement is corroborated against Panther to see whether the bypass is already being exercised.
Needs `okta.policies.read` on the Okta MCP's app.

---

## Sensor corroboration

Trinity grades entitlements **on paper** (Steps 2–5), then sharpens them with three read-only sensor
sub-agents, each run only against the shortlist of privilege-creep candidates, stale accounts, MFA gaps,
and service accounts — never every identity:

| Sensor | Question it answers | Effect |
|---|---|---|
| [Panther](../../../.claude/agents/panther.md) (5b) | Is this account actually logging in, bypassing MFA, or authenticating from new geos? | A "stale" account with recent logins is escalated, not deprioritized; MFA-bypass on a privileged account bumps severity |
| [Wing](../../../.claude/agents/wing.md) (5c) | What SaaS OAuth grants / non-human identities does it hold, with which scopes? | Broad scopes on a sensitive app are real over-privilege the IdP role didn't show |
| [Bedrock](../../../.claude/agents/bedrock.md) (5d) | How many sensitive records can this principal actually reach? Is it THIRD_PARTY? | Privilege is weighted by data reach — an over-privileged role reaching nothing sensitive is graded lower |

If a sensor is unavailable, the report says so and falls back to the entitlement-only call — never a
silent skip.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Okta MCP | Users, MFA, groups, OAuth apps, policies | Private-key-JWT via `OKTA_CLIENT_ID` / `OKTA_KEY_ID` / `OKTA_PRIVATE_KEY` (headless) or Device Authorization Grant (interactive) |
| GitHub CLI (`gh`) | Org members, collaborators, repos, tokens | `read:org`, `repo` scopes |
| Wiz MCP | AWS IAM identities, entitlements, excessive access | MCP server auth |
| AWS CLI | IAM fallback if Wiz unavailable | Profile with `SecurityAuditAccess` |
| Linear MCP | Attach findings to ticket | MCP server auth |
| Panther / Wing / Bedrock sub-agents | Auth telemetry, SaaS grants, data reach (read-only) | Each sensor's own credentials |

---

## Prerequisites

1. **Okta MCP**: configure your Okta MCP server (an API Services app with private-key-JWT for headless runs, or Device Authorization Grant for interactive use)
   - Required scopes: `okta.users.read okta.groups.read okta.logs.read okta.apps.read` (+ `okta.policies.read` for policy-drift)
2. **GitHub CLI**: `gh auth login` with `read:org` and `repo` scopes
3. **Wiz MCP**: active in session (preferred IAM source)
4. **AWS CLI** (optional fallback): profile with `SecurityAuditAccess` managed policy
5. **Diff mode**: an HMAC salt in your credential vault (`<your-trinity-item>`) or `TRINITY_HMAC_SALT` in the environment

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

Trinity produces a structured Markdown findings report with severity ratings (Critical/High/Medium/Low) and recommended actions, and emits one `findings/<id>.md` per material finding (see [findings/SCHEMA.md](../../../findings/SCHEMA.md); example: [findings/examples/2026-05-29-trinity-okta-mfa-gap-7f3a9c.md](../../../findings/examples/2026-05-29-trinity-okta-mfa-gap-7f3a9c.md)). The report can be attached to a Linear ticket or posted (Executive Summary only) to Slack.

Findings about individuals go to **terminal + Linear only** — never auto-posted to Slack.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active breach or compromised credential | John Wick |
| Stale / over-privileged admin account (may be abused) | John Wick + Morpheus |
| Shadow SaaS OAuth app with customer data | Oracle |
| Compliance implications (SOC 2, ISO 27001) | Keymaker |
| Finding explicitly accepted / won't-fix | `/keymaker declined-blocker` (risk register) |
| Account holder needs MFA enrollment / awareness | Morpheus |
| Employee offboarding gaps | Platform team (Okta admin) + your offboarding access-removal runbook — human team, not a `suggested_next` |

---

## Service account requirements

- **Okta service account**: dedicated API Services app with read-only scopes and private-key-JWT auth; must not be tied to a personal Okta identity. Device Auth (personal browser) is acceptable for interactive runs only.
- **GitHub token**: org-level token with `read:org` + `repo`; use a dedicated service account PAT for headless runs.
- **AWS**: `SecurityAuditAccess` IAM role; use a dedicated read-only role assumption for headless runs.

---

## Cleanup

Trinity writes temp files to `/tmp/trinity-*.csv` and `/tmp/trinity-*.json`. These are deleted at session end automatically. If the session is interrupted, run:
```bash
rm -f /tmp/trinity-*.csv /tmp/trinity-*.json
```
