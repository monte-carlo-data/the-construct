# Cypher — Software Development Security Agent Runbook

**Character**: Cypher from *The Matrix*  
**Domain**: CISSP Domain 8 — Software Development Security  
**Skill**: [`/cypher`](../../../.claude/commands/cypher.md)  
**Status**: Live

---

## What it does

Cypher finds secrets in code, vulnerable dependencies, SDLC gaps, and SAST risk density across the GitHub org. He queries Aikido, Wiz, and GitHub — then ranks repos by risk and surfaces untracked CVEs. Read-only — he surfaces, humans act.

> "I know what you're thinking, 'cause right now I'm thinking the same thing."

---

## How to invoke

```text
/cypher                 # all four domains
/cypher secrets         # secrets detection only (Aikido + Wiz)
/cypher deps            # dependency risk only (Critical + High CVEs)
/cypher sdlc            # SDLC gap audit (branch protection, security workflows, CODEOWNERS)
/cypher sast            # SAST posture (finding density by repo)
/cypher --recent-only   # limit to repos pushed within 90 days
/cypher SEC-1234        # load scope from Linear ticket
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Aikido MCP | Secrets, SCA findings, SAST findings | MCP server auth (Agent: Aikido) |
| Wiz MCP | Secret findings in cloud infra, SAST supplementary | MCP server auth |
| GitHub CLI (`gh`) | Repo list, branch protection, workflows, CODEOWNERS | `read:org`, `repo` scopes |
| Linear MCP | Dedup against existing vuln tickets, attach report | MCP server auth |

---

## What Cypher audits

### Secrets
- **Aikido**: API keys, tokens, passwords, private keys in code
- **Wiz**: Secrets in Lambda env vars, ECS tasks, container images
- Public repo secrets flagged Critical; private repo secrets flagged High

### Dependency Risk
- Aikido SCA: Critical + High CVEs across the org
- Dedup against existing Linear vuln tickets (avoid duplicate filing)
- Wiz supplementary: CVEs in deployed container infrastructure

### Secure SDLC Gaps
- Branch protection (required reviews, status checks)
- Security scanning workflows (Aikido, Snyk, CodeQL, Semgrep, Trivy, Gitleaks)
- SECURITY.md presence
- CODEOWNERS presence
- Default to repos pushed within 90 days (use `--recent-only` to enforce)

### SAST Posture
- Injection, XSS, SQLi, path traversal, deserialization, SSRF, insecure crypto findings
- Risk score = `(critical × 10) + (high × 3) + (medium × 1)`
- Top 10 highest-risk repos by score

---

## Critical rule: never output secret values

Secret finding output is limited to: repo, file path, line number, secret type, severity. The actual secret value **must never appear** in any output, log, or report.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Active credential leak or confirmed exfiltration | John Wick |
| Secret found in cloud infra (not code) | The Merovingian or Oracle |
| IAM / overprivileged roles discovered | Trinity |
| Compliance implications | Keymaker |
| Developer outreach needed | Morpheus |
| Pentest to confirm SAST finding exploitability | Neo |
| PR security review needed | The Architect |

---

## Developer guidance

After scanning, Cypher can draft remediation guidance per finding type. All drafts are labeled `⚠️ SUGGESTED GUIDANCE — Review before sending.` Never auto-distributes — routes through Morpheus for any actual outreach.

---

## Service account requirements

- **Aikido MCP**: "<your-aikido-item>" in your-credentials-vault — already shared
- **GitHub `gh` auth**: `read:org`, `repo` scopes; currently personal — needs service account PAT
- **Wiz MCP**: shared integration; currently session auth
- **Linear MCP**: read access for dedup; currently personal

---

## Cleanup

```bash
rm -f /tmp/cypher-*.json /tmp/cypher-*.csv
```
