# Oracle — AI Exposure & Shadow IT Monitor Runbook

**Character**: The Oracle from *The Matrix*  
**Domain**: CISSP Domain 7 (Security Operations, partial) / Domain 4 (Network Security, partial)  
**Skill**: [`/oracle`](../../../.claude/commands/oracle.md)  
**Status**: Live

---

## What it does

Oracle monitors your organization's external attack surface and internal AI deployment activity. She scans for exposed subdomains, shadow AI tools in GitHub and Slack, cloud misconfigurations, and unauthorized integrations. She runs daily in scheduled mode and on-demand.

Oracle feeds the rest of the agent roster — surfacing Critical findings for John Wick, compliance findings for Keymaker, and shadow IT findings for Morpheus.

---

## How to invoke

```text
/oracle               # full scan, on-demand (interactive)
/oracle               # in scheduled mode: runs silently, auto-proceeds
```

Scheduled mode is triggered via your security bot's cron or `/loop 24h /oracle`.

A **consult** (a question about one named entity, typically dispatched by the Concierge on behalf of the Analyst) answers only that question with targeted lookups — no full scan, no org sweep, no sensor sub-agent re-dispatch — inside a ~10-minute budget. A consult that falls through to a full scan blows the headless run guard and returns nothing; a partial answer with an explicit `not covered:` line is always better than a killed run.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| SecurityTrails API | Subdomain enumeration | `SECURITYTRAILS_API_KEY` |
| Shodan API | Exposed service scanning | `SHODAN_API_KEY` |
| Censys API | Exposed service scanning | `CENSYS_API_ID` + `CENSYS_API_SECRET` |
| Aikido MCP | Cloud misconfigs, exposed secrets | MCP server auth (read-scoped) |
| GitHub API | AI signal detection in repos and Actions | `GITHUB_TOKEN` (`read:org`, `repo`) |
| GitHub App (org-owned) | Read the two approved-inventory lists from their Git source of truth | `GITHUB_APP_ID` + `GITHUB_APP_INSTALLATION_ID` + private key in your credential vault; `contents:read` only, via `.github/scripts/github_app_fetch.py` |
| Slack MCP | Shadow AI signals in channels | MCP server auth |
| Linear MCP | Create/update findings tickets | MCP server auth |
| Panther / Wing / Bedrock sub-agents | Confirm live traffic, SaaS authorization, and sensitive data behind an exposure | Read-scoped sensor credentials ([`panther`](../../../.claude/agents/panther.md), [`wing`](../../../.claude/agents/wing.md), [`bedrock`](../../../.claude/agents/bedrock.md)) |

There is no Notion dependency: the approved-inventory lists are plain markdown tables in Git, and a hosted Notion MCP cannot run headless.

---

## Prerequisites

All API keys must be available in the environment. Missing keys degrade scan coverage but do not abort the run — gaps are noted in the digest.

| Secret | Where to get |
|---|---|
| `SECURITYTRAILS_API_KEY` | SecurityTrails account (shared item in your credential vault) |
| `SHODAN_API_KEY` | Shodan account (shared item in your credential vault) |
| `CENSYS_API_ID` + `CENSYS_API_SECRET` | Censys account (shared item in your credential vault) |
| `GITHUB_TOKEN` | GitHub org PAT, `read:org` + `repo` scopes |
| GitHub App credentials | Org-owned App installed on your security repo with `contents:read`; App id, installation id, and private key in your credential vault |

---

## Scan modules

| Module | What it does |
|---|---|
| 2a — SecurityTrails | Enumerates subdomains for your apex domains (e.g. `example.com`) |
| 2b — Shodan/Censys | Passive exposure scanning of your org's IP ranges and domains |
| 2c — Aikido | Cloud misconfigs, public S3 buckets, exposed secrets |
| 3a — GitHub org | AI library signals in repos and Actions workflows |
| 3b — Slack | AI adoption signals in your AI, engineering-wide, product, and hackathon channels |
| 4 — Cross-reference | Approves assets against Centralized Internal Apps and the Approved Vendor List (both read from Git via the GitHub App) |
| 4b–4d — Sensors | Panther (is the endpoint actually hit?), Wing (is the SaaS/AI app authorized, who connected it?), Bedrock (is real sensitive data behind it?) |

---

## Scheduled vs. on-demand behavior

| Action | Scheduled | On-demand |
|---|---|---|
| All scan modules | Auto | Auto |
| Create Critical Linear tickets | Auto | Confirm first |
| Queue High tickets | Queue only | Confirm first |
| Post daily digest to `#security-helpdesk` | Auto | Ask user |
| Draft Slack outreach (Medium) | No — deferred to next on-demand session | Via Morpheus |

---

## Inventory

Oracle maintains `artifacts/oracle-inventory.csv` — a running record of all findings across scans. Before creating any ticket, Oracle checks for duplicates in this file and Linear.

CSV columns: `scan_date, source, asset_type, asset_url_or_id, owner_name, owner_email, severity, status, linear_ticket, notes`

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Severity / shape | Route |
|---|---|
| Critical — exposed PII / customer data / credentials, sensitive data live | John Wick (incident response) |
| High / Medium — a *person* shipped it | Morpheus (outreach draft) |
| High / Medium — infra, no clear person | Owner-routed Linear ticket (+ Security Steve for architectural triage) |
| Compliance-relevant (PII, regulated data) | add Keymaker |
| Low | Log in digest only |

### Act on classification (Step 6b)

Oracle does not end at a labeled list — Step 6b turns each finding's person-vs-infra classification
into a **concrete routed artifact**: a finding a *person* shipped becomes a drafted Morpheus outreach to
that owner (mapped to the right scenario — `shadow-ai` / `ai-deployment` / `public-share` —
`source=oracle`, logged to Morpheus's outreach ledger, never auto-sent); an *infra* exposure becomes
an owner-routed Linear ticket (`[security-steve]` for architectural triage); a *critical* live exposure
is flagged for John Wick with no outreach. On-demand confirms the routing first; scheduled runs create
tickets but defer the interactive Morpheus drafts to the next on-demand session. The digest reports
drafts-queued / tickets-routed / IR-flagged counts.

---

## Scheduling

```yaml
# your security bot cron config
schedules:
  - name: oracle-daily
    cron: "0 17 * * 1-5"   # 9 AM PT, Mon–Fri
    command: /oracle
    mode: scheduled
    notify_channel: "<your-slack-channel-id>"
```

A queue-backed headless runtime can also host Oracle as a Concierge consult target; in that mode the
read-only posture is enforced by read-scoped credentials and a mutation-free MCP config, not by prose.

---

## Service account requirements

- **GitHub token**: org-level PAT with `read:org` + `repo`; must be a service account token, not personal
- **GitHub App**: org-owned, `contents:read` on your security repo only — no PAT, no user identity; token minted hourly at call time
- **SecurityTrails/Shodan/Censys**: API keys stored in your credential vault; not personal accounts
- **Slack MCP**: needs bot token with search scope
- **Aikido MCP**: needs a read-scoped API key (shared `<your-aikido-item>` in your credential vault)
- **Sensor sub-agents**: read-scoped Panther / Wing / Bedrock credentials
