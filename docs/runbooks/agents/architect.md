# The Architect — Security Code Review Agent Runbook

**Character**: The Architect from *The Matrix*  
**Domain**: CISSP Domain 3 — Security Architecture & Engineering (partial)  
**Skill**: [`/architect`](../../../.claude/commands/architect.md)  
**Status**: Live

---

## What it does

The Architect guides security reviews of GitHub pull requests using the `pr-review.yml` GitHub Action in the mc-security repo. It helps gather required inputs, triggers the review workflow, explains outputs, and walks through findings.

The Architect reviews new PRs and code changes. Niobe audits what's already running.

> "You are here because Zion is about to be destroyed."

---

## How to invoke

```text
/architect https://github.com/org/repo/pull/42      # PR URL
/architect                                           # prompts for PR URL
```

---

## Systems accessed

| System | Purpose | Auth |
|---|---|---|
| GitHub Actions | Run `pr-review.yml` workflow | `github.token` or `SOURCE_REPO_TOKEN` |
| GitHub API | Fetch PR diff and metadata | `gh` CLI auth |
| Notion MCP | Optional SDD context for the review | `NOTION_TOKEN` secret |
| Slack webhook | Optional notifications to `#team-security` | `SDD_SLACK_WEBHOOK_URL` secret |
| Linear MCP | Create triage ticket for Required reviews | `LINEAR_API_KEY` secret |

---

## Trigger options

### Manual (workflow_dispatch)
Go to **Actions > PR Security Review > Run workflow** in the mc-security repo.

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
    uses: <your-org>/the-construct/.github/workflows/pr-review-reusable.yml@main
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
| `NOTION_TOKEN` | Only if SDD URL provided | Fetch design context |
| `SDD_SLACK_WEBHOOK_URL` | Optional | Slack notifications |
| `LINEAR_API_KEY` | Optional | Create Linear triage ticket |

Configure at: **Settings > Secrets and variables > Actions**

---

## Review output interpretation

| Recommendation | Meaning | Action |
|---|---|---|
| **Required** | Security team must be consulted before merge | Post in `#team-security` before merging |
| **Recommended** | Security team should review but not blocking | Consider async review in `#team-security` |
| **Not Required** | No security team involvement needed | Proceed — address questions in code review |

Questions with <70% confidence are suppressed from the PR comment. Full list is in `pr_review_output.json`.

---

## Decision capture

After reviewing results, decisions can be recorded using `/decision <slug>`. Saved to `review-software/reviews/<slug>/decisions.md`.

Valid decisions: `Resolved`, `Accepted Risk` (requires feedback), `Deferred` (requires feedback), `Requires Fix`.

---

## Troubleshooting

| Error | Fix |
|---|---|
| "Could not parse GitHub PR URL" | Ensure URL is `https://github.com/org/repo/pull/N` |
| GitHub API 404 | Pass `SOURCE_REPO_TOKEN` PAT with `repo` scope for private repos outside the caller's org |
| "NOTION_TOKEN required" | Remove `notion_sdd_url` or add the `NOTION_TOKEN` secret |
| Generic review output | Add a Notion SDD URL and a descriptive PR title/body |

---

## Service account requirements

- **`ANTHROPIC_API_KEY`**: "Agent: Anthropic" in your-credentials-vault — already a service credential
- **`LINEAR_API_KEY`**: needs a Linear API key tied to a service account, not personal
- **`NOTION_TOKEN`**: needs an integration token tied to a workspace integration, not personal
- **`SOURCE_REPO_TOKEN`**: optional GitHub PAT; if used, should be a machine user token

The GitHub Actions workflow itself runs as `github.token` — already a service credential.
