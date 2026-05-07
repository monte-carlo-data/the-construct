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
/neo SEC-1425                    # load target from Linear ticket
/neo status                      # check stack status
/neo findings                    # read current findings
/neo stop                        # shut down the stack
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| PentAGI | Autonomous pentesting engine | API token (1Password: "<your-pentagi-token-item>") |
| Wiz MCP | Cross-check infrastructure findings | MCP server auth |
| Linear MCP | Read ticket scope / file findings | MCP server auth |
| Docker | Run the PentAGI stack locally | Local Docker daemon |

---

## Prerequisites

1. Docker Desktop running
2. `vuln-mgmt-attacker/` directory present in the repo
3. 1Password CLI (`op`) authenticated
4. `ANTHROPIC_API_KEY` in 1Password your-credentials-vault ("<your-anthropic-key-item>")
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

---

## Stack endpoints (when running)

- PentAGI web UI: `https://localhost:8443`
- PentAGI REST API: `https://localhost:8443/api/v1`
- DVWA target: `http://localhost:8080`
- Juice Shop target: `http://localhost:3000`

---

## Secrets (1Password, your-credentials-vault)

| Secret | 1Password Item |
|---|---|
| `ANTHROPIC_API_KEY` | "<your-anthropic-key-item>" |
| `PENTAGI_API_TOKEN` | "<your-pentagi-token-item>" |

---

## Routing

| Situation | Route to |
|---|---|
| Confirmed vuln in production | John Wick (incident response) |
| Exposed internal tool found | Oracle |
| SaaS tool selected for adoption | `/vendor-review` (add your own vendor review skill) |
| Compliance implications | Carlton |

---

## Service account requirements

- **PentAGI API token**: stored in 1Password, not personal — must survive engineer turnover
- **`ANTHROPIC_API_KEY`**: "<your-anthropic-key-item>" in your-credentials-vault, not tied to personal account
- Docker must run locally (no remote runner yet)

---

## Known limitations

- Requires local Docker — cannot run headlessly without a runner
- PentAGI first-time setup requires a browser (web UI token generation)
- ASK_USER=true by default — PentAGI pauses for human confirmation on risky actions

## Model guardrails — Cyber Verification Program

Opus 4.7 ships with built-in guardrails that automatically detect and block requests
flagged as high-risk cybersecurity use. Legitimate red team work (exploit development,
payload crafting, offensive tooling) may trigger these blocks.

If Neo or an agent invocation is blocked by Opus 4.7 guardrails during authorized testing,
the resolution path is Anthropic's **Cyber Verification Program** — a verification process
for security professionals conducting legitimate vulnerability research, penetration testing,
and red team engagements. Apply through Anthropic's enterprise account contact.
