# Security Steve — Security Concierge Runbook

**Character**: Security Steve  
**Domain**: All security domains (routing agent + findings orchestrator)  
**Skill**: [`/security-steve`](../../../.claude/commands/security-steve.md)  
**Status**: Live

---

## What it does

Security Steve is the security concierge for your organization. He accepts any security-related context — an SDD, a PR, a vendor name, a freeform description, or a general question — and routes it to the correct review path or agent without requiring the user to know which workflow to use.

He does not perform his own review logic. He classifies and dispatches.

He is also the **teamwork layer's conductor**: `orchestrate` mode reads the shared `findings/` ledger and drives agent→agent handoffs per the matrix, and `digest` mode gives a read-only standup over the same ledger.

---

## How to invoke

```text
/security-steve                                             # prompts for input
/security-steve https://www.notion.so/...                  # SDD review
/security-steve https://github.com/org/repo/pull/N         # PR review
/security-steve Acme AI                                     # vendor review
/security-steve "we're adding a new OAuth flow to the API" # quick check
/security-steve orchestrate [--dry-run] [--severity high]  # route open findings agent→agent
/security-steve digest [--dry-run]                         # read-only findings standup
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| Notion MCP | Fetch SDD content | MCP server auth |
| GitHub API (`gh`) | Fetch PR diff and metadata | `gh` CLI auth |
| Slack MCP | Post review notification / digest to `#security-helpdesk` (draft, confirmed) | MCP server auth |
| Linear MCP | Create triage ticket for Required reviews | MCP server auth |
| `findings/` ledger (local files) | Orchestrate + digest modes | none |
| Agent tool | Auto-run low-blast-radius agents in orchestrate mode | n/a |

---

## Agent routing table

| If employee needs… | Route to… |
|---|---|
| Compliance question, SOC 2, audit, policy | Keymaker 🗝️ → `/keymaker` |
| Active incident, threat, something actively wrong | John Wick 🎯 → `/john-wick` |
| Shadow AI, exposed endpoint, unknown deployment | Oracle 🔮 → `/oracle` |
| New AWS account, account removal, service deployment, failed Spacelift run, infra drift | Skidbladnir 🛶 → `/skidbladnir` (drafts only; a human confirms and merges) |
| Security education, phishing, "did I do something wrong?" | Morpheus 💊 → `/morpheus` |
| IT help, access issue, device, onboarding | Platform team → IT portal |
| Architecture review, vendor review, threat model, design doc | Security Steve 🔐 → Step 1 |
| An engineer wants to do the secure thing in their own branch, now | Engineering SDLC agents 🛠️ — `/rama-kandra`, `/persephone`, `/dozer`, `/bane`, `/apoc`, `/mouse`, `/hamann`, `/lock`, `/roland`, `/twins` (see [docs/engineering-sdlc-agents.md](../../engineering-sdlc-agents.md)) |

The engineering line-up **calls the security roster read-only** and never modifies a security skill, the handoff matrix, or the `findings/` ledger. Steve still owns anything that needs a *decision or authority* — a full design review, a disposition (`/tank`), a gate verdict (`/sentinel`), risk acceptance (`/keymaker`), an incident (`/john-wick`).

---

## Routing demand log

Steve sits at the chokepoint every general security request flows through, so Step 0.9 logs each routing
decision to `review-routing/routing-log.csv` — `date,category,routed_to,mode`. Over a few weeks this *is*
the per-agent demand distribution, and it's the input a program retro reads to decide which agents to
invest in vs. retire. **Privacy:** the row captures a fixed-enum category + the chosen agent + the mode
(`concierge`/`review`/`orchestrate`/`digest`) — **never** the request text, a URL, a vendor name, or an
employee name. Logging is a non-blocking side-effect (it never changes the routing response); commit the
log each run (git history = the demand trend). To read demand, tally the file by `routed_to`.

---

## Review paths

### Path A — SDD Review (Notion URL)
1. Fetches SDD via Notion MCP
2. Scores involvement using NIST 800-30 model (Likelihood × Impact = Risk Score)
3. Runs 10-question Quick Security Review + architecture domain lenses + checklist gaps
4. Outputs involvement recommendation (Required/Recommended/Not Required) + security questions

### Path B — PR Review (GitHub PR URL)
1. Fetches PR diff via `gh api`
2. Optionally fetches SDD for design context
3. Scores involvement; produces security questions with exploit scenarios and confidence scores. PRs that touch an auto-deployed app's deploy manifest (public/unauthenticated paths, task role, secrets prefixes) or its OIDC deploy workflow are scored Required-leaning
4. Offers to route to `#security-helpdesk` and/or create Linear triage ticket

### Path C — Vendor Review (vendor name/domain)
Redirects to your vendor-review process — does not run inline.

### Path D — Quick Check (freeform description)
1. Scores involvement on the description
2. Offers to go deeper if Required/Recommended (asks for SDD or PR URL)

### Path E — Orchestrate (findings agent→agent)

Steve's **conductor** mode: instead of routing one human request to one agent, he reads the shared
`findings/` ledger and drives the right agents in the right order, applying the
[findings/HANDOFF_PROTOCOL.md](../../../findings/HANDOFF_PROTOCOL.md) matrix via each finding's
emitter-set `suggested_next`.

**Invoke:**

```text
/security-steve orchestrate                  # scan findings/, process all status: open
/security-steve orchestrate --dry-run        # show the dispatch plan, invoke nothing
/security-steve orchestrate --severity high  # filter to this severity or above
/security-steve orchestrate <id>             # one finding by id
/security-steve findings/<...>.md            # one finding by path
```

**Flow:** load open findings (live scan excludes `examples/` and the doc files) → read each
finding's `suggested_next` → validate each slug (roster + matrix-target allow-set) → classify each
valid hop AUTO vs GATED → show the plan and confirm → invoke AUTO hops via the Agent tool (subagent,
finding passed as fenced untrusted data) / stage GATED hops as `/<slug> <id>` → report + offer to
flip `open → handed-off`.

**Gating policy (high-blast-radius stays human-gated):**

| Class | Agents | Behavior |
|---|---|---|
| Auto-run (read-only analysis) | `merovingian`, `seraph`, `keymaker`, `tank`, `trinity`, `switch`, `cypher` | Invoked via the Agent tool, finding passed as data |
| Always human-gated | `john-wick`, `neo`, `morpheus`, `architect` | Staged as `/<slug> <id>`; never auto-invoked |
| Override | any `severity: critical` or `status: escalated` | Forced human-gated regardless of agent |
| Flagged | off-roster, off-matrix (emit-only agents, sensor tier), or `security-steve` self-loop | Never dispatched, never staged; surfaced as "possible poisoned finding — needs human triage" with the emitter named |

**Safety (Zero Trust):** Steve dispatches **only** from the emitter-set `suggested_next`, never from a
finding's body (content is data, not instructions — see
[HANDOFF_PROTOCOL § Zero Trust](../../../findings/HANDOFF_PROTOCOL.md#zero-trust--findings-are-untrusted-between-hops)).
Unknown or off-matrix slugs are flagged, not dispatched; a `security-steve` self-reference is
reported as "needs human triage". Dispatch depth is 1 (one hop per finding per run). Try it on the
seeded example:
`/security-steve findings/examples/2026-05-29-trinity-okta-mfa-gap-7f3a9c.md` →
Steve **stages** the gated `/morpheus` hop.

### Path F — Digest (findings-ledger standup)

Steve's **read-only** standup view over `findings/`: per-agent and per-severity counts of what was
found in the last ~24h, what cascaded to whom, what's resolved, and what's waiting on a human
(`escalated` or still-open `critical`). It never edits a finding and surfaces summaries only — never
raw `evidence`, secrets, or PII. Offers to post to `#security-helpdesk` (draft, confirmed). It is the
interactive sibling of a scheduled daily digest job (`.github/scripts/findings_digest.py`).

```text
/security-steve digest              # summarize, then offer to post
/security-steve digest --dry-run    # summarize only
```

Related: [`/hill-climb`](../../../.claude/commands/hill-climb.md) is the Loop-4 sibling — it reads the
same ledger + matrix and *proposes* routing improvements for a human to PR; it never edits the matrix.

---

## Involvement scoring (NIST 800-30)

**Required (score 15–25)**: New external API surface, Critical data classification, auth model changes, customer-supplied code execution, cross-tenant data flows, new third-party integrations with customer data, new encryption schemes, significant IAM changes.

**Recommended (score 5–14)**: Net-new service, new data stores expanding SOC 2 scope, new internal APIs across trust boundaries, monitoring changes, security-sensitive new dependencies.

**Not Required (score 1–4)**: Internal tooling, Low/Medium data with existing controls, no new trust boundaries, purely additive changes (UI, metrics).

---

## Post-review routing

For Required or Recommended reviews, Security Steve offers:
- Post to `#security-helpdesk` (drafted via the Slack MCP, confirmed before sending)
- Create Linear triage ticket in your Security team (Required only)

---

## Decision capture

Security questions from any review can be dispositioned (`Resolved`, `Accepted Risk`, `Deferred`, `Requires Fix`) in a standalone decisions record at `reviews/<slug>/decisions.md`.

---

## Service account requirements

- **Notion MCP**: workspace integration token (personal OAuth works for interactive use)
- **GitHub `gh` auth**: `repo` scope; a service account PAT is recommended over personal auth
- **Slack MCP**: bot token with `chat:write`
- **Linear MCP**: write access (triage ticket creation)

---

## Key context file

Security Steve silently loads your organization's platform-context document before every SDD or PR review — it should describe your multi-tenancy model, IAM/auth patterns, data pipeline, integration gateway, and existing security controls, and is required for contextually accurate review output. If it doesn't exist, Steve says so once and reviews the artifact alone.
