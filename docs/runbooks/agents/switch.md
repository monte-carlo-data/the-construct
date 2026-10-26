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
/switch SEC-1234    # load scope from Linear ticket
/switch cert-watch  # weekly cert-expiry early-warning (TLS only)
/switch perimeter   # DNS + cert-transparency monitoring via SecurityTrails
```

---

## Weekly cert-expiry early-warning

`/switch cert-watch` is Switch's one high-signal recurring job: it runs **only** the TLS/cert check
(Step 2), keeps certs expiring within **30 days** (≤14 High, ≤7 Critical per the existing ladder), and
drafts a `#security-helpdesk` early-warning listing each soonest-first with its owning resource + days left.
If nothing's in-window it stays silent. Critical (≤7-day) certs also emit a finding for the owner. The
broad four-domain audit stays available on-demand. Read-only — Switch warns, the owner renews. Run
weekly; human-run (Wiz MCP auth). Slack carries resource-name-level detail only, not raw IPs/ARNs.

---

## DNS + certificate-transparency monitoring

`/switch perimeter` adds the **external** view Wiz can't provide. Via the SecurityTrails org credential
it monitors, per configured domain, **CT-log certificate issuances** (flagging certs issued by an
unexpected CA / for an unexpected CN — possible impersonation, High) and **DNS records + DNSSEC status**
(flagging new/changed NS/MX/CNAME as High, TXT/other as Medium, and newly-disabled DNSSEC as High). It
diffs against `artifacts/switch/perimeter-baseline.json` (expected issuers/CNs/records/DNSSEC) so
only **unexpected** items alert — expected certs/records are baselined out. First run baselines; the
baseline advances only on confirmation. Unexpected items emit findings (possible impersonation →
`[john-wick]`) and a `#security-helpdesk` summary. Complements (doesn't replace) Step 5's Wiz in-cloud DNS
findings; pairs with `cert-watch` to make Switch a perimeter watcher. Read-only; human-run weekly.

**Agentic-risk controls.** Perimeter mode introduces external content + a Critical credential into an
agent that also has Slack/Linear write tools. A prose rule cannot enforce an egress boundary against
the exact prompt-injection class it targets, so the controls are structural: (1) **the skill has no
`WebFetch` tool at all** — SecurityTrails is fetched only through `.github/scripts/securitytrails_fetch.py`
(run via `Bash`), which by construction contacts only the SecurityTrails API host (hardcoded constant,
validated domain arg, no caller-supplied URL). The agent literally cannot make an arbitrary outbound
request — an *enforced* boundary, not an instruction. (2) **CT/DNS JSON is untrusted input** — compared
against the baseline, never acted on, never chooses the next tool/recipient. (3) The **SecurityTrails API
key** (your credential vault, `<your-securitytrails-item>`) is read at call time by the script and never
appears in a prompt, URL, log, finding, or post. Baseline roll-forward is a human-made git commit
(branch-first; the skill never auto-commits the baseline), so the durable control is human-in-the-loop +
PR review.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Wiz MCP | All data: attack surface, cloud config, network exposure, resources | MCP server auth |
| Linear MCP | Attach findings to ticket, post summary | MCP server auth |
| SecurityTrails | `perimeter` mode only — CT-log certs + DNS/DNSSEC (external view) | Org API key in your credential vault, via the deterministic `securitytrails_fetch.py` script (no agent WebFetch). If the key is not provisioned, perimeter runs report INCOMPLETE; the key-free CT view is `.github/scripts/domain_surface_discover.py` (crt.sh, host-pinned) |
| Panther sub-agent | Corroborate whether an exposed surface is actually receiving traffic (Step 5c) | Read-scoped SIEM credentials ([`panther`](../../../.claude/agents/panther.md)) |

Switch uses **Wiz** as its primary data source for the four core domains (TLS/SG/VPC/DNS); if Wiz MCP is
unavailable those cannot run. The `perimeter` mode additionally uses **SecurityTrails** for the
external CT-log + DNS view.

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
| Exposed secrets or credentials in cloud resources | The Merovingian + Oracle |
| Data exposure through network path | The Merovingian |
| Newly-public sensitive store reachable over the network | John Wick + Niobe |
| IAM / overprivileged roles with network access | Trinity |
| Compliance implications (PCI, SOC 2, HIPAA) | Keymaker (+ Seraph for a $-figure) |
| Engineering accepts / won't-fix a finding | `/keymaker declined-blocker` |
| Pentest to confirm open port exploitability | Neo |
| Security architecture review of VPC design | Niobe |

Engineering-side follow-through is a pointer, not a handoff: name [`/hamann`](../../../.claude/commands/hamann.md) (IaC review pre-merge) or [`/bane`](../../../.claude/commands/bane.md) (CI pipeline) in the recommended action. See [Engineering SDLC agents](../../engineering-sdlc-agents.md).

---

## Service account requirements

- **Wiz MCP**: shared integration; needs a dedicated read-only service account
- **Linear MCP**: read/write access; needs a service account token
- **SecurityTrails**: org API key in your credential vault, read at call time by the fetch script only
