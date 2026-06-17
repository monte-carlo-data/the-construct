# The Construct

> *"The Construct is our loading program. We can load anything."*

The Construct is Monte Carlo's AI-powered security agent roster — a team of Claude-powered specialists, each one owning a specific security domain. Every agent is a Claude Code skill: drop it in your repo, configure your MCP servers, and it runs.

They're named after characters from *The Matrix*.

---

## The Matrix

| Agent | What it does | Security Domain | Invoke |
|---|---|---|---|
| **Neo** | Red team — autonomous penetration tests via PentAGI | CISSP Domain 6: Security Assessment & Testing | `/neo` |
| **Trinity** | Identity & access — audits Okta, GitHub, and AWS IAM for over-privileged accounts and stale access | CISSP Domain 5: Identity & Access Management | `/trinity` |
| **Oracle** | Shadow IT & exposure — monitors for unapproved AI tools, exposed endpoints, and cloud misconfiguration | CISSP Domain 7 / Domain 4 (partial) | `/oracle` |
| **Morpheus** | Security awareness — drafts just-in-time Slack outreach when risky behavior is detected | CISSP Domain 1: Security & Risk Management | `/morpheus` |
| **Seraph** | Cyber risk quantification — translates a risk, ticket, or finding into dollar-denominated loss exposure (FAIR + Monte Carlo) | CISSP Domain 1: Security & Risk Management | `/seraph` |
| **Tank** | Vulnerability triage & management — investigates Aikido and Wiz findings, routes to remediation | CISSP Domain 6: Security Assessment & Testing | `/tank` |
| **The Architect** | Security code review — PR security reviews | CISSP Domain 3: Security Architecture & Engineering | `/architect` |
| **The Merovingian** | Asset security & data classification — data inventory, classification, privacy exposure | CISSP Domain 2: Asset Security | `/merovingian` |
| **Cypher** | Software development security — secrets detection, dependency risk, SAST findings | CISSP Domain 8: Software Development Security | `/cypher` |
| **Switch** | Network security — TLS/certificate health, firewall rules, VPC review | CISSP Domain 4: Communication & Network Security | `/switch` |
| **Niobe** | Security architecture — cryptography controls, Zero Trust posture, secrets management | CISSP Domain 3: Security Architecture & Engineering | `/niobe` |
| **The Keymaker** | Compliance & risk register — keeper of the register; reviews open GRC risk tickets and records declined blockers / accepted risks handed off by the roster | CISSP Domain 1: Security & Risk Management | `/keymaker` |

### Supporting Characters

| Agent | What it does | Invoke |
|---|---|---|
| **John Wick** | Incident response — investigates active breaches, suspicious logins, credential leaks | `/john-wick` |
| **Security Steve** | Concierge — routes any security question or request to the right agent | `/security-steve` |

---

## How to Use

All agents run inside **[Claude Code](https://claude.ai/code)**. Drop the skill files into your repo's `.claude/commands/` directory and invoke with a slash command:

```bash
/security-steve        # not sure where to start? start here
/neo target.example.com
/trinity
/tank
```

Not sure which agent to use? Start with `/security-steve` — it routes you.

---

## How agents work together

The agents aren't 14 solo operators — they're a team. The coordination layer is a **shared findings
store** under [`findings/`](findings/): any agent emits a finding (a markdown file with YAML
frontmatter), and any agent can read it. Each finding declares its own next hop in a
`suggested_next` field — a list of agent slugs that should act next — so a leaked-secret finding
from Cypher routes itself to Merovingian (blast-radius) and John Wick (containment) without a human
wiring it up.

- **[`findings/SCHEMA.md`](findings/SCHEMA.md)** — the finding contract: the fields, the controlled
  vocabularies, and how it aligns (conceptually) with the [A2A protocol](https://a2a-protocol.org).
- **[`findings/HANDOFF_PROTOCOL.md`](findings/HANDOFF_PROTOCOL.md)** — the handoff matrix: which
  agent acts next on each finding-type, the deterministic logic for picking `suggested_next`, and
  the **Zero Trust** rules that treat every finding as untrusted input between hops.

**Security Steve executes the cascade.** `/security-steve orchestrate` reads a finding's
`suggested_next` and dispatches the next agent — auto-running low-blast-radius analysis agents and
**staging consequential ones** (`john-wick`, `neo`, `morpheus`, `architect`, and anything
`critical`/`escalated`) for human approval. `/security-steve digest` gives a read-only standup
summary of the ledger.

---

## What's in this repo

```
.claude/commands/      # Claude Code skill files — one per agent
docs/runbooks/agents/  # Runbooks: systems accessed, prerequisites, workflows
docs/LEARNINGS.md      # Patterns that emerged building the roster (keeper-of-the-register, handoffs, naming)
findings/              # Shared findings store + the schema and handoff matrix (the teamwork layer)
```

Each agent has two files:
- **Skill** (`.claude/commands/<agent>.md`) — the Claude Code workflow that runs
- **Runbook** (`docs/runbooks/agents/<agent>.md`) — systems, prerequisites, scope rules, known limitations

---

## Prerequisites

Agents are built on Claude Code and use MCP servers to connect to security tools. The agents in this roster use some combination of:

| Tool | Agents |
|---|---|
| [Wiz MCP](https://docs.wiz.io) | Trinity, Oracle, Tank, Merovingian, Cypher, Switch, Niobe, John Wick |
| [Okta MCP](https://developer.okta.com/docs/api/) | Trinity, John Wick |
| [Aikido MCP](https://aikido.dev) | Oracle, Tank, Cypher, John Wick |
| [Linear MCP](https://linear.app/developers) | Neo, Trinity, Tank, Architect, Morpheus, Keymaker |
| [Slack MCP](https://api.slack.com/mcp) | Oracle, Morpheus, John Wick, Security Steve |
| [Notion MCP](https://developers.notion.com) | Oracle, Merovingian, Architect, Security Steve |
| GitHub CLI (`gh`) | Architect, Cypher, Keymaker |
| Docker (local) | Neo (PentAGI stack) |

See each agent's runbook for its specific requirements.

---

## Adapting for Your Organization

These skills were built for Monte Carlo's environment. To use them:

1. Replace MCP tool references with your own MCP server configurations
2. Update credential references (1Password vault names, AWS profile names) to match your setup
3. Update Slack channel references to your security team's channel
4. Review scope rules in each runbook — especially for Neo (red team) and John Wick (incident response)

---

## The Story

Built by Monte Carlo's security team. The idea: every CISSP domain should have an agent that can autonomously investigate and report. They run in Claude Code, they use the same MCP integrations the security team uses day-to-day, and they [hand off to each other](findings/HANDOFF_PROTOCOL.md) when a finding crosses domains.

See also: [Secure Design Practicum](https://github.com/monte-carlo-data/secure-design-practicum) — our toolkit for security architecture reviews.

---

## License

Apache 2.0. See [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md) for our vulnerability disclosure policy.
