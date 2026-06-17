# Morpheus — Security Awareness & Training Agent Runbook

**Character**: Morpheus from *The Matrix*  
**Domain**: CISSP Domain 1 — Security & Risk Management  
**Skill**: [`/morpheus`](../../../.claude/commands/morpheus.md)  
**Status**: Live

---

## What it does

Morpheus drafts just-in-time security awareness outreach to employees for risky behaviors: shadow AI adoption, phishing simulation failures, sensitive data exposure, new AI deployments without review, access red flags, and public sharing of internal content.

**Morpheus never auto-sends.** Every message goes to Slack Drafts. The engineer reviews and sends it.

He is empowering, never accusatory — informs, never enforces.

---

## How to invoke

```text
/morpheus shadow-ai @employee       # unreviewed AI tool adoption
/morpheus phishing @employee        # phishing sim failure
/morpheus data-exposure @employee   # sensitive data in wrong place
/morpheus ai-deployment @employee   # new AI repo without security review
/morpheus access-flag @employee     # unusual access pattern
/morpheus public-share @employee    # internal content shared publicly
/morpheus escalate @employee        # follow-up on unacknowledged outreach
/morpheus train #channel topic      # team-level awareness post
/morpheus SEC-1234                  # load scenario from Linear ticket
/morpheus                           # show scenario menu
```

Target can be: `@name`, `@email`, a Slack display name, or `#channel` for team posts.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Slack MCP | Look up user profiles, queue message drafts | MCP server auth |
| Linear MCP | Read ticket context, add comments | MCP server auth |

---

## Message structure (all scenarios)

Every Morpheus message follows this 5-part structure:

1. **WHAT HAPPENED** — specific, factual, non-judgmental
2. **WHY IT MATTERS** — security risk in plain language
3. **WHAT TO DO NEXT** — clear, actionable steps
4. **RELEVANT LINKS** — 1–3 Notion policy links
5. **ESCALATION PATH** — "If we don't hear back within 3 business days, we'll follow up directly."

---

## Scenarios

| Keyword | Trigger |
|---|---|
| `shadow-ai` | Oracle detects employee using unreviewed AI tool |
| `phishing` | Employee clicked simulated phishing link |
| `data-exposure` | DLP or Wiz detects PII/customer data in wrong place |
| `ai-deployment` | Oracle detects new repo with LLM integration, no security review |
| `access-flag` | Unusual access pattern or request |
| `public-share` | Internal Notion doc or Drive file set to public |
| `escalate` | Prior outreach unacknowledged after 3 business days |
| `train` | Team-level awareness post to a channel |

---

## Hard rules

- **Never auto-send** — always use Slack Drafts
- **Always confirm target** before drafting (resolve Slack profile, show to engineer)
- **No disciplinary language** — if asked to draft a warning/HR message, refuse and offer a neutral awareness message instead
- **No PII or account details in Slack** — DM only; never channel posts with named individuals

---

## Notion policy links to include

| Resource | URL |
|---|---|
| Approved AI Vendor List | <your-approved-ai-vendors-notion-url> |
| Security Review Process | (confirm URL — stored in Notion) |
| Data Classification Policy | (confirm URL — open question) |
| Phishing Response Guide | (confirm URL — open question) |

---

## Routing

> **This table is a slice of the [handoff matrix](../../../findings/HANDOFF_PROTOCOL.md).** That matrix is the authoritative, machine-readable cascade; this list is the quick reference for this agent. When a rule changes, change it there first. Emit handoffs as `suggested_next` slugs per [findings/SCHEMA.md](../../../findings/SCHEMA.md).

| Situation | Route to |
|---|---|
| Confirmed active compromise | John Wick immediately — do not send awareness outreach |
| Compliance policy questions from employee | Keymaker |
| IT/access/device issues | Platform team |
| Disciplinary or HR-scope request | Refuse; route to manager or People team |
| No response after 3 business days | `/morpheus escalate @employee` |
| Architectural risk from shadow AI | Security Steve (after outreach) |

---

## Service account requirements

- **Slack MCP**: needs bot token with `users:read`, `chat:write` (drafts) scopes; currently personal OAuth
- **Linear MCP**: read access; currently personal

No credentials stored in 1Password specific to Morpheus — depends on shared MCP auth.
