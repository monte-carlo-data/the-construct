# Security Steve — Security Concierge Runbook

**Character**: Security Steve  
**Domain**: All security domains (routing agent)  
**Skill**: [`/security-steve`](../../../.claude/commands/security-steve.md)  
**Status**: Live

---

## What it does

Security Steve is the security concierge for Monte Carlo. He accepts any security-related context — an SDD, a PR, a vendor name, a freeform description, or a general question — and routes it to the correct review path or agent without requiring the user to know which workflow to use.

He does not perform his own review logic. He classifies and dispatches.

---

## How to invoke

```text
/security-steve                                             # prompts for input
/security-steve https://www.notion.so/...                  # SDD review
/security-steve https://github.com/org/repo/pull/N         # PR review
/security-steve Acme AI                                     # vendor review
/security-steve "we're adding a new OAuth flow to the API" # quick check
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Notion MCP | Fetch SDD content | MCP server auth |
| GitHub API (`gh`) | Fetch PR diff and metadata | `gh` CLI auth |
| Slack MCP | Post review notification to `<your-security-channel>` | MCP server auth |
| Linear MCP | Create triage ticket for Required reviews | MCP server auth |

---

## Agent routing table

| If employee needs… | Route to… |
|---|---|
| Compliance question, SOC 2, audit, policy | Keymaker 🕺 → `/keymaker` |
| Active incident, threat, something actively wrong | John Wick 🎯 → `/john-wick` |
| Shadow AI, exposed endpoint, unknown deployment | Oracle 🔮 → `/oracle` |
| Security education, phishing, "did I do something wrong?" | Morpheus 💊 → `/morpheus` |
| IT help, access issue, device, onboarding | Platform team → IT portal |
| Architecture review, vendor review, threat model, design doc | Security Steve 🔐 → Step 1 |

---

## Review paths

### Path A — SDD Review (Notion URL)
1. Fetches SDD via Notion MCP
2. Scores involvement using NIST 800-30 model (Likelihood × Impact = Risk Score)
3. Runs 10-question Quick Security Review + architecture domain lenses + checklist gaps
4. Outputs involvement recommendation (Required/Recommended/Not Required) + security questions

### Path B — PR Review (GitHub PR URL)
1. Fetches PR diff via `gh api`
2. Optionally fetches SDD for design context
3. Scores involvement; produces security questions with exploit scenarios and confidence scores
4. Offers to route to `<your-security-channel>` and/or create Linear triage ticket

### Path C — Vendor Review (vendor name/domain)
Redirects to `/vendor-review` (add your own vendor review skill) — does not run inline.

### Path D — Quick Check (freeform description)
1. Scores involvement on the description
2. Offers to go deeper if Required/Recommended (asks for SDD or PR URL)

---

## Involvement scoring (NIST 800-30)

**Required (score 15–25)**: New external API surface, Critical data classification, auth model changes, customer-supplied code execution, cross-tenant data flows, new third-party integrations with customer data, new encryption schemes, significant IAM changes.

**Recommended (score 5–14)**: Net-new service, new data stores expanding SOC 2 scope, new internal APIs across trust boundaries, monitoring changes, security-sensitive new dependencies.

**Not Required (score 1–4)**: Internal tooling, Low/Medium data with existing controls, no new trust boundaries, purely additive changes (UI, metrics).

---

## Post-review routing

For Required or Recommended reviews, Security Steve offers:
- Post to `<your-security-channel>` (channel `<your-slack-channel-id>`)
- Create Linear triage ticket (Required only)

---

## Decision capture

Security questions from any review can be dispositioned using `/decision <slug>`. Saved to `review-software/reviews/<slug>/decisions.md`.

---

## Service account requirements

- **Notion MCP**: integration token; currently personal — needs workspace integration token
- **GitHub `gh` auth**: `repo` scope; currently personal — needs service account PAT
- **Slack MCP**: bot token with `chat:write`; currently personal OAuth
- **Linear MCP**: write access (triage ticket creation); currently personal

---

## Key context file

Security Steve loads `review-software/guides/platform_context.md` silently before every SDD or PR review — this describes MC's architecture (AccountContext, IGW, JWT patterns, Kinesis, etc.) and is required for contextually accurate review output.
