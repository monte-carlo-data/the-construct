# Switch — Network Security Agent Runbook

**Character**: Switch from *The Matrix*  
**Domain**: CISSP Domain 4 — Communication & Network Security  
**Skill**: [`/switch`](../../../.claude/commands/switch.md)  
**Status**: Live

---

## What it does

Switch audits TLS/certificate health, firewall and security group rules, VPC configurations, and DNS misconfiguration risk. She queries Wiz for network exposure, attack surface, and cloud configuration findings. Read-only — she surfaces, humans act.

> "You're going to pop your eye out."

---

## How to invoke

```text
/switch             # all four domains
/switch tls         # TLS/certificate health only
/switch sg          # security group and firewall review only
/switch vpc         # VPC configuration audit only
/switch dns         # DNS misconfiguration audit only
/switch SEC-1535    # load scope from Linear ticket
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Wiz MCP | All data: attack surface, cloud config, network exposure, resources | MCP server auth |
| Linear MCP | Attach findings to ticket, post summary | MCP server auth |

Switch uses **Wiz exclusively** as its data source. If Wiz MCP is unavailable, Switch cannot run.

---

## What Switch audits

### TLS / Certificate Health
- Expiring certificates (Critical: ≤7 days, High: ≤14 days, Medium: ≤30 days)
- Weak TLS configs (TLS 1.0/1.1 still enabled, self-signed certs)
- HTTP endpoints without HTTPS redirect
- Missing HSTS headers

### Security Groups
- 0.0.0.0/0 ingress on high-risk ports (Critical): SSH (22), RDP (3389), MySQL (3306), PostgreSQL (5432), Redis (6379), MongoDB (27017), Elasticsearch (9200/9300)
- Unrestricted egress (High)
- Orphaned security groups (Low)
- **Load balancer exemption**: ports 443 and 80 on ALB/NLB/CLB are intentionally public — not flagged

### VPC Configuration
- Flow logs disabled (High)
- Permissive NACLs (High)
- Default VPCs in use (Medium)
- VPC peering without route restrictions (Medium)

### DNS
- Dangling CNAME records — subdomain takeover risk (Critical)
- Zone transfer enabled publicly (High)
- Missing CAA records on public domains (Medium)
- Publicly exposed internal DNS zones (Medium)

---

## Output

Structured Markdown report with severity ratings and recommended actions. Goes to terminal + Linear. **Slack gets Executive Summary only** — never resource ARNs, internal IPs, port ranges, CIDR blocks, VPC IDs, security group names, or DNS zone details.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active network intrusion or lateral movement | John Wick |
| Exposed secrets or credentials in cloud resources | Cypher |
| IAM / overprivileged roles with network access | Trinity |
| Data exposure through network path | The Merovingian |
| Compliance implications (PCI, SOC 2, HIPAA) | Keymaker |
| Pentest to confirm open port exploitability | Neo |
| Security architecture review of VPC design | Niobe |

---

## Service account requirements

- **Wiz MCP**: shared integration; currently session auth — needs dedicated service account
- **Linear MCP**: read/write access; currently personal — needs service account token
