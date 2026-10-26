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
/merovingian --snowflake-account=<id>   # scope the Step 7h field-instance leak check
/merovingian SEC-1234   # load scope from Linear ticket
```

**Consult mode.** When dispatched by the Concierge (e.g. a `Posture consult for Panther alert <id>.`
from the Analyst) or asked about one named resource, the Merovingian skips the scope prompt and the
five-source audit and answers only the named resource's question within a bounded time budget,
returning partial coverage rather than a killed run.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Wiz MCP | Data findings, datastore inventory, classification labels | MCP server auth |
| Aikido MCP | Secrets in code, hardcoded credentials, data leaks | MCP server auth |
| AWS CLI | S3 bucket inventory, public access, encryption, tags | Profile with `SecurityAuditAccess` |
| GitHub CLI (`gh`) | Public repo scan, security policy and CODEOWNERS | `read:org`, `repo` scopes |
| Notion MCP | Sensitive-keyword page search, sharing status | MCP server auth |
| Panther (via [`panther`](../../../.claude/agents/panther.md) sensor) | Real data-access logs for the lifecycle/sensitive shortlist — Step 7e | MCP server auth (read-only) |
| Wing (via [`wing`](../../../.claude/agents/wing.md) sensor) | SaaS-app classification, compliance tags, OAuth scopes — Step 7f | MCP server auth (read-only) |
| Bedrock MCP (via [`bedrock`](../../../.claude/agents/bedrock.md) sensor) | DSPM classification — `impactSeverity`, sensitive-record counts, `dataTypeSets`, principal reach, incl. Snowflake | MCP server auth (read-only) |
| Data-observability lineage MCP (e.g. Monte Carlo) | Asset lineage — upstream tracing for the Step 7h prod-data-path check | MCP server auth |
| Linear MCP | Attach findings to ticket, open owner-routed remediation tickets | MCP server auth |

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
- Coverage honesty: the integration only sees pages shared with it, so negatives are phrased "none found in the visible set"

### Panther access logs (Step 7e)
- Who/what actually touched a store in the last 30–90 days, for the stale / decommissioned / sensitive-and-unowned shortlist
- A "stale" store with live reads is **not dormant** — the deletion recommendation is dropped and ownership is escalated instead

### Wing SaaS posture (Step 7f)
- Which discovered SaaS apps carry a sensitive `classification` or regulated `compliances` tag
- Which OAuth connections (and scopes) reach them — where org data flows into SaaS

### Bedrock DSPM (Step 7g)
- What data is actually behind a store: `impactSeverity`, `numSensitiveRecords`, `dataTypeSets`
- Which principals reach it (flags `THIRD_PARTY` / over-broad roles)
- Covers the warehouse layer (Snowflake, DynamoDB) that Wiz/S3 alone don't classify

### Snowflake field-instance leak detection (Step 7h)
A **field / demo Snowflake instance** lets field engineers hold elevated perms — fine for synthetic
data, **not fine once customer data lands there**. Two baselines:

- **A — classification (Bedrock)**: sensitive data classified in a field/dev instance
- **B — lineage (your data-observability platform's lineage MCP)**: a field table tracing **upstream to a prod/customer source**

Either is a finding; **both together is Critical**. Routes `[trinity]` to review the elevated perms —
**drafted, human-confirmed** (Merovingian never drops a permission).

> **Lineage comes from the lineage MCP, not Bedrock.** Bedrock has no lineage API — its schema has no
> `lineage`/`upstream`/`provenance` field. A data-observability platform (e.g. Monte Carlo) supplies it.
>
> ⚠️ **Coverage**: organizations typically run many more Snowflake accounts (one SSO app each — count
> them in Okta) than Bedrock has onboarded. The skill enumerates both sets and diffs them, checks
> `lastScanTime`, and reports a clean 7h result as **INCOMPLETE, not an all-clear**, listing which
> accounts were not onboarded or stale (> 30 days).

### Data lifecycle (multi-source)
- Orphaned assets (no owner tag + not referenced in code + not in Notion)
- Stale data stores exceeding the threshold
- Sensitive + unowned asset combinations (highest risk)
- **Decommissioned-but-data-holding** — a store last active > 180d whose owning service
  appears gone (no compute ref + no code ref + no owner); Medium, "review for deletion/archival —
  confirm no retention obligation first." Stale+ownerless reports as one lifecycle finding, not three.
  All lifecycle findings route through Step 8b (owner → ticket: document/delete or assign-owner).

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

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active data breach or confirmed exfiltration | John Wick |
| Newly-public sensitive data store | John Wick + Niobe |
| Shadow SaaS or unauthorized integration | Oracle |
| Compliance implications (SOC 2, GDPR, CCPA) | Keymaker |
| Secrets found in code → rotate immediately | Repo owner + Platform team |
| IAM / access control issues | Trinity |
| Customer/sensitive data in a field or dev Snowflake instance (Step 7h) | Trinity — review elevated perms (drafted, human-confirmed) |
| Vendor handling sensitive data | your vendor-review process |

### Owner-routed remediation tickets (Step 8b)

The Merovingian no longer ends at an orphan report — Step 8b resolves each actionable finding's owning
team (asset tags from the S3 step, else your resource-owner lookup: system-ownership record → AWS tags
→ Slack / Notion / GitHub fallback), groups findings by owner, and opens **one Linear ticket per owning
team** with a clear ask: **classify** (unclassified sensitive store), **lock down** (public/unencrypted),
or **document/delete** (orphaned/stale); sensitive-and-unowned gets *assign-an-owner + classify*. True
orphans with no resolvable owner go to a single Security "unowned store" ticket — never dropped. It
dedups against existing open tickets for the same asset+gap so repeated runs converge, confirms the
planned tickets before creating them (read-only posture — it files tickets, never touches the data),
and prints a per-owner routing summary. Same owner-routing pattern Oracle uses.

---

## Service account requirements

- **AWS CLI**: `SecurityAuditAccess` IAM policy; a dedicated read-only role is recommended over personal credentials
- **GitHub `gh` auth**: `read:org`, `repo` scopes; a service account PAT is recommended over personal auth
- **Wiz MCP**: shared integration; session auth
- **Aikido MCP**: `<your-aikido-item>` in `$YOUR_CREDENTIAL_VAULT` (see [knowledge/config.md](../../../knowledge/config.md))
- **Notion MCP**: workspace integration token (remember it only sees pages shared with it)
- **Lineage MCP**: read-only API key for your data-observability platform
- **Sensor sub-agents**: read-scoped Panther / Wing / Bedrock credentials, per each agent's own runbook

---

## Cleanup

```bash
rm -f /tmp/merovingian-*.json /tmp/merovingian-*.csv
```
