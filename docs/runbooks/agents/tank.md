# Tank — Vulnerability Investigation & Disposition Runbook

**Character**: Tank from *The Matrix*  
**Domain**: CISSP Domain 6 — Security Assessment & Testing  
**Skill**: [`/tank`](../../../.claude/commands/tank.md)  
**Status**: Live

---

## What it does

Tank investigates a single Aikido or Wiz finding (or a Linear vulnerability ticket), reads the actual source code or cloud context, and makes a disposition decision: **false positive** (suppress + close) or **real vulnerability** (summarize fix path and hand off).

Named after Tank from The Matrix: born free, no implants. "I'm the operator. I load the guns."

---

## How to invoke

```text
/tank SEC-1395                          # Linear ticket ID
/tank https://app.aikido.dev/...        # Aikido finding URL
/tank https://app.wiz.io/issues#...     # Wiz issue URL
/tank "yaml.load finding in common"     # freeform description
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Aikido API | Fetch finding metadata, suppress false positives | `AIKIDO_CLIENT_ID` + `AIKIDO_CLIENT_SECRET` (1Password: "Agent: Aikido" in your-credentials-vault) |
| Wiz MCP | Fetch Wiz issue details, container findings | MCP server auth |
| GitHub API / `gh` | Read source code for SAST/SCA findings | `gh` CLI auth |
| AWS CLI | Check EC2 instance state (cloud_instance findings) | AWS profile |
| Docker | Pull and scan container images (wizcli) | Local Docker daemon |
| `wizcli` | First-party container image scan | Wiz auth |
| Linear MCP | Read ticket, post analysis comment, close/update ticket | MCP server auth |

---

## Disposition paths

### False positive
1. Suppress in Aikido via `PUT /api/public/v1/issues/groups/{group_id}/ignore`
2. Comment on Linear ticket with analysis
3. Close Linear ticket (state: Done)
4. Check for duplicate open tickets with same finding

### EOL finding — not yet EOL
1. Snooze in Aikido until `eol_date - 60 days`
2. Comment with actual EOL date and snooze rationale
3. Leave ticket open

### Real vulnerability
1. Look up system owner in `knowledge/System_Ownership.md`
2. Comment with attack vector, blast radius, fix path, and recommended owner
3. Update ticket priority if severity differs from Aikido's rating
4. Route: SCP/ENG team → assign; GTM/Finance/People/Legal → leave unassigned, GRC must act

### Exception requested
1. Collect: assigned engineer, committed remediation date, reason
2. Apply `Exception` label (ID: `a830c04a-c844-4ab6-83b6-a5090daebad9`)
3. Set state to `Exception Requested` (ID: `822b835e-47c5-4009-98ba-ad099e4f41d4`)
4. Comment with exception details; do not suppress in Aikido

---

## Key technical details

**Aikido credentials** (1Password, your-credentials-vault):
```bash
AIKIDO_CLIENT_ID=$(op item get --vault "your-credentials-vault" "Agent: Aikido" --fields username)
AIKIDO_CLIENT_SECRET=$(op item get --vault "your-credentials-vault" "Agent: Aikido" --fields credential --reveal)
```

**Container image findings**: Tank uses a 3-step verification process:
1. Cross-check Wiz + Aikido finding lists
2. Run `wizcli scan container-image` for first-party confirmation
3. Code reachability analysis — just because a package is present doesn't mean the CVE is exploitable

**SAST findings**: Tank finds the true author by walking git history beyond `git blame` — migration commits are pass-throughs and must not be attributed.

---

## Routing

| Situation | Route to |
|---|---|
| Real vuln confirmed, no known owner | GRC (accept risk or find owner) |
| Confirmed exploitable vuln in production | John Wick |

---

## Service account requirements

- **Aikido API key**: "Agent: Aikido" in your-credentials-vault
- **GitHub `gh` auth**: currently personal; needs service account token with `repo` read scope
- **AWS CLI**: currently personal; needs dedicated read-only role
- **wizcli**: authenticated via Wiz MCP; ensure service account has container scan permissions
