# Oracle — AI Exposure & Shadow IT Monitor Runbook

**Character**: The Oracle from *The Matrix*  
**Domain**: CISSP Domain 7 (Security Operations, partial) / Domain 4 (Network Security, partial)  
**Skill**: [`/oracle`](../../../.claude/commands/oracle.md)  
**Status**: Live

---

## What it does

Oracle monitors Monte Carlo's external attack surface and internal AI deployment activity. She scans for exposed subdomains, shadow AI tools in GitHub and Slack, cloud misconfigurations, and unauthorized integrations. She runs daily in scheduled mode and on-demand.

Oracle feeds the rest of the agent roster — surfacing Critical findings for John Wick, compliance findings for Carlton, and shadow IT findings for Morpheus.

---

## How to invoke

```text
/oracle               # full scan, on-demand (interactive)
/oracle               # in scheduled mode: runs silently, auto-proceeds
```

Scheduled mode is triggered via the MC Security Bot cron or `/loop 24h /oracle`.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| SecurityTrails API | Subdomain enumeration | `SECURITYTRAILS_API_KEY` |
| Shodan API | Exposed service scanning | `SHODAN_API_KEY` |
| Censys API | Exposed service scanning | `CENSYS_API_ID` + `CENSYS_API_SECRET` |
| Aikido MCP | Cloud misconfigs, exposed secrets | MCP server auth |
| GitHub API | AI signal detection in repos and Actions | `GITHUB_TOKEN` (`read:org`, `repo`) |
| Slack MCP | Shadow AI signals in channels | MCP server auth |
| Notion MCP | Cross-reference approved app inventory | MCP server auth |
| Linear MCP | Create/update findings tickets | MCP server auth |

---

## Prerequisites

All API keys must be available in the environment. Missing keys degrade scan coverage but do not abort the run — gaps are noted in the digest.

| Secret | Where to get |
|---|---|
| `SECURITYTRAILS_API_KEY` | SecurityTrails account (shared your-credentials-vault) |
| `SHODAN_API_KEY` | Shodan account (shared your-credentials-vault) |
| `CENSYS_API_ID` + `CENSYS_API_SECRET` | Censys account (shared your-credentials-vault) |
| `GITHUB_TOKEN` | GitHub org PAT, `read:org` + `repo` scopes |

---

## Scan modules

| Module | What it does |
|---|---|
| 2a — SecurityTrails | Enumerates subdomains for `<your-domain>`, `<your-secondary-domain>`, `<your-other-domain>` |
| 2b — Shodan/Censys | Passive exposure scanning of MC IP ranges and domains |
| 2c — Aikido | Cloud misconfigs, public S3 buckets, exposed secrets |
| 3a — GitHub org | AI library signals in repos and Actions workflows |
| 3b — Slack | AI adoption signals in channels like `#all-in-on-ai`, `#eng-all` |
| 4 — Cross-reference | Approves assets against Centralized Internal Apps and Approved Vendor List |

---

## Scheduled vs. on-demand behavior

| Action | Scheduled | On-demand |
|---|---|---|
| All scan modules | Auto | Auto |
| Create Critical Linear tickets | Auto | Confirm first |
| Queue High tickets | Queue only | Confirm first |
| Post daily digest to `<your-security-channel>` | Auto | Ask user |
| Draft Slack outreach (Medium) | No — via shadow-it outreach workflow | Via shadow-it outreach workflow |

---

## Inventory

Oracle maintains `artifacts/oracle-inventory.csv` — a running record of all findings across scans. Before creating any ticket, Oracle checks for duplicates in this file and Linear.

CSV columns: `scan_date, source, asset_type, asset_url_or_id, owner_name, owner_email, severity, status, linear_ticket, notes`

---

## Routing

| Severity | Route |
|---|---|
| Critical | John Wick (incident response) |
| High | Linear ticket + Security Steve (architectural review) |
| Medium | Linear ticket + shadow-it outreach workflow for outreach |
| Low | Log in digest only |

---

## Scheduling

```yaml
# MC Security Bot cron config
schedules:
  - name: oracle-daily
    cron: "0 17 * * 1-5"   # 9 AM PT, Mon–Fri
    command: /oracle
    mode: scheduled
    notify_channel: "<your-slack-channel-id>"
```

---

## Service account requirements

- **GitHub token**: org-level PAT with `read:org` + `repo`; must be a service account token, not personal
- **SecurityTrails/Shodan/Censys**: API keys stored in your-credentials-vault; not personal accounts
- **Slack MCP**: needs bot token with search scope (currently personal OAuth)
- **Notion MCP**: needs integration token (currently personal)
- **Aikido MCP**: needs API key (shared "<your-aikido-item>" in your-credentials-vault)
