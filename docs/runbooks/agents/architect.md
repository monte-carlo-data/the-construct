# The Architect — Security Code Review Agent Runbook

**Character**: The Architect from *The Matrix*  
**Domain**: CISSP Domain 3 — Security Architecture & Engineering (partial)  
**Skill**: [`/architect`](../../../.claude/commands/architect.md)  
**Status**: Live

---

## What it does

The Architect guides security reviews of GitHub pull requests using your PR-review workflow (a GitHub Action that runs the review script). It helps gather required inputs, triggers the review workflow, explains outputs, and walks through findings.

The Architect reviews new PRs and code changes. Niobe audits what's already running.

> "You are here because Zion is about to be destroyed."

---

## How to invoke

```text
/architect https://github.com/org/repo/pull/42      # PR URL
/architect                                           # prompts for PR URL
```

### Auto-runs on security-relevant PRs (optional)

You can wire the Architect review to fire automatically — no invocation needed — when a PR touches a
security-relevant path. Scope the path allowlist in the `pull_request:` trigger of your PR-review
workflow: CI/scripts under `.github/`, shared code, dependency manifests, `.claude/commands`, or any
path matching `auth`/`secret`/`iam`/`oauth`/`credential`/`token`. The PR URL is derived from the event,
so no `pr-review-config.yml` is required. Findings post as a PR comment; **Required** involvement also
opens a Security Triage ticket and posts to `#security-helpdesk`. Docs/spec-only PRs (outside the
allowlist) do not trigger a review.

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| GitHub Actions | Run the PR-review workflow | `github.token` or `SOURCE_REPO_TOKEN` |
| GitHub API | Fetch PR diff and metadata | `gh` CLI auth |
| Notion MCP | Optional design-doc context for the review | `NOTION_TOKEN` secret |
| Slack webhook | Optional notifications to `#security-helpdesk` | `SDD_SLACK_WEBHOOK_URL` secret |
| Linear MCP | Create triage ticket for Required reviews | `LINEAR_API_KEY` secret |

---

## Trigger options

### Manual (workflow_dispatch)
Go to **Actions > PR Security Review > Run workflow** in your security repo.

### Config file
Add `.github/pr-review-config.yml` to the PR branch:
```yaml
pr_review_url: "https://github.com/org/repo/pull/N"
skip_notifications: false
```

### Reusable workflow (caller pattern)
```yaml
jobs:
  pr-review:
    uses: <your-org>/<your-security-repo>/.github/workflows/pr-review-reusable.yml@main
    with:
      pr-review-url: "https://github.com/org/repo/pull/N"
    secrets:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
      SDD_SLACK_WEBHOOK_URL: ${{ secrets.SDD_SLACK_WEBHOOK_URL }}
      LINEAR_API_KEY: ${{ secrets.LINEAR_API_KEY }}
```

---

## Required secrets (in the repo running the workflow)

| Secret | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Claude API for review |
| `NOTION_TOKEN` | Only if design-doc URL provided | Fetch design context |
| `SDD_SLACK_WEBHOOK_URL` | Optional | Slack notifications |
| `LINEAR_API_KEY` | Optional | Create Linear triage ticket |

Configure at: **Settings > Secrets and variables > Actions**

---

## Review output interpretation

| Recommendation | Meaning | Action |
|---|---|---|
| **Required** | Security team must be consulted before merge | Open a Security ticket, then consult before merging |
| **Recommended** | Security team should review but not blocking | Consider async review in `#security-helpdesk` |
| **Not Required** | No security team involvement needed | Proceed — address questions in code review |

Questions with <70% confidence are suppressed from the PR comment. Full list is in `pr_review_output.json`.

Never treat a label, tag, or Security approval on the PR as the merge unblock — Security does not sign off; the reviewing team owns the merge decision with the findings in hand. The Linear ticket is the intake path for any verdict above `Not Required`.

### Deploy-surface awareness (optional)

If some of your repos auto-deploy to a cloud account on push, make the reviewer deploy-aware: boost
deploy manifests, `.github/workflows/**`, and auth code into the diff budget and score these deltas as
**Required**-leaning — adding/loosening a public (SSO-bypassing, internet-reachable) route, changing the
task role / IAM, adding secrets prefixes or integrations, or editing the OIDC deploy workflow. The
privileged control-plane repo is the highest blast radius.

### Unified design + code review

Design review and code review are one pipeline. When your design-review workflow reviews a design doc,
it writes a carry-forward artifact `reviews/<slug>/design-findings.md` — the **code-verifiable** design
findings (auth checks, secrets handling, input validation, etc.), keyed by the design-doc URL. When the
Architect later reviews the implementing PR with that URL, it loads those findings (Step 2.5) and checks
each against the PR diff (Step 5C), producing a **"Design findings carried forward"** section that marks
each ✅ addressed / ❌ not addressed / ⚠️ can't determine. Unaddressed Critical/High design findings
become security questions and push involvement toward Required — so a design concern can't quietly ship
unaddressed. The design↔PR pair is linked in your design-review tracking record. A PR with no design
context behaves exactly as before.

---

## Decision capture

After reviewing results, decisions can be recorded via your decision-capture workflow. Saved to `reviews/<slug>/decisions.md`.

Valid decisions: `Resolved`, `Accepted Risk` (requires feedback), `Deferred` (requires feedback), `Requires Fix`. An `Accepted Risk` can be handed to Keymaker to record in the risk register.

---

## Troubleshooting

| Error | Fix |
|---|---|
| "Could not parse GitHub PR URL" | Ensure URL is `https://github.com/org/repo/pull/N` |
| GitHub API 404 | Pass `SOURCE_REPO_TOKEN` PAT with `repo` scope for private repos outside the caller's org |
| "NOTION_TOKEN required" | Remove `notion_sdd_url` or add the `NOTION_TOKEN` secret |
| Generic review output | Add a design-doc URL and a descriptive PR title/body |

---

## Engineering-side follow-through

The Architect produces the review; the author lands the fix with an engineering SDLC agent — a separate line-up outside the findings ledger. Name the right one in the review comment: [`/apoc`](../../../.claude/commands/apoc.md) (code-level flaw), [`/bane`](../../../.claude/commands/bane.md) (CI/CD weakness), [`/hamann`](../../../.claude/commands/hamann.md) (IaC misconfig), [`/dozer`](../../../.claude/commands/dozer.md) (risky dependency), [`/mouse`](../../../.claude/commands/mouse.md) (regression tests), [`/persephone`](../../../.claude/commands/persephone.md) (threat model). These are pointers for the author, never `suggested_next` values. See [Engineering SDLC agents](../../engineering-sdlc-agents.md).

---

## Service account requirements

- **`ANTHROPIC_API_KEY`**: `<your-anthropic-key-item>` in your credential vault — already a service credential
- **`LINEAR_API_KEY`**: needs a Linear API key tied to a service account, not personal
- **`NOTION_TOKEN`**: needs an integration token tied to a workspace integration, not personal
- **`SOURCE_REPO_TOKEN`**: optional GitHub PAT; if used, should be a machine user token

The GitHub Actions workflow itself runs as `github.token` — already a service credential.
