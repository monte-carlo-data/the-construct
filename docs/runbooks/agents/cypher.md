# Cypher — Software Development Security Agent Runbook

**Character**: Cypher from *The Matrix*  
**Domain**: CISSP Domain 8 — Software Development Security  
**Skill**: [`/cypher`](../../../.claude/commands/cypher.md)  
**Status**: Live

---

## What it does

Cypher finds secrets in code, vulnerable dependencies, SDLC gaps, and SAST risk density across the GitHub org. He queries Aikido, Wiz, Socket, and GitHub — then ranks repos by risk and surfaces untracked CVEs. Read-only — he surfaces, humans act.

> "I know what you're thinking, 'cause right now I'm thinking the same thing."

---

## How to invoke

```text
/cypher                 # all four domains
/cypher secrets         # secrets detection only (Aikido + Wiz)
/cypher deps            # dependency risk only (Critical + High CVEs; Socket malware/typosquats)
/cypher sdlc            # SDLC gap audit (branch protection, security workflows, CODEOWNERS)
/cypher sast            # SAST posture (finding density by repo)
/cypher --recent-only   # limit to repos pushed within 90 days
/cypher SEC-1234        # load scope from Linear ticket
/cypher scorecard       # weekly posture scorecard + trend delta
```

---

## Weekly posture scorecard

`/cypher scorecard` turns Cypher's point-in-time report into a **trend**. After a full audit it appends
5 headline metrics — open secrets (C+H), vulnerable deps (C+H), repos without branch protection, SAST
findings (C+H), repos missing a security-scanning workflow — to `.cypher/scorecard.csv`,
computes the delta vs. the previous row (↓ improved / ↑ regressed / → flat), and drafts a "better/worse
than last week" post to `#security-helpdesk` (draft-then-send). All five are aggregate counts Cypher already
computes — **no PII, no repo names in the ledger or the post**. First run captures a baseline and posts
nothing; the CSV (committed each run) is the long-run trend. Any full `/cypher` run also appends a row
(Step 8c); domain-scoped runs don't (partial metrics would corrupt the trend). `--no-append` for a dry
delta. Run weekly; human-run (the audit hits Aikido/Wiz/GitHub interactively).

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Aikido MCP | Secrets, SCA findings, SAST findings | MCP server auth (`<your-aikido-item>`) |
| Socket (`.github/scripts/socket_threat_feed.py`) | Malware / typosquat matches for repos in a Socket-covered org | `SOCKET_API_TOKEN` (`packages:list`) |
| Wiz MCP | Secret findings in cloud infra, SAST supplementary | MCP server auth |
| GitHub CLI (`gh`) | Repo list, branch protection, workflows, CODEOWNERS | `read:org`, `repo` scopes |
| Linear MCP | Dedup against existing vuln tickets, attach report | MCP server auth |
| [Panther](../../../.claude/agents/panther.md) / [Bedrock](../../../.claude/agents/bedrock.md) sub-agents | Was a leaked secret used? What sensitive data does its principal reach? (read-only) | Each sensor's own credentials |

---

## What Cypher audits

### Secrets
- **Aikido**: API keys, tokens, passwords, private keys in code
- **Wiz**: Secrets in Lambda env vars, ECS tasks, container images
- Public repo secrets flagged Critical; private repo secrets flagged High
- Confirmed live secrets are corroborated against Panther (was it used?) and Bedrock (what can it reach?) before severity is final

### Dependency Risk
- Aikido SCA: Critical + High CVEs across the org
- Dedup against existing Linear vuln tickets (avoid duplicate filing)
- Wiz supplementary: CVEs in deployed container infrastructure
- Socket threat feed: malware, AI-detected malware, and typosquats for repos in the org(s) where Socket is installed — Aikido remains the malware source everywhere else. An `INCOMPLETE` Socket result is reported as such, never as "0 malicious packages"

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
| Socket-covered dependency on the Socket threat feed (malware / typosquat) | John Wick |
| Leaked secret in source code | The Merovingian + John Wick |
| Secret found in cloud infra (not code) | The Merovingian or Oracle |
| IAM / overprivileged roles discovered | Trinity |
| Compliance implications | Keymaker (+ Seraph if a $-figure helps) |
| Finding explicitly accepted / won't-fix | `/keymaker declined-blocker` (risk register) |
| Developer outreach needed | Morpheus |
| Pentest to confirm SAST finding exploitability | Neo |
| PR or design doc security review needed | The Architect |
| Fix is engineering work | pointer only (not a `suggested_next`): `/roland` (dependency upgrade), `/dozer` (new-dependency vetting), `/apoc` (SAST/secret fix in-branch), `/bane` (CI/CD hardening) — see [Engineering SDLC agents](../../engineering-sdlc-agents.md) |

---

## Developer guidance

After scanning, Cypher can draft remediation guidance per finding type. All drafts are labeled `⚠️ SUGGESTED GUIDANCE — Review before sending.` Never auto-distributes — routes through Morpheus for any actual outreach.

---

## Service account requirements

- **Aikido MCP**: `<your-aikido-item>` in your credential vault — shared integration
- **Socket**: `SOCKET_API_TOKEN` with `packages:list` (Enterprise); `syft` installed for SBOM generation; `gh` read on the Socket-covered org(s)
- **GitHub `gh` auth**: `read:org`, `repo` scopes; use a dedicated service account PAT for headless runs
- **Wiz MCP**: shared integration; session auth
- **Linear MCP**: read access for dedup

---

## Cleanup

```bash
rm -f /tmp/cypher-*.json /tmp/cypher-*.csv
```
