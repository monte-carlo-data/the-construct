# Neo — Red Team Agent Runbook

**Character**: Neo from *The Matrix*  
**Domain**: CISSP Domain 6 — Security Assessment & Testing  
**Skill**: [`/neo`](../../../.claude/commands/neo.md)  
**Status**: Live

---

## What it does

Neo runs autonomous penetration tests against authorized targets using PentAGI — a self-hosted, Claude-powered pentesting engine with 20+ tools (nmap, metasploit, sqlmap, nikto, ffuf, etc.). Give it a domain or IP and it spins up the Docker stack, submits the task to PentAGI, monitors findings, triages results, and reports what's real.

Neo is not a coordinator — he is the hacker.

---

## How to invoke

```text
/neo target.example.com          # external target
/neo dvwa                        # internal test target (DVWA container)
/neo SEC-1234                    # load target from Linear ticket
/neo validate <ticket-id>        # proof-or-kill one hypothesis via the nuclei harness
/neo status                      # check stack status
/neo findings                    # read current findings
/neo stop                        # shut down the stack
/neo recurring                   # run the authorized standing target + auto-file findings
```

---

## Recurring pentest + auto-file

`/neo recurring` turns Neo from on-demand into a standing control. It loads the explicitly-authorized
target(s) from `review-pentest/recurring-targets.md` (a target lives there only if it's a sanctioned
**non-production** test env with documented authorization — the registry is an allowlist, not an
auto-proceed), **re-confirms scope**, runs the assessment, and on completion **auto-files** via
WORKFLOW F: for each **confirmed** finding, dedup against existing open Neo tickets, resolve the owning
team via your resource-ownership lookup, and open one routed Linear ticket. Needs-manual-verification and
false-positive findings are **deferred, not filed**. Monthly cadence (documented; a scheduled runner can
call `/neo recurring` later). Safety unchanged: per-run scope confirmation, never-target-production,
`ASK_USER=true`, and confirmed-only filing all still apply.

---

## Hypothesis validation harness (WORKFLOW G)

`/neo validate <ticket-id | R-id>` runs one hand-written nuclei template per unvalidated hypothesis
through an RoE-guarded runner (`vuln-mgmt-attacker/nuclei/run.sh`), then records validated/killed on
the ticket and updates `coverage.md`. Hypotheses that aren't request-provable are routed to the owning
lane (config review via the `aws` sub-agent, or log correlation via `panther`/`aws`) instead of being
forced into a template. Default target is a disposable test instance; production requires explicit
in-conversation authorization plus a deconfliction notice, and the runner enforces
`--prod-ok --deconflicted` on top. Request counts are never escalated to force a match.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| PentAGI | Autonomous pentesting engine | API token (your credential vault: `<your-pentagi-token-item>`) |
| Wiz MCP | Cross-check infrastructure findings | MCP server auth |
| Linear MCP | Read ticket scope / file findings | MCP server auth |
| Docker | Run the PentAGI stack locally | Local Docker daemon |

---

## Prerequisites

1. Docker Desktop running
2. `vuln-mgmt-attacker/` directory present in the repo
3. Credential vault CLI (e.g. `op`) authenticated
4. `ANTHROPIC_API_KEY` in your credential vault (`<your-anthropic-key-item>`)
5. PentAGI API token stored via `./secrets.sh set-token <token>`

**First-time setup:**
```bash
cd vuln-mgmt-attacker
./secrets.sh check              # verify credentials are reachable
./secrets.sh run docker compose up -d pentagi pgvector scraper searxng
# Then open https://localhost:8443, generate an API token, and store it:
./secrets.sh set-token <your-token>
```

---

## Scope rules (non-negotiable)

- Neo prints the target and asks for **explicit yes** before launching — no exceptions
- Never target production environments
- Never target shared infrastructure
- All findings are unconfirmed until reviewed by a human
- No Linear tickets or Slack posts without explicit confirmation

---

## Key workflows

| Workflow | What it does |
|---|---|
| A — Spin up stack | Starts PentAGI + pgvector + scraper + SearXNG via Docker Compose |
| B — Launch assessment | Submits pentest task to PentAGI REST API, monitors progress |
| C — Read findings | Fetches and triages findings from completed flow |
| D — Stop stack | Shuts down containers; findings preserved in volumes |
| E — Evaluate new tool | Scores a candidate pentest tool against 7 criteria |
| F — Auto-file | Turns confirmed findings into deduped, owner-routed Linear tickets (recurring runs) |
| G — Validate hypothesis | Proof-or-kill one hypothesis via the RoE-guarded nuclei harness |

---

## Stack endpoints (when running)

- PentAGI web UI: `https://localhost:8443`
- PentAGI REST API: `https://localhost:8443/api/v1`
- DVWA target: `http://localhost:8080`
- Juice Shop target: `http://localhost:3000`

---

## Secrets (your credential vault)

| Secret | Vault Item |
|---|---|
| `ANTHROPIC_API_KEY` | `<your-anthropic-key-item>` |
| `PENTAGI_API_TOKEN` | `<your-pentagi-token-item>` |

See [knowledge/config.md](../../../knowledge/config.md) for the item-name mapping.

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Confirmed vuln in production | John Wick (incident response) |
| Exposed internal tool found | Oracle |
| SaaS tool selected for adoption | Your vendor-review process |
| Compliance implications | Keymaker |

---

## Service account requirements

- **PentAGI API token**: stored in your credential vault, not personal — must survive engineer turnover
- **`ANTHROPIC_API_KEY`**: `<your-anthropic-key-item>` in your credential vault, not tied to personal account
- Docker must run locally (no remote runner yet)

---

## Known limitations

- Requires local Docker — cannot run headlessly without a runner
- PentAGI first-time setup requires a browser (web UI token generation)
- ASK_USER=true by default — PentAGI pauses for human confirmation on risky actions

## Model guardrails — Cyber Verification Program

Current Claude models ship with built-in guardrails that automatically detect and block requests
flagged as high-risk cybersecurity use. Legitimate red team work (exploit development, payload
crafting, offensive tooling) may trigger these blocks.

If Neo or an agent invocation is blocked by those guardrails during authorized testing, the
resolution path is Anthropic's **Cyber Verification Program** — a verification process for security
professionals conducting legitimate vulnerability research, penetration testing, and red team
engagements. Apply through Anthropic's enterprise account contact.
