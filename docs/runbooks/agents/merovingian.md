# The Merovingian — Asset Security & Data Classification Agent Runbook

**Character**: The Merovingian from *The Matrix Reloaded/Revolutions*  
**Domain**: CISSP Domain 2 — Asset Security  
**Skill**: [`/merovingian`](../../../.claude/commands/merovingian.md)  
**Status**: Live

---

## What it does

The Merovingian maps what sensitive data exists, where it lives, who touches it, and whether it's classified correctly. He audits Wiz data findings, Aikido, AWS S3, GitHub public repos, and Notion — surfacing classification gaps, privacy exposures, and orphaned data stores before they become incidents.

Read-only — he surfaces, humans act.

> "There is only one constant, one universal — causality. Action, reaction. Cause and effect."

---

## How to invoke

```text
/merovingian            # all sources: Wiz + Aikido + S3 + GitHub + Notion
/merovingian wiz        # Wiz data findings only
/merovingian aikido     # Aikido secrets/data leak scan only
/merovingian s3         # AWS S3 bucket inventory only
/merovingian github     # GitHub public repo scan only
/merovingian notion     # Notion sensitive doc scan only
/merovingian --stale-days=90    # override 180-day stale threshold
/merovingian SEC-1533   # load scope from Linear ticket
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Wiz MCP | Data findings, datastore inventory, classification labels | MCP server auth |
| Aikido MCP | Secrets in code, hardcoded credentials, data leaks | MCP server auth (Agent: Aikido) |
| AWS CLI | S3 bucket inventory, public access, encryption, tags | Profile with `SecurityAuditAccess` |
| GitHub CLI (`gh`) | Public repo scan, security policy and CODEOWNERS | `read:org`, `repo` scopes |
| Notion MCP | Sensitive-keyword page search, sharing status | MCP server auth |
| Linear MCP | Attach findings to ticket, post summary | MCP server auth |

---

## What The Merovingian audits

### Wiz
- Sensitive data findings by classification label
- Datastores with no classification or public exposure
- Scan freshness (flags if >7 days stale)

### Aikido
- Secrets/credentials in source code
- Hardcoded database passwords and API keys
- Data leaks (PII patterns in code or config)

### AWS S3
- Public access block status (all four flags)
- Default encryption enabled
- Owner/team/service/project tags
- Stale buckets (no owner + old creation date)

### GitHub (public repos)
- SECURITY.md presence
- CODEOWNERS presence
- Sensitive keywords in recent commit messages (indicators only — not confirmed exposures)

### Notion
- Pages matching sensitive keywords (PII, customer data, SSN, password, API key, credentials, etc.)
- Public sharing enabled on sensitive pages
- Stale or unowned pages with sensitive content

### Data lifecycle (multi-source)
- Orphaned assets (no owner tag + not referenced in code + not in Notion)
- Stale data stores exceeding the threshold
- Sensitive + unowned asset combinations (highest risk)

---

## Output

The Merovingian produces a structured Markdown report covering all sources, severity ratings, and recommended actions. Report goes to terminal + Linear. Slack gets Executive Summary only (never full findings with data store names or Notion page titles).

---

## Important rules

- **Report locations, never data** — output describes WHERE sensitive data lives, never the raw data itself
- **No secret values ever** — finding output is limited to repo, file path, and type (not the value)
- **Partial audits labeled** — if a source fails, section says "INCOMPLETE — [reason]"
- **Cleanup**: temp files at `/tmp/merovingian-*` are removed at session end

---

## Routing

| Situation | Route to |
|---|---|
| Active data breach or confirmed exfiltration | John Wick |
| Shadow SaaS or unauthorized integration | Oracle |
| Compliance implications (SOC 2, GDPR, CCPA) | Carlton |
| Secrets found in code → rotate immediately | Repo owner + Platform team |
| IAM / access control issues | Trinity |
| Vendor handling sensitive data | `/vendor-review` |

---

## Service account requirements

- **AWS CLI**: `SecurityAuditAccess` IAM policy; currently personal — needs dedicated read-only role
- **GitHub `gh` auth**: `read:org`, `repo` scopes; currently personal — needs service account PAT
- **Wiz MCP**: shared integration; currently session auth
- **Aikido MCP**: "Agent: Aikido" in your-credentials-vault — already shared
- **Notion MCP**: needs integration token; currently personal

---

## Cleanup

```bash
rm -f /tmp/merovingian-*.json /tmp/merovingian-*.csv
```
